"""Matchers: find geometric relationships within a network, as plain tables.

Each matcher returns a DataFrame of candidates and changes nothing. To match
across networks, put them side by side with :func:`snkit.combine` and use a
``condition`` on the ``source`` column.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import numpy as np
import pandas as pd
import shapely

from snkit import _kernel as K
from snkit.core import GEOM, ID, Arrays, Lines, check_distance
from snkit.network import Network

Condition = Optional[Callable[[pd.DataFrame], Any]]


def apply_condition(
    matches: pd.DataFrame,
    condition: Condition,
    network: Network,
    keys: Dict[str, str],
) -> pd.DataFrame:
    """Keep the matches for which ``condition`` is true.

    The condition is called once with the match table, widened with the
    attributes of the features on each side. ``keys`` maps each id column of
    the match table to ``"nodes"`` or ``"edges"``; attributes are suffixed
    with the end of the id column's name (``_a``, ``_b``, ``_node``, ``_edge``).
    """
    if condition is None or len(matches) == 0:
        return matches
    view = matches
    for column, kind in keys.items():
        table = pd.DataFrame(getattr(network, kind)).drop(columns=GEOM)
        suffix = "_" + column.split("_")[-1]
        view = view.join(table.set_index(ID).add_suffix(suffix), on=column)
    mask = np.asarray(condition(view), dtype=bool)
    return matches[mask].reset_index(drop=True)


def node_pairs(arrays: Arrays, tolerance: float) -> pd.DataFrame:
    """Pairs of node positions within tolerance, each pair once"""
    a, b = K.point_pairs(arrays.xy, tolerance)
    distance = np.hypot(*(arrays.xy[a] - arrays.xy[b]).T)
    return pd.DataFrame({"a": a, "b": b, "distance": distance})


def match_nodes(network: Network, tolerance: float, condition: Condition = None) -> pd.DataFrame:
    """Find pairs of nodes within ``tolerance`` of each other.

    Returns a table with columns ``node_a``, ``node_b``, ``distance``. Each
    pair appears once, with ``node_a`` earlier in the nodes table.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges(
    ...     [LineString([(0, 0), (1, 0)]), LineString([(1.5, 0), (3, 0)])])
    >>> snkit.match_nodes(network, tolerance=0.5).values.tolist()
    [[1.0, 2.0, 0.5]]
    """
    check_distance(network, tolerance)
    arrays = Arrays(network)
    pairs = node_pairs(arrays, tolerance)
    matches = pd.DataFrame(
        {
            "node_a": arrays.node_ids[pairs["a"].to_numpy()],
            "node_b": arrays.node_ids[pairs["b"].to_numpy()],
            "distance": pairs["distance"].to_numpy(),
        }
    )
    return apply_condition(matches, condition, network, {"node_a": "nodes", "node_b": "nodes"})


def node_edge_pairs(
    arrays: Arrays,
    tolerance: Optional[float],
    how: str = "all",
    nodes: Optional[Any] = None,
) -> pd.DataFrame:
    """Nodes near edges they are not an end of, by position.

    Columns: ``node``, ``edge``, ``measure``, ``x``, ``y``, ``distance``, and
    ``end`` (-1 if the nearest place on the edge is its start, 1 its end, 0
    otherwise).
    """
    if how not in ("all", "nearest"):
        raise ValueError("how must be 'all' or 'nearest'")
    if how == "all" and tolerance is None:
        raise ValueError("a tolerance is needed to find all edges near each node")
    chosen = np.arange(arrays.n)
    if nodes is not None:
        chosen = chosen[np.asarray(nodes, dtype=bool)]
    node = edge = np.zeros(0, dtype=np.int64)
    if len(chosen) and arrays.m:
        tree = shapely.STRtree(arrays.lines)

        def within(candidates: Any, distance: float) -> Any:
            found, e = tree.query(arrays.points[candidates], predicate="dwithin", distance=distance)
            n = candidates[found]
            other = (arrays.src[e] != n) & (arrays.dst[e] != n)
            return n[other], e[other]

        if tolerance is not None:
            node, edge = within(chosen, tolerance)
        else:
            found, e = tree.query_nearest(arrays.points[chosen], all_matches=False)
            n = chosen[found]
            other = (arrays.src[e] != n) & (arrays.dst[e] != n)
            node, edge = n[other], e[other]
            # a node whose nearest edge is one of its own: widen the search in steps
            pending = np.setdiff1d(chosen, node)
            low, high = arrays.coords.min(axis=0), arrays.coords.max(axis=0)
            reach = float(np.hypot(*(high - low))) + 1.0
            radius = reach / np.sqrt(arrays.m + 1)
            while len(pending) and radius <= 4 * reach:
                n, e = within(pending, radius)
                node, edge = np.concatenate([node, n]), np.concatenate([edge, e])
                pending = np.setdiff1d(pending, n)
                radius *= 4

    lines, points = arrays.lines[edge], arrays.points[node]
    measure = shapely.line_locate_point(lines, points)
    xy = shapely.get_coordinates(shapely.line_interpolate_point(lines, measure)).reshape(-1, 2)
    length = shapely.length(lines)
    end = np.where(measure <= 0, -1, np.where(measure >= length, 1, 0))
    matches = pd.DataFrame(
        {
            "node": node,
            "edge": edge,
            "measure": measure,
            "x": xy[:, 0],
            "y": xy[:, 1],
            "distance": np.hypot(*(xy - arrays.xy[node]).T),
            "end": end,
        }
    )
    matches = matches.sort_values(["node", "distance", "edge"], kind="stable")
    if how == "nearest":
        matches = matches.drop_duplicates("node")
    return matches.reset_index(drop=True)


def match_nodes_to_edges(
    network: Network,
    tolerance: Optional[float] = None,
    how: str = "all",
    nodes: Optional[Any] = None,
    condition: Condition = None,
) -> pd.DataFrame:
    """Find nodes near edges that they are not already an end of.

    Parameters
    ----------
    tolerance
        Furthest distance between node and edge. Required for ``how="all"``.
    how
        ``"all"``: every edge within tolerance of each node.
        ``"nearest"``: only the nearest edge to each node.
    nodes
        Boolean mask over the nodes table choosing which nodes to match.

    Notes
    -----
    Returns a table with columns ``node``, ``edge``, ``measure`` (distance
    along the edge of the nearest place to the node), ``x``, ``y`` (that
    place) and ``distance``. With ``how="all"``, a node whose nearest place on
    an edge is the very end of it is not reported: that node is near another
    node, not near the edge.

    Examples
    --------
    >>> from shapely import LineString, Point
    >>> import snkit
    >>> network = snkit.from_nodes_and_edges(
    ...     [Point(1, 0.5)], [LineString([(0, 0), (2, 0)])])
    >>> snkit.match_nodes_to_edges(network, how="nearest").values.tolist()
    [[0.0, 0.0, 1.0, 1.0, 0.0, 0.5]]
    """
    check_distance(network, tolerance)
    arrays = Arrays(network)
    pairs = node_edge_pairs(arrays, tolerance, how, nodes)
    if how == "all":
        pairs = pairs[pairs["end"] == 0]
    matches = pd.DataFrame(
        {
            "node": arrays.node_ids[pairs["node"].to_numpy()],
            "edge": arrays.edge_ids[pairs["edge"].to_numpy()],
            "measure": pairs["measure"].to_numpy(),
            "x": pairs["x"].to_numpy(),
            "y": pairs["y"].to_numpy(),
            "distance": pairs["distance"].to_numpy(),
        }
    )
    return apply_condition(matches, condition, network, {"node": "nodes", "edge": "edges"})


def crossing_events(arrays: Lines, end_to_end: bool = False) -> pd.DataFrame:
    """Places where edges meet away from a shared end, by position.

    Columns, for each side ``a`` and ``b``: ``edge``, ``vertex`` and ``frac``
    (the place is ``frac`` of the way along the segment starting at
    ``vertex``), ``measure``, ``end`` (-1 at the start of the edge, 1 at the
    end, 0 otherwise); and the coordinate ``x``, ``y``.
    """
    columns = [f"{name}_{side}" for side in "ab" for name in ("edge", "vertex", "frac", "measure", "end")]
    empty = pd.DataFrame({c: np.zeros(0, dtype=float) for c in columns + ["x", "y"]})
    if arrays.m == 0:
        return empty
    offsets = arrays.offsets
    seg_a, seg_b, t, u, xy = K.segment_crossings(arrays.coords, offsets, end_to_end)
    if len(seg_a) == 0:
        return empty

    owner = K.vertex_edge(offsets)
    data: Dict[str, Any] = {}
    for side, seg, frac in (("a", seg_a, t), ("b", seg_b, u)):
        edge = owner[seg]
        # a place at the far end of a segment is the start of the next
        vertex = seg + (frac == 1)
        frac = np.where(frac == 1, 0.0, frac)
        at_start = (vertex == offsets[edge]) & (frac == 0)
        at_end = vertex == offsets[edge + 1] - 1
        data[f"edge_{side}"] = edge
        data[f"vertex_{side}"] = vertex
        data[f"frac_{side}"] = frac
        data[f"measure_{side}"] = arrays.measure[vertex] + frac * arrays.seglen[vertex]
        data[f"end_{side}"] = np.where(at_start, -1, np.where(at_end, 1, 0))
    data["x"], data["y"] = xy[:, 0], xy[:, 1]
    events = pd.DataFrame(data)
    events = events.drop_duplicates(["edge_a", "vertex_a", "frac_a", "edge_b", "vertex_b", "frac_b"])
    if not end_to_end:
        # where two edges meet end to end there is a node already, or two nodes to merge
        events = events[(events["end_a"] == 0) | (events["end_b"] == 0)]
    # one place on one edge is not a crossing
    same = (events["edge_a"] == events["edge_b"]) & (events["measure_a"] == events["measure_b"])
    events = events[~same]
    return events.sort_values(["edge_a", "measure_a", "edge_b", "measure_b"], kind="stable").reset_index(drop=True)


def find_crossings(network: Network, condition: Condition = None) -> pd.DataFrame:
    """Find places where edges meet without a node.

    This includes edges that cross, an edge that ends on the middle of another
    and an edge that crosses itself. Where edges share a stretch of line, the
    ends of the stretch are reported.

    Returns a table with columns ``edge_a``, ``measure_a``, ``edge_b``,
    ``measure_b`` (distance along each edge) and ``x``, ``y``.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges(
    ...     [LineString([(0, 0), (2, 0)]), LineString([(1, -1), (1, 1)])])
    >>> snkit.find_crossings(network).values.tolist()
    [[0.0, 1.0, 1.0, 1.0, 1.0, 0.0]]
    """
    arrays = Arrays(network)
    events = crossing_events(arrays)
    matches = pd.DataFrame(
        {
            "edge_a": arrays.edge_ids[events["edge_a"].to_numpy(dtype=np.int64)],
            "measure_a": events["measure_a"].to_numpy(),
            "edge_b": arrays.edge_ids[events["edge_b"].to_numpy(dtype=np.int64)],
            "measure_b": events["measure_b"].to_numpy(),
            "x": events["x"].to_numpy(),
            "y": events["y"].to_numpy(),
        }
    )
    return apply_condition(matches, condition, network, {"edge_a": "edges", "edge_b": "edges"})


def edge_overlaps(arrays: Arrays, tolerance: float, min_length: float, directed: bool = False) -> pd.DataFrame:
    """Stretches where two edges run within tolerance of each other, by position.

    Columns: ``a``, ``start_a``, ``end_a``, ``b``, ``start_b``, ``end_b``,
    ``reversed``, ``distance``.
    """
    columns = ["a", "start_a", "end_a", "b", "start_b", "end_b", "reversed", "distance"]
    empty = pd.DataFrame({c: np.zeros(0, dtype=float) for c in columns})
    if arrays.m < 2:
        return empty
    lines = arrays.lines
    tree = shapely.STRtree(lines)
    i, j = tree.query(lines, predicate="dwithin", distance=tolerance)
    once = i < j
    i, j = i[once], j[once]
    if len(i) == 0:
        return empty
    if tolerance > 0:
        used, inverse = np.unique(j, return_inverse=True)
        near = shapely.buffer(lines[used], tolerance)[inverse]
    else:
        near = lines[j]
    shared = shapely.line_merge(shapely.intersection(lines[i], near))
    parts, pair = shapely.get_parts(shared, return_index=True)
    is_line = (shapely.get_type_id(parts) == 1) & (shapely.length(parts) > 0)
    parts, pair = parts[is_line], pair[is_line]
    if len(parts) == 0:
        return empty
    a, b = i[pair], j[pair]
    line_a, line_b = lines[a], lines[b]
    # project the ends of each stretch of a onto b, then back, so that both
    # intervals end at places that face each other
    at_b0 = shapely.line_locate_point(line_b, shapely.get_point(parts, 0))
    at_b1 = shapely.line_locate_point(line_b, shapely.get_point(parts, -1))
    at_a0 = shapely.line_locate_point(line_a, shapely.line_interpolate_point(line_b, at_b0))
    at_a1 = shapely.line_locate_point(line_a, shapely.line_interpolate_point(line_b, at_b1))
    # how far the stretch of a strays from b: measured at its two ends and at
    # the vertices of a between them
    low, high = np.minimum(at_a0, at_a1), np.maximum(at_a0, at_a1)
    distance = np.maximum(
        shapely.distance(shapely.line_interpolate_point(line_a, low), line_b),
        shapely.distance(shapely.line_interpolate_point(line_a, high), line_b),
    )
    vertices, part_index = shapely.get_coordinates(parts, return_index=True)
    vertices = shapely.points(vertices)
    along = shapely.line_locate_point(line_a[part_index], vertices)
    inside = (along >= low[part_index]) & (along <= high[part_index])
    gap = shapely.distance(vertices[inside], line_b[part_index[inside]])
    np.maximum.at(distance, part_index[inside], gap)

    matches = pd.DataFrame(
        {
            "a": a,
            "start_a": np.minimum(at_a0, at_a1),
            "end_a": np.maximum(at_a0, at_a1),
            "b": b,
            "start_b": np.minimum(at_b0, at_b1),
            "end_b": np.maximum(at_b0, at_b1),
            "reversed": (at_b0 > at_b1) != (at_a0 > at_a1),
            "distance": distance,
        }
    )
    long_enough = (matches["end_a"] - matches["start_a"] >= min_length) & (
        matches["end_b"] - matches["start_b"] >= min_length
    )
    positive = (matches["end_a"] > matches["start_a"]) & (matches["end_b"] > matches["start_b"])
    matches = matches[long_enough & positive]
    if directed:
        matches = matches[~matches["reversed"]]
    matches = matches.drop_duplicates(["a", "start_a", "end_a", "b", "start_b", "end_b"])
    return matches.sort_values(["a", "start_a", "b", "start_b"], kind="stable").reset_index(drop=True)


def match_edges(
    network: Network,
    tolerance: float,
    min_length: Optional[float] = None,
    directed: bool = False,
    condition: Condition = None,
) -> pd.DataFrame:
    """Find stretches where two edges run within ``tolerance`` of each other.

    Parameters
    ----------
    min_length
        Shortest stretch to report, by default twice the tolerance, so that
        edges that merely cross or meet are not reported as running together
        for a short way around the crossing.
    directed
        Only report stretches where both edges run the same way.

    Notes
    -----
    Returns a table with columns ``edge_a``, ``start_a``, ``end_a``,
    ``edge_b``, ``start_b``, ``end_b`` (distances along each edge),
    ``reversed`` (the edges run in opposite directions) and ``distance`` (the
    furthest that the stretch of ``a`` strays from ``b``).

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges(
    ...     [LineString([(0, 0), (10, 0)]), LineString([(4, 0.1), (14, 0.1)])])
    >>> snkit.match_edges(network, tolerance=0.5).round(3).values.tolist()
    [[0, 4.0, 10.0, 1, 0.0, 6.0, False, 0.1]]
    """
    check_distance(network, tolerance)
    arrays = Arrays(network)
    if min_length is None:
        min_length = 2 * tolerance
    overlaps = edge_overlaps(arrays, tolerance, min_length, directed)
    matches = pd.DataFrame(
        {
            "edge_a": arrays.edge_ids[overlaps["a"].to_numpy(dtype=np.int64)],
            "start_a": overlaps["start_a"].to_numpy(),
            "end_a": overlaps["end_a"].to_numpy(),
            "edge_b": arrays.edge_ids[overlaps["b"].to_numpy(dtype=np.int64)],
            "start_b": overlaps["start_b"].to_numpy(),
            "end_b": overlaps["end_b"].to_numpy(),
            "reversed": overlaps["reversed"].to_numpy(dtype=bool),
            "distance": overlaps["distance"].to_numpy(),
        }
    )
    return apply_condition(matches, condition, network, {"edge_a": "edges", "edge_b": "edges"})
