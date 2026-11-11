"""Building a network that is too large for memory, tile by tile.

:func:`build_network` turns a file (or stream) of lines into a network of
nodes and edges on disk, with a node at each end and each crossing, holding
only one tile of it in memory at a time. The result is the same network that
:func:`snkit.from_edges` followed by :func:`snkit.split_edges_at_crossings`
would give, were there memory enough.

How it works:

1. **Plan.** The area is divided into tiles by a tree of splits, placed where
   the data is thick so that each tile holds about the same number of edges,
   whatever its size. The plan comes from a sample of the edges or, for a
   GeoParquet file already sorted in space, from its row-group statistics
   without reading any data.
2. **Partition.** The edges are read once, in batches, and written to
   scratch files by tile. An edge goes to every tile it reaches into, and
   belongs to the tile its first vertex is in.
3. **Find.** Each tile, alone in memory, finds the nodes in it: the ends of
   edges that lie in the tile, and the crossings that lie in the tile. Every
   place is in exactly one tile, so every node is found exactly once. What
   each edge needs to know - its end nodes, and where to cut it - is written
   to scratch files for the tile the edge belongs to.
4. **Cut.** Each tile, alone in memory again, loads the edges that belong to
   it with what was found for them, cuts them, and writes them out.

Nothing is cut at tile boundaries and nothing is approximate: an edge that
runs through ten tiles has its crossings found by ten tiles and is cut once.
"""

from __future__ import annotations

import shutil
import tempfile
import warnings
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

from snkit import _kernel as K
from snkit import _native
from snkit import io as sio
from snkit.arrays import GEOM, LineArray, PointArray
from snkit.core import FROM, ID, RESERVED, TO, Lines, _distinct, _edge_ends, _refuse
from snkit.match import crossing_events

ROW = "__row"


class Tiling:
    """A division of the plane into tiles by a tree of splits.

    Tiles do not overlap and leave no gaps, so every place is in exactly one.
    """

    def __init__(self, axis: Any, split: Any, low: Any, high: Any):
        self.axis = np.asarray(axis, dtype=np.int64)
        self.split = np.asarray(split, dtype=float)
        self.low = np.asarray(low, dtype=np.int64)
        self.high = np.asarray(high, dtype=np.int64)
        self.count = len(self.axis) + 1

    @classmethod
    def plan(cls, sample: Any, total: int, max_per_tile: int) -> "Tiling":
        """Divide space so that no tile holds more than about ``max_per_tile``
        of ``total`` places, of which ``sample`` (an array of coordinates) is
        a fair sample. Each split is at the median along the wider axis."""
        weight = total / max(len(sample), 1)
        nodes: List[List[Any]] = []
        leaves = [0]

        def build(points: Any) -> int:
            if len(points) * weight > max_per_tile and len(points) > 1:
                for axis in np.argsort(-np.ptp(points, axis=0)):
                    values = points[:, axis]
                    split = float(np.median(values))
                    below = values < split
                    if not below.any():  # the median is the least value: split just above it
                        split = float(values[values > split].min()) if (values > split).any() else split
                        below = values < split
                    if below.any() and not below.all():
                        node = len(nodes)
                        nodes.append([int(axis), split, 0, 0])
                        nodes[node][2] = build(points[below])
                        nodes[node][3] = build(points[~below])
                        return node
            leaves[0] += 1
            return -leaves[0]

        build(np.asarray(sample, dtype=float).reshape(-1, 2))
        return cls(*(zip(*nodes) if nodes else ([], [], [], [])))

    def owners(self, xy: Any) -> Any:
        """The tile each place is in"""
        return _native.tile_owners(self.axis, self.split, self.low, self.high, np.ascontiguousarray(xy, dtype=float))

    def reaches(self, boxes: Any) -> Tuple[Any, Any]:
        """Every (box, tile) where a box ``(xmin, ymin, xmax, ymax)`` reaches into a tile"""
        boxes = np.ascontiguousarray(boxes, dtype=float)
        return _native.tile_reaches(self.axis, self.split, self.low, self.high, boxes)  # type: ignore[no-any-return]


@dataclass
class Built:
    """What :func:`build_network` made"""

    nodes: Path
    edges: Path
    node_count: int
    edge_count: int
    tiles: int
    largest_tile: int

    def read(self, bbox: Optional[Any] = None) -> Any:
        """Read the network, or the part of it in a bounding box, into memory
        as an :class:`snkit.ArrayNetwork`.

        Within a box, edges are those that reach into it; nodes are the ends
        of those edges.
        """
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq

        if bbox is None:
            return sio.read_network(self.nodes, self.edges)
        edges = pa.table(sio.read_parquet(self.edges, bbox))
        wanted = pa.array(np.union1d(edges[FROM].to_numpy(), edges[TO].to_numpy()))
        file = pq.ParquetFile(self.nodes)
        groups = [file.read_row_group(g) for g in range(file.metadata.num_row_groups)]
        nodes = pa.concat_tables([g.filter(pc.is_in(g[ID], value_set=wanted)) for g in groups])
        return sio.read_network(nodes.cast(file.schema_arrow), edges)


def _sorted_in_space(groups: pd.DataFrame) -> bool:
    """Whether row groups each cover a small part of the whole, so that their boxes tell where the data is"""
    known = groups.dropna()
    if len(known) < len(groups) or len(groups) < 2:
        return False
    whole = (known["xmax"].max() - known["xmin"].min()) * (known["ymax"].max() - known["ymin"].min())
    each = ((known["xmax"] - known["xmin"]) * (known["ymax"] - known["ymin"])).sum()
    return bool(whole > 0 and each <= 4 * whole)


def _sample_from_statistics(groups: pd.DataFrame, size: int = 200_000) -> Any:
    """Places spread evenly over the box of each row group, in proportion to its rows"""
    rng = np.random.default_rng(0)
    share = np.maximum(1, (groups["rows"] / groups["rows"].sum() * size).astype(int))
    return np.concatenate(
        [rng.uniform([g.xmin, g.ymin], [g.xmax, g.ymax], (n, 2)) for g, n in zip(groups.itertuples(index=False), share)]
    )


class _Reservoir:
    """A fair sample of a stream of places, of bounded size"""

    def __init__(self, size: int = 200_000):
        self.size, self.rng = size, np.random.default_rng(0)
        self.keys, self.xy = np.zeros(0), np.zeros((0, 2))

    def add(self, xy: Any) -> None:
        self.keys = np.concatenate([self.keys, self.rng.random(len(xy))])
        self.xy = np.concatenate([self.xy, xy])
        if len(self.keys) > 2 * self.size:
            keep = np.argpartition(self.keys, self.size)[: self.size]
            self.keys, self.xy = self.keys[keep], self.xy[keep]


class _Scratch:
    """Record batches written to scratch files under a key, to be read back by key"""

    def __init__(self, directory: Path, limit: int):
        self.directory, self.limit = directory, limit
        self.waiting: Dict[Any, List[Any]] = {}
        self.rows = 0
        self.files = 0

    def add(self, kind: str, tile: int, table: Any) -> None:
        if len(table):
            self.waiting.setdefault((kind, tile), []).append(table)
            self.rows += len(table)
            if self.rows >= self.limit:
                self.flush()

    def flush(self) -> None:
        import pyarrow as pa

        for (kind, tile), tables in self.waiting.items():
            folder = self.directory / kind / str(tile)
            folder.mkdir(parents=True, exist_ok=True)
            table = pa.concat_tables(tables)
            with pa.ipc.new_file(folder / f"{self.files}.arrow", table.schema) as writer:
                writer.write_table(table)
        self.files += 1
        self.waiting, self.rows = {}, 0

    def put(self, kind: str, tile: int, name: str, table: Any) -> None:
        """Write a table at once, under a name that only the caller uses (so safe from several threads)"""
        import pyarrow as pa

        if len(table):
            folder = self.directory / kind / str(tile)
            folder.mkdir(parents=True, exist_ok=True)
            with pa.ipc.new_file(folder / f"{name}.arrow", table.schema) as writer:
                writer.write_table(table)

    def read(self, kind: str, tile: int) -> Optional[Any]:
        import pyarrow as pa

        folder = self.directory / kind / str(tile)
        if not folder.exists():
            return None
        tables = [pa.ipc.open_file(path).read_all() for path in sorted(folder.iterdir())]
        return pa.concat_tables(tables).combine_chunks()

    def discard(self, kind: str, tile: int) -> None:
        shutil.rmtree(self.directory / kind / str(tile), ignore_errors=True)


def _normalise(batch: Any, name: str, invalid: str, first_row: int) -> Tuple[Any, Any, Any]:
    """One row for each single line, numbered, with its geometry as arrays"""
    import pyarrow as pa

    table = pa.Table.from_batches([batch])
    coords, offsets, row, bad, rows = _native.read_geometry(table.select([name]), "lines", name)
    _refuse(len(bad), "lines", invalid)
    attributes = sio.plain(table.drop_columns([name] + sio._covering(table.schema, name))).take(pa.array(row))
    clash = {c: f"{c}_original" for c in attributes.column_names if c in RESERVED or c in (ROW, GEOM)}
    attributes = attributes.rename_columns([clash.get(c, c) for c in attributes.column_names])
    numbers = pa.array(np.arange(first_row, first_row + len(row), dtype=np.int64))
    return attributes.append_column(ROW, numbers), coords, offsets


def _lines_table(rows: Any, lines: LineArray) -> Any:
    import pyarrow as pa

    array, field = sio.geometry_array(lines)
    return pa.Table.from_arrays([pa.array(rows), array], schema=pa.schema([pa.field(ROW, pa.int64()), field]))


def _read_lines(table: Any) -> Tuple[Any, Lines]:
    coords, offsets, _, _, _ = _native.read_geometry(table.select([GEOM]), "lines", GEOM)
    return table[ROW].to_numpy(), Lines(LineArray(coords, offsets))


def _partition(batches: Iterator[Tuple[Any, Any, Any]], tiling: Tiling, scratch: _Scratch) -> Any:
    """Write each edge to the tile it belongs to, and its line to every tile it reaches into.

    Returns how many edges reach into each tile.
    """
    import pyarrow as pa

    reaching = np.zeros(tiling.count, dtype=np.int64)
    for attributes, coords, offsets in batches:
        lines = LineArray(coords, offsets)
        rows = attributes[ROW].to_numpy()
        starts = offsets[:-1]
        boxes = np.column_stack(
            [
                np.minimum.reduceat(coords[:, 0], starts),
                np.minimum.reduceat(coords[:, 1], starts),
                np.maximum.reduceat(coords[:, 0], starts),
                np.maximum.reduceat(coords[:, 1], starts),
            ]
        )
        owned = (np.arange(len(rows)), tiling.owners(coords[starts]))
        reached = tiling.reaches(boxes)
        reaching += np.bincount(reached[1], minlength=tiling.count)
        for kind, (line, tile) in (("own", owned), ("reach", reached)):
            order = np.argsort(tile, kind="stable")
            line, tile = line[order], tile[order]
            first = np.concatenate([[0], np.flatnonzero(np.diff(tile)) + 1, [len(tile)]])
            for start, end in zip(first[:-1], first[1:]):
                chosen = line[start:end]
                table = _lines_table(rows[chosen], lines.take(chosen))
                if kind == "own":
                    extra = attributes.drop_columns([ROW]).take(pa.array(chosen))
                    for column in extra.column_names:
                        table = table.append_column(extra.schema.field(column), extra[column])
                scratch.add(kind, int(tile[start]), table)
    scratch.flush()
    return reaching


def _find(tile: int, tiling: Tiling, scratch: _Scratch, crossings: bool) -> Optional[Any]:
    """Find the nodes that lie in one tile, and note what each edge needs to know of them.

    Returns the coordinates of the tile's nodes. In what is noted for edges a
    node is named by this tile and its position among them, since its id is
    not known until the tiles before this one have been counted.
    """
    import pyarrow as pa

    table = scratch.read("reach", tile)
    if table is None:
        return None
    rows, lines = _read_lines(table)
    del table
    home = tiling.owners(lines.coords[lines.offsets[:-1]])  # the tile each edge belongs to

    # ends of edges that lie in this tile
    ends = _edge_ends(lines.coords, lines.offsets)
    mine = np.flatnonzero(tiling.owners(ends) == tile)
    places = [ends[mine]]

    cut_edge = cut_vertex = np.zeros(0, dtype=np.int64)
    cut_measure, cut_place = np.zeros(0), np.zeros(0, dtype=np.int64)
    if crossings:
        events = crossing_events(lines)
        xy = events[["x", "y"]].to_numpy()
        events = events[tiling.owners(xy) == tile]
        xy = events[["x", "y"]].to_numpy()
        places.append(xy)
        # cut each edge that is met away from its own ends
        sides = []
        for side in "ab":
            inside = np.flatnonzero(events[f"end_{side}"].to_numpy() == 0)
            edge = events[f"edge_{side}"].to_numpy(dtype=np.int64)[inside]
            vertex = events[f"vertex_{side}"].to_numpy(dtype=np.int64)[inside] - lines.offsets[edge]
            sides.append((edge, vertex, events[f"measure_{side}"].to_numpy()[inside], len(mine) + inside))
        cut_edge, cut_vertex, cut_measure, cut_place = (np.concatenate(part) for part in zip(*sides))

    # one node for each distinct place: an end and a crossing at the same place share it
    node_xy, index = _distinct(np.concatenate(places))
    node = index
    here = np.full(len(mine), tile, dtype=np.int64)

    end_tables = pa.table(
        {ROW: rows[mine // 2], "end": (mine % 2).astype(np.int8), "tile": here, "node": node[: len(mine)]}
    )
    cut_tables = pa.table(
        {
            ROW: rows[cut_edge],
            "vertex": cut_vertex,
            "measure": cut_measure,
            "x": node_xy[index[cut_place], 0] if len(cut_place) else np.zeros(0),
            "y": node_xy[index[cut_place], 1] if len(cut_place) else np.zeros(0),
            "tile": np.full(len(cut_place), tile, dtype=np.int64),
            "node": node[cut_place],
        }
    )
    for kind, records, owner in (("ends", end_tables, home[mine // 2]), ("cuts", cut_tables, home[cut_edge])):
        for target in np.unique(owner):
            scratch.put(kind, int(target), f"from-{tile}", records.filter(pa.array(owner == target)))
    scratch.discard("reach", tile)
    return node_xy


def _cut(tile: int, scratch: _Scratch, first_node: Any) -> Optional[Any]:
    """Cut the edges that belong to one tile at the places found for them.

    ``first_node`` gives the id of the first node of each tile. The edges are returned without ids.
    """
    import pyarrow as pa

    table = scratch.read("own", tile)
    if table is None:
        return None
    rows, lines = _read_lines(table)
    position = pd.Index(rows)
    ends = scratch.read("ends", tile)
    which = position.get_indexer(ends[ROW].to_numpy())
    at_end = ends["end"].to_numpy().astype(bool)
    src, dst = np.full(len(rows), -1, dtype=np.int64), np.full(len(rows), -1, dtype=np.int64)
    end_node = first_node[ends["tile"].to_numpy()] + ends["node"].to_numpy()
    src[which[~at_end]] = end_node[~at_end]
    dst[which[at_end]] = end_node[at_end]
    if (src < 0).any() or (dst < 0).any():  # pragma: no cover
        raise RuntimeError("an edge is missing an end node: this is a fault in snkit")

    cuts = scratch.read("cuts", tile)
    if cuts is None:
        coords, offsets, parent = lines.coords, lines.offsets, np.arange(len(rows))
    else:
        found = cuts.to_pandas()
        found["node"] = first_node[found["tile"].to_numpy()] + found["node"].to_numpy()
        found["edge"] = position.get_indexer(found[ROW].to_numpy())
        found["seg"] = lines.offsets[found["edge"].to_numpy()] + found["vertex"].to_numpy()
        found = found.sort_values(["edge", "seg", "measure", "node"], kind="stable")
        found = found.drop_duplicates(["edge", "measure", "node"])
        coords, offsets, src, dst, parent = K.split(
            lines.coords,
            lines.offsets,
            src,
            dst,
            found["edge"].to_numpy(),
            found["seg"].to_numpy(),
            found[["x", "y"]].to_numpy(),
            found["node"].to_numpy(),
        )
    attributes = table.drop_columns([ROW, GEOM]).take(pa.array(parent))
    geometry, field = sio.geometry_array(LineArray(coords, offsets), "separated")
    out = pa.table({FROM: pa.array(src.astype(np.uint64)), TO: pa.array(dst.astype(np.uint64))})
    for column in attributes.column_names:
        out = out.append_column(attributes.schema.field(column), attributes[column])
    for kind in ("own", "ends", "cuts"):
        scratch.discard(kind, tile)
    return out.append_column(field, geometry)


class _Pool:
    """Run work on tiles, one at a time here or several at once in other processes.

    Other processes, not threads: much of the work on a tile is done in
    Python, which runs one thread at a time.
    """

    def __init__(self, workers: int):
        self.workers = max(1, workers)
        self.pool = None
        if self.workers > 1:
            import multiprocessing

            self.pool = ProcessPoolExecutor(self.workers, mp_context=multiprocessing.get_context("spawn"))

    def __enter__(self) -> "_Pool":
        return self

    def __exit__(self, *error: Any) -> None:
        if self.pool is not None:
            self.pool.shutdown()

    def in_order(self, work: Any, count: int, *arguments: Any) -> Iterator[Any]:
        """Results of ``work(0, ...)``, ``work(1, ...)``, ... in order.

        No more than a few results are ever waiting to be used, so that what
        is held in memory does not grow with the number of tiles.
        """
        if self.pool is None:
            for item in range(count):
                yield work(item, *arguments)
            return
        waiting: List[Any] = []
        for item in range(count):
            waiting.append(self.pool.submit(work, item, *arguments))
            if len(waiting) >= 2 * self.workers:
                yield waiting.pop(0).result()
        for future in waiting:
            yield future.result()


def _nodes_table(ids: Any, xy: Any, crs: Any) -> Any:
    import pyarrow as pa

    geometry, field = sio.geometry_array(PointArray(xy), "separated")
    table = pa.Table.from_arrays([pa.array(ids), geometry], schema=pa.schema([pa.field(ID, pa.uint64()), field]))
    return table.replace_schema_metadata({b"geo": sio.geo_metadata("points", crs)})


def build_network(
    source: Any,
    destination: Any,
    max_tile_edges: int = 250_000,
    split_at_crossings: bool = True,
    tolerance: float = 0,
    column: Optional[str] = None,
    layer: Optional[str] = None,
    invalid: str = "raise",
    workdir: Optional[Any] = None,
    workers: int = 1,
) -> Built:
    """Build a network from lines, file to file, without holding it all in memory.

    A node is made at each distinct end of a line and, with
    ``split_at_crossings``, wherever lines cross or one ends on another; edges
    are cut there. Ends and crossings are matched exactly; nodes that end up
    within ``tolerance`` of each other are then merged, if one is given.
    Attributes of each line are copied to the edges cut from it.

    Parameters
    ----------
    source
        A path to a file of lines (GeoParquet, or anything GDAL reads), or
        Arrow data: a record batch reader or anything else that offers an
        Arrow stream, such as the result of a query in SedonaDB or DuckDB.
    destination
        A directory, made if need be, to hold ``nodes.parquet`` and
        ``edges.parquet``.
    max_tile_edges
        About how many edges to work on at once: this sets the memory needed.
        The area is divided, finely where edges are dense and coarsely where
        they are sparse, into tiles of no more than about this many edges.
    tolerance
        Merge nodes within this distance of each other once the network is
        built (see :func:`snkit.tiled.merge_nodes`). By default, none.
    workers
        How many tiles to work on at once, each in a process of its own.
        Memory needed grows in proportion.
    column
        The geometry column, if the source does not say which it is.
    layer
        The layer to read, for formats with more than one.
    invalid
        ``"raise"`` or ``"drop"`` geometries that are missing, empty,
        zero-length or not lines.
    workdir
        Where to put scratch files, which take about three times the space of
        the source while the build runs. By default a temporary directory.

    Returns
    -------
    Built
        The paths of the two files and counts of what is in them. The files
        are GeoParquet with ``id`` on nodes and ``id``, ``from_id``, ``to_id``
        on edges. Each tile is a row group, so the files record the area that
        each row group covers and :func:`snkit.io.read_parquet` can read part
        of the network by bounding box. ``Built.read()`` reads it into memory.

    Examples
    --------
    >>> import tempfile
    >>> import geopandas
    >>> from shapely import LineString
    >>> import snkit
    >>> folder = tempfile.mkdtemp()
    >>> lines = geopandas.GeoDataFrame(
    ...     {"name": ["a", "b"]}, geometry=[LineString([(0, 0), (2, 2)]), LineString([(0, 2), (2, 0)])])
    >>> lines.to_parquet(f"{folder}/lines.parquet")
    >>> built = snkit.build_network(f"{folder}/lines.parquet", f"{folder}/network")
    >>> built.node_count, built.edge_count
    (5, 4)
    >>> network = built.read()
    >>> sorted((name, line.wkt) for name, line in zip(network.edges["name"], network.edges.geometry))[0]
    ('a', 'LINESTRING (0 0, 1 1)')
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    scratch_dir = Path(tempfile.mkdtemp(prefix="snkit-", dir=workdir))
    scratch = _Scratch(scratch_dir, limit=4 * max_tile_edges)
    is_path = isinstance(source, (str, Path))
    try:
        reader = sio.read(source, layer=layer) if is_path else sio.reader(source)
        name = sio.geometry_field(reader.schema, column)
        crs = sio._crs(reader.schema, name)

        def normalised(batches: Any) -> Iterator[Tuple[Any, Any, Any]]:
            count = 0
            for batch in batches:
                attributes, coords, offsets = _normalise(batch, name, invalid, count)
                count += len(attributes)
                if len(attributes):
                    yield attributes, coords, offsets

        # plan the tiles: from the file's own statistics if they say where the
        # data is, otherwise from a sample taken while copying the edges to scratch
        tiling = None
        if is_path and str(source).lower().endswith((".parquet", ".geoparquet", ".pq")):
            groups = sio.parquet_row_groups(source, name)
            if _sorted_in_space(groups):
                tiling = Tiling.plan(_sample_from_statistics(groups), int(groups["rows"].sum()), max_tile_edges)
        if tiling is not None:
            batches = normalised(reader)
        else:
            sample, total, staged = _Reservoir(), 0, 0
            for attributes, coords, offsets in normalised(reader):
                sample.add(coords[offsets[:-1]])
                total += len(attributes)
                table = _lines_table(attributes[ROW].to_numpy(), LineArray(coords, offsets))
                for field_name in attributes.drop_columns([ROW]).column_names:
                    table = table.append_column(attributes.schema.field(field_name), attributes[field_name])
                scratch.add("stage", staged, table)
                staged += 1
            scratch.flush()
            tiling = Tiling.plan(sample.xy, total, max_tile_edges)

            def staged_batches() -> Iterator[Tuple[Any, Any, Any]]:
                for part in range(staged):
                    table = scratch.read("stage", part)
                    scratch.discard("stage", part)
                    if table is not None:
                        coords, offsets, _, _, _ = _native.read_geometry(table.select([GEOM]), "lines", GEOM)
                        yield table.drop_columns([GEOM]), coords, offsets

            batches = staged_batches()

        reaching = _partition(batches, tiling, scratch)
        largest = int(reaching.max()) if len(reaching) else 0
        if largest > 4 * max_tile_edges:
            warnings.warn(
                f"one tile has {largest:,} edges reaching into it, well over max_tile_edges={max_tile_edges:,}: "
                "long edges, or many edges at one place, cannot be divided between tiles"
            )

        node_count = edge_count = 0
        nodes_path, edges_path = destination / "nodes.parquet", destination / "edges.parquet"
        first_node = np.zeros(tiling.count, dtype=np.int64)
        with _Pool(workers) as pool:
            writer = None
            found = pool.in_order(_find, tiling.count, tiling, scratch, split_at_crossings)
            for tile, xy in enumerate(found):
                first_node[tile] = node_count
                if xy is None or len(xy) == 0:
                    continue
                table = _nodes_table(np.arange(node_count, node_count + len(xy), dtype=np.uint64), xy, crs)
                writer = writer or pq.ParquetWriter(nodes_path, table.schema)
                writer.write_table(table)
                node_count += len(xy)
            if writer is not None:
                writer.close()

            writer = None
            for table in pool.in_order(_cut, tiling.count, scratch, first_node):
                if table is None:
                    continue
                ids = pa.array(np.arange(edge_count, edge_count + len(table), dtype=np.uint64))
                table = table.add_column(0, ID, ids)
                table = table.replace_schema_metadata({b"geo": sio.geo_metadata("lines", crs)})
                writer = writer or pq.ParquetWriter(edges_path, table.schema)
                writer.write_table(table.cast(writer.schema))
                edge_count += len(table)
            if writer is not None:
                writer.close()
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)
    if edge_count == 0:
        raise ValueError("the source has no lines to build a network from")
    built = Built(nodes_path, edges_path, node_count, edge_count, tiling.count, largest)
    if tolerance:
        # join ends that nearly meet, as snkit.from_edges does with a tolerance
        merged = merge_nodes(built, destination / "merging", tolerance, max_tile_edges, workdir=workdir)
        for path in (merged.nodes, merged.edges):
            path.replace(destination / path.name)
        (destination / "merging").rmdir()
        built = Built(nodes_path, edges_path, merged.node_count, merged.edge_count, tiling.count, largest)
    return built


# ---------------------------------------------------------------------------
# Operations on a network that is already on disk


def open_network(network: Any) -> Built:
    """A network on disk: a :class:`Built`, or a directory holding ``nodes.parquet`` and ``edges.parquet``"""
    import pyarrow.parquet as pq

    if isinstance(network, Built):
        return network
    nodes, edges = Path(network) / "nodes.parquet", Path(network) / "edges.parquet"
    node_file, edge_file = pq.ParquetFile(nodes), pq.ParquetFile(edges)
    return Built(nodes, edges, node_file.metadata.num_rows, edge_file.metadata.num_rows, node_file.num_row_groups, 0)


def _row_groups(path: Path) -> Iterator[Any]:
    import pyarrow.parquet as pq

    file = pq.ParquetFile(path)
    for group in range(file.num_row_groups):
        yield file.read_row_group(group)


def _rewrite(source: Path, destination: Path, change: Any) -> int:
    """Copy a file row group by row group, passing each through ``change``; returns the rows written"""
    import pyarrow.parquet as pq

    writer, rows = None, 0
    for table in _row_groups(source):
        table = change(table)
        writer = writer or pq.ParquetWriter(destination, table.schema)
        writer.write_table(table)
        rows += len(table)
    if writer is not None:
        writer.close()
    return rows


def label_components(network: Any, destination: Any, column: str = "component") -> Built:
    """Number the connected parts of a network on disk, as :func:`snkit.label_components` does in memory.

    Writes new ``nodes.parquet`` and ``edges.parquet`` in ``destination`` with
    a column added that numbers the connected part each node and edge is in,
    from 0 in order of the lowest node id in each part.

    Connectivity is a property of the whole network, so this cannot be done
    tile by tile. The edges are read through once in batches, joining the
    parts their ends are in, with twelve bytes held in memory for each node id
    (about 1 GB for a network of 80 million nodes). Node ids must not be far
    larger than the number of nodes, as is so for a network made by
    :func:`snkit.build_network`.
    """
    import pyarrow as pa

    built = open_network(network)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    highest = max((int(pa.compute.max(table[ID]).as_py()) for table in _row_groups(built.nodes)), default=-1)
    parent = np.arange(highest + 1, dtype=np.uint32)
    for table in _row_groups(built.edges):
        _native.components_link(parent, table[FROM].to_numpy().astype(np.int64), table[TO].to_numpy().astype(np.int64))
    _native.components_settle(parent)

    # number the parts in order of their lowest node, counting only ids that are in use
    present = np.zeros(len(parent), dtype=bool)
    for table in _row_groups(built.nodes):
        present[table[ID].to_numpy()] = True
    number = np.cumsum(present & (parent == np.arange(len(parent)))) - 1

    def labelled(key: str) -> Any:
        def change(table: Any) -> Any:
            part = number[parent[table[key].to_numpy()]]
            at = table.schema.get_field_index(GEOM)
            return table.add_column(at, column, pa.array(part))

        return change

    nodes, edges = destination / "nodes.parquet", destination / "edges.parquet"
    node_count = _rewrite(built.nodes, nodes, labelled(ID))
    edge_count = _rewrite(built.edges, edges, labelled(FROM))
    return Built(nodes, edges, node_count, edge_count, built.tiles, built.largest_tile)


def _pairs_in(tile: int, tiling: Tiling, scratch: _Scratch, tolerance: float) -> Optional[Any]:
    """Pairs of near nodes that it falls to one tile to report"""
    table = scratch.read("near", tile)
    scratch.discard("near", tile)
    if table is None:
        return None
    ids = table[ID].to_numpy()
    xy = np.column_stack([table["x"].to_numpy(), table["y"].to_numpy()])
    a, b = K.point_pairs(xy, tolerance)
    low = np.where(ids[a] < ids[b], a, b)
    mine = tiling.owners(xy[low]) == tile
    a, b = a[mine], b[mine]
    return pd.DataFrame({"a": ids[a], "b": ids[b], "ax": xy[a, 0], "ay": xy[a, 1], "bx": xy[b, 0], "by": xy[b, 1]})


def _near_pairs(built: Built, tolerance: float, max_tile_nodes: int, scratch: _Scratch, workers: int) -> Any:
    """Pairs of nodes within tolerance of each other, found tile by tile.

    Tiles overlap by the tolerance: a node is given to every tile within
    tolerance of it, and a pair is reported by the tile that the node with
    the lower id lies in, so each pair is found once.
    """
    import pyarrow as pa

    groups = sio.parquet_row_groups(built.nodes)
    if _sorted_in_space(groups):
        tiling = Tiling.plan(_sample_from_statistics(groups), built.node_count, max_tile_nodes)
    else:
        sample = _Reservoir()
        for table in _row_groups(built.nodes):
            sample.add(_native.read_geometry(table.select([GEOM]), "points", GEOM)[0])
        tiling = Tiling.plan(sample.xy, built.node_count, max_tile_nodes)

    for table in _row_groups(built.nodes):
        xy = _native.read_geometry(table.select([GEOM]), "points", GEOM)[0]
        ids = table[ID].to_numpy().astype(np.int64)
        row, tile = tiling.reaches(np.column_stack([xy - tolerance, xy + tolerance]))
        order = np.argsort(tile, kind="stable")
        row, tile = row[order], tile[order]
        first = np.concatenate([[0], np.flatnonzero(np.diff(tile)) + 1, [len(tile)]])
        for start, end in zip(first[:-1], first[1:]):
            chosen = row[start:end]
            scratch.add("near", int(tile[start]), pa.table({ID: ids[chosen], "x": xy[chosen, 0], "y": xy[chosen, 1]}))
    scratch.flush()

    with _Pool(workers) as pool:
        each = pool.in_order(_pairs_in, tiling.count, tiling, scratch, tolerance)
        found = [pairs for pairs in each if pairs is not None and len(pairs)]
    columns = ["a", "b", "ax", "ay", "bx", "by"]
    return pd.concat(found, ignore_index=True) if found else pd.DataFrame({c: [] for c in columns})


def merge_nodes(
    network: Any,
    destination: Any,
    tolerance: float,
    max_tile_nodes: int = 500_000,
    position: str = "centroid",
    workdir: Optional[Any] = None,
    workers: int = 1,
) -> Built:
    """Merge nodes of a network on disk that are within ``tolerance`` of each
    other, as :func:`snkit.merge_nodes` does in memory.

    Writes new ``nodes.parquet`` and ``edges.parquet`` in ``destination``.
    Nodes are merged in chains. The merged node keeps the lowest id of its
    members and their attributes, and sits at their centroid, or with
    ``position="first"`` where the member with the lowest id was. Ends of edges move with their
    nodes; an edge whose two ends merge into one node is dropped if it was no
    longer than the tolerance.

    Near nodes are found tile by tile, in tiles of about ``max_tile_nodes``
    that overlap by the tolerance. What is then held in memory is only the
    nodes that are to be merged, while both files are rewritten a row group
    at a time.
    """
    import pyarrow as pa

    if position not in ("centroid", "first"):
        raise ValueError("position must be 'centroid' or 'first'")
    built = open_network(network)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    crs = sio._crs(sio.read_parquet(built.nodes).schema, GEOM)
    if tolerance and crs is not None and crs.is_geographic:
        raise ValueError("this network has a geographic CRS, so a distance would be in degrees: reproject first")
    scratch_dir = Path(tempfile.mkdtemp(prefix="snkit-", dir=workdir))
    try:
        pairs = _near_pairs(built, tolerance, max_tile_nodes, _Scratch(scratch_dir, 4 * max_tile_nodes), workers)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    # the nodes that take part in a merge, their groups, and where each group's node will sit
    ends = pd.DataFrame(
        {
            ID: np.concatenate([pairs["a"], pairs["b"]]).astype(np.int64),
            "x": np.concatenate([pairs["ax"], pairs["bx"]]),
            "y": np.concatenate([pairs["ay"], pairs["by"]]),
        }
    ).drop_duplicates(ID)
    ends = ends.sort_values(ID, ignore_index=True)
    involved = pd.Index(ends[ID])
    labels = K.components(len(ends), involved.get_indexer(pairs["a"]), involved.get_indexer(pairs["b"]))
    keeper = ends[ID].to_numpy()[labels]  # sorted by id, so the label is the member with the lowest id
    place = ends[["x", "y"]].to_numpy()[labels]
    if position == "centroid" and len(ends):
        place = ends.groupby(labels)[["x", "y"]].transform("mean").to_numpy()
    merged_away = pa.array(ends[ID].to_numpy()[keeper != ends[ID].to_numpy()])

    def change_nodes(table: Any) -> Any:
        table = table.filter(pa.compute.invert(pa.compute.is_in(table[ID], value_set=merged_away.cast(table[ID].type))))
        xy = _native.read_geometry(table.select([GEOM]), "points", GEOM)[0].copy()
        which = involved.get_indexer(table[ID].to_numpy().astype(np.int64))
        xy[which >= 0] = place[which[which >= 0]]
        geometry, field = sio.geometry_array(PointArray(xy), "separated")
        return table.set_column(
            table.schema.get_field_index(GEOM), table.schema.field(GEOM), geometry.cast(table.schema.field(GEOM).type)
        )

    def change_edges(table: Any) -> Any:
        coords, offsets, _, _, _ = _native.read_geometry(table.select([GEOM]), "lines", GEOM)
        coords = coords.copy()
        length = K.line_measures(coords, offsets)[2]
        ends_now = {}
        for key, vertex in ((FROM, offsets[:-1]), (TO, offsets[1:] - 1)):
            ids = table[key].to_numpy().astype(np.int64)
            which = involved.get_indexer(ids)
            moved = which >= 0
            coords[vertex[moved]] = place[which[moved]]
            now = ids.copy()
            now[moved] = keeper[which[moved]]
            ends_now[key] = (ids, now)
        (was_from, now_from), (was_to, now_to) = ends_now[FROM], ends_now[TO]
        collapsed = (now_from == now_to) & (was_from != was_to)
        collapsed &= (length <= tolerance) | (K.line_measures(coords, offsets)[2] == 0)
        keep = np.flatnonzero(~collapsed)
        geometry, _ = sio.geometry_array(LineArray(coords, offsets).take(keep), "separated")
        table = table.take(pa.array(keep))
        for key, values in ((FROM, now_from), (TO, now_to)):
            at = table.schema.get_field_index(key)
            table = table.set_column(
                at, table.schema.field(key), pa.array(values[keep]).cast(table.schema.field(key).type)
            )
        at = table.schema.get_field_index(GEOM)
        return table.set_column(at, table.schema.field(GEOM), geometry.cast(table.schema.field(GEOM).type))

    nodes, edges = destination / "nodes.parquet", destination / "edges.parquet"
    node_count = _rewrite(built.nodes, nodes, change_nodes)
    edge_count = _rewrite(built.edges, edges, change_edges)
    return Built(nodes, edges, node_count, edge_count, built.tiles, built.largest_tile)
