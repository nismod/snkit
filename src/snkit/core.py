"""Data model for topological networks: creation, validation, lineage.

A topological network has unsigned integer ``id`` on nodes and edges, and
``from_id``/``to_id`` on edges naming their end nodes. The first and last
vertex of each edge are exactly the positions of those nodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
import shapely
from geopandas import GeoDataFrame, GeoSeries

from snkit import _kernel as K
from snkit.arrays import (
    Frame,
    LineArray,
    PointArray,
    _like,
    is_arrays,
    lines_of,
    operation,
    points_of,
    with_geometry,
)
from snkit.network import Network

ID = "id"
FROM = "from_id"
TO = "to_id"
GEOM = "geometry"
RESERVED = (ID, FROM, TO)

# Lines or points to make a network from: a GeoDataFrame, a GeoSeries, a
# sequence of geometries, or Arrow data (anything that offers an Arrow stream)
Geometries = Union[GeoDataFrame, GeoSeries, Iterable[Any]]
Agg = Optional[Dict[str, Union[str, Callable[..., Any]]]]


@dataclass
class Lineage:
    """Which input features each output feature came from.

    ``nodes`` and ``edges`` each have columns ``id`` and ``parent_id``. A
    feature that was split appears as the parent of several rows; a feature
    made by merging has several rows. Features that are entirely new (a node
    created at a crossing, a linking edge) have no rows.
    """

    nodes: pd.DataFrame
    edges: pd.DataFrame

    def then(self, later: "Lineage") -> "Lineage":
        """Compose with the lineage of a following operation"""
        return Lineage(_compose(self.nodes, later.nodes), _compose(self.edges, later.edges))


def _pairs(ids: Any, parents: Any) -> pd.DataFrame:
    return pd.DataFrame(
        {
            ID: np.asarray(ids, dtype="uint64"),
            "parent_id": np.asarray(parents, dtype="uint64"),
        }
    )


def _compose(first: pd.DataFrame, second: pd.DataFrame) -> pd.DataFrame:
    joined = second.merge(first, left_on="parent_id", right_on=ID, suffixes=("", "_first"))
    out = _pairs(joined[ID], joined["parent_id_first"])
    return out.drop_duplicates(ignore_index=True)


def identity_lineage(network: Network) -> Lineage:
    return Lineage(
        _pairs(network.nodes[ID], network.nodes[ID]),
        _pairs(network.edges[ID], network.edges[ID]),
    )


def finish(
    network: Network, lineages: Sequence[Lineage], return_lineage: bool
) -> Union[Network, Tuple[Network, Lineage]]:
    """Return a network, with composed lineage if requested"""
    if not return_lineage:
        return network
    lineage = lineages[0]
    for later in lineages[1:]:
        lineage = lineage.then(later)
    return network, lineage


class Lines:
    """Array view of a set of line geometries"""

    def __init__(self, lines: Any):
        self.lines = LineArray.from_shapely(lines)
        self.coords, self.offsets = self.lines.coords, self.lines.offsets
        self.m = len(self.lines)
        self.seglen, self.measure, self.length = K.line_measures(self.coords, self.offsets)

    def place(self, vertex: Any, frac: Any) -> Any:
        """Distance along its line of a place given by vertex and fraction"""
        return self.measure[vertex] + frac * self.seglen[vertex]

    def end(self, line: Any, vertex: Any, frac: Any) -> Any:
        """Whether a place is the start (-1) or the end (1) of its line, or neither (0)"""
        at_start = (vertex == self.offsets[line]) & (frac == 0)
        at_end = (vertex == self.offsets[line + 1] - 1) | ((vertex == self.offsets[line + 1] - 2) & (frac == 1))
        return np.where(at_start, -1, np.where(at_end, 1, 0))

    def locate(self, line: Any, at: Any) -> Any:
        """The vertex, fraction and coordinate of places given distances along lines"""
        return K.locate(self.coords, self.offsets, self.seglen, self.measure, line, at)


class Arrays(Lines):
    """Array view of a topological network, as the kernel needs it"""

    def __init__(self, network: Network):
        nodes, edges = network.nodes, network.edges
        for name, table, columns in (("nodes", nodes, (ID,)), ("edges", edges, RESERVED)):
            missing = [c for c in columns if c not in table.columns]
            if missing:
                raise ValueError(
                    f"{name} table has no {missing} column: build the network with "
                    "snkit.from_edges, from_nodes_and_edges or from_topology first"
                )
        super().__init__(lines_of(edges))
        self.node_ids = nodes[ID].to_numpy(dtype="uint64")
        self.edge_ids = edges[ID].to_numpy(dtype="uint64")
        self.points = points_of(nodes)
        self.xy = self.points.xy
        index = pd.Index(self.node_ids)
        self.src = index.get_indexer(edges[FROM].to_numpy(dtype="uint64")).astype(np.int64)
        self.dst = index.get_indexer(edges[TO].to_numpy(dtype="uint64")).astype(np.int64)
        if (self.src < 0).any() or (self.dst < 0).any():
            raise ValueError("edges refer to node ids that are not in the nodes table")
        self.n = len(self.node_ids)

    def degree(self) -> K.IntArray:
        return np.bincount(self.src, minlength=self.n) + np.bincount(self.dst, minlength=self.n)


def geometry_array(table: GeoDataFrame) -> Any:
    return np.asarray(table.geometry.values, dtype=object)


def to_ragged(lines: Any) -> Tuple[K.FloatArray, K.IntArray]:
    lines = LineArray.from_shapely(lines)
    return lines.coords, lines.offsets


def from_ragged(coords: K.FloatArray, offsets: K.IntArray) -> LineArray:
    return LineArray(coords, offsets)


def next_ids(existing: Any, count: int) -> Any:
    start = int(np.max(existing)) + 1 if len(existing) else 0
    return np.arange(start, start + count, dtype="uint64")


def append_rows(table: Frame, rows: Frame) -> Frame:
    """Add rows that have only id columns and geometry; other attributes are left null"""
    if len(rows) == 0:
        return table
    combined = pd.concat([pd.DataFrame(table), pd.DataFrame(rows)], ignore_index=True, sort=False)
    for column in RESERVED:
        if column in combined.columns:
            combined[column] = combined[column].astype("uint64")
    return with_geometry(combined, combined[GEOM].array, table.crs)


def check_distance(network: Network, distance: Optional[float]) -> None:
    """Refuse a distance in degrees"""
    if not distance:
        return
    crs = network.edges.crs if len(network.edges) else network.nodes.crs
    if crs is not None and crs.is_geographic:
        raise ValueError(
            "this network has a geographic CRS, so a distance would be in degrees: "
            "reproject first, for example network.to_crs(network.edges.estimate_utm_crs())"
        )


def aggregate(table: pd.DataFrame, group: K.IntArray, count: int, agg: Agg) -> pd.DataFrame:
    """Reduce a table to one row per group.

    A group of one keeps its row. Otherwise each attribute follows its rule in
    ``agg``, by default keeping a value only where every member agrees.
    """
    agg = agg or {}
    table = pd.DataFrame(table).reset_index(drop=True)
    first = np.full(count, -1, dtype=np.int64)
    first[group[::-1]] = np.arange(len(group))[::-1]
    out = table.iloc[first].reset_index(drop=True)
    size = np.bincount(group, minlength=count)
    multi = size > 1
    if not multi.any():
        return out
    members = multi[group]
    grouped = table[members].groupby(group[members], sort=True)
    for column in table.columns:
        if column in RESERVED or column == GEOM:
            continue
        rule = agg.get(column, "unanimous")
        if rule == "unanimous":
            value = grouped[column].first()
            value = value.where(grouped[column].nunique(dropna=False) == 1)
        elif rule == "list":
            value = grouped[column].agg(list)
        else:
            value = grouped[column].agg(rule)
        single = out[column][~multi]
        if value.isna().all():
            merged = single.reindex(range(count))
        else:
            merged = pd.concat([single, value]).sort_index()
        out[column] = merged.to_numpy()
    return out


# ---------------------------------------------------------------------------
# Creation


def _is_arrow(data: Any) -> bool:
    """Whether data is Arrow (a table, a reader, a query result) and not a pandas table"""
    return hasattr(data, "__arrow_c_stream__") and not isinstance(data, (pd.DataFrame, pd.Series))


def _in_arrays(*data: Any) -> bool:
    """Whether a network made from this data should hold its geometry in arrays"""
    return any(_is_arrow(item) or isinstance(item, Frame) for item in data)


def _read(data: Geometries, want: str, invalid: str) -> Frame:
    """Read lines or points, from whatever form they come in, into a Frame.

    Multi-part lines become a row for each part. Geometries that are missing,
    empty, of the wrong kind or (for lines) without length are refused or dropped.
    """
    if invalid not in ("raise", "drop"):
        raise ValueError("invalid must be 'raise' or 'drop'")
    kind = LineArray if want == "lines" else PointArray
    if isinstance(data, Frame):
        if not isinstance(data[GEOM].array, kind):
            raise ValueError(f"expected {want}, in a table whose geometry is a {kind.__name__}")
        return with_geometry(data, data[GEOM].array, data.crs)
    if _is_arrow(data):
        from snkit.io import arrow_to_frame

        return arrow_to_frame(data, want, invalid)

    if isinstance(data, GeoDataFrame):
        table, geoms, crs = pd.DataFrame(data.drop(columns=data.geometry.name)), data.geometry.values, data.crs
    elif isinstance(data, GeoSeries):
        table, geoms, crs = pd.DataFrame(index=range(len(data))), data.values, data.crs
    else:
        geoms, crs = list(data), None
        table = pd.DataFrame(index=range(len(geoms)))
    geoms = np.empty(len(table), dtype=object) if len(table) == 0 else np.asarray(geoms, dtype=object)
    rows = np.arange(len(geoms))
    multi = shapely.get_type_id(geoms) == 5
    if want == "lines" and multi.any():
        # a row for each part, in place and in order
        parts, index = shapely.get_parts(geoms[multi], return_index=True)
        rows = np.concatenate([np.flatnonzero(~multi), np.flatnonzero(multi)[index]])
        order = np.argsort(rows, kind="stable")
        rows, geoms = rows[order], np.concatenate([geoms[~multi], parts])[order]
    geoms = shapely.force_2d(geoms)
    ok = ~shapely.is_missing(geoms)
    ok &= shapely.get_type_id(geoms) == (1 if want == "lines" else 0)
    ok &= ~shapely.is_empty(geoms)
    if want == "lines":
        ok &= shapely.length(geoms) > 0
    _refuse(int((~ok).sum()), want, invalid)
    return with_geometry(table.iloc[rows[ok]], kind.from_shapely(geoms[ok]), crs)


def _refuse(count: int, want: str, invalid: str) -> None:
    if count and invalid == "raise":
        what = "edges" if want == "lines" else "nodes"
        raise ValueError(
            f"{count} geometries are not usable as {what} (missing, empty, "
            "zero-length or the wrong type); pass invalid='drop' to discard them"
        )


def _set_ids(table: Frame, column: Optional[str]) -> Frame:
    """Give a table an unsigned integer ``id``.

    A column of unique non-negative integers is used as the id. Anything else
    is kept as an ordinary attribute and a new id is generated.
    """
    geoms, crs = table[GEOM].array, table.crs
    if column is None and ID in table.columns:
        column = ID
    table = pd.DataFrame(table)
    if column is not None:
        if column not in table.columns:
            raise ValueError(f"no column named {column!r}")
        values = table[column]
        usable = pd.api.types.is_integer_dtype(values) and not values.isna().any() and bool((values >= 0).all())
        if usable:
            if not values.is_unique:
                raise ValueError(f"ids in column {column!r} are not unique")
            ids = values.to_numpy(dtype="uint64")
            table = table.drop(columns=column)
            table[ID] = ids
            return with_geometry(table, geoms, crs)
        if column in RESERVED:
            table = table.rename(columns={column: f"{column}_original"})
    table[ID] = np.arange(len(table), dtype="uint64")
    return with_geometry(table, geoms, crs)


def _distinct(points: K.FloatArray) -> Tuple[K.FloatArray, K.IntArray]:
    """Distinct coordinates in order of first appearance, and the index of each input"""
    if len(points) == 0:
        return points.reshape(0, 2), np.zeros(0, dtype=np.int64)
    points = points + 0.0  # so that -0.0 and 0.0 are one place
    _, first, inverse = np.unique(points, axis=0, return_index=True, return_inverse=True)
    order = np.argsort(first, kind="stable")
    rank = np.empty(len(order), dtype=np.int64)
    rank[order] = np.arange(len(order))
    return points[first[order]], rank[np.ravel(inverse)]


def _edge_ends(coords: K.FloatArray, offsets: K.IntArray) -> K.FloatArray:
    ends = np.empty((2 * (len(offsets) - 1), 2))
    ends[0::2] = coords[offsets[:-1]]
    ends[1::2] = coords[offsets[1:] - 1]
    return ends


def from_edges(
    edges: Geometries,
    tolerance: float = 0,
    edge_id: Optional[str] = None,
    invalid: str = "raise",
) -> Network:
    """Create a network from lines, with a node at each distinct end point.

    Parameters
    ----------
    edges
        A GeoDataFrame, GeoSeries or sequence of line geometries. Multi-part
        lines become one edge per part.
    tolerance
        Join line ends that are within this distance of each other. By default
        ends are joined only where their coordinates are equal.
    edge_id
        Column to use as edge ids. It is used directly if it holds unique
        non-negative integers; otherwise it is kept as an attribute and
        integer ids are generated. Defaults to a column named ``id`` if any.
    invalid
        ``"raise"`` or ``"drop"`` geometries that are missing, empty,
        zero-length or not lines.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges([
    ...     LineString([(0, 0), (1, 0)]),
    ...     LineString([(1, 0), (2, 0)]),
    ...     LineString([(1, 0), (1, 1)]),
    ... ])
    >>> [point.wkt for point in network.nodes.geometry]
    ['POINT (0 0)', 'POINT (1 0)', 'POINT (2 0)', 'POINT (1 1)']
    >>> network.edges[["id", "from_id", "to_id"]].values.tolist()
    [[0, 0, 1], [1, 1, 2], [2, 1, 3]]
    """
    table = _set_ids(_read(edges, "lines", invalid), edge_id)
    lines, crs = lines_of(table), table.crs
    xy, index = _distinct(_edge_ends(lines.coords, lines.offsets))
    table[FROM] = index[0::2].astype("uint64")
    table[TO] = index[1::2].astype("uint64")
    nodes = with_geometry(pd.DataFrame({ID: np.arange(len(xy), dtype="uint64")}), PointArray(xy), crs)
    network = Network(nodes, with_geometry(table, lines, crs))
    if tolerance:
        from snkit.operations import merge_nodes

        network = merge_nodes(network, tolerance)  # type: ignore[assignment]
    return _like(network, _in_arrays(edges))  # type: ignore[no-any-return]


def from_nodes_and_edges(
    nodes: Geometries,
    edges: Geometries,
    tolerance: float = 0,
    node_id: Optional[str] = None,
    edge_id: Optional[str] = None,
    invalid: str = "raise",
) -> Network:
    """Create a network from points and lines that do not yet refer to each other.

    Each line end is attached to the nearest node within ``tolerance`` and
    moved exactly onto it. Ends with no node in reach get a new node.

    Examples
    --------
    >>> from shapely import LineString, Point
    >>> import snkit
    >>> network = snkit.from_nodes_and_edges(
    ...     [Point(0, 0), Point(1.001, 0)],
    ...     [LineString([(0, 0), (1, 0)]), LineString([(1, 0), (2, 0)])],
    ...     tolerance=0.01,
    ... )
    >>> [point.wkt for point in network.nodes.geometry]
    ['POINT (0 0)', 'POINT (1.001 0)', 'POINT (2 0)']
    >>> [line.wkt for line in network.edges.geometry]
    ['LINESTRING (0 0, 1.001 0)', 'LINESTRING (1.001 0, 2 0)']
    >>> network.edges[["from_id", "to_id"]].values.tolist()
    [[0, 1], [1, 2]]
    """
    node_table = _set_ids(_read(nodes, "points", invalid), node_id)
    edge_table = _set_ids(_read(edges, "lines", invalid), edge_id)
    crs = edge_table.crs if edge_table.crs is not None else node_table.crs
    if node_table.crs is not None and edge_table.crs is not None and node_table.crs != edge_table.crs:
        raise ValueError("nodes and edges have different CRS")
    check_distance(Network(node_table, edge_table), tolerance)

    xy = points_of(node_table).xy
    coords, offsets = to_ragged(lines_of(edge_table))
    ends = _edge_ends(coords, offsets)
    attached = K.nearest_points(ends, xy, tolerance)

    loose = attached < 0
    new_xy, new_index = _distinct(ends[loose])
    attached[loose] = len(xy) + new_index
    new_nodes = with_geometry(
        pd.DataFrame({ID: next_ids(node_table[ID].to_numpy(), len(new_xy))}), PointArray(new_xy), crs
    )
    node_table = append_rows(with_geometry(node_table, PointArray(xy), crs), new_nodes)
    all_xy = np.concatenate([xy, new_xy])
    src, dst = attached[0::2], attached[1::2]
    coords = K.sync_ends(coords, offsets, all_xy, src, dst)
    node_ids = node_table[ID].to_numpy(dtype="uint64")
    edge_table[FROM] = node_ids[src]
    edge_table[TO] = node_ids[dst]
    # an edge both of whose ends were moved onto one node may be left with no length
    has_length = K.line_measures(coords, offsets)[2] > 0
    _refuse(int((~has_length).sum()), "lines", invalid)
    edge_table = with_geometry(edge_table, from_ragged(coords, offsets), crs)
    edge_table = with_geometry(edge_table[has_length], lines_of(edge_table)[has_length], crs)
    return _like(Network(node_table, edge_table), _in_arrays(nodes, edges))  # type: ignore[no-any-return]


def from_topology(
    nodes: GeoDataFrame,
    edges: GeoDataFrame,
    tolerance: float = 0,
    node_id: str = ID,
    from_id: str = FROM,
    to_id: str = TO,
    edge_id: Optional[str] = None,
) -> Network:
    """Create a network from tables that already refer to each other by id.

    Use this for data that has node ids and from/to columns of any type, for
    example a network made by earlier versions of snkit. Ids are converted to
    unsigned integers; ids that are not already non-negative integers are kept
    as ordinary attributes (suffixed ``_original`` where the name is taken).

    Each edge end must lie within ``tolerance`` of its node, and is moved
    exactly onto it.

    Examples
    --------
    >>> import geopandas
    >>> from shapely import LineString, Point
    >>> import snkit
    >>> nodes = geopandas.GeoDataFrame(
    ...     {"id": ["a", "b"]}, geometry=[Point(0, 0), Point(1, 0)])
    >>> edges = geopandas.GeoDataFrame(
    ...     {"from_id": ["a"], "to_id": ["b"]}, geometry=[LineString([(0, 0), (1, 0)])])
    >>> network = snkit.from_topology(nodes, edges)
    >>> network.nodes[["id", "id_original"]].values.tolist()
    [[0, 'a'], [1, 'b']]
    >>> network.edges[["id", "from_id", "to_id"]].values.tolist()
    [[0, 0, 1]]
    """
    original = _read(nodes, "points", "raise")
    if node_id not in original.columns:
        raise ValueError(f"nodes have no column named {node_id!r}")
    keys = pd.Index(original[node_id])
    if not keys.is_unique:
        raise ValueError(f"node ids in column {node_id!r} are not unique")
    node_table = _set_ids(original, node_id)
    edge_table = _read(edges, "lines", "raise")
    edge_lines, edge_crs = lines_of(edge_table), edge_table.crs
    for column in (from_id, to_id):
        if column not in edge_table.columns:
            raise ValueError(f"edges have no column named {column!r}")
    src = keys.get_indexer(edge_table[from_id])
    dst = keys.get_indexer(edge_table[to_id])
    if (src < 0).any() or (dst < 0).any():
        raise ValueError("edges refer to node ids that are not in the nodes table")
    node_ids = node_table[ID].to_numpy(dtype="uint64")
    converted = not np.array_equal(node_ids, np.asarray(keys))
    renames = {}
    for column in (from_id, to_id):
        if converted:
            renames[column] = f"{column}_original" if column in RESERVED else column
    edge_table = pd.DataFrame(edge_table).rename(columns=renames)
    if not converted:
        edge_table = edge_table.drop(columns=[c for c in (from_id, to_id) if c not in RESERVED])
    edge_table[FROM] = node_ids[src]
    edge_table[TO] = node_ids[dst]
    edge_table = _set_ids(with_geometry(edge_table, edge_lines, edge_crs), edge_id)

    check_distance(Network(node_table, edge_table), tolerance)
    xy = points_of(node_table).xy
    coords, offsets = to_ragged(lines_of(edge_table))
    ends = _edge_ends(coords, offsets)
    gap = np.hypot(*(ends - xy[np.column_stack([src, dst]).ravel()]).T)
    if len(gap) and gap.max() > tolerance:
        raise ValueError(
            f"{int((gap > tolerance).sum())} edge ends are further than tolerance from "
            f"their node (the furthest is {gap.max():g} away): pass a larger tolerance "
            "to move them onto their nodes"
        )
    coords = K.sync_ends(coords, offsets, xy, src, dst)
    edge_table = with_geometry(edge_table, from_ragged(coords, offsets), edge_crs)
    return _like(Network(node_table, edge_table), _in_arrays(nodes, edges))  # type: ignore[no-any-return]


def validate(network: Network, raise_errors: bool = False) -> List[str]:
    """Check that a network is topological. Returns a list of problems, empty if valid.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> snkit.validate(snkit.from_edges([LineString([(0, 0), (1, 0)])]))
    []
    """
    problems: List[str] = []
    nodes, edges = network.nodes, network.edges
    for name, table, columns in (("nodes", nodes, (ID,)), ("edges", edges, RESERVED)):
        for column in columns:
            if column not in table.columns:
                problems.append(f"{name} have no '{column}' column")
            elif table[column].dtype != np.dtype("uint64"):
                problems.append(f"{name} '{column}' is not an unsigned integer column")
    if not problems:
        if not nodes[ID].is_unique:
            problems.append("node ids are not unique")
        if not edges[ID].is_unique:
            problems.append("edge ids are not unique")
        known = pd.Index(nodes[ID])
        dangling = ~edges[FROM].isin(known) | ~edges[TO].isin(known)
        if dangling.any():
            problems.append(f"{int(dangling.sum())} edges refer to nodes that do not exist")
    if len(nodes) and len(edges) and nodes.crs != edges.crs:
        problems.append("nodes and edges have different CRS")
    if not is_arrays(network):  # geometry held in arrays is points and lines by construction
        points, lines = geometry_array(nodes), geometry_array(edges)
        bad_points = shapely.is_missing(points) | (shapely.get_type_id(points) != 0)
        bad_points |= shapely.is_empty(points)
        if bad_points.any():
            problems.append(f"{int(bad_points.sum())} node geometries are not non-empty Points")
        bad_lines = shapely.is_missing(lines) | (shapely.get_type_id(lines) != 1)
        bad_lines |= shapely.is_empty(lines)
        if bad_lines.any():
            problems.append(f"{int(bad_lines.sum())} edge geometries are not non-empty LineStrings")
    if not problems and len(edges):
        arrays = Arrays(network)
        ends = _edge_ends(arrays.coords, arrays.offsets)
        expected = arrays.xy[np.column_stack([arrays.src, arrays.dst]).ravel()]
        off = (ends != expected).any(axis=1)
        if off.any():
            problems.append(f"{int(off.sum())} edge ends are not exactly at the position of their node")
    if problems and raise_errors:
        raise ValueError("not a valid network: " + "; ".join(problems))
    return problems
