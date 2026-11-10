"""Networks with their geometry held in arrays.

A :class:`geopandas.GeoDataFrame` keeps one Python object for every geometry.
That is convenient and, for a large network, costly: most of the memory of a
network held that way is those objects. Here geometry is kept as the kernel
wants it - one array of coordinates for all the lines, with offsets marking
where each begins - inside an ordinary column of an ordinary table.

- :class:`LineArray` and :class:`PointArray` are column types for pandas.
- :class:`Frame` is a :class:`pandas.DataFrame` with a ``geometry`` column of
  one of those types and a ``crs``.
- :class:`ArrayNetwork` is a network whose nodes and edges are Frames. Every
  operation accepts one, and gives one back.

Arrow is the way in and out: an ArrayNetwork is made from any Arrow data
(:func:`snkit.from_edges` takes a table, a record batch reader, or anything
else that offers an Arrow stream) and gives Arrow tables with GeoArrow geometry.
"""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Optional, Sequence, Tuple, TypeVar

import numpy as np
import pandas as pd
import shapely
from geopandas import GeoDataFrame, GeoSeries
from pandas.api.extensions import ExtensionArray, ExtensionDtype, register_extension_dtype

from snkit.network import Network

GEOM = "geometry"
RESERVED = ("id", "from_id", "to_id")
F = TypeVar("F", bound=Callable[..., Any])


class _GeometryDtype(ExtensionDtype):
    type = object
    na_value = None

    @classmethod
    def construct_from_string(cls, string: str) -> Any:
        if string == cls.name:
            return cls()
        raise TypeError(f"cannot construct a {cls.__name__} from '{string}'")


@register_extension_dtype
class LineDtype(_GeometryDtype):
    name = "snkit.linestring"

    @classmethod
    def construct_array_type(cls) -> Any:
        return LineArray


@register_extension_dtype
class PointDtype(_GeometryDtype):
    name = "snkit.point"

    @classmethod
    def construct_array_type(cls) -> Any:
        return PointArray


class _GeometryArray(ExtensionArray):
    """What the two array types share: no missing values, no changing in place"""

    def isna(self) -> Any:
        return np.zeros(len(self), dtype=bool)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, (int, np.integer)):
            return self._one(int(item) + (len(self) if item < 0 else 0))
        item = pd.api.indexers.check_array_indexer(self, item)
        return self.take(np.arange(len(self))[item])

    def __setitem__(self, key: Any, value: Any) -> None:
        raise TypeError("geometry held in arrays cannot be changed in place")

    def __eq__(self, other: Any) -> Any:  # type: ignore[override]
        return np.asarray(self.to_shapely() == np.asarray(other, dtype=object), dtype=bool)

    def _formatter(self, boxed: bool = False) -> Callable[[Any], str]:
        return lambda geom: geom.wkt

    def _one(self, i: int) -> Any:
        raise NotImplementedError

    def to_shapely(self) -> Any:
        raise NotImplementedError

    def __arrow_array__(self, type: Any = None) -> Any:
        """As a GeoArrow array, sharing the coordinate memory (how pyarrow converts a column)"""
        from snkit.io import geometry_array

        return geometry_array(self)[0]

    def _checked(self, indices: Any, allow_fill: bool) -> Any:
        indices = np.asarray(indices, dtype=np.int64)
        if allow_fill and len(indices) and indices.min() < 0:
            raise ValueError("a table of this kind cannot hold a row without geometry")
        if len(indices) and (indices.max() >= len(self) or indices.min() < -len(self)):
            raise IndexError("position out of bounds")
        return np.where(indices < 0, indices + len(self), indices)

    @classmethod
    def _from_factorized(cls, values: Any, original: Any) -> Any:
        raise TypeError("geometry cannot be factorized")


class LineArray(_GeometryArray):
    """Lines, as one array of coordinates and the offset at which each line starts"""

    def __init__(self, coords: Any, offsets: Any):
        self.coords = np.ascontiguousarray(coords, dtype=float).reshape(-1, 2)
        self.offsets = np.ascontiguousarray(offsets, dtype=np.int64)

    dtype = LineDtype()

    def __len__(self) -> int:
        return len(self.offsets) - 1

    @property
    def nbytes(self) -> int:
        return int(self.coords.nbytes + self.offsets.nbytes)

    def _one(self, i: int) -> Any:
        return shapely.LineString(self.coords[self.offsets[i] : self.offsets[i + 1]])

    def take(self, indices: Any, allow_fill: bool = False, fill_value: Any = None) -> "LineArray":
        indices = self._checked(indices, allow_fill)
        counts = self.offsets[indices + 1] - self.offsets[indices]
        offsets = np.zeros(len(indices) + 1, dtype=np.int64)
        np.cumsum(counts, out=offsets[1:])
        # each new vertex position, less the start of its line in the new array, plus its start in the old
        vertex = np.arange(offsets[-1]) + np.repeat(self.offsets[indices] - offsets[:-1], counts)
        return LineArray(self.coords[vertex], offsets)

    def copy(self) -> "LineArray":
        return LineArray(self.coords.copy(), self.offsets.copy())

    @classmethod
    def _concat_same_type(cls, to_concat: Sequence["LineArray"]) -> "LineArray":
        shift = np.cumsum([0] + [len(a.coords) for a in to_concat])
        offsets = [a.offsets[:-1] + s for a, s in zip(to_concat, shift)] + [shift[-1:]]
        return LineArray(np.concatenate([a.coords for a in to_concat]), np.concatenate(offsets))

    @classmethod
    def _from_sequence(cls, scalars: Any, *, dtype: Any = None, copy: bool = False) -> "LineArray":
        return cls.from_shapely(np.asarray(scalars, dtype=object))

    @classmethod
    def from_shapely(cls, lines: Any) -> "LineArray":
        if isinstance(lines, LineArray):
            return lines
        if len(lines) == 0:
            return LineArray(np.empty((0, 2)), np.zeros(1, dtype=np.int64))
        kind, coords, offsets = shapely.to_ragged_array(np.asarray(lines, dtype=object), include_z=False)
        if kind != shapely.GeometryType.LINESTRING:
            raise ValueError("edge geometries must all be LineStrings")
        return LineArray(coords, offsets[0])

    def to_shapely(self) -> Any:
        if len(self) == 0:
            return np.empty(0, dtype=object)
        return shapely.from_ragged_array(shapely.GeometryType.LINESTRING, self.coords, (self.offsets,))


class PointArray(_GeometryArray):
    """Points, as an array of coordinates"""

    def __init__(self, xy: Any):
        self.xy = np.ascontiguousarray(xy, dtype=float).reshape(-1, 2)

    dtype = PointDtype()

    def __len__(self) -> int:
        return len(self.xy)

    @property
    def nbytes(self) -> int:
        return int(self.xy.nbytes)

    def _one(self, i: int) -> Any:
        return shapely.Point(self.xy[i])

    def take(self, indices: Any, allow_fill: bool = False, fill_value: Any = None) -> "PointArray":
        return PointArray(self.xy[self._checked(indices, allow_fill)])

    def copy(self) -> "PointArray":
        return PointArray(self.xy.copy())

    @classmethod
    def _concat_same_type(cls, to_concat: Sequence["PointArray"]) -> "PointArray":
        return PointArray(np.concatenate([a.xy for a in to_concat]))

    @classmethod
    def _from_sequence(cls, scalars: Any, *, dtype: Any = None, copy: bool = False) -> "PointArray":
        return cls.from_shapely(np.asarray(scalars, dtype=object))

    @classmethod
    def from_shapely(cls, points: Any) -> "PointArray":
        if isinstance(points, PointArray):
            return points
        points = np.asarray(points, dtype=object)
        if len(points) and not (shapely.get_type_id(points) == 0).all():
            raise ValueError("node geometries must all be Points")
        return PointArray(shapely.get_coordinates(points))

    def to_shapely(self) -> Any:
        return shapely.points(self.xy)


class Frame(pd.DataFrame):
    """A table with a ``geometry`` column held in arrays, and a ``crs``"""

    _metadata = ["crs"]
    crs: Any = None

    @property
    def _constructor(self) -> Any:
        return Frame

    @property
    def geometry(self) -> Any:
        return self[GEOM]

    def to_geopandas(self) -> GeoDataFrame:
        """The same table as a GeoDataFrame, with a geometry object for each row"""
        table = pd.DataFrame(self).drop(columns=GEOM)
        return GeoDataFrame(table, geometry=GeoSeries(self[GEOM].array.to_shapely(), crs=self.crs), crs=self.crs)

    def to_arrow(self, encoding: str = "interleaved") -> Any:
        """The same table as a :class:`pyarrow.Table` with GeoArrow geometry.

        ``"interleaved"`` shares the coordinate memory with this table.
        ``"separated"`` copies it into ``x`` and ``y`` arrays, which is the
        form GeoParquet stores and keeps statistics on.
        """
        from snkit.io import frame_to_arrow

        return frame_to_arrow(self, encoding)

    def __arrow_c_stream__(self, requested_schema: Any = None) -> Any:
        return self.to_arrow().__arrow_c_stream__(requested_schema)


def with_geometry(table: Any, geoms: Any, crs: Any) -> Frame:
    """Rebuild a table as a Frame with new geometries, id columns first"""
    if not isinstance(geoms, _GeometryArray):
        raise TypeError("geometry must be a LineArray or PointArray")
    table = pd.DataFrame(table).reset_index(drop=True)
    if GEOM in table.columns:
        table = table.drop(columns=GEOM)
    front = [c for c in RESERVED if c in table.columns]
    frame = Frame(table[front + [c for c in table.columns if c not in front]])
    frame[GEOM] = geoms
    frame.crs = crs
    return frame


def _geometry(table: Any, kind: Any) -> Any:
    if isinstance(table, GeoDataFrame):
        return kind.from_shapely(np.asarray(table.geometry.values, dtype=object))
    column = table[GEOM].array
    if not isinstance(column, kind):
        raise ValueError(f"expected a geometry column holding a {kind.__name__}")
    return column


def lines_of(table: Any) -> LineArray:
    """The geometry of an edges table, as arrays"""
    return _geometry(table, LineArray)  # type: ignore[no-any-return]


def points_of(table: Any) -> PointArray:
    """The geometry of a nodes table, as arrays"""
    return _geometry(table, PointArray)  # type: ignore[no-any-return]


def crs_of(network: Network) -> Any:
    return network.edges.crs if len(network.edges) else network.nodes.crs


class ArrayNetwork(Network):
    """A network whose geometry is held in arrays.

    ``nodes`` and ``edges`` are :class:`Frame` tables. Every operation in snkit
    that takes a network takes one of these, and returns one; nothing is
    converted to geometry objects along the way.

    Make one from Arrow data with :func:`snkit.from_edges` and the other
    creation functions, from files with :func:`snkit.read_network`, or from a
    network of GeoDataFrames with :func:`snkit.to_arrays`.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.to_arrays(snkit.from_edges(
    ...     [LineString([(0, 0), (2, 2)]), LineString([(0, 2), (2, 0)])]))
    >>> split = snkit.split_edges_at_crossings(network)
    >>> type(split).__name__, len(split.edges)
    ('ArrayNetwork', 4)
    >>> split.edges.geometry[0].wkt
    'LINESTRING (0 0, 1 1)'
    >>> split.to_geopandas().edges.geometry.length.round(3).tolist()
    [1.414, 1.414, 1.414, 1.414]
    """

    def __init__(self, nodes: Optional[Frame] = None, edges: Optional[Frame] = None):
        crs = None
        for table in (edges, nodes):
            if table is not None and getattr(table, "crs", None) is not None:
                crs = table.crs
        self.nodes = with_geometry(pd.DataFrame(), PointArray(np.empty((0, 2))), crs) if nodes is None else nodes
        if edges is None:
            edges = with_geometry(pd.DataFrame(), LineArray(np.empty((0, 2)), np.zeros(1, dtype=np.int64)), crs)
        self.edges = edges

    def to_geopandas(self) -> Network:
        """The same network with GeoDataFrames for nodes and edges"""
        return Network(self.nodes.to_geopandas(), self.edges.to_geopandas())

    def to_arrow(self, encoding: str = "interleaved") -> Tuple[Any, Any]:
        """The nodes and edges as :class:`pyarrow.Table` with GeoArrow geometry"""
        return self.nodes.to_arrow(encoding), self.edges.to_arrow(encoding)

    def set_crs(self, crs: Any = None, epsg: Optional[int] = None, allow_override: bool = False) -> None:
        """Say what coordinate reference system the coordinates are in"""
        import pyproj

        new = pyproj.CRS.from_user_input(crs) if crs is not None else pyproj.CRS.from_epsg(epsg)
        for table in (self.nodes, self.edges):
            if table.crs is not None and table.crs != new and not allow_override:
                raise ValueError("the network already has a different CRS: pass allow_override=True to replace it")
            table.crs = new

    def to_crs(self, crs: Any = None, epsg: Optional[int] = None) -> None:
        """Transform all coordinates to another coordinate reference system"""
        import pyproj

        new = pyproj.CRS.from_user_input(crs) if crs is not None else pyproj.CRS.from_epsg(epsg)
        if crs_of(self) is None:
            raise ValueError("the network has no CRS to transform from: use set_crs first")
        transform = pyproj.Transformer.from_crs(crs_of(self), new, always_xy=True).transform
        nodes, lines = points_of(self.nodes), lines_of(self.edges)
        xy = np.column_stack(transform(nodes.xy[:, 0], nodes.xy[:, 1])) if len(nodes) else nodes.xy
        coords = (
            np.column_stack(transform(lines.coords[:, 0], lines.coords[:, 1])) if len(lines.coords) else lines.coords
        )
        self.nodes = with_geometry(self.nodes, PointArray(xy), new)
        self.edges = with_geometry(self.edges, LineArray(coords, lines.offsets), new)

    def to_file(
        self, filename: Any, nodes_layer: Optional[str] = "nodes", edges_layer: Optional[str] = "edges", **kwargs: Any
    ) -> None:
        """Write nodes and edges to a geographic data file with layers, by way of GeoPandas"""
        self.to_geopandas().to_file(filename, nodes_layer, edges_layer, **kwargs)

    def to_parquet(self, nodes_path: Any, edges_path: Any, **kwargs: Any) -> None:
        """Write nodes and edges to two GeoParquet files (see :func:`snkit.io.write_parquet`)"""
        from snkit.io import write_parquet

        write_parquet(self.nodes, nodes_path, **kwargs)
        write_parquet(self.edges, edges_path, **kwargs)


def to_arrays(network: Network) -> ArrayNetwork:
    """Hold a network's geometry in arrays (see :class:`ArrayNetwork`).

    The network must be made only of points and single lines, as one made by
    :func:`snkit.from_edges` and the other creation functions is.
    """
    if isinstance(network, ArrayNetwork):
        return network
    return ArrayNetwork(
        with_geometry(network.nodes, points_of(network.nodes), network.nodes.crs),
        with_geometry(network.edges, lines_of(network.edges), network.edges.crs),
    )


def is_arrays(network: Any) -> bool:
    return isinstance(network, Network) and isinstance(network.nodes, Frame) and isinstance(network.edges, Frame)


def _like(result: Any, as_arrays: bool) -> Any:
    """Give a result the form that the caller's network had"""
    if isinstance(result, tuple):
        return tuple(_like(item, as_arrays) for item in result)
    if not isinstance(result, Network):
        return result
    if as_arrays:
        return result if isinstance(result, ArrayNetwork) else ArrayNetwork(result.nodes, result.edges)
    return to_arrays(result).to_geopandas() if is_arrays(result) else result


def operation(function: F) -> F:
    """Mark a function that works on networks.

    Inside, networks are worked on in arrays whatever form they arrived in.
    The result is an :class:`ArrayNetwork` if every network passed in was one,
    and otherwise a network of GeoDataFrames.
    """

    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        given = []

        def opened(value: Any) -> Any:
            if isinstance(value, Network):
                given.append(is_arrays(value))
                return value if given[-1] else to_arrays(value)
            if isinstance(value, dict):
                return {key: opened(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return type(value)(opened(item) for item in value)
            return value

        args = tuple(opened(value) for value in args)
        kwargs = {name: opened(value) for name, value in kwargs.items()}
        return _like(function(*args, **kwargs), bool(given) and all(given))

    return wrapper  # type: ignore[return-value]
