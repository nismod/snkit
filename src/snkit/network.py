"""Network representation and utilities"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Set, Tuple, Union
import warnings

import geopandas
import numpy as np
import numpy.typing as npt
import pandas
import pyproj
import shapely.errors

try:
    import networkx as nx

    USE_NX = True
except ImportError:
    USE_NX = False

try:
    import igraph

    USE_IGRAPH = True
except ImportError:
    USE_IGRAPH = False

from geopandas import GeoDataFrame
from shapely import Geometry
from shapely.geometry import (
    GeometryCollection,
    LineString,
    mapping,
    MultiPoint,
    Point,
    shape,
)
from shapely.ops import split, linemerge, unary_union

from collections import Counter

# SNKIT_PROGRESS and SNKIT_PROCESSES were read here to turn on progress bars
# and parallel processing. Operations now run in bulk, so neither has any effect.
PARALLEL_PROCESS_COUNT = 0

Number = Union[int, float]


class Network:
    """A Network is composed of nodes (points in space) and edges (lines)

    Parameters
    ----------
    nodes : geopandas.geodataframe.GeoDataFrame, optional
    edges : geopandas.geodataframe.GeoDataFrame, optional

    Attributes
    ----------
    nodes : geopandas.geodataframe.GeoDataFrame
    edges : geopandas.geodataframe.GeoDataFrame

    """

    def __init__(
        self, nodes: Optional[GeoDataFrame] = None, edges: Optional[GeoDataFrame] = None
    ):
        """ """
        if nodes is None:
            nodes = GeoDataFrame(geometry=[])
        self.nodes = nodes

        if edges is None:
            edges = GeoDataFrame(geometry=[])
        self.edges = edges

    def set_crs(
        self,
        crs: Optional[pyproj.CRS] = None,
        epsg: Optional[int] = None,
        allow_override: bool = False,
    ) -> None:
        """Set the coordinate reference system (CRS) of the network nodes and
        edges.

        Parameters
        ----------
        crs : optional if epsg is specified
            The value can be anything accepted by pyproj.CRS.from_user_input(),
            such as an authority string (eg “EPSG:4326”) or a WKT string.
        epsg : optional if crs is specified
            EPSG code specifying output projection.
        allow_override : default False
            If the nodes or edges GeoDataFrame already has a CRS, allow to
            replace the existing CRS, even when both are not equal.

        """
        inplace = True
        self.edges.set_crs(crs, epsg, inplace, allow_override)
        self.nodes.set_crs(crs, epsg, inplace, allow_override)

    def to_crs(
        self, crs: Optional[pyproj.CRS] = None, epsg: Optional[int] = None
    ) -> None:
        """Transform network nodes and edges geometries to a new coordinate
        reference system (CRS).

        Parameters
        ----------
        crs : optional if epsg is specified
            The value can be anything accepted by pyproj.CRS.from_user_input(),
            such as an authority string (eg “EPSG:4326”) or a WKT string.
        epsg : optional if crs is specified
            EPSG code specifying output projection.

        """
        inplace = True
        self.edges.to_crs(crs, epsg, inplace)
        self.nodes.to_crs(crs, epsg, inplace)

    def to_file(
        self,
        filename: str,
        nodes_layer: Optional[str] = "nodes",
        edges_layer: Optional[str] = "edges",
        **kwargs: Any,
    ) -> None:
        """Write nodes and edges to a geographic data file with layers.

        Any additional keyword arguments are passed through to `geopandas.GeoDataFrame.to_file`.

        Parameters
        ----------
        filename : str
            Path to geographic data file with layers
        nodes_layer : str, optional, default 'nodes'
            Layer name for nodes.
        edges_layer : str, optional, default 'edges'
            Layer name for edges.
        """
        self.nodes.to_file(filename, layer=nodes_layer, **kwargs)
        self.edges.to_file(filename, layer=edges_layer, **kwargs)


def read_file(
    filename: str,
    nodes_layer: Optional[str] = "nodes",
    edges_layer: Optional[str] = "edges",
    **kwargs: Any,
) -> Network:
    """Read a geographic data file with layers containing nodes and edges.

    Any additional keyword arguments are passed through to `geopandas.read_file`.

    Parameters
    ----------
    filename
        Path to geographic data file with layers
    nodes_layer :, optional, default 'nodes'
        Layer name for nodes, or None if nodes should not be read.
    edges_layer :, optional, default 'edges'
        Layer name for edges, or None if edges should not be read.
    """
    if nodes_layer is not None:
        nodes = geopandas.read_file(filename, layer=nodes_layer, **kwargs)
    else:
        nodes = None

    if edges_layer is not None:
        edges = geopandas.read_file(filename, layer=edges_layer, **kwargs)
    else:
        edges = None

    return Network(nodes, edges)


def add_ids(
    network: Network,
    id_col: Optional[str] = "id",
    edge_prefix: Optional[str] = "edge",
    node_prefix: Optional[str] = "node",
) -> Network:
    """Add or replace an id column with ascending ids"""
    nodes = network.nodes.copy()
    if not nodes.empty:
        nodes = nodes.reset_index(drop=True)

    edges = network.edges.copy()
    if not edges.empty:
        edges = edges.reset_index(drop=True)

    nodes[id_col] = ["{}_{}".format(node_prefix, i) for i in range(len(nodes))]
    edges[id_col] = ["{}_{}".format(edge_prefix, i) for i in range(len(edges))]

    return Network(nodes=nodes, edges=edges)


def add_topology(network: Network, id_col: str = "id") -> Network:
    """Add or replace from_id, to_id to edges

    Each end of each edge is given the id of the node nearest to it, however
    far away that is. See :func:`snkit.from_nodes_and_edges` for a version
    that only attaches ends to nodes within a tolerance.
    """
    edges = network.edges.copy()
    if len(edges) == 0:
        edges["from_id"] = []
        edges["to_id"] = []
        return Network(nodes=network.nodes, edges=edges)

    ends = _line_ends(_geoms(edges))
    tree = shapely.STRtree(_geoms(network.nodes))
    ids = network.nodes[id_col].to_numpy()[tree.nearest(shapely.points(ends))]
    edges["from_id"] = ids[0::2]
    edges["to_id"] = ids[1::2]
    return Network(nodes=network.nodes, edges=edges)


def get_endpoints(network: Network) -> GeoDataFrame:
    """Get nodes for each edge endpoint"""
    geoms = _geoms(network.edges)
    parts = shapely.get_parts(geoms[~shapely.is_missing(geoms)])
    endpoints = shapely.points(_line_ends(parts)) if len(parts) else []

    # create dataframe to match the nodes geometry column name
    return matching_gdf_from_geoms(network.nodes, list(endpoints))


def add_endpoints(network: Network) -> Network:
    """Add nodes at line endpoints"""
    endpoints = get_endpoints(network)
    nodes = concat_dedup([network.nodes, endpoints])

    return Network(nodes=nodes, edges=network.edges)


def round_geometries(network: Network, precision: int = 3) -> Network:
    """Round coordinates of all node points and vertices of edge linestrings to some precision"""
    for table in (network.nodes, network.edges):
        if len(table):
            table.geometry = _round(_geoms(table), precision)
    return network


def split_multilinestrings(network: Network, merge_parts: bool = False) -> Network:
    """
    Create multiple edges from any MultiLineString edge

    Ensures that edge geometries are all LineStrings, duplicates attributes
    over any created multi-edges.

    Parameters
    ----------
    merge_parts : default False
        Merge parts of geometries if they are connected, before splitting to multiple edges
    """

    edges = network.edges
    geom_col: str = geometry_column_name(edges)
    if merge_parts:
        edges.geometry = edges.geometry.apply(merge_multilinestring)
    split_edges = edges.explode(column=geom_col, ignore_index=True)

    geo_types = set(split_edges.geom_type)
    if geo_types != {"LineString"}:
        raise ValueError(
            f"exploded edges are of type(s) {geo_types} but should only be LineString"
        )

    return Network(nodes=network.nodes, edges=split_edges)


def merge_multilinestring(geom: Geometry) -> Geometry:
    """Merge a MultiLineString to LineString"""
    try:
        if geom.geom_type == "MultiLineString":
            geom_inb = linemerge(geom)
            if geom_inb.is_ring:
                return geom

            # In case of linestring merge issues, we could add this to the script again
            #            from centerline.main import Centerline
            #            if geom_inb.geom_type == 'MultiLineString':
            #                return linemerge(Centerline(geom.buffer(0.5)))
            else:
                return geom_inb
        else:
            return geom
    except Exception:
        return GeometryCollection()


def snap_nodes(network: Network, threshold: Optional[Number] = None) -> Network:
    """Move nodes (within threshold) to edges"""
    nodes = network.nodes.copy()
    if len(nodes) and len(network.edges):
        points, lines = _geoms(nodes), _geoms(network.edges)
        nearest_line = lines[shapely.STRtree(lines).nearest(points)]
        snapped = shapely.line_interpolate_point(nearest_line, shapely.line_locate_point(nearest_line, points))
        if threshold is not None:
            snapped = np.where(shapely.distance(snapped, points) > threshold, points, snapped)
        nodes[geometry_column_name(nodes)] = geopandas.GeoSeries(snapped, index=nodes.index, crs=nodes.crs)

    return Network(nodes=nodes, edges=network.edges)





def split_edges_at_nodes(network: Network, tolerance: Number = 1e-9, chunk_size: Optional[int] = None) -> Network:
    """
    Split network edges where they intersect node geometries.

    Args:
        network: Network object to split edges for.
        tolerance: Proximity within which nodes are said to intersect an edge.
        chunk_size: No longer used. The work is done in bulk, so there is
            nothing to gain from splitting it between processes.

    Returns:
        Network with edges split at nodes (within proximity tolerance).
    """
    edges = network.edges
    if len(edges) == 0 or len(network.nodes) == 0:
        return Network(nodes=network.nodes, edges=edges)
    from snkit.core import Lines

    lines = Lines(_geoms(edges))
    points = _geoms(network.nodes)
    node, edge = shapely.STRtree(lines.lines).query(points, predicate="dwithin", distance=tolerance)
    xy = shapely.get_coordinates(points)[node]
    measure = shapely.line_locate_point(lines.lines[edge], points[node])
    return Network(nodes=network.nodes, edges=_cut_edges(edges, lines, edge, measure, xy))


def split_edges_at_intersections(network: Network, tolerance: Optional[Number] = 1e-9) -> Network:
    """Split network edges where they intersect line geometries

    Edges are split where they cross, where one ends on another, where an edge
    crosses itself, and at each end of a stretch that two edges share. A node
    is added at each of these places and at both ends of every edge, unless
    there is a node there already.

    Args:
        network: Network object to split edges for.
        tolerance: No longer used. Edges are split only where they meet.
    """
    edges = network.edges
    if len(edges) == 0:
        return Network(nodes=network.nodes, edges=edges)
    from snkit.core import Lines
    from snkit.match import crossing_events

    lines = Lines(_geoms(edges))
    events = crossing_events(lines, end_to_end=True)
    xy = events[["x", "y"]].to_numpy()
    cut_edge, cut_measure, cut_xy, cut_seg = [], [], [], []
    for side in "ab":
        interior = events[f"end_{side}"].to_numpy() == 0
        cut_edge.append(events[f"edge_{side}"].to_numpy(dtype=np.int64)[interior])
        cut_measure.append(events[f"measure_{side}"].to_numpy(dtype=float)[interior])
        cut_seg.append(events[f"vertex_{side}"].to_numpy(dtype=np.int64)[interior])
        cut_xy.append(xy[interior])
    split = _cut_edges(
        edges,
        lines,
        np.concatenate(cut_edge),
        np.concatenate(cut_measure),
        np.concatenate(cut_xy),
        np.concatenate(cut_seg),
    )

    # combine the original nodes with nodes where edges meet and at the ends of
    # every edge, keeping the original where there is already a node at the same place
    places = np.concatenate([xy, _line_ends(lines.lines)])
    new_nodes = matching_gdf_from_geoms(network.nodes, list(shapely.points(places)))
    nodes = concat_dedup([network.nodes, new_nodes])
    return Network(nodes=nodes, edges=split)


NodeEdgeCondition = Callable[["pandas.Series[Any]", "pandas.Series[Any]"], bool]


def link_nodes_to_edges_within(
    network: Network,
    distance: Number,
    condition: Optional[NodeEdgeCondition] = None,
    tolerance: Number = 1e-9,
) -> Network:
    """Link nodes to all edges within some distance"""
    if len(network.nodes) == 0 or len(network.edges) == 0:
        return network
    points, lines = _geoms(network.nodes), _geoms(network.edges)
    node, edge = shapely.STRtree(lines).query(points, predicate="dwithin", distance=distance)
    order = np.lexsort((edge, node))
    node, edge = node[order], edge[order]
    if condition is not None:
        node_rows = list(network.nodes.itertuples(index=False))
        edge_rows = list(network.edges.itertuples())
        keep = [bool(condition(node_rows[n], edge_rows[e])) for n, e in zip(node, edge)]
        node, edge = node[keep], edge[keep]
    return _link(network, node, edge, tolerance)


def link_nodes_to_nearest_edge(
    network: Network,
    condition: Optional[NodeEdgeCondition] = None,
) -> Network:
    """Link nodes to the nearest edge"""
    if len(network.nodes) == 0 or len(network.edges) == 0:
        return network
    points, lines = _geoms(network.nodes), _geoms(network.edges)
    node = np.arange(len(points))
    edge = shapely.STRtree(lines).nearest(points)
    if condition is not None:
        node_rows = list(network.nodes.itertuples(index=False))
        keep = [bool(condition(node_rows[n], network.edges.iloc[e])) for n, e in zip(node, edge)]
        node, edge = node[keep], edge[keep]
    return _link(network, node, edge, 1e-9)


def _link(network: Network, node: Any, edge: Any, tolerance: Number) -> Network:
    """Add a node at the nearest place on each edge to each node, and an edge to it"""
    points, lines = _geoms(network.nodes)[node], _geoms(network.edges)[edge]
    nearest = shapely.line_interpolate_point(lines, shapely.line_locate_point(lines, points))
    start, end = shapely.get_coordinates(points), shapely.get_coordinates(nearest)
    apart = (start != end).any(axis=1)
    links = shapely.linestrings(np.stack([start[apart], end[apart]], axis=1))

    new_nodes = matching_gdf_from_geoms(network.nodes, list(nearest[apart]))
    all_nodes = concat_dedup([network.nodes, new_nodes])
    new_edges = matching_gdf_from_geoms(network.edges, list(links))
    all_edges = concat_dedup([network.edges, new_edges])

    # split edges as necessary after new node creation
    return split_edges_at_nodes(Network(nodes=all_nodes, edges=all_edges), tolerance)


def _geoms(table: GeoDataFrame) -> Any:
    return np.asarray(table.geometry.values, dtype=object)


def _line_ends(lines: Any) -> Any:
    """Start and end coordinates of each line, interleaved"""
    from snkit.core import _edge_ends, to_ragged

    return _edge_ends(*to_ragged(lines))


def _round(geoms: Any, precision: int) -> Any:
    geoms = geoms.copy()
    present = ~shapely.is_missing(geoms)
    for has_z in (False, True):
        chosen = present & (shapely.has_z(geoms) == has_z)
        if chosen.any():
            geoms[chosen] = shapely.transform(
                geoms[chosen], lambda coords: np.round(coords, precision), include_z=has_z
            )
    return geoms


def _cut_edges(
    edges: GeoDataFrame, lines: Any, edge: Any, measure: Any, xy: Any, seg: Optional[Any] = None
) -> GeoDataFrame:
    """Cut edges at places along them, putting the given coordinate at each cut.

    Attributes are copied to each piece. A place at the very end of an edge
    cuts it only if its coordinate differs from the end's.
    """
    from snkit import _kernel as K
    from snkit.core import from_ragged

    edge = np.asarray(edge, dtype=np.int64)
    first, last = lines.offsets[edge], lines.offsets[edge + 1] - 1
    at_end = (xy == lines.coords[first]).all(axis=1) | (xy == lines.coords[last]).all(axis=1)
    if seg is None:
        seg = K.locate_segment(lines.running, lines.offsets, edge, measure)
    else:
        seg = np.clip(seg, first, last - 1)
    table = pandas.DataFrame(
        {"edge": edge, "seg": seg, "measure": measure, "x": xy[:, 0], "y": xy[:, 1]}
    )[~at_end]
    table = table.sort_values(["edge", "seg", "measure", "x", "y"], kind="stable")
    table = table.drop_duplicates(["edge", "measure", "x", "y"])
    if len(table) == 0:
        return edges
    cut_edge = table["edge"].to_numpy()
    nothing = np.zeros(lines.m, dtype=np.int64)
    coords, offsets, _, _, parent = K.split(
        lines.coords,
        lines.offsets,
        nothing,
        nothing,
        cut_edge,
        table["seg"].to_numpy(),
        table[["x", "y"]].to_numpy(),
        np.zeros(len(cut_edge), dtype=np.int64),
    )
    split = edges.iloc[parent].reset_index(drop=True)
    split[geometry_column_name(edges)] = geopandas.GeoSeries(from_ragged(coords, offsets), crs=edges.crs)
    return split


def merge_edges(network: Network, id_col: Optional[str] = "id", by: Optional[List[str]] = None) -> Network:
    """Merge edges that share a node with a connectivity degree of 2

    Parameters
    ----------
    network : snkit.network.Network
    id_col : string
    by : List[string], optional
      list of columns to use when merging an edge path - will not merge if
      edges have different values.

    Notes
    -----
    A merged edge takes the attributes, including the id, of the first of
    the edges it was made from, and takes that edge's place in the table.
    """
    from snkit.core import from_topology
    from snkit.operations import merge_edges as merge

    nodes, edges = network.nodes, network.edges
    if len(edges) == 0:
        return network
    position = pandas.Index(nodes[id_col])
    temp_nodes = GeoDataFrame({"id": np.arange(len(nodes))}, geometry=_geoms(nodes), crs=nodes.crs)
    temp_edges = GeoDataFrame(
        {
            "id": np.arange(len(edges)),
            "from_id": position.get_indexer(edges["from_id"]),
            "to_id": position.get_indexer(edges["to_id"]),
            **{column: edges[column].to_numpy() for column in by or []},
        },
        geometry=_geoms(edges),
        crs=edges.crs,
    )
    # ends are moved exactly onto their nodes, as merging by topology requires
    merged, lineage = merge(
        from_topology(temp_nodes, temp_edges, tolerance=np.inf), by=by, return_lineage=True
    )
    first = lineage.edges.drop_duplicates("id").set_index("id")["parent_id"]
    out_edges = edges.iloc[first.reindex(merged.edges["id"]).to_numpy()].reset_index(drop=True)
    # the temporary ids are positions in the original tables
    node_ids = nodes[id_col].to_numpy()
    kept = merged.nodes["id"].to_numpy(dtype=np.int64)
    out_edges["from_id"] = node_ids[merged.edges["from_id"].to_numpy(dtype=np.int64)]
    out_edges["to_id"] = node_ids[merged.edges["to_id"].to_numpy(dtype=np.int64)]
    out_edges[geometry_column_name(edges)] = geopandas.GeoSeries(_geoms(merged.edges), crs=edges.crs)

    out_nodes = nodes.iloc[kept].reset_index(drop=True)
    if "degree" not in out_nodes.columns:
        ends = pandas.concat([out_edges["from_id"], out_edges["to_id"]]).value_counts()
        out_nodes["degree"] = ends.reindex(out_nodes[id_col]).fillna(0).astype(int).to_numpy()
    return Network(nodes=out_nodes, edges=out_edges)


def geometry_column_name(gdf: GeoDataFrame) -> str:
    """Get geometry column name, fall back to 'geometry'"""
    try:
        geom_col: str = gdf.geometry.name
    except AttributeError:
        geom_col = "geometry"
    return geom_col


def matching_gdf_from_geoms(gdf: GeoDataFrame, geoms: List[Geometry]) -> GeoDataFrame:
    """Create a geometry-only GeoDataFrame with column name to match an existing GeoDataFrame"""
    geom_col = geometry_column_name(gdf)
    geom_arr = geoms_to_array(geoms)
    matching_gdf = GeoDataFrame(geometry=geom_arr, crs=gdf.crs)
    matching_gdf.geometry.name = geom_col
    return matching_gdf


def geoms_to_array(
    geoms: List[Geometry],
) -> npt.ArrayLike:
    geom_arr = np.empty(len(geoms), dtype="object")
    geom_arr[:] = geoms

    return geom_arr


def concat_dedup(dfs: List[pandas.DataFrame]) -> GeoDataFrame:
    """Concatenate a list of GeoDataFrames, dropping duplicate geometries
    - note: repeatedly drops indexes for deduplication to work
    """
    cat = pandas.concat(dfs, axis=0, sort=False)
    cat.reset_index(drop=True, inplace=True)
    cat_dedup = drop_duplicate_geometries(cat)
    cat_dedup.reset_index(drop=True, inplace=True)
    return cat_dedup


def node_connectivity_degree(node: str, network: Network) -> int:
    return len(
        network.edges[(network.edges.from_id == node) | (network.edges.to_id == node)]
    )


def drop_duplicate_geometries(
    gdf: GeoDataFrame, keep: Optional[str] = "first"
) -> GeoDataFrame:
    """Drop duplicate geometries from a dataframe"""
    # as of geopandas ~0.6 this should work without explicit conversion to wkb
    # discussed in https://github.com/geopandas/geopandas/issues/521
    return gdf.drop_duplicates([gdf.geometry.name])


def nearest_point_on_edges(point: Point, edges: GeoDataFrame) -> Point:
    """Find nearest point on edges to a point"""
    edge = nearest_edge(point, edges)
    snap = nearest_point_on_line(point, edge.geometry)
    return snap


def nearest_node(point: Point, nodes: GeoDataFrame) -> "pandas.Series[Any]":
    """Find nearest node to a point"""
    return nearest(point, nodes)


def nearest_edge(point: Point, edges: GeoDataFrame) -> "pandas.Series[Any]":
    """Find nearest edge to a point"""
    return nearest(point, edges)


def nearest(geom: Geometry, gdf: GeoDataFrame) -> "pandas.Series[Any]":
    """Find the element of a GeoDataFrame nearest a shapely geometry"""
    try:
        match_idx = gdf.sindex.nearest(geom, return_all=False)[1][0]
        nearest_geom: "pandas.Series[Any]" = gdf.iloc[match_idx]
        return nearest_geom

    except TypeError:
        warnings.warn("Falling back to RTree index method for nearest element")
        matches_idx = gdf.sindex.nearest(geom.bounds)
        nearest_geom = min(
            [gdf.iloc[match_idx] for match_idx in matches_idx],
            key=lambda match: geom.distance(match.geometry),
        )
        return nearest_geom


def edges_within(point: Point, edges: GeoDataFrame, distance: Number) -> GeoDataFrame:
    """Find edges within a distance of point"""
    return d_within(point, edges, distance)


def edges_intersecting_points(
    line: LineString, edges: GeoDataFrame, tolerance: Optional[Number] = 1e-9
) -> GeoDataFrame:
    """Return intersection points of intersecting edges"""
    hits = edges_intersecting(line, edges, tolerance)

    hits_points: List[Point] = []
    for hit in hits.geometry:
        # first extract the actual intersections from the hits
        # for being new geometrical objects, they are not in the sindex
        intersection = line.intersection(hit)
        # if the line is not simple, there is a self-crossing point
        # (note that it will always interact with itself)
        # note that __eq__ is used on purpose instead of equals()
        # this is stricter: for geometries constructed in the same way
        # it makes sense since the sindex is used here
        if line == hit and not line.is_simple:
            # there is not built-in way to find self-crossing points
            # duplicated points after unary_union are the intersections
            intersection = unary_union(line)
            segments_coordinates = []
            for seg in intersection.geoms:
                segments_coordinates.extend(list(seg.coords))
            intersection = [
                Point(p) for p, c in Counter(segments_coordinates).items() if c > 1
            ]
            intersection = MultiPoint(intersection)

        # then extract the intersection points
        hits_points = intersection_endpoints(intersection, hits_points)

    return hits_points


def edges_intersecting(
    line: LineString, edges: GeoDataFrame, tolerance: Optional[Number] = 1e-9
) -> GeoDataFrame:
    """Find edges intersecting line"""
    return intersects(line, edges, tolerance)


def nodes_intersecting(
    line: LineString, nodes: GeoDataFrame, tolerance: Optional[Number] = 1e-9
) -> GeoDataFrame:
    """Find nodes intersecting line"""
    return intersects(line, nodes, tolerance)


def intersects(
    geom: Geometry, gdf: GeoDataFrame, tolerance: Optional[Number] = 1e-9
) -> GeoDataFrame:
    """Find the subset of a GeoDataFrame intersecting with a shapely geometry"""
    return _intersects(geom, gdf, tolerance)


def d_within(geom: Geometry, gdf: GeoDataFrame, distance: Number) -> GeoDataFrame:
    """Find the subset of a GeoDataFrame within some distance of a shapely geometry"""
    return _intersects(geom, gdf, distance)


def _intersects(
    geom: Geometry, gdf: GeoDataFrame, tolerance: Optional[Number] = 1e-9
) -> GeoDataFrame:
    if geom.is_empty:
        return geopandas.GeoDataFrame()
    buf = geom.buffer(tolerance)
    if buf.is_empty:
        # can have an empty buffer with too small a tolerance, fallback to original geom
        buf = geom
    try:
        return _intersects_gdf(buf, gdf)
    except (shapely.errors.TopologicalError, shapely.errors.GEOSException):
        # can exceptionally buffer to an invalid geometry, so try re-buffering
        buf = buf.buffer(0)
        return _intersects_gdf(buf, gdf)


def _intersects_gdf(geom: Geometry, gdf: GeoDataFrame) -> GeoDataFrame:
    candidate_idxs = list(gdf.sindex.intersection(geom.bounds))
    candidates = gdf.iloc[candidate_idxs]
    return candidates[candidates.intersects(geom)]


def line_endpoints(line: LineString) -> Tuple[Point, Point]:
    """Return points at first and last vertex of a line"""
    try:
        coords = np.array(line.coords)
        start = Point(coords[0])
        end = Point(coords[-1])
    except NotImplementedError as e:
        print(line)
        raise e
    return start, end


def intersection_endpoints(
    geom: Geometry, output: Optional[List[Point]] = None
) -> List[Point]:
    """Return the points from an intersection geometry

    It extracts the starting and ending points of intersection
    geometries recursively and appends them to `output`.
    This doesn't handle polygons or collections of polygons.
    """
    if output is None:
        output = []

    geom_type = geom.geom_type
    if geom.is_empty:
        pass
    elif geom_type == "Point":
        output.append(geom)
    elif geom_type == "LineString":
        start = Point(geom.coords[0])
        end = Point(geom.coords[-1])
        output.append(start)
        output.append(end)
    # recursively for collections of geometries
    # note that there is no shared inheritance relationship
    elif (
        geom_type == "MultiPoint"
        or geom_type == "MultiLineString"
        or geom_type == "GeometryCollection"
    ):
        for geom_ in geom.geoms:
            output = intersection_endpoints(geom_, output)

    return output


def split_edge_at_points(
    edge: geopandas.GeoSeries,
    points: Union[Point, MultiPoint],
    tolerance: Optional[Number] = 1e-9,
) -> GeoDataFrame:
    """Split edge at point/multipoint"""
    try:
        segments = split_line(edge.geometry, points, tolerance)
    except (ValueError, shapely.errors.GeometryTypeError):
        # GeometryTypeError derives from ShapelyError and not TypeError or
        # ValueError since Shapely 2.0. May be raised if splitting fails, e.g.
        # because points is an empty GeometryCollection
        segments = [edge.geometry]
    edges = GeoDataFrame([edge] * len(segments))
    edges.geometry = segments
    return edges


def split_line(
    line: LineString,
    points: Union[Point, MultiPoint],
    tolerance: Optional[Number] = 1e-9,
) -> List[LineString]:
    """Split line at point or multipoint, within some tolerance"""
    to_split = snap_line(line, points, tolerance)
    # when the splitter is a self-intersection point, shapely splits in
    # two parts only in a semi-arbitrary way, see the related question:
    # https://gis.stackexchange.com/questions/435879/python-shapely-split-a-complex-line-at-self-intersections?noredirect=1#comment711214_435879
    # checking only that the line is complex might not be enough
    # but the difference operation is useless in the worst case
    if not to_split.is_simple:
        to_split = to_split.difference(points)
    return list(split(to_split, points).geoms)


def snap_line(
    line: LineString,
    points: Union[Point, MultiPoint],
    tolerance: Optional[Number] = 1e-9,
) -> LineString:
    """Snap a line to points within tolerance, inserting vertices as necessary"""
    if points.geom_type == "Point":
        if points.distance(line) < tolerance:
            line = add_vertex(line, points)
    elif points.geom_type == "MultiPoint":
        points = [point for point in points.geoms if point.distance(line) < tolerance]
        for point in points:
            line = add_vertex(line, point)
    return line


def add_vertex(line: LineString, point: Point) -> LineString:
    """Add a vertex to a line at a point"""
    v_idx = nearest_vertex_idx_on_line(point, line)
    point_coords = np.array(point.coords)[0]
    line_coords = np.array(line.coords)

    if (point_coords == line_coords[v_idx]).all():
        # nearest vertex could be identical to point, so return unchanged
        return line

    insert_before_idx = None
    if v_idx == 0:
        # nearest vertex could be start, so insert just after (or could extend)
        insert_before_idx = 1
    elif v_idx == len(line_coords) - 1:
        # nearest vertex could be end, so insert just before (or could extend)
        insert_before_idx = v_idx
    else:
        # otherwise insert in between vertices of nearest segment
        segment_before = LineString([line_coords[v_idx], line_coords[v_idx - 1]])
        segment_after = LineString([line_coords[v_idx], line_coords[v_idx + 1]])
        if point.distance(segment_before) < point.distance(segment_after):
            insert_before_idx = v_idx
        else:
            insert_before_idx = v_idx + 1
    # insert point coords before index, return new linestring
    new_coords = list(line_coords)
    new_coords.insert(insert_before_idx, point_coords)
    return LineString(new_coords)


def nearest_vertex_idx_on_line(point: Point, line: LineString) -> int:
    """Return the index of nearest vertex to a point on a line"""
    # distance to all points is calculated here - and this is called once per splitting point
    # any way to avoid this m x n behaviour?
    # idea: put line vertices in an STRTree and query it repeatedly for nearest (with each
    # splitting point)
    line_coords = np.array(line.coords)
    nearest_idx, _ = min(
        [
            (idx, point.distance(Point(coords)))
            for idx, coords in enumerate(line_coords)
        ],
        key=lambda item: item[1],
    )
    return nearest_idx


def nearest_point_on_line(point: Point, line: LineString) -> Point:
    """Return the nearest point on a line"""
    return line.interpolate(line.project(point))


def set_precision(geom: Geometry, precision: int) -> Geometry:
    """Set geometry precision"""
    geom_mapping = mapping(geom)
    geom_mapping["coordinates"] = np.round(
        np.array(geom_mapping["coordinates"]), precision
    )
    return shape(geom_mapping)


def to_networkx(
    network: Network, directed: bool = False, weight_col: Optional[str] = None
) -> Union[nx.Graph, nx.DiGraph]:
    """Return a networkx graph"""
    if not USE_NX:
        raise ImportError("No module named networkx")
    else:
        # init graph
        if not directed:
            G = nx.Graph()
        else:
            G = nx.MultiDiGraph()
        # get nodes from network data
        G.add_nodes_from(network.nodes.id.to_list())

        # add nodal positions from geom
        for node_id, x, y in zip(
            network.nodes.id, network.nodes.geometry.x, network.nodes.geometry.y
        ):
            G.nodes[node_id]["pos"] = (x, y)

        # get edges from network data
        if weight_col is None:
            # default to geometry length
            edges_as_list = list(
                zip(
                    network.edges.from_id,
                    network.edges.to_id,
                    network.edges.geometry.length,
                )
            )
        else:
            edges_as_list = list(
                zip(
                    network.edges.from_id,
                    network.edges.to_id,
                    network.edges[weight_col],
                )
            )
        # add edges to graph
        G.add_weighted_edges_from(edges_as_list)
        return G


def to_igraph(
    network: Network, directed: bool = False, weight_col: Optional[str] = None
) -> "igraph.Graph":
    """Return an igraph Graph representation of the network

    Parameters
    ----------
    network : snkit.network.Network
        The network to convert
    directed : bool, optional
        If True, create a directed graph. Default is False (undirected)
    weight_col : str, optional
        Column name to use for edge weights. If None, uses geometry length.

    Returns
    -------
    igraph.Graph
        An igraph Graph object with nodes and edges from the network

    Raises
    ------
    ImportError
        If igraph is not installed
    """
    if not USE_IGRAPH:
        raise ImportError("No module named igraph")

    # Create graph (directed or undirected)
    g = igraph.Graph(directed=directed)

    # Add vertices with their node IDs
    node_ids = network.nodes.id.to_list()
    g.add_vertices(len(node_ids))

    # Set vertex names and positions
    g.vs["name"] = node_ids
    g.vs["x"] = network.nodes.geometry.x.to_list()
    g.vs["y"] = network.nodes.geometry.y.to_list()

    # Create mapping from node ID to vertex index for edge creation
    node_id_to_idx = {node_id: idx for idx, node_id in enumerate(node_ids)}

    # Prepare edges with weights
    edge_list = []
    weights = []

    edge_list = [
        (node_id_to_idx[from_id], node_id_to_idx[to_id])
        for from_id, to_id in zip(network.edges.from_id, network.edges.to_id)
    ]
    # Get weight from specified column or use geometry length
    if weight_col is None:
        weights = network.edges.geometry.length.to_list()
    else:
        weights = network.edges[weight_col].to_list()

    # Add edges to graph
    g.add_edges(edge_list)

    # Set edge weights
    g.es["weight"] = weights

    return g


def get_connected_components(network: Network) -> List[Set[Any]]:
    """Get connected components within network and id to each individual graph"""
    if not USE_NX:
        raise ImportError("No module named networkx")
    else:
        G = to_networkx(network)
        return sorted(nx.connected_components(G), key=len, reverse=True)


def add_component_ids(network: Network, id_col: str = "component_id") -> Network:
    """Add column of connected component IDs to network edges and nodes"""

    # get connected components in descending size order
    connected_parts = get_connected_components(network)

    # init id_col
    network.edges[id_col] = 0
    network.nodes[id_col] = 0

    # add unique id for each graph component
    for count, part in enumerate(connected_parts):
        # edges
        edge_mask = network.edges.from_id.isin(part).values
        network.edges.loc[edge_mask, id_col] = count + 1

        # nodes
        node_mask = network.nodes.id.isin(part).values
        network.nodes.loc[node_mask, id_col] = count + 1

    return network
