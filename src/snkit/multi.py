"""Operations on two or more networks."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from snkit import _kernel as K
from snkit.core import (
    FROM,
    ID,
    TO,
    Agg,
    Arrays,
    _distinct,
    check_distance,
)
from snkit.match import edge_overlaps, node_pairs
from snkit.arrays import GEOM, ArrayNetwork, crs_of, operation, with_geometry
from snkit.network import Network
from snkit.operations import (
    _add_nodes,
    _merge_groups,
    _split,
    duplicate_pairs,
)

Networks = Union[Dict[Any, Network], Sequence[Network]]
_SIDE = "_snkit_side"


@operation
def combine(networks: Networks, column: Optional[str] = "source") -> Network:
    """Place networks side by side in one network, without connecting them.

    Parameters
    ----------
    networks
        A dict of name to network, or a sequence of networks (named 0, 1, ...).
    column
        Name of a column added to nodes and edges recording which network
        each came from. None to add no column.

    Notes
    -----
    The first network keeps its ids. Ids of each later network are shifted up
    to follow on from the one before.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> road = snkit.from_edges([LineString([(0, 0), (1, 0)])])
    >>> rail = snkit.from_edges([LineString([(0, 1), (1, 1)])])
    >>> both = snkit.combine({"road": road, "rail": rail})
    >>> both.edges[["id", "from_id", "to_id", "source"]].values.tolist()
    [[0, 0, 1, 'road'], [1, 2, 3, 'rail']]
    """
    named = networks if isinstance(networks, dict) else dict(enumerate(networks))
    if not named:
        return ArrayNetwork()
    crs = None
    node_tables, edge_tables = [], []
    node_shift = edge_shift = 0
    for name, network in named.items():
        nodes, edges = pd.DataFrame(network.nodes).copy(), pd.DataFrame(network.edges).copy()
        for table in (network.nodes, network.edges):
            if len(table) and table.crs is not None:
                if crs is not None and table.crs != crs:
                    raise ValueError("networks have different CRS: reproject them to one first")
                crs = table.crs
        if column is not None:
            if column in nodes.columns or column in edges.columns:
                raise ValueError(f"a column named {column!r} already exists: choose another with column=")
            nodes[column] = name
            edges[column] = name
        nodes[ID] = nodes[ID].to_numpy(dtype="uint64") + np.uint64(node_shift)
        edges[ID] = edges[ID].to_numpy(dtype="uint64") + np.uint64(edge_shift)
        edges[FROM] = edges[FROM].to_numpy(dtype="uint64") + np.uint64(node_shift)
        edges[TO] = edges[TO].to_numpy(dtype="uint64") + np.uint64(node_shift)
        if len(nodes):
            node_shift = int(nodes[ID].max()) + 1
        if len(edges):
            edge_shift = int(edges[ID].max()) + 1
        node_tables.append(nodes)
        edge_tables.append(edges)
    nodes = pd.concat(node_tables, ignore_index=True, sort=False)
    edges = pd.concat(edge_tables, ignore_index=True, sort=False)
    return Network(
        with_geometry(nodes, nodes[GEOM].array, crs),
        with_geometry(edges, edges[GEOM].array, crs),
    )


@operation
def stitch(
    networks: Networks,
    tolerance: float = 0,
    on: Optional[str] = None,
    column: Optional[str] = "source",
) -> Network:
    """Join networks at the nodes they share.

    For networks that were cut apart, by tile or by country, and have nodes
    in common along the cut.

    Parameters
    ----------
    tolerance
        Nodes from different networks within this distance are the same node.
    on
        Instead of matching by position, nodes from different networks with
        the same value in this column are the same node. Use ``"id"`` to
        match on the ids the networks had before stitching.
    column
        As for :func:`snkit.combine`.

    Notes
    -----
    A shared node takes the position and id it has in the earliest network.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> west = snkit.from_edges([LineString([(0, 0), (1, 0)])])
    >>> east = snkit.from_edges([LineString([(1, 0), (2, 0)])])
    >>> whole = snkit.stitch([west, east])
    >>> whole.edges[["from_id", "to_id"]].values.tolist()
    [[0, 1], [1, 3]]
    """
    named = networks if isinstance(networks, dict) else dict(enumerate(networks))
    both = combine(named, _SIDE)
    arrays = Arrays(both)
    side = pd.factorize(both.nodes[_SIDE])[0]
    if on is None:
        check_distance(both, tolerance)
        pairs = node_pairs(arrays, tolerance)
        a, b = pairs["a"].to_numpy(), pairs["b"].to_numpy()
    else:
        if on == ID:
            key = pd.concat([n.nodes[ID] for n in named.values()], ignore_index=True)
        else:
            key = both.nodes[on]
        table = pd.DataFrame({"key": key.to_numpy(), "node": np.arange(arrays.n)}).dropna()
        table = table[table.duplicated("key", keep=False)]
        first = table.drop_duplicates("key").set_index("key")["node"]
        a, b = first.reindex(table["key"]).to_numpy(), table["node"].to_numpy()
    cross = side[a] != side[b]
    labels = K.components(arrays.n, a[cross], b[cross])
    take_first: Agg = {str(column): "first" for column in both.nodes.columns}
    merged, _ = _merge_groups(both, arrays, labels, "first", "move", tolerance, take_first)
    return _rename_side(merged, column, named)


def _rename_side(network: Network, column: Optional[str], named: Dict[Any, Network]) -> Network:
    nodes, edges = network.nodes, network.edges
    if column is None:
        nodes, edges = nodes.drop(columns=_SIDE), edges.drop(columns=_SIDE)
    else:
        if column in nodes.columns or column in edges.columns:
            raise ValueError(f"a column named {column!r} already exists: choose another")
        nodes, edges = nodes.rename(columns={_SIDE: column}), edges.rename(columns={_SIDE: column})
    return Network(
        with_geometry(nodes, nodes[GEOM].array, crs_of(network)),
        with_geometry(edges, edges[GEOM].array, crs_of(network)),
    )


def _overlay(a: Network, b: Network, tolerance: float, split: bool) -> Tuple[Network, Any, Any, Any]:
    """Line two networks up against each other.

    Returns the combined network with matching nodes merged; for each edge,
    whether it has a twin on the other side; for each node, whether it is in
    both networks; and for each node, whether it has no edge on side a.
    """
    both = combine({"a": a, "b": b}, _SIDE)
    check_distance(both, tolerance)
    if split:
        arrays = Arrays(both)
        side = both.edges[_SIDE].to_numpy()
        overlaps = edge_overlaps(arrays, tolerance, 2 * tolerance)
        ea = overlaps["a"].to_numpy(dtype=np.int64)
        eb = overlaps["b"].to_numpy(dtype=np.int64)
        cross = side[ea] != side[eb]
        overlaps, ea, eb = overlaps[cross], ea[cross], eb[cross]
        edge = np.concatenate([ea, ea, eb, eb])
        measure = np.concatenate([overlaps[c].to_numpy(dtype=float) for c in ("start_a", "end_a", "start_b", "end_b")])
        interior = (measure > tolerance) & (measure < arrays.length[edge] - tolerance)
        edge, measure = edge[interior], measure[interior]
        new_xy, index = _distinct(arrays.locate(edge, measure)[2])
        new_side = np.empty(len(new_xy), dtype=object)
        new_side[index] = side[edge]
        both = _add_nodes(both, new_xy)
        nodes = both.nodes.copy()
        nodes.loc[nodes.index[arrays.n :], _SIDE] = new_side
        both = Network(with_geometry(nodes, nodes[GEOM].array, crs_of(both)), both.edges)
        both, _ = _split(
            both,
            arrays,
            edge,
            measure,
            arrays.n + index,
            None,
            (),
            np.concatenate([arrays.xy, new_xy]),
        )

    # a's nodes first, so that a merged node takes a's position and id
    order = np.argsort(both.nodes[_SIDE].to_numpy() != "a", kind="stable")
    nodes = both.nodes.iloc[order]
    both = Network(with_geometry(nodes, nodes[GEOM].array, crs_of(both)), both.edges)
    arrays = Arrays(both)
    node_side = both.nodes[_SIDE].to_numpy()
    pairs = node_pairs(arrays, tolerance)
    pa, pb = pairs["a"].to_numpy(), pairs["b"].to_numpy()
    cross = node_side[pa] != node_side[pb]
    labels = K.components(arrays.n, pa[cross], pb[cross])
    group, is_first = K.group_index(labels)
    count = int(is_first.sum())
    in_a = np.bincount(group, weights=node_side == "a", minlength=count) > 0
    in_b = np.bincount(group, weights=node_side == "b", minlength=count) > 0
    # a node in both networks takes a's attributes
    take_first: Agg = {str(column): "first" for column in both.nodes.columns}
    merged, _ = _merge_groups(both, arrays, labels, "first", "move", tolerance, take_first)

    arrays = Arrays(merged)
    edge_side = merged.edges[_SIDE].to_numpy()
    first, second = duplicate_pairs(arrays, tolerance)
    cross = edge_side[first] != edge_side[second]
    twin = np.zeros(arrays.m, dtype=bool)
    twin[first[cross]] = True
    twin[second[cross]] = True
    from_a = edge_side == "a"
    used_by_a = np.zeros(arrays.n, dtype=bool)
    used_by_a[arrays.src[from_a]] = True
    used_by_a[arrays.dst[from_a]] = True
    return merged, twin, in_a & in_b, in_a & ~used_by_a


def _select(network: Network, keep_edges: Any, keep_nodes: Any) -> Network:
    arrays = Arrays(network)
    keep_nodes = keep_nodes.copy()
    keep_nodes[arrays.src[keep_edges]] = True
    keep_nodes[arrays.dst[keep_edges]] = True
    nodes = network.nodes[keep_nodes].drop(columns=_SIDE)
    edges = network.edges[keep_edges].drop(columns=_SIDE)
    return Network(
        with_geometry(nodes, nodes[GEOM].array, crs_of(network)),
        with_geometry(edges, edges[GEOM].array, crs_of(network)),
    )


@operation
def union(a: Network, b: Network, tolerance: float = 0, split: bool = False) -> Network:
    """Everything in either network, with what they share kept once.

    Nodes of ``a`` and ``b`` within ``tolerance`` are the same node. An edge
    of ``b`` is the same as an edge of ``a`` if they join the same two nodes
    and their lines stay within ``tolerance`` of each other; ``a``'s is kept.

    Parameters
    ----------
    split
        First split edges of each network where they start or stop running
        alongside an edge of the other, so that edges that only partly
        overlap can be matched.

    Notes
    -----
    Features of ``a`` keep their ids and positions; ids of ``b`` are shifted
    up to follow on.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> a = snkit.from_edges([LineString([(0, 0), (10, 0)])])
    >>> b = snkit.from_edges([LineString([(4, 0.1), (14, 0.1)])])
    >>> joined = snkit.union(a, b, tolerance=0.5, split=True)
    >>> [line.wkt for line in joined.edges.geometry]
    ['LINESTRING (0 0, 4 0)', 'LINESTRING (4 0, 10 0)', 'LINESTRING (10 0, 14 0.1)']
    """
    merged, twin, _, _ = _overlay(a, b, tolerance, split)
    from_b = merged.edges[_SIDE].to_numpy() == "b"
    return _select(merged, ~(twin & from_b), np.ones(len(merged.nodes), dtype=bool))


@operation
def intersection(a: Network, b: Network, tolerance: float = 0, split: bool = False) -> Network:
    """The parts of ``a`` that are also in ``b``.

    Edges of ``a`` that have a matching edge in ``b``, with their end nodes,
    and nodes of ``a`` with no edges that match a node of ``b``. See
    :func:`snkit.union` for what matches, and for ``split``.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> a = snkit.from_edges([LineString([(0, 0), (10, 0)])])
    >>> b = snkit.from_edges([LineString([(4, 0.1), (14, 0.1)])])
    >>> shared = snkit.intersection(a, b, tolerance=0.5, split=True)
    >>> [line.wkt for line in shared.edges.geometry]
    ['LINESTRING (4 0, 10 0)']
    """
    merged, twin, in_both, lone = _overlay(a, b, tolerance, split)
    from_a = merged.edges[_SIDE].to_numpy() == "a"
    return _select(merged, twin & from_a, lone & in_both)


@operation
def difference(a: Network, b: Network, tolerance: float = 0, split: bool = False) -> Network:
    """The parts of ``a`` that are not in ``b``.

    Edges of ``a`` that have no matching edge in ``b``, with their end nodes,
    and nodes of ``a`` with no edges that match no node of ``b``. See
    :func:`snkit.union` for what matches, and for ``split``.

    Examples
    --------
    >>> from shapely import LineString
    >>> import snkit
    >>> a = snkit.from_edges([LineString([(0, 0), (10, 0)])])
    >>> b = snkit.from_edges([LineString([(4, 0.1), (14, 0.1)])])
    >>> rest = snkit.difference(a, b, tolerance=0.5, split=True)
    >>> [line.wkt for line in rest.edges.geometry]
    ['LINESTRING (0 0, 4 0)']
    """
    merged, twin, in_both, lone = _overlay(a, b, tolerance, split)
    from_a = merged.edges[_SIDE].to_numpy() == "a"
    return _select(merged, ~twin & from_a, lone & ~in_both)
