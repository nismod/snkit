"""Operations on one topological network.

Each operation finds candidates with a matcher (see :mod:`snkit.match`),
optionally filters them with a ``condition``, then applies exact topological
edits. Operations return a new network and never modify their input.

Pass ``return_lineage=True`` to also get a :class:`snkit.Lineage` recording
which input features each output feature came from.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
import shapely

from snkit import _kernel as K
from snkit.core import (
    FROM,
    ID,
    TO,
    Agg,
    Arrays,
    Lineage,
    _distinct,
    _pairs,
    aggregate,
    append_rows,
    check_distance,
    finish,
    from_ragged,
    identity_lineage,
    next_ids,
    with_geometry,
)
from snkit.match import (
    Condition,
    apply_condition,
    crossing_events,
    node_edge_pairs,
    node_pairs,
)
from snkit.network import Network

Result = Union[Network, Tuple[Network, Lineage]]


# ---------------------------------------------------------------------------
# Edits: exact changes to topology, by position


def _add_nodes(network: Network, xy: K.FloatArray) -> Network:
    """Append nodes at coordinates. Existing node positions are unchanged."""
    if len(xy) == 0:
        return network
    rows = with_geometry(
        pd.DataFrame({ID: next_ids(network.nodes[ID].to_numpy(), len(xy))}),
        shapely.points(xy),
        network.nodes.crs,
    )
    return Network(append_rows(network.nodes, rows), network.edges)


def _add_edges(network: Network, arrays: Arrays, src: K.IntArray, dst: K.IntArray) -> Network:
    """Append straight edges between nodes"""
    if len(src) == 0:
        return network
    xy = shapely.get_coordinates(np.asarray(network.nodes.geometry.values, dtype=object))
    node_ids = network.nodes[ID].to_numpy(dtype="uint64")
    lines = shapely.linestrings(np.stack([xy[src], xy[dst]], axis=1))
    rows = with_geometry(
        pd.DataFrame(
            {
                ID: next_ids(arrays.edge_ids, len(src)),
                FROM: node_ids[src],
                TO: node_ids[dst],
            }
        ),
        lines,
        network.edges.crs,
    )
    return Network(network.nodes, append_rows(network.edges, rows))


def _move_nodes(network: Network, arrays: Arrays, nodes: K.IntArray, xy: K.FloatArray) -> Network:
    """Move nodes, taking the ends of their edges with them"""
    if len(nodes) == 0:
        return network
    new_xy = arrays.xy.copy()
    new_xy[nodes] = xy
    coords = K.sync_ends(arrays.coords, arrays.offsets, new_xy, arrays.src, arrays.dst)
    return Network(
        with_geometry(network.nodes, shapely.points(new_xy), network.nodes.crs),
        with_geometry(network.edges, from_ragged(coords, arrays.offsets), network.edges.crs),
    )


def _split(
    network: Network,
    arrays: Arrays,
    edge: K.IntArray,
    measure: K.FloatArray,
    node: K.IntArray,
    seg: Optional[K.IntArray] = None,
    extensive: Sequence[str] = (),
    xy: Optional[K.FloatArray] = None,
) -> Tuple[Network, Lineage]:
    """Cut edges at measures, putting an existing node at each cut.

    The edge is bent to pass exactly through the node. ``xy`` gives node
    coordinates where the nodes table of ``network`` has more nodes than
    ``arrays`` knows about.
    """
    xy = arrays.xy if xy is None else xy
    edge = np.asarray(edge, dtype=np.int64)
    node = np.asarray(node, dtype=np.int64)
    measure = np.asarray(measure, dtype=float)
    if seg is None:
        seg = K.locate_segment(arrays.running, arrays.offsets, edge, measure)
    else:
        seg = np.clip(seg, arrays.offsets[edge], arrays.offsets[edge + 1] - 2)
    # a cut at an end that names the node already there changes nothing
    no_op = ((measure <= 0) & (node == arrays.src[edge])) | (
        (measure >= arrays.length[edge]) & (node == arrays.dst[edge])
    )
    order = np.lexsort((node, measure, seg, edge))
    order = order[~no_op[order]]
    edge, measure, node, seg = edge[order], measure[order], node[order], seg[order]
    repeat = np.zeros(len(edge), dtype=bool)
    repeat[1:] = (edge[1:] == edge[:-1]) & (node[1:] == node[:-1]) & (measure[1:] == measure[:-1])
    edge, node, seg = edge[~repeat], node[~repeat], seg[~repeat]
    if len(edge) == 0:
        return network, identity_lineage(network)

    coords, offsets, src, dst, parent = K.split(
        arrays.coords, arrays.offsets, arrays.src, arrays.dst, edge, seg, xy[node], node
    )
    was_cut = np.bincount(edge, minlength=arrays.m)[parent] > 0
    ids = arrays.edge_ids[parent]
    ids[was_cut] = next_ids(arrays.edge_ids, int(was_cut.sum()))
    node_ids = network.nodes[ID].to_numpy(dtype="uint64")
    table = pd.DataFrame(network.edges).iloc[parent].reset_index(drop=True)
    table[ID] = ids
    table[FROM] = node_ids[src]
    table[TO] = node_ids[dst]
    if extensive:
        seglen = K.segment_lengths(coords, offsets)
        length = np.add.reduceat(seglen, offsets[:-1])
        total = np.bincount(parent, weights=length, minlength=arrays.m)[parent]
        pieces = np.bincount(parent, minlength=arrays.m)[parent]
        share = np.where(total > 0, length / np.where(total > 0, total, 1), 1 / pieces)
        for column in extensive:
            table[column] = table[column].to_numpy(dtype=float) * share
    edges = with_geometry(table, from_ragged(coords, offsets), network.edges.crs)
    lineage = Lineage(_pairs(arrays.node_ids, arrays.node_ids), _pairs(ids, arrays.edge_ids[parent]))
    return Network(network.nodes, edges), lineage


def _merge_groups(
    network: Network,
    arrays: Arrays,
    labels: K.IntArray,
    position: str,
    geometry: str,
    tolerance: float,
    agg: Agg,
    max_spread: Optional[float] = None,
) -> Tuple[Network, Lineage]:
    """Replace each group of nodes with one node"""
    if position not in ("centroid", "first"):
        raise ValueError("position must be 'centroid' or 'first'")
    if geometry not in ("move", "extend"):
        raise ValueError("geometry must be 'move' or 'extend'")
    group, is_first = K.group_index(labels)
    count = int(is_first.sum())
    if count == arrays.n:
        return network, identity_lineage(network)
    xy = arrays.xy[is_first].copy()
    if position == "centroid":
        size = np.bincount(group, minlength=count)
        many = size > 1
        for axis in (0, 1):
            mean = np.bincount(group, weights=arrays.xy[:, axis], minlength=count) / size
            xy[many, axis] = mean[many]
    spread = np.hypot(*(arrays.xy - xy[group]).T)
    if max_spread is not None and len(spread) and spread.max() > max_spread:
        raise ValueError(
            f"merging would move a node {spread.max():g}, more than max_spread={max_spread:g}: "
            "nodes are merged in chains, so use a smaller tolerance or merge in stages"
        )

    node_table = aggregate(network.nodes, group, count, agg)
    node_ids = arrays.node_ids[is_first]
    node_table[ID] = node_ids
    nodes = with_geometry(node_table, shapely.points(xy), network.nodes.crs)

    src, dst = group[arrays.src], group[arrays.dst]
    if geometry == "move":
        coords = K.sync_ends(arrays.coords, arrays.offsets, xy, src, dst)
        offsets = arrays.offsets
    else:
        coords, offsets = K.extend_ends(arrays.coords, arrays.offsets, xy, src, dst)
    if arrays.m:
        new_length = np.add.reduceat(K.segment_lengths(coords, offsets), offsets[:-1])
    else:
        new_length = np.zeros(0)
    collapsed = (src == dst) & (arrays.src != arrays.dst)
    collapsed &= (arrays.length <= tolerance) | (new_length == 0)
    keep = ~collapsed
    table = pd.DataFrame(network.edges).reset_index(drop=True)
    table[FROM] = node_ids[src]
    table[TO] = node_ids[dst]
    edges = with_geometry(table, from_ragged(coords, offsets), network.edges.crs)[keep]
    edges = with_geometry(edges, np.asarray(edges.geometry.values, dtype=object), edges.crs)
    lineage = Lineage(
        _pairs(node_ids[group], arrays.node_ids),
        _pairs(arrays.edge_ids[keep], arrays.edge_ids[keep]),
    )
    return Network(nodes, edges), lineage


def _cluster(xy: K.FloatArray, tolerance: float) -> Tuple[K.FloatArray, K.IntArray]:
    """Group coordinates within tolerance: the first of each group, and each one's group"""
    if tolerance <= 0 or len(xy) < 2:
        return _distinct(xy)
    points = shapely.points(xy)
    a, b = shapely.STRtree(points).query(points, predicate="dwithin", distance=tolerance)
    group, is_first = K.group_index(K.components(len(xy), a, b))
    return xy[is_first], group


def _filtered(
    pairs: pd.DataFrame,
    condition: Condition,
    network: Network,
    arrays: Arrays,
    keys: Dict[str, Tuple[str, str]],
) -> pd.DataFrame:
    """Apply a condition to a table of positions, presenting it with ids"""
    if condition is None or len(pairs) == 0:
        return pairs
    view = pairs.reset_index(drop=True).copy()
    names = {}
    for column, (public, kind) in keys.items():
        ids = arrays.node_ids if kind == "nodes" else arrays.edge_ids
        view[public] = ids[view[column].to_numpy(dtype=np.int64)]
        names[public] = kind
    view = view.drop(columns=[c for c in keys if c not in names])
    view["_row"] = np.arange(len(view))
    kept = apply_condition(view, condition, network, names)["_row"].to_numpy()
    return pairs.iloc[kept].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Operations


def merge_nodes(
    network: Network,
    tolerance: float,
    position: str = "centroid",
    geometry: str = "move",
    condition: Condition = None,
    agg: Agg = None,
    max_spread: Optional[float] = None,
    return_lineage: bool = False,
) -> Result:
    """Merge nodes that are within ``tolerance`` of each other into one node.

    Nodes are merged in chains: if A is near B and B is near C, all three
    become one node even if A is not near C.

    Parameters
    ----------
    position
        Where the merged node sits: the ``"centroid"`` of its members, or the
        position of the ``"first"`` member in the nodes table.
    geometry
        ``"move"`` the end vertex of each edge to the merged node, or
        ``"extend"`` each edge with an extra vertex to reach it, leaving its
        original line intact.
    condition
        Function of the :func:`snkit.match_nodes` table (with node attributes
        suffixed ``_a`` and ``_b``) returning which pairs may merge.
    agg
        Rule per attribute column for merged nodes: ``"first"``, ``"sum"``,
        ``"min"``, ``"max"``, ``"mean"``, ``"list"`` or a function. By default
        a value is kept only if all members agree, and is otherwise null.
    max_spread
        Raise an error if merging would move any node further than this.

    Notes
    -----
    The merged node keeps the id of its first member. An edge whose two ends
    merge into one node is dropped if it was no longer than ``tolerance``.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges(
    ...     [LineString([(0, 0), (1, 0)]), LineString([(1.05, 0), (2, 0)])])
    >>> merged = snkit.merge_nodes(network, tolerance=0.1)
    >>> [line.wkt for line in merged.edges.geometry]
    ['LINESTRING (0 0, 1.025 0)', 'LINESTRING (1.025 0, 2 0)']
    >>> merged.edges[["from_id", "to_id"]].values.tolist()
    [[0, 1], [1, 3]]
    """
    check_distance(network, tolerance)
    arrays = Arrays(network)
    pairs = node_pairs(arrays, tolerance)
    pairs = _filtered(pairs, condition, network, arrays, {"a": ("node_a", "nodes"), "b": ("node_b", "nodes")})
    labels = K.components(arrays.n, pairs["a"].to_numpy(), pairs["b"].to_numpy())
    merged, lineage = _merge_groups(network, arrays, labels, position, geometry, tolerance, agg, max_spread)
    return finish(merged, [lineage], return_lineage)


def link_nodes(
    network: Network,
    tolerance: float,
    how: str = "all",
    condition: Condition = None,
    return_lineage: bool = False,
) -> Result:
    """Add an edge between nodes that are within ``tolerance`` of each other.

    Parameters
    ----------
    how
        ``"all"``: link every pair within tolerance.
        ``"nearest"``: link each node only to its nearest neighbour.
    condition
        Function of the :func:`snkit.match_nodes` table returning which pairs
        to link.

    Notes
    -----
    Pairs that already share an edge, and nodes at exactly the same place,
    are not linked.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges(
    ...     [LineString([(0, 0), (1, 0)]), LineString([(1.05, 0), (2, 0)])])
    >>> linked = snkit.link_nodes(network, tolerance=0.1)
    >>> [line.wkt for line in linked.edges.geometry][-1]
    'LINESTRING (1 0, 1.05 0)'
    """
    if how not in ("all", "nearest"):
        raise ValueError("how must be 'all' or 'nearest'")
    check_distance(network, tolerance)
    arrays = Arrays(network)
    pairs = node_pairs(arrays, tolerance)
    pairs = pairs[pairs["distance"] > 0]
    pairs = _filtered(pairs, condition, network, arrays, {"a": ("node_a", "nodes"), "b": ("node_b", "nodes")})
    a, b = pairs["a"].to_numpy(), pairs["b"].to_numpy()
    if how == "nearest" and len(a):
        both = pd.DataFrame(
            {
                "node": np.concatenate([a, b]),
                "pair": np.tile(np.arange(len(a)), 2),
                "distance": np.tile(pairs["distance"].to_numpy(), 2),
            }
        ).sort_values(["node", "distance", "pair"], kind="stable")
        chosen = np.unique(both.drop_duplicates("node")["pair"].to_numpy())
        a, b = a[chosen], b[chosen]
    low, high = np.minimum(arrays.src, arrays.dst), np.maximum(arrays.src, arrays.dst)
    linked = np.isin(a * arrays.n + b, low * arrays.n + high)
    out = _add_edges(network, arrays, a[~linked], b[~linked])
    return finish(out, [identity_lineage(network)], return_lineage)


def split_edges(
    network: Network,
    locations: pd.DataFrame,
    tolerance: float = 0,
    extensive: Sequence[str] = (),
    return_lineage: bool = False,
) -> Result:
    """Cut edges at given locations, with a node at each cut.

    Parameters
    ----------
    locations
        Table with columns ``edge`` (id) and ``measure`` (distance along the
        edge), and optionally ``node``: the id of an existing node to put at
        the cut, in which case the edge is bent to pass through it. Without a
        node, a new one is created on the line.
    tolerance
        A cut that would create a new node within this distance (along the
        edge) of an end of the edge is not made. New nodes within this
        distance of each other become one node.
    extensive
        Columns holding quantities that belong to the whole edge, to be
        shared between pieces in proportion to length. Other attributes are
        copied to each piece.

    Notes
    -----
    Pieces of a cut edge all get new ids.

    Examples
    --------
    >>> import pandas as pd
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges([LineString([(0, 0), (4, 0)])])
    >>> cut = snkit.split_edges(network, pd.DataFrame({"edge": [0], "measure": [1.0]}))
    >>> [line.wkt for line in cut.edges.geometry]
    ['LINESTRING (0 0, 1 0)', 'LINESTRING (1 0, 4 0)']
    """
    check_distance(network, tolerance)
    arrays = Arrays(network)
    edge = pd.Index(arrays.edge_ids).get_indexer(locations["edge"].to_numpy())
    if (edge < 0).any():
        raise ValueError("locations refer to edge ids that are not in the network")
    measure = locations["measure"].to_numpy(dtype=float)
    node = np.full(len(edge), -1, dtype=np.int64)
    if "node" in locations.columns:
        given = locations["node"].notna().to_numpy()
        found = pd.Index(arrays.node_ids).get_indexer(locations["node"][given].to_numpy())
        if (found < 0).any():
            raise ValueError("locations refer to node ids that are not in the network")
        node[given] = found
    fresh = node < 0
    near_end = fresh & ((measure <= tolerance) | (measure >= arrays.length[edge] - tolerance))
    edge, measure, node = edge[~near_end], measure[~near_end], node[~near_end]
    fresh = node < 0
    on_line = shapely.line_interpolate_point(arrays.lines[edge[fresh]], measure[fresh])
    new_xy, index = _cluster(shapely.get_coordinates(on_line).reshape(-1, 2), tolerance)
    node[fresh] = arrays.n + index
    out = _add_nodes(network, new_xy)
    out, lineage = _split(out, arrays, edge, measure, node, None, extensive, np.concatenate([arrays.xy, new_xy]))
    return finish(out, [lineage], return_lineage)


def split_edges_at_nodes(
    network: Network,
    tolerance: float = 0,
    move: str = "edge",
    condition: Condition = None,
    extensive: Sequence[str] = (),
    return_lineage: bool = False,
) -> Result:
    """Split edges at nodes that lie on or near them.

    Parameters
    ----------
    tolerance
        How near a node must be to an edge to split it.
    move
        ``"edge"``: bend the edge to pass through the node, which stays put.
        ``"node"``: move the node onto the nearest edge first.
    condition
        Function of the :func:`snkit.match_nodes_to_edges` table (with
        attributes suffixed ``_node`` and ``_edge``) returning which matches
        to act on.
    extensive
        Columns to share between pieces in proportion to length.

    Examples
    --------
    >>> from shapely import LineString, Point
    >>> import snkit
    >>> network = snkit.from_nodes_and_edges(
    ...     [Point(1, 0.01)], [LineString([(0, 0), (2, 0)])])
    >>> split = snkit.split_edges_at_nodes(network, tolerance=0.05)
    >>> [line.wkt for line in split.edges.geometry]
    ['LINESTRING (0 0, 1 0.01)', 'LINESTRING (1 0.01, 2 0)']
    """
    if move not in ("edge", "node"):
        raise ValueError("move must be 'edge' or 'node'")
    check_distance(network, tolerance)
    lineages = [identity_lineage(network)]
    for _ in range(10):
        arrays = Arrays(network)
        pairs = node_edge_pairs(arrays, tolerance, "all")
        pairs = pairs[pairs["end"] == 0]
        pairs = _filtered(pairs, condition, network, arrays, {"node": ("node", "nodes"), "edge": ("edge", "edges")})
        if len(pairs) == 0:
            break
        if move == "node":
            nearest = pairs.drop_duplicates("node")
            network = _move_nodes(
                network,
                arrays,
                nearest["node"].to_numpy(),
                nearest[["x", "y"]].to_numpy(),
            )
            moved = Arrays(network)
            again = node_edge_pairs(moved, tolerance, "all")
            again = again[again["end"] == 0]
            pairs = again.merge(pairs[["node", "edge"]], on=["node", "edge"])
            arrays = moved
        network, lineage = _split(
            network,
            arrays,
            pairs["edge"].to_numpy(),
            pairs["measure"].to_numpy(),
            pairs["node"].to_numpy(),
            None,
            extensive,
        )
        lineages.append(lineage)
    return finish(network, lineages, return_lineage)


def link_nodes_to_edges(
    network: Network,
    how: str = "nearest",
    max_distance: Optional[float] = None,
    nodes: Optional[Any] = None,
    condition: Condition = None,
    link: bool = True,
    tolerance: float = 0,
    extensive: Sequence[str] = (),
    return_lineage: bool = False,
) -> Result:
    """Connect nodes to edges: project each node onto an edge, split the edge
    there, and add a new edge from the node to the split.

    Parameters
    ----------
    how
        ``"nearest"``: connect each node to its nearest edge.
        ``"all"``: connect each node to every edge within ``max_distance``.
    max_distance
        Furthest a node may be from an edge to be connected to it.
    nodes
        Boolean mask over the nodes table choosing which nodes to connect. By
        default, the nodes that have no edges.
    condition
        Function of the :func:`snkit.match_nodes_to_edges` table returning
        which matches to act on.
    link
        If False, move each node onto its nearest edge and split the edge
        there, without adding a connecting edge.
    tolerance
        Where the projection lands within this distance of an end of the
        edge, connect to the node at that end and do not split.
    extensive
        Columns to share between pieces in proportion to length.

    Notes
    -----
    A node is never connected to an edge it is already an end of.

    Examples
    --------
    >>> from shapely import LineString, Point
    >>> import snkit
    >>> network = snkit.from_nodes_and_edges(
    ...     [Point(1, 1)], [LineString([(0, 0), (2, 0)])])
    >>> linked = snkit.link_nodes_to_edges(network)
    >>> [line.wkt for line in linked.edges.geometry]
    ['LINESTRING (0 0, 1 0)', 'LINESTRING (1 0, 2 0)', 'LINESTRING (1 1, 1 0)']
    """
    if not link and how != "nearest":
        raise ValueError("link=False needs how='nearest': a node can only move to one place")
    check_distance(network, max_distance)
    check_distance(network, tolerance)
    arrays = Arrays(network)
    mask = arrays.degree() == 0 if nodes is None else np.asarray(nodes, dtype=bool)
    pairs = node_edge_pairs(arrays, max_distance, how, mask)
    pairs = _filtered(pairs, condition, network, arrays, {"node": ("node", "nodes"), "edge": ("edge", "edges")})
    node = pairs["node"].to_numpy(dtype=np.int64)
    edge = pairs["edge"].to_numpy(dtype=np.int64)
    measure = pairs["measure"].to_numpy(dtype=float)
    distance = pairs["distance"].to_numpy(dtype=float)
    end = pairs["end"].to_numpy()
    at_start = (end == -1) | (measure <= tolerance)
    at_end = ~at_start & ((end == 1) | (measure >= arrays.length[edge] - tolerance))
    interior = ~at_start & ~at_end

    if not link:
        out = _move_nodes(network, arrays, node[interior], pairs[["x", "y"]].to_numpy()[interior])
        moved = Arrays(out)
        out, lineage = _split(out, moved, edge[interior], measure[interior], node[interior], None, extensive)
        return finish(out, [lineage], return_lineage)

    target = np.where(at_start, arrays.src[edge], np.where(at_end, arrays.dst[edge], -1))
    on_edge = interior & (distance == 0)
    target[on_edge] = node[on_edge]
    fresh = target < 0
    new_xy, index = _cluster(pairs[["x", "y"]].to_numpy()[fresh], tolerance)
    target[fresh] = arrays.n + index
    out = _add_nodes(network, new_xy)
    out, lineage = _split(
        out,
        arrays,
        edge[interior],
        measure[interior],
        target[interior],
        None,
        extensive,
        np.concatenate([arrays.xy, new_xy]),
    )
    wanted = (target != node) & (distance > 0)
    a, b = node[wanted], target[wanted]
    count = arrays.n + len(new_xy)
    key = np.minimum(a, b) * count + np.maximum(a, b)
    _, first = np.unique(key, return_index=True)
    first.sort()
    a, b, key = a[first], b[first], key[first]
    low, high = np.minimum(arrays.src, arrays.dst), np.maximum(arrays.src, arrays.dst)
    exists = np.isin(key, low * count + high)
    out = _add_edges(out, Arrays(out), a[~exists], b[~exists])
    return finish(out, [lineage], return_lineage)


def split_edges_at_crossings(
    network: Network,
    tolerance: float = 0,
    condition: Condition = None,
    extensive: Sequence[str] = (),
    return_lineage: bool = False,
) -> Result:
    """Split edges where they cross, with a shared node at each crossing.

    Also splits an edge where another edge ends on it, and where an edge
    crosses itself.

    Parameters
    ----------
    tolerance
        A crossing within this distance (along the edge) of an end of one of
        the edges uses the node at that end, bending the other edge to it,
        instead of creating a new node beside it. Crossings within this
        distance of each other share a node.
    condition
        Function of the :func:`snkit.find_crossings` table (with edge
        attributes suffixed ``_a`` and ``_b``) returning which crossings to
        split, for example ``lambda x: x.level_a == x.level_b``.
    extensive
        Columns to share between pieces in proportion to length.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges(
    ...     [LineString([(0, 0), (2, 2)]), LineString([(0, 2), (2, 0)])])
    >>> split = snkit.split_edges_at_crossings(network)
    >>> [line.wkt for line in split.edges.geometry]  # doctest: +NORMALIZE_WHITESPACE
    ['LINESTRING (0 0, 1 1)', 'LINESTRING (1 1, 2 2)',
     'LINESTRING (0 2, 1 1)', 'LINESTRING (1 1, 2 0)']
    >>> split.nodes.geometry.iloc[-1].wkt
    'POINT (1 1)'
    """
    check_distance(network, tolerance)
    lineages = [identity_lineage(network)]
    for _ in range(10):
        arrays = Arrays(network)
        events = crossing_events(arrays)
        events = _filtered(
            events,
            condition,
            network,
            arrays,
            {"edge_a": ("edge_a", "edges"), "edge_b": ("edge_b", "edges")},
        )
        if len(events) == 0:
            break
        side = {}
        for name in "ab":
            edge = events[f"edge_{name}"].to_numpy(dtype=np.int64)
            measure = events[f"measure_{name}"].to_numpy(dtype=float)
            end = events[f"end_{name}"].to_numpy()
            at_start = (end == -1) | (measure <= tolerance)
            at_end = ~at_start & ((end == 1) | (measure >= arrays.length[edge] - tolerance))
            end_node = np.where(at_start, arrays.src[edge], np.where(at_end, arrays.dst[edge], -1))
            side[name] = (edge, measure, end, end_node)
        node = np.where(side["a"][3] >= 0, side["a"][3], side["b"][3])
        fresh = node < 0
        new_xy, index = _cluster(events[["x", "y"]].to_numpy()[fresh], tolerance)
        node[fresh] = arrays.n + index

        cut_edge, cut_measure, cut_node, cut_seg = [], [], [], []
        for name in "ab":
            edge, measure, end, end_node = side[name]
            # no cut where the crossing is at this edge's own end
            cut = (end == 0) & (end_node != node)
            cut_edge.append(edge[cut])
            cut_measure.append(measure[cut])
            cut_node.append(node[cut])
            cut_seg.append(events[f"vertex_{name}"].to_numpy(dtype=np.int64)[cut])
        if sum(len(c) for c in cut_edge) == 0:
            break
        network = _add_nodes(network, new_xy)
        network, lineage = _split(
            network,
            arrays,
            np.concatenate(cut_edge),
            np.concatenate(cut_measure),
            np.concatenate(cut_node),
            np.concatenate(cut_seg),
            extensive,
            np.concatenate([arrays.xy, new_xy]),
        )
        lineages.append(lineage)
    return finish(network, lineages, return_lineage)


def _crossing_pairs(network: Network) -> Any:
    arrays = Arrays(network)
    events = crossing_events(arrays)
    return np.unique(events["edge_a"].to_numpy(dtype=np.int64) * arrays.m + events["edge_b"].to_numpy(dtype=np.int64))


def simplify_edges(network: Network, tolerance: float, return_lineage: bool = False) -> Result:
    """Simplify edge geometries, removing vertices that change the line by less
    than ``tolerance``.

    End vertices never move, so the topology is unchanged. An edge whose
    simplified line would cross an edge it did not cross before keeps its
    original line.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges([LineString([(0, 0), (1, 0.001), (2, 0)])])
    >>> [line.wkt for line in snkit.simplify_edges(network, tolerance=0.01).edges.geometry]
    ['LINESTRING (0 0, 2 0)']
    """
    check_distance(network, tolerance)
    arrays = Arrays(network)
    original = arrays.lines
    simple = shapely.simplify(original, tolerance, preserve_topology=False)
    degenerate = (shapely.length(simple) == 0) | (shapely.get_num_points(simple) < 2)
    simple = np.where(degenerate, original, simple)
    changed = shapely.get_num_points(simple) != shapely.get_num_points(original)
    if changed.any():
        before = _crossing_pairs(network)
        while True:
            candidate = Network(network.nodes, with_geometry(network.edges, simple, network.edges.crs))
            created = np.setdiff1d(_crossing_pairs(candidate), before)
            involved = np.unique(np.concatenate([created // arrays.m, created % arrays.m]))
            involved = involved[changed[involved]]
            if len(involved) == 0:
                break
            simple[involved] = original[involved]
            changed[involved] = False
    out = Network(network.nodes, with_geometry(network.edges, simple, network.edges.crs))
    return finish(out, [identity_lineage(network)], return_lineage)


def merge_edges(
    network: Network,
    by: Optional[Sequence[str]] = None,
    keep: Optional[Any] = None,
    directed: bool = False,
    agg: Agg = None,
    return_lineage: bool = False,
) -> Result:
    """Merge chains of edges that meet at nodes with exactly two edges.

    Each chain becomes one edge and the nodes along it are removed.

    Parameters
    ----------
    by
        Only merge edges that have equal values in these columns.
    keep
        Nodes to keep even if they have two edges: a boolean mask over the
        nodes table, or the name of a boolean column in it.
    directed
        Only merge through a node with one edge arriving and one leaving. By
        default direction is ignored, and edges are reversed as needed to run
        the same way as the earliest edge of the chain in the edges table.
    agg
        Rule per attribute column for merged edges: ``"first"``, ``"sum"``,
        ``"min"``, ``"max"``, ``"mean"``, ``"list"`` or a function. By default
        a value is kept only if all members agree, and is otherwise null.

    Notes
    -----
    A merged edge gets a new id and takes the place of its earliest member. A
    closed ring of such nodes keeps one node, as a single edge from that node
    to itself.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges(
    ...     [LineString([(0, 0), (1, 0)]), LineString([(2, 0), (1, 0)])])
    >>> merged = snkit.merge_edges(network)
    >>> [line.wkt for line in merged.edges.geometry]
    ['LINESTRING (0 0, 1 0, 2 0)']
    >>> merged.nodes["id"].tolist()
    [0, 2]
    """
    arrays = Arrays(network)
    n, m = arrays.n, arrays.m
    src, dst = arrays.src, arrays.dst
    # the two edge ends at each node that has exactly two
    end_node = np.concatenate([src, dst])
    end_edge = np.tile(np.arange(m), 2)
    end_is_dst = np.repeat([False, True], m)
    order = np.argsort(end_node, kind="stable")
    block = np.searchsorted(end_node[order], np.arange(n))
    through = np.flatnonzero(arrays.degree() == 2)
    first, second = order[block[through]], order[block[through] + 1]
    e1, e2 = end_edge[first], end_edge[second]
    ok = e1 != e2
    if keep is not None:
        kept = network.nodes[keep] if isinstance(keep, str) else keep
        ok &= ~np.asarray(kept, dtype=bool)[through]
    for column in by or ():
        values = network.edges[column]
        left, right = values.iloc[e1].reset_index(drop=True), values.iloc[e2].reset_index(drop=True)
        ok &= ((left == right) | (left.isna() & right.isna())).to_numpy(dtype=bool)
    if directed:
        ok &= end_is_dst[first] != end_is_dst[second]
    through, e1, e2 = through[ok], e1[ok], e2[ok]
    labels = K.components(m, e1, e2)
    group, is_first = K.group_index(labels)
    count = int(is_first.sum())
    if count == m:
        return finish(network, [identity_lineage(network)], return_lineage)

    # walk each chain from one end to the other
    passes = dict(zip(through.tolist(), zip(e1.tolist(), e2.tolist())))
    src_l, dst_l = src.tolist(), dst.tolist()
    size = np.bincount(group, minlength=count)
    in_chain = np.flatnonzero(size[group] > 1)
    members: Dict[int, List[int]] = {}
    for e, g in zip(in_chain.tolist(), group[in_chain].tolist()):
        members.setdefault(g, []).append(e)
    chain_group, chain_src, chain_dst, take, lengths = [], [], [], [], []
    removed: List[int] = []
    offsets = arrays.offsets
    for g, edges_in in members.items():
        start = None
        for e in edges_in:
            if src_l[e] not in passes:
                start = (e, False)
                break
            if dst_l[e] not in passes:
                start = (e, True)
                break
        anchor = None
        if start is None:  # a ring: begin at its earliest edge and keep that node
            start = (edges_in[0], False)
            anchor = src_l[edges_in[0]]
        path = []
        e, backwards = start
        while True:
            path.append((e, backwards))
            node = src_l[e] if backwards else dst_l[e]
            if node not in passes or node == anchor:
                break
            a, b = passes[node]
            e = b if a == e else a
            backwards = dst_l[e] == node
        if dict(path)[edges_in[0]]:
            path = [(e, not backwards) for e, backwards in reversed(path)]
        total = 0
        for position, (e, backwards) in enumerate(path):
            index = np.arange(offsets[e], offsets[e + 1])
            if backwards:
                index = index[::-1]
            if position:
                removed.append(src_l[e] if not backwards else dst_l[e])
                index = index[1:]
            take.append(index)
            total += len(index)
        first_edge, first_backwards = path[0]
        last_edge, last_backwards = path[-1]
        chain_group.append(g)
        chain_src.append(dst_l[first_edge] if first_backwards else src_l[first_edge])
        chain_dst.append(src_l[last_edge] if last_backwards else dst_l[last_edge])
        lengths.append(total)

    chain_lines = from_ragged(arrays.coords[np.concatenate(take)], np.concatenate([[0], np.cumsum(lengths)]))
    groups = np.asarray(chain_group, dtype=np.int64)
    lines = arrays.lines[is_first].copy()
    lines[groups] = chain_lines
    new_src, new_dst = src[is_first].copy(), dst[is_first].copy()
    new_src[groups], new_dst[groups] = chain_src, chain_dst
    ids = arrays.edge_ids[is_first].copy()
    ids[groups] = next_ids(arrays.edge_ids, len(groups))

    table = aggregate(network.edges, group, count, agg)
    table[ID] = ids
    table[FROM] = arrays.node_ids[new_src]
    table[TO] = arrays.node_ids[new_dst]
    edges = with_geometry(table, lines, network.edges.crs)
    keep_node = np.ones(n, dtype=bool)
    keep_node[removed] = False
    nodes = with_geometry(network.nodes[keep_node], arrays.points[keep_node], network.nodes.crs)
    lineage = Lineage(
        _pairs(arrays.node_ids[keep_node], arrays.node_ids[keep_node]),
        _pairs(ids[group], arrays.edge_ids),
    )
    return finish(Network(nodes, edges), [lineage], return_lineage)


def duplicate_pairs(arrays: Arrays, tolerance: float, directed: bool = False) -> Tuple[K.IntArray, K.IntArray]:
    """Pairs of edge positions with the same end nodes and nearly the same line"""
    src, dst = arrays.src, arrays.dst
    if not directed:
        src, dst = np.minimum(src, dst), np.maximum(src, dst)
    table = pd.DataFrame({"key": src * max(arrays.n, 1) + dst, "edge": np.arange(arrays.m)})
    table = table[table.duplicated("key", keep=False)]
    pairs = table.merge(table, on="key")
    pairs = pairs[pairs["edge_x"] < pairs["edge_y"]]
    a, b = pairs["edge_x"].to_numpy(), pairs["edge_y"].to_numpy()
    apart = shapely.hausdorff_distance(arrays.lines[a], arrays.lines[b])
    same = apart <= tolerance
    return a[same], b[same]


def drop_duplicate_edges(
    network: Network,
    tolerance: float = 0,
    directed: bool = False,
    return_lineage: bool = False,
) -> Result:
    """Drop edges that duplicate an earlier edge: the same two end nodes, and
    lines within ``tolerance`` of each other all along.

    With ``directed=True`` an edge running the opposite way is not a duplicate.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges(
    ...     [LineString([(0, 0), (1, 0)]), LineString([(1, 0), (0.5, 0), (0, 0)])])
    >>> len(snkit.drop_duplicate_edges(network).edges)
    1
    """
    check_distance(network, tolerance)
    arrays = Arrays(network)
    _, later = duplicate_pairs(arrays, tolerance, directed)
    keep = np.ones(arrays.m, dtype=bool)
    keep[later] = False
    edges = with_geometry(network.edges[keep], arrays.lines[keep], network.edges.crs)
    lineage = Lineage(
        _pairs(arrays.node_ids, arrays.node_ids),
        _pairs(arrays.edge_ids[keep], arrays.edge_ids[keep]),
    )
    return finish(Network(network.nodes, edges), [lineage], return_lineage)


def label_components(network: Network, column: str = "component") -> Network:
    """Add a column to nodes and edges numbering the connected part each is in.

    Parts are numbered from 0 in order of their first node.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> network = snkit.from_edges(
    ...     [LineString([(0, 0), (1, 0)]), LineString([(5, 5), (6, 5)])])
    >>> snkit.label_components(network).edges["component"].tolist()
    [0, 1]
    """
    arrays = Arrays(network)
    group, _ = K.group_index(K.components(arrays.n, arrays.src, arrays.dst))
    nodes, edges = network.nodes.copy(), network.edges.copy()
    nodes[column] = group
    edges[column] = group[arrays.src]
    return Network(
        with_geometry(nodes, arrays.points, nodes.crs),
        with_geometry(edges, arrays.lines, edges.crs),
    )


__all__ = [
    "drop_duplicate_edges",
    "label_components",
    "link_nodes",
    "link_nodes_to_edges",
    "merge_edges",
    "merge_nodes",
    "simplify_edges",
    "split_edges",
    "split_edges_at_crossings",
    "split_edges_at_nodes",
]
