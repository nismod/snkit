"""Reading and writing networks as Arrow.

Everything here deals in Arrow record batches with geometry as GeoArrow or
WKB, and hands them to the kernel as a stream. That keeps the choice of
reader open. Anything that offers an Arrow stream can feed snkit:

- :func:`read_parquet` reads GeoParquet with pyarrow. Given a bounding box,
  it uses the statistics kept for each row group to skip those that cannot
  hold anything in the box.
- :func:`read` also reads the formats GDAL knows (GeoPackage, FlatGeobuf,
  Shapefile, ...) through pyogrio. Given a bounding box, GDAL uses the
  spatial index of the format where it has one.
- A query engine such as SedonaDB or DuckDB gives results as an Arrow stream,
  which can be passed straight to :func:`snkit.from_edges` or
  :func:`snkit.build_network`.

pyarrow is needed for this module: ``pip install snkit[arrow]``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from snkit import _native
from snkit.arrays import GEOM, ArrayNetwork, Frame, LineArray, PointArray, with_geometry
from snkit.network import Network

PathLike = Union[str, Path]
Box = Sequence[float]
EXTENSION = "ARROW:extension:name"
EXTENSION_METADATA = "ARROW:extension:metadata"


def _pyarrow() -> Any:
    try:
        import pyarrow
    except ImportError as error:  # pragma: no cover
        raise ImportError("this needs pyarrow: pip install snkit[arrow]") from error
    return pyarrow


def geometry_field(schema: Any, column: Optional[str] = None) -> str:
    """The name of the geometry column of an Arrow schema"""
    if column is not None:
        if column not in schema.names:
            raise ValueError(f"no column named {column!r}")
        return column
    for field in schema:
        name = (field.metadata or {}).get(EXTENSION.encode(), b"").decode()
        if name.startswith("geoarrow.") or name == "ogc.wkb":
            return str(field.name)
    geo = _geo_metadata(schema)
    if geo.get("primary_column") in schema.names:
        return str(geo["primary_column"])
    for name in ("geometry", "geom", "wkb_geometry"):
        if name in schema.names:
            return name
    raise ValueError("no geometry column found: name it with column=")


def _geo_metadata(schema: Any) -> Dict[str, Any]:
    raw = (schema.metadata or {}).get(b"geo")
    return json.loads(raw) if raw else {}


def _crs(schema: Any, name: str) -> Any:
    """The coordinate reference system recorded for a geometry column, if any"""
    import pyproj

    field_metadata = schema.field(name).metadata or {}
    described = json.loads(field_metadata.get(EXTENSION_METADATA.encode(), b"{}") or b"{}")
    crs = described.get("crs")
    if crs is None:
        column = _geo_metadata(schema).get("columns", {}).get(name)
        if column is not None:
            # GeoParquet: no crs recorded means longitude and latitude
            crs = column.get("crs", "OGC:CRS84")
    return None if crs is None else pyproj.CRS.from_user_input(crs)


def _table(data: Any) -> Any:
    pa = _pyarrow()
    return data if isinstance(data, pa.Table) else pa.table(data)


def reader(data: Any) -> Any:
    """Arrow data of any kind as a :class:`pyarrow.RecordBatchReader`, read as it is used where possible"""
    pa = _pyarrow()
    if isinstance(data, pa.RecordBatchReader):
        return data
    if hasattr(pa.RecordBatchReader, "from_stream"):
        return pa.RecordBatchReader.from_stream(data)
    return pa.table(data).to_reader()  # older pyarrow: read it all first


def plain(table: Any) -> Any:
    """A table with any string-view or binary-view columns (which query engines
    produce, and pyarrow cannot yet reorder) as ordinary strings and binary"""
    pa = _pyarrow()
    fields = []
    for field in table.schema:
        if str(field.type) == "string_view":
            field = field.with_type(pa.large_string())
        elif str(field.type) == "binary_view":
            field = field.with_type(pa.large_binary())
        fields.append(field)
    schema = pa.schema(fields, table.schema.metadata)
    return table if schema.equals(table.schema) else table.cast(schema)


def arrow_to_frame(data: Any, want: str, invalid: str = "raise", column: Optional[str] = None) -> Frame:
    """Read Arrow data into a Frame, decoding its geometry in the kernel.

    ``data`` is a table, a record batch reader, or anything else that offers
    an Arrow stream. Multi-part lines become a row for each part.
    """
    from snkit.core import _refuse

    table = _table(data)
    name = geometry_field(table.schema, column)
    coords, offsets, row, bad, rows = _native.read_geometry(table.select([name]), want, name)
    _refuse(len(bad), want, invalid)
    attributes = plain(table.drop_columns([name] + _covering(table.schema, name)))
    if len(row) != rows or len(bad):
        attributes = attributes.take(row)
    geometry = LineArray(coords, offsets) if want == "lines" else PointArray(coords)
    return with_geometry(attributes.to_pandas(ignore_metadata=True), geometry, _crs(table.schema, name))


def _covering(schema: Any, name: str) -> List[str]:
    """Columns that only repeat the bounding box of each geometry"""
    covering = _geo_metadata(schema).get("columns", {}).get(name, {}).get("covering", {}).get("bbox", {})
    columns = {path[0] for path in covering.values() if path}
    return [c for c in columns if c in schema.names]


def geometry_array(geometry: Any, encoding: str = "interleaved", crs: Any = None) -> Tuple[Any, Any]:
    """A LineArray or PointArray as a GeoArrow array and the field describing it"""
    pa = _pyarrow()
    if encoding not in ("interleaved", "separated"):
        raise ValueError("encoding must be 'interleaved' or 'separated'")
    lines = isinstance(geometry, LineArray)
    xy = geometry.coords if lines else geometry.xy
    if encoding == "interleaved":
        vertices = pa.FixedSizeListArray.from_arrays(
            pa.array(xy.reshape(-1)), type=pa.list_(pa.field("xy", pa.float64(), False), 2)
        )
    else:
        columns = [pa.array(np.ascontiguousarray(xy[:, 0])), pa.array(np.ascontiguousarray(xy[:, 1]))]
        fields = [pa.field("x", pa.float64(), False), pa.field("y", pa.float64(), False)]
        vertices = pa.StructArray.from_arrays(columns, fields=fields)
    if lines:
        item = pa.field("vertices", vertices.type, False)
        if len(xy) < 2**31:
            array = pa.ListArray.from_arrays(pa.array(geometry.offsets.astype(np.int32)), vertices, type=pa.list_(item))
        else:
            array = pa.LargeListArray.from_arrays(pa.array(geometry.offsets), vertices, type=pa.large_list(item))
    else:
        array = vertices
    metadata = {EXTENSION: "geoarrow.linestring" if lines else "geoarrow.point"}
    metadata[EXTENSION_METADATA] = json.dumps({} if crs is None else {"crs": json.loads(crs.to_json())})
    return array, pa.field(GEOM, array.type, False, metadata)


def frame_to_arrow(frame: Frame, encoding: str = "interleaved") -> Any:
    """A Frame as a :class:`pyarrow.Table` with GeoArrow geometry"""
    pa = _pyarrow()
    table = pa.Table.from_pandas(pd.DataFrame(frame).drop(columns=GEOM), preserve_index=False)
    array, field = geometry_array(frame[GEOM].array, encoding, frame.crs)
    return table.append_column(field, array).replace_schema_metadata(None)


def geo_metadata(kind: str, crs: Any, bounds: Optional[Box] = None) -> bytes:
    """The ``geo`` entry that makes a Parquet file GeoParquet, for points or lines stored natively"""
    column: Dict[str, Any] = {
        "encoding": "linestring" if kind == "lines" else "point",
        "geometry_types": ["LineString" if kind == "lines" else "Point"],
    }
    if crs is not None:
        column["crs"] = json.loads(crs.to_json())
    else:
        column["crs"] = None  # recorded as unknown, where absent would mean longitude and latitude
    if bounds is not None and np.isfinite(bounds).all():
        column["bbox"] = [float(v) for v in bounds]
    return json.dumps({"version": "1.1.0", "primary_column": GEOM, "columns": {GEOM: column}}).encode()


def _along_curve(xy: Any) -> Any:
    """Order places along a space-filling curve, so that those near in order are near in space"""
    if len(xy) == 0:
        return np.zeros(0, dtype=np.int64)
    low, high = xy.min(axis=0), xy.max(axis=0)
    cell = ((xy - low) / np.where(high > low, high - low, 1) * 65535).astype(np.uint64)
    key = np.zeros(len(xy), dtype=np.uint64)
    for bit in range(16):  # interleave the bits of x and y
        key |= ((cell[:, 0] >> np.uint64(bit)) & np.uint64(1)) << np.uint64(2 * bit)
        key |= ((cell[:, 1] >> np.uint64(bit)) & np.uint64(1)) << np.uint64(2 * bit + 1)
    return np.argsort(key, kind="stable")


def write_parquet(table: Frame, path: PathLike, row_group_size: int = 50_000, sort: bool = True) -> None:
    """Write a Frame as GeoParquet.

    Geometry is stored natively, as ``x`` and ``y`` columns, so that the file
    keeps the range of each for every row group. With ``sort`` (the default)
    rows are first put in order along a space-filling curve, so that each row
    group covers a small area and those ranges are useful: :func:`read_parquet`
    can then find the part of a large network in a bounding box without
    reading the rest.
    """
    import pyarrow.parquet as pq

    geometry = table[GEOM].array
    lines = isinstance(geometry, LineArray)
    if sort and len(table):
        place = geometry.coords[geometry.offsets[:-1]] if lines else geometry.xy
        order = _along_curve(place)
        table = with_geometry(pd.DataFrame(table).iloc[order], geometry.take(order), table.crs)
        geometry = table[GEOM].array
    xy = geometry.coords if lines else geometry.xy
    bounds = [*xy.min(axis=0), *xy.max(axis=0)] if len(xy) else None
    arrow = frame_to_arrow(table, "separated")
    arrow = arrow.replace_schema_metadata({b"geo": geo_metadata("lines" if lines else "points", table.crs, bounds)})
    pq.write_table(arrow, path, row_group_size=row_group_size)


def _bbox_statistics(file: Any, name: str) -> Optional[Dict[str, int]]:
    """Which columns of a Parquet file hold the range of x and y, if any do.

    Either the file says so (a GeoParquet covering), or the geometry is stored
    natively and its own ``x`` and ``y`` columns serve.
    """
    paths = [file.schema.column(i).path for i in range(len(file.schema.names))]
    covering = _geo_metadata(file.schema_arrow).get("columns", {}).get(name, {}).get("covering", {}).get("bbox")
    if covering and all(".".join(covering[k]) in paths for k in ("xmin", "ymin", "xmax", "ymax")):
        return {k: paths.index(".".join(covering[k])) for k in ("xmin", "ymin", "xmax", "ymax")}
    x = [i for i, p in enumerate(paths) if p.split(".")[0] == name and p.endswith(".x")]
    y = [i for i, p in enumerate(paths) if p.split(".")[0] == name and p.endswith(".y")]
    if len(x) == 1 and len(y) == 1:
        return {"xmin": x[0], "ymin": y[0], "xmax": x[0], "ymax": y[0]}
    return None


def parquet_row_groups(path: PathLike, column: Optional[str] = None) -> pd.DataFrame:
    """The row groups of a GeoParquet file: how many rows each has and, where
    the file records it, the bounding box of each.

    Returns a table with columns ``rows``, ``xmin``, ``ymin``, ``xmax``,
    ``ymax``; the box is NaN where the file has no statistics for it.
    """
    import pyarrow.parquet as pq

    file = pq.ParquetFile(path)
    name = geometry_field(file.schema_arrow, column)
    where = _bbox_statistics(file, name)
    out = []
    for g in range(file.metadata.num_row_groups):
        group = file.metadata.row_group(g)
        box = [np.nan] * 4
        if where is not None:
            stats = [group.column(where[k]).statistics for k in ("xmin", "ymin", "xmax", "ymax")]
            if all(s is not None and s.has_min_max for s in stats):
                box = [stats[0].min, stats[1].min, stats[2].max, stats[3].max]
        out.append([group.num_rows, *box])
    return pd.DataFrame(out, columns=["rows", "xmin", "ymin", "xmax", "ymax"])


def _in_box(batch: Any, name: str, bbox: Box) -> Any:
    """The rows of a table whose geometry reaches into a bounding box"""
    boxes = _native.geometry_bounds(batch.select([name]), name)
    keep = (boxes[:, 0] <= bbox[2]) & (boxes[:, 2] >= bbox[0]) & (boxes[:, 1] <= bbox[3]) & (boxes[:, 3] >= bbox[1])
    return batch if keep.all() else batch.filter(_pyarrow().array(keep))


def read_parquet(
    path: PathLike, bbox: Optional[Box] = None, columns: Optional[Sequence[str]] = None, column: Optional[str] = None
) -> Any:
    """Read a GeoParquet file as a stream of Arrow record batches.

    Parameters
    ----------
    bbox
        ``(xmin, ymin, xmax, ymax)``: read only rows whose geometry reaches
        into this box. Row groups that the file's statistics show to lie
        outside it are not read at all.
    columns
        Attribute columns to read, by default all. Geometry is always read.
    column
        The geometry column, if the file does not say which it is.

    Returns
    -------
    pyarrow.RecordBatchReader
        One batch for each row group read.
    """
    import pyarrow.parquet as pq

    pa = _pyarrow()
    file = pq.ParquetFile(path)
    name = geometry_field(file.schema_arrow, column)
    groups = parquet_row_groups(path, name)
    wanted = np.ones(len(groups), dtype=bool)
    if bbox is not None:
        known = groups["xmin"].notna().to_numpy()
        outside = (
            (groups["xmin"] > bbox[2])
            | (groups["xmax"] < bbox[0])
            | (groups["ymin"] > bbox[3])
            | (groups["ymax"] < bbox[1])
        )
        wanted = ~(known & outside.to_numpy())
    names = None if columns is None else list(dict.fromkeys([*columns, name]))
    schema = (
        file.schema_arrow
        if names is None
        else pa.schema([file.schema_arrow.field(n) for n in names], file.schema_arrow.metadata)
    )

    def batches() -> Iterator[Any]:
        for g in np.flatnonzero(wanted):
            table = file.read_row_group(int(g), columns=names).cast(schema)
            if bbox is not None:
                table = _in_box(table, name, bbox)
            yield from table.combine_chunks().to_batches()

    return pa.RecordBatchReader.from_batches(schema, batches())


def read(
    path: PathLike,
    layer: Optional[str] = None,
    bbox: Optional[Box] = None,
    columns: Optional[Sequence[str]] = None,
    **kwargs: Any,
) -> Any:
    """Read a geographic data file as a stream of Arrow record batches.

    GeoParquet is read by :func:`read_parquet`. Any other format is read by
    GDAL through pyogrio, which passes ``bbox`` to GDAL to use the spatial
    index of the format where there is one (the R-tree of a GeoPackage, the
    packed tree of a FlatGeobuf, the ``.qix`` of a Shapefile, ...). Extra
    keyword arguments go to :func:`pyogrio.raw.open_arrow`.

    Returns a :class:`pyarrow.RecordBatchReader`, to pass to
    :func:`snkit.from_edges` and the like, or to :func:`snkit.build_network`.
    """
    pa = _pyarrow()
    if str(path).lower().endswith((".parquet", ".geoparquet", ".pq")):
        return read_parquet(path, bbox, columns)
    import pyogrio

    source = pyogrio.raw.open_arrow(
        path, layer=layer, bbox=None if bbox is None else tuple(bbox), columns=columns, use_pyarrow=True, **kwargs
    )
    meta, reader = source.__enter__()
    name = meta.get("geometry_name") or "wkb_geometry"
    described = json.dumps({} if not meta.get("crs") else {"crs": meta["crs"]})
    fields = [
        f.with_metadata({EXTENSION: "geoarrow.wkb", EXTENSION_METADATA: described}) if f.name == name else f
        for f in reader.schema
    ]
    schema = pa.schema(fields)

    def batches() -> Iterator[Any]:
        try:
            for batch in reader:
                yield pa.RecordBatch.from_arrays(batch.columns, schema=schema)
        finally:
            source.__exit__(None, None, None)

    return pa.RecordBatchReader.from_batches(schema, batches())


def read_network(nodes: Any, edges: Any, tolerance: float = 0) -> ArrayNetwork:
    """Read a network that was written with ids, as an :class:`snkit.ArrayNetwork`.

    ``nodes`` and ``edges`` are each a path (read with :func:`read`) or Arrow
    data. The tables must have ``id``, and edges ``from_id`` and ``to_id``, as
    written by :meth:`snkit.ArrayNetwork.to_parquet` or :func:`snkit.build_network`.
    """
    from snkit.core import from_topology

    opened = [read(item) if isinstance(item, (str, Path)) else item for item in (nodes, edges)]
    network: Network = from_topology(opened[0], opened[1], tolerance)
    return ArrayNetwork(network.nodes, network.edges)
