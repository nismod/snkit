"""Tests of the spatial network operations API.

The small cases here are the worked examples of docs/source/design.md.
"""

import geopandas
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely import LineString, MultiLineString, Point

import snkit


def lines(*coords):
    return [LineString(c) for c in coords]


def net(*coords, **kwargs):
    return snkit.from_edges(lines(*coords), **kwargs)


def edge_wkt(network):
    return [g.wkt for g in network.edges.geometry]


def node_wkt(network):
    return [g.wkt for g in network.nodes.geometry]


def topology(network):
    return network.edges[["from_id", "to_id"]].values.tolist()


def valid(network):
    assert snkit.validate(network) == []
    return network


def total_length(network):
    return float(network.edges.geometry.length.sum())


# ---------------------------------------------------------------------------
# Creation and validation


def test_from_edges():
    network = valid(net([(0, 0), (1, 0)], [(1, 0), (2, 0)], [(1, 0), (1, 1)]))
    assert node_wkt(network) == ["POINT (0 0)", "POINT (1 0)", "POINT (2 0)", "POINT (1 1)"]
    assert topology(network) == [[0, 1], [1, 2], [1, 3]]
    assert network.edges["id"].dtype == np.dtype("uint64")
    assert network.nodes["id"].dtype == np.dtype("uint64")


def test_from_edges_joins_only_equal_ends_unless_given_tolerance():
    coords = [[(0, 0), (1, 0)], [(1.001, 0), (2, 0)]]
    assert len(net(*coords).nodes) == 4
    joined = valid(net(*coords, tolerance=0.01))
    assert len(joined.nodes) == 3
    assert topology(joined) == [[0, 1], [1, 3]]


def test_from_edges_splits_multilinestrings_and_keeps_attributes():
    edges = geopandas.GeoDataFrame(
        {"name": ["a", "b"]},
        geometry=[MultiLineString([[(0, 0), (1, 0)], [(1, 0), (2, 0)]]), LineString([(2, 0), (3, 0)])],
        crs="EPSG:27700",
    )
    network = valid(snkit.from_edges(edges))
    assert network.edges["name"].tolist() == ["a", "a", "b"]
    assert network.edges.crs == network.nodes.crs == edges.crs
    assert len(network.nodes) == 4


def test_from_edges_invalid_geometries():
    bad = [LineString([(0, 0), (1, 0)]), LineString([(1, 1), (1, 1)]), None, Point(0, 0)]
    with pytest.raises(ValueError, match="3 geometries"):
        snkit.from_edges(bad)
    assert len(snkit.from_edges(bad, invalid="drop").edges) == 1


def test_from_edges_drops_z():
    network = valid(snkit.from_edges([LineString([(0, 0, 5), (1, 0, 6)])]))
    assert edge_wkt(network) == ["LINESTRING (0 0, 1 0)"]


def test_from_edges_empty():
    network = valid(snkit.from_edges([]))
    assert len(network.nodes) == 0 and len(network.edges) == 0


@pytest.mark.parametrize(
    "ids, expected_ids, kept",
    [
        ([7, 3], [7, 3], False),  # non-negative integers are used as ids
        (["x", "y"], [0, 1], True),  # anything else becomes an attribute
        ([-1, 3], [0, 1], True),
        ([1.5, 2.5], [0, 1], True),
    ],
)
def test_supplied_edge_ids(ids, expected_ids, kept):
    edges = geopandas.GeoDataFrame({"id": ids}, geometry=lines([(0, 0), (1, 0)], [(1, 0), (2, 0)]))
    network = valid(snkit.from_edges(edges))
    assert network.edges["id"].tolist() == expected_ids
    assert ("id_original" in network.edges.columns) == kept
    if kept:
        assert network.edges["id_original"].tolist() == ids


def test_supplied_ids_from_named_column():
    edges = geopandas.GeoDataFrame(
        {"ref": [10, 20], "name": ["a", "b"]}, geometry=lines([(0, 0), (1, 0)], [(1, 0), (2, 0)])
    )
    by_ref = snkit.from_edges(edges, edge_id="ref")
    assert by_ref.edges["id"].tolist() == [10, 20] and "ref" not in by_ref.edges.columns
    by_name = snkit.from_edges(edges, edge_id="name")
    assert by_name.edges["id"].tolist() == [0, 1]
    assert by_name.edges["name"].tolist() == ["a", "b"]


def test_duplicate_integer_ids_are_refused():
    edges = geopandas.GeoDataFrame({"id": [1, 1]}, geometry=lines([(0, 0), (1, 0)], [(1, 0), (2, 0)]))
    with pytest.raises(ValueError, match="not unique"):
        snkit.from_edges(edges)


def test_from_nodes_and_edges():
    network = valid(
        snkit.from_nodes_and_edges(
            [Point(0, 0), Point(1.001, 0)],
            lines([(0, 0), (1, 0)], [(1, 0), (2, 0)]),
            tolerance=0.01,
        )
    )
    assert node_wkt(network) == ["POINT (0 0)", "POINT (1.001 0)", "POINT (2 0)"]
    assert edge_wkt(network) == ["LINESTRING (0 0, 1.001 0)", "LINESTRING (1.001 0, 2 0)"]
    assert topology(network) == [[0, 1], [1, 2]]


def test_from_nodes_and_edges_does_not_attach_to_far_nodes():
    network = valid(snkit.from_nodes_and_edges([Point(0, 5)], lines([(0, 0), (1, 0)])))
    assert len(network.nodes) == 3
    assert topology(network) == [[1, 2]]


def test_from_nodes_and_edges_attaches_to_nearest_node():
    network = valid(snkit.from_nodes_and_edges([Point(0, 0.3), Point(0, 0.1)], lines([(0, 0), (5, 0)]), tolerance=0.5))
    assert topology(network) == [[1, 2]]


def test_from_topology_converts_ids():
    nodes = geopandas.GeoDataFrame({"id": ["node_0", "node_1"]}, geometry=[Point(0, 0), Point(1, 0)])
    edges = geopandas.GeoDataFrame(
        {"id": ["edge_0"], "from_id": ["node_0"], "to_id": ["node_1"]},
        geometry=lines([(0, 0), (1, 0)]),
    )
    network = valid(snkit.from_topology(nodes, edges))
    assert network.nodes["id_original"].tolist() == ["node_0", "node_1"]
    assert network.edges[["id", "from_id", "to_id"]].values.tolist() == [[0, 0, 1]]
    assert network.edges["from_id_original"].tolist() == ["node_0"]
    assert network.edges["id_original"].tolist() == ["edge_0"]


def test_from_topology_keeps_integer_ids():
    nodes = geopandas.GeoDataFrame({"id": [5, 9]}, geometry=[Point(0, 0), Point(1, 0)])
    edges = geopandas.GeoDataFrame({"from_id": [9], "to_id": [5]}, geometry=lines([(1, 0), (0, 0)]))
    network = valid(snkit.from_topology(nodes, edges))
    assert topology(network) == [[9, 5]]
    assert "from_id_original" not in network.edges.columns


def test_from_topology_moves_ends_within_tolerance_only():
    nodes = geopandas.GeoDataFrame({"id": [0, 1]}, geometry=[Point(0, 0), Point(1, 0)])
    edges = geopandas.GeoDataFrame({"from_id": [0], "to_id": [1]}, geometry=lines([(0, 0), (1, 1e-7)]))
    with pytest.raises(ValueError, match="further than tolerance"):
        snkit.from_topology(nodes, edges)
    network = valid(snkit.from_topology(nodes, edges, tolerance=1e-6))
    assert edge_wkt(network) == ["LINESTRING (0 0, 1 0)"]


def test_from_topology_missing_node():
    nodes = geopandas.GeoDataFrame({"id": [0]}, geometry=[Point(0, 0)])
    edges = geopandas.GeoDataFrame({"from_id": [0], "to_id": [1]}, geometry=lines([(0, 0), (1, 0)]))
    with pytest.raises(ValueError, match="not in the nodes table"):
        snkit.from_topology(nodes, edges)


def test_validate_reports_problems():
    network = net([(0, 0), (1, 0)])
    moved = snkit.Network(network.nodes.copy(), network.edges.copy())
    moved.nodes.geometry = [Point(0, 0), Point(1, 0.5)]
    assert snkit.validate(moved) == ["1 edge ends are not exactly at the position of their node"]
    with pytest.raises(ValueError, match="not a valid network"):
        snkit.validate(moved, raise_errors=True)

    untyped = snkit.Network(network.nodes, network.edges.drop(columns="from_id"))
    assert "edges have no 'from_id' column" in snkit.validate(untyped)

    dangling = snkit.Network(network.nodes.iloc[:1], network.edges)
    assert "1 edges refer to nodes that do not exist" in snkit.validate(dangling)


def test_operations_need_a_topological_network():
    raw = snkit.Network(edges=geopandas.GeoDataFrame(geometry=lines([(0, 0), (1, 0)])))
    with pytest.raises(ValueError, match="from_edges"):
        snkit.merge_edges(raw)


def test_distance_in_degrees_is_refused():
    edges = geopandas.GeoDataFrame(geometry=lines([(0, 0), (1, 0)]), crs="EPSG:4326")
    network = snkit.from_edges(edges)
    with pytest.raises(ValueError, match="geographic CRS"):
        snkit.merge_nodes(network, tolerance=0.1)
    snkit.split_edges_at_crossings(network)  # no distance involved


# ---------------------------------------------------------------------------
# Matchers


def test_match_nodes():
    network = net([(0, 0), (1, 0)], [(1.05, 0), (2, 0)])
    matches = snkit.match_nodes(network, tolerance=0.1)
    assert matches.values.tolist() == [[1, 2, pytest.approx(0.05)]]
    assert snkit.match_nodes(network, tolerance=0.01).empty


def test_match_nodes_to_edges_ignores_own_edges_and_ends():
    network = snkit.from_nodes_and_edges([Point(1, 0.01), Point(2.01, 0)], lines([(0, 0), (2, 0)]), tolerance=0)
    matches = snkit.match_nodes_to_edges(network, tolerance=0.05)
    assert matches[["node", "edge", "measure", "x", "y"]].values.tolist() == [[0, 0, 1, 1, 0]]


def test_find_crossings_kinds():
    crossing = net([(0, 0), (2, 2)], [(0, 2), (2, 0)])
    assert snkit.find_crossings(crossing)[["x", "y"]].values.tolist() == [[1, 1]]
    t_junction = net([(0, 0), (2, 0)], [(1, 0), (1, 1)])
    found = snkit.find_crossings(t_junction)
    assert found[["edge_a", "measure_a", "edge_b", "measure_b"]].values.tolist() == [[0, 1, 1, 0]]
    shared_node = net([(0, 0), (1, 0)], [(1, 0), (1, 1)])
    assert snkit.find_crossings(shared_node).empty
    apart = net([(0, 0), (1, 0)], [(0, 1), (1, 1)])
    assert snkit.find_crossings(apart).empty


def test_find_crossings_reports_ends_of_a_shared_stretch():
    network = net([(0, 0), (3, 0)], [(1, 0), (5, 0)])
    assert snkit.find_crossings(network)[["x", "y"]].values.tolist() == [[1, 0], [3, 0]]


def test_match_edges():
    network = net([(0, 0), (10, 0)], [(4, 0.1), (14, 0.1)])
    matches = snkit.match_edges(network, tolerance=0.5)
    assert matches.values.tolist() == [
        [0, pytest.approx(4), pytest.approx(10), 1, pytest.approx(0), pytest.approx(6), False, pytest.approx(0.1)]
    ]
    opposite = net([(0, 0), (10, 0)], [(14, 0.1), (4, 0.1)])
    assert snkit.match_edges(opposite, tolerance=0.5)["reversed"].tolist() == [True]
    assert snkit.match_edges(opposite, tolerance=0.5, directed=True).empty


def test_match_edges_ignores_edges_that_only_cross():
    network = net([(0, 0), (10, 0)], [(5, -5), (5, 5)])
    assert snkit.match_edges(network, tolerance=0.5).empty


def test_match_edges_exact_overlap():
    network = net([(0, 0), (3, 0)], [(1, 0), (5, 0)])
    matches = snkit.match_edges(network, tolerance=0)
    assert matches[["start_a", "end_a", "start_b", "end_b"]].values.tolist() == [[1, 3, 0, 2]]


def test_condition_sees_attributes_of_both_sides():
    edges = geopandas.GeoDataFrame(
        {"level": [0, 1, 0]},
        geometry=lines([(0, 0), (2, 2)], [(0, 2), (2, 0)], [(0, 1), (2, 1)]),
    )
    network = snkit.from_edges(edges)
    assert len(snkit.find_crossings(network)) == 3
    same_level = snkit.find_crossings(network, condition=lambda x: x.level_a == x.level_b)
    assert same_level[["edge_a", "edge_b"]].values.tolist() == [[0, 2]]


# ---------------------------------------------------------------------------
# Operations


def test_merge_nodes():
    network = net([(0, 0), (1, 0)], [(1.05, 0), (2, 0)])
    merged = valid(snkit.merge_nodes(network, tolerance=0.1))
    assert node_wkt(merged) == ["POINT (0 0)", "POINT (1.025 0)", "POINT (2 0)"]
    assert edge_wkt(merged) == ["LINESTRING (0 0, 1.025 0)", "LINESTRING (1.025 0, 2 0)"]
    assert topology(merged) == [[0, 1], [1, 3]]
    assert snkit.match_nodes(merged, tolerance=0.1).empty


def test_merge_nodes_position_and_geometry_options():
    network = net([(0, 0), (1, 0)], [(1.05, 0), (2, 0)])
    first = valid(snkit.merge_nodes(network, tolerance=0.1, position="first"))
    assert edge_wkt(first) == ["LINESTRING (0 0, 1 0)", "LINESTRING (1 0, 2 0)"]
    extended = valid(snkit.merge_nodes(network, tolerance=0.1, geometry="extend"))
    assert edge_wkt(extended) == [
        "LINESTRING (0 0, 1 0, 1.025 0)",
        "LINESTRING (1.025 0, 1.05 0, 2 0)",
    ]


def test_merge_nodes_drops_short_edges_between_merged_nodes_but_keeps_loops():
    network = net([(0, 0), (1, 0)], [(1, 0), (1.05, 0)], [(1.05, 0), (2, 0)])
    merged = valid(snkit.merge_nodes(network, tolerance=0.1))
    assert len(merged.edges) == 2
    loop = net([(0, 0), (5, 5), (0.05, 0)])
    merged = valid(snkit.merge_nodes(loop, tolerance=0.1, position="first"))
    assert edge_wkt(merged) == ["LINESTRING (0 0, 5 5, 0 0)"]
    assert topology(merged) == [[0, 0]]


def test_merge_nodes_in_chains_and_max_spread():
    network = net([(0, 0), (0.08, 0)], [(0.16, 0), (5, 0)])
    merged = valid(snkit.merge_nodes(network, tolerance=0.1))
    assert len(merged.nodes) == 2
    with pytest.raises(ValueError, match="max_spread"):
        snkit.merge_nodes(network, tolerance=0.1, max_spread=0.05)


def test_merge_nodes_attributes():
    network = snkit.from_nodes_and_edges(
        geopandas.GeoDataFrame(
            {"kind": ["a", "a", "b"], "owner": ["x", "y", "z"], "load": [1.0, 2.0, 4.0]},
            geometry=[Point(0, 0), Point(0.01, 0), Point(5, 0)],
        ),
        lines([(0, 0), (5, 0)]),
    )
    merged = valid(snkit.merge_nodes(network, tolerance=0.1, agg={"load": "sum"}))
    assert merged.nodes["kind"].tolist() == ["a", "b"]
    assert merged.nodes["owner"].isna().tolist() == [True, False]
    assert merged.nodes["load"].tolist() == [3.0, 4.0]


def test_merge_nodes_condition():
    network = net([(0, 0), (1, 0)], [(1.05, 0), (2, 0)])
    kept = snkit.merge_nodes(network, tolerance=0.1, condition=lambda m: m.distance < 0.01)
    assert len(kept.nodes) == 4


def test_link_nodes():
    network = net([(0, 0), (1, 0)], [(1.05, 0), (2, 0)])
    linked = valid(snkit.link_nodes(network, tolerance=0.1))
    assert edge_wkt(linked)[2] == "LINESTRING (1 0, 1.05 0)"
    assert topology(linked)[2] == [1, 2]
    assert len(linked.nodes) == 4
    again = snkit.link_nodes(linked, tolerance=0.1)
    assert edge_wkt(again) == edge_wkt(linked)


def test_link_nodes_nearest_and_condition():
    network = net([(0, 0), (0, 5)], [(1, 0), (1, 5)], [(3, 0), (3, 5)])
    assert len(snkit.link_nodes(network, tolerance=4).edges) == 3 + 6
    nearest = valid(snkit.link_nodes(network, tolerance=4, how="nearest"))
    assert edge_wkt(nearest)[3:] == [
        "LINESTRING (0 0, 1 0)",
        "LINESTRING (0 5, 1 5)",
        "LINESTRING (1 0, 3 0)",
        "LINESTRING (1 5, 3 5)",
    ]
    parts = snkit.label_components(network)
    across = snkit.link_nodes(parts, tolerance=1.5, condition=lambda m: m.component_a != m.component_b)
    assert len(across.edges) == 5


def test_split_edges_at_nodes():
    network = snkit.from_nodes_and_edges([Point(1, 0.01)], lines([(0, 0), (2, 0)]))
    split = valid(snkit.split_edges_at_nodes(network, tolerance=0.05))
    assert edge_wkt(split) == ["LINESTRING (0 0, 1 0.01)", "LINESTRING (1 0.01, 2 0)"]
    assert topology(split) == [[1, 0], [0, 2]]
    assert node_wkt(split) == node_wkt(network)
    assert snkit.match_nodes_to_edges(split, tolerance=0.05).empty
    assert len(snkit.split_edges_at_nodes(network).edges) == 1


def test_split_edges_at_nodes_moving_the_node():
    network = snkit.from_nodes_and_edges([Point(1, 0.01)], lines([(0, 0), (2, 0)]))
    split = valid(snkit.split_edges_at_nodes(network, tolerance=0.05, move="node"))
    assert edge_wkt(split) == ["LINESTRING (0 0, 1 0)", "LINESTRING (1 0, 2 0)"]
    assert node_wkt(split)[0] == "POINT (1 0)"


def test_split_edges_at_nodes_several_on_one_edge_and_on_a_vertex():
    network = snkit.from_nodes_and_edges([Point(3, 0), Point(1, 0), Point(2, 0)], lines([(0, 0), (2, 0), (4, 0)]))
    split = valid(snkit.split_edges_at_nodes(network))
    assert edge_wkt(split) == [
        "LINESTRING (0 0, 1 0)",
        "LINESTRING (1 0, 2 0)",
        "LINESTRING (2 0, 3 0)",
        "LINESTRING (3 0, 4 0)",
    ]
    assert len(set(split.edges["id"])) == 4 and 0 not in set(split.edges["id"])


def test_split_shares_extensive_attributes_and_copies_others():
    edges = geopandas.GeoDataFrame({"cost": [8.0], "name": ["a"]}, geometry=lines([(0, 0), (4, 0)]))
    network = snkit.from_nodes_and_edges([Point(1, 0)], edges)
    split = snkit.split_edges_at_nodes(network, extensive=["cost"])
    assert split.edges["cost"].tolist() == [2.0, 6.0]
    assert split.edges["name"].tolist() == ["a", "a"]


def test_link_nodes_to_edges():
    network = snkit.from_nodes_and_edges([Point(1, 1)], lines([(0, 0), (2, 0)]))
    linked = valid(snkit.link_nodes_to_edges(network))
    assert edge_wkt(linked) == [
        "LINESTRING (0 0, 1 0)",
        "LINESTRING (1 0, 2 0)",
        "LINESTRING (1 1, 1 0)",
    ]
    assert node_wkt(linked)[-1] == "POINT (1 0)"
    assert topology(linked) == [[1, 3], [3, 2], [0, 3]]
    again = snkit.link_nodes_to_edges(linked)
    assert edge_wkt(again) == edge_wkt(linked)


def test_link_nodes_to_edges_at_an_end_uses_the_end_node():
    network = snkit.from_nodes_and_edges([Point(-1, 1), Point(0.05, 1)], lines([(0, 0), (2, 0)]))
    linked = valid(snkit.link_nodes_to_edges(network, tolerance=0.1))
    assert edge_wkt(linked) == [
        "LINESTRING (0 0, 2 0)",
        "LINESTRING (-1 1, 0 0)",
        "LINESTRING (0.05 1, 0 0)",
    ]


def test_link_nodes_to_edges_within_distance_and_shared_projection():
    network = snkit.from_nodes_and_edges(
        [Point(1, 1), Point(1, -1), Point(1, 9)], lines([(0, 0), (2, 0)], [(0, 2), (2, 2)])
    )
    linked = valid(snkit.link_nodes_to_edges(network, how="all", max_distance=1.5))
    # both near nodes meet the first edge at one shared new node; the far node is left
    assert len(linked.nodes) == 3 + 4 + 2
    assert len(linked.edges) == 4 + 3
    assert snkit.find_crossings(linked).empty


def test_link_nodes_to_edges_chosen_nodes_skip_their_own_edges():
    network = net([(0, 0), (2, 0)], [(1, 1), (1, 3)])
    mask = [False, False, True, False]
    linked = valid(snkit.link_nodes_to_edges(network, nodes=mask))
    assert edge_wkt(linked)[-1] == "LINESTRING (1 1, 1 0)"


def test_link_nodes_to_edges_without_link_moves_the_node():
    network = snkit.from_nodes_and_edges([Point(1, 1)], lines([(0, 0), (2, 0)]))
    moved = valid(snkit.link_nodes_to_edges(network, link=False))
    assert node_wkt(moved)[0] == "POINT (1 0)"
    assert edge_wkt(moved) == ["LINESTRING (0 0, 1 0)", "LINESTRING (1 0, 2 0)"]


def test_split_edges_at_crossings():
    network = net([(0, 0), (2, 2)], [(0, 2), (2, 0)])
    split = valid(snkit.split_edges_at_crossings(network))
    assert edge_wkt(split) == [
        "LINESTRING (0 0, 1 1)",
        "LINESTRING (1 1, 2 2)",
        "LINESTRING (0 2, 1 1)",
        "LINESTRING (1 1, 2 0)",
    ]
    assert node_wkt(split)[-1] == "POINT (1 1)"
    assert topology(split) == [[0, 4], [4, 1], [2, 4], [4, 3]]
    assert snkit.find_crossings(split).empty


def test_split_edges_at_crossings_t_junction_uses_the_end_node():
    network = net([(0, 0), (2, 0)], [(1, 0), (1, 1)])
    split = valid(snkit.split_edges_at_crossings(network))
    assert len(split.nodes) == 4
    assert topology(split) == [[0, 2], [2, 1], [2, 3]]


def test_split_edges_at_crossings_near_an_end_with_tolerance():
    network = net([(0, 0), (2, 0)], [(1, -0.01), (1, 1)])
    exact = valid(snkit.split_edges_at_crossings(network))
    assert len(exact.nodes) == 5 and len(exact.edges) == 4
    snapped = valid(snkit.split_edges_at_crossings(network, tolerance=0.05))
    assert len(snapped.nodes) == 4
    assert edge_wkt(snapped) == [
        "LINESTRING (0 0, 1 -0.01)",
        "LINESTRING (1 -0.01, 2 0)",
        "LINESTRING (1 -0.01, 1 1)",
    ]


def test_split_edges_at_crossings_three_edges_through_one_point():
    network = net([(0, 0), (2, 2)], [(0, 2), (2, 0)], [(0, 1), (2, 1)])
    split = valid(snkit.split_edges_at_crossings(network))
    assert len(split.nodes) == 7 and len(split.edges) == 6
    assert snkit.find_crossings(split).empty


def test_split_edges_at_crossings_self_crossing_edge():
    network = net([(0, 0), (2, 2), (2, 0), (0, 2)])
    split = valid(snkit.split_edges_at_crossings(network))
    assert edge_wkt(split) == [
        "LINESTRING (0 0, 1 1)",
        "LINESTRING (1 1, 2 2, 2 0, 1 1)",
        "LINESTRING (1 1, 0 2)",
    ]
    assert topology(split) == [[0, 2], [2, 2], [2, 1]]


def test_split_edges_at_crossings_condition():
    edges = geopandas.GeoDataFrame({"level": [0, 1]}, geometry=lines([(0, 0), (2, 2)], [(0, 2), (2, 0)]))
    network = snkit.from_edges(edges)
    bridge = snkit.split_edges_at_crossings(network, condition=lambda x: x.level_a == x.level_b)
    assert len(bridge.edges) == 2


def test_split_edges_at_crossings_overlapping_edges():
    network = net([(0, 0), (3, 0)], [(1, 0), (5, 0)])
    split = valid(snkit.split_edges_at_crossings(network))
    assert sorted(edge_wkt(split)) == [
        "LINESTRING (0 0, 1 0)",
        "LINESTRING (1 0, 3 0)",
        "LINESTRING (1 0, 3 0)",
        "LINESTRING (3 0, 5 0)",
    ]
    assert len(snkit.drop_duplicate_edges(split).edges) == 3


def test_split_edges_by_location_table():
    network = net([(0, 0), (4, 0)], [(4, 0), (4, 4)])
    locations = pd.DataFrame({"edge": [0, 0, 0], "measure": [1.0, 3.0, 3.99]})
    split = valid(snkit.split_edges(network, locations, tolerance=0.05))
    assert edge_wkt(split) == [
        "LINESTRING (0 0, 1 0)",
        "LINESTRING (1 0, 3 0)",
        "LINESTRING (3 0, 4 0)",
        "LINESTRING (4 0, 4 4)",
    ]
    with_node = pd.DataFrame({"edge": [0], "measure": [2.0], "node": [2]})
    bent = valid(snkit.split_edges(network, with_node))
    assert edge_wkt(bent)[:2] == ["LINESTRING (0 0, 4 4)", "LINESTRING (4 4, 4 0)"]
    with pytest.raises(ValueError, match="edge ids"):
        snkit.split_edges(network, pd.DataFrame({"edge": [99], "measure": [1.0]}))


def test_simplify_edges():
    network = net([(0, 0), (1, 0.001), (2, 0)], [(2, 0), (3, 1), (4, 0)])
    simple = valid(snkit.simplify_edges(network, tolerance=0.01))
    assert edge_wkt(simple) == ["LINESTRING (0 0, 2 0)", "LINESTRING (2 0, 3 1, 4 0)"]


def test_simplify_edges_does_not_create_crossings():
    # the dog-leg goes round the end of the short edge; straightened, it would cross it
    network = net([(0, 0), (2, 0.5), (4, 0)], [(2, 0.2), (2, -1)])
    assert snkit.find_crossings(network).empty
    simple = valid(snkit.simplify_edges(network, tolerance=1))
    assert edge_wkt(simple) == edge_wkt(network)
    assert snkit.find_crossings(simple).empty


def test_merge_edges():
    network = net([(0, 0), (1, 0)], [(2, 0), (1, 0)])
    merged = valid(snkit.merge_edges(network))
    assert edge_wkt(merged) == ["LINESTRING (0 0, 1 0, 2 0)"]
    assert topology(merged) == [[0, 2]]
    assert merged.nodes["id"].tolist() == [0, 2]
    assert merged.edges["id"].tolist() == [2]


def test_merge_edges_stops_at_junctions_and_keeps_order():
    network = net([(0, 0), (1, 0)], [(1, 0), (2, 0)], [(2, 0), (3, 0)], [(2, 0), (2, 1)], [(2, 1), (2, 2)])
    merged = valid(snkit.merge_edges(network))
    assert edge_wkt(merged) == [
        "LINESTRING (0 0, 1 0, 2 0)",
        "LINESTRING (2 0, 3 0)",
        "LINESTRING (2 0, 2 1, 2 2)",
    ]
    assert total_length(merged) == total_length(network)


def test_merge_edges_by_keep_and_directed():
    edges = geopandas.GeoDataFrame(
        {"kind": ["a", "a", "b"], "cost": [1.0, 2.0, 4.0]},
        geometry=lines([(0, 0), (1, 0)], [(1, 0), (2, 0)], [(2, 0), (3, 0)]),
    )
    network = snkit.from_edges(edges)
    by_kind = valid(snkit.merge_edges(network, by=["kind"], agg={"cost": "sum"}))
    assert edge_wkt(by_kind) == ["LINESTRING (0 0, 1 0, 2 0)", "LINESTRING (2 0, 3 0)"]
    assert by_kind.edges["cost"].tolist() == [3.0, 4.0]
    assert by_kind.edges["kind"].tolist() == ["a", "b"]

    everything = snkit.merge_edges(network)
    assert everything.edges["kind"].isna().tolist() == [True]

    kept = valid(snkit.merge_edges(network, keep=[False, True, False, False]))
    assert edge_wkt(kept) == ["LINESTRING (0 0, 1 0)", "LINESTRING (1 0, 2 0, 3 0)"]

    facing = net([(0, 0), (1, 0)], [(2, 0), (1, 0)])
    assert len(snkit.merge_edges(facing, directed=True).edges) == 2
    following = net([(0, 0), (1, 0)], [(1, 0), (2, 0)])
    assert len(snkit.merge_edges(following, directed=True).edges) == 1


def test_merge_edges_ring_keeps_one_node():
    network = net([(0, 0), (1, 0)], [(1, 0), (1, 1)], [(1, 1), (0, 0)])
    merged = valid(snkit.merge_edges(network))
    assert edge_wkt(merged) == ["LINESTRING (0 0, 1 0, 1 1, 0 0)"]
    assert topology(merged) == [[0, 0]]
    assert len(merged.nodes) == 1


def test_merge_edges_leaves_loops_and_parallel_edges_alone():
    loop = net([(0, 0), (1, 1), (1, 0), (0, 0)])
    assert edge_wkt(snkit.merge_edges(loop)) == edge_wkt(loop)
    parallel = net([(0, 0), (1, 0)], [(0, 0), (0.5, 0.5), (1, 0)])
    merged = valid(snkit.merge_edges(parallel))
    assert len(merged.edges) == 1 and len(merged.nodes) == 1


def test_merge_edges_undoes_split_edges_at_nodes():
    network = net([(0, 0), (4, 0)], [(4, 0), (4, 4)], [(4, 0), (8, 0)])
    with_nodes = snkit.from_nodes_and_edges([Point(1, 0), Point(2, 0), Point(4, 2)], network.edges[["geometry"]])
    split = snkit.split_edges_at_nodes(with_nodes)
    assert len(split.edges) == 6
    merged = valid(snkit.merge_edges(split))
    assert topology(merged) == [[3, 4], [4, 5], [4, 6]]
    # the merged lines keep a vertex where each node was
    assert edge_wkt(merged)[0] == "LINESTRING (0 0, 1 0, 2 0, 4 0)"
    assert edge_wkt(snkit.simplify_edges(merged, tolerance=0)) == edge_wkt(network)


def test_drop_duplicate_edges():
    network = net([(0, 0), (1, 0)], [(1, 0), (0.5, 0.01), (0, 0)], [(0, 0), (0.5, 3), (1, 0)])
    assert len(snkit.drop_duplicate_edges(network).edges) == 3
    dropped = valid(snkit.drop_duplicate_edges(network, tolerance=0.05))
    assert dropped.edges["id"].tolist() == [0, 2]
    assert len(snkit.drop_duplicate_edges(network, tolerance=0.05, directed=True).edges) == 3


def test_label_components():
    network = net([(0, 0), (1, 0)], [(1, 0), (2, 0)], [(5, 5), (6, 5)])
    labelled = snkit.label_components(network)
    assert labelled.nodes["component"].tolist() == [0, 0, 0, 1, 1]
    assert labelled.edges["component"].tolist() == [0, 0, 1]
    assert "component" not in network.nodes.columns


def test_operations_on_an_empty_network():
    empty = snkit.from_edges([])
    for operation in (
        lambda n: snkit.merge_nodes(n, 1),
        lambda n: snkit.link_nodes(n, 1),
        snkit.split_edges_at_nodes,
        snkit.link_nodes_to_edges,
        snkit.split_edges_at_crossings,
        lambda n: snkit.simplify_edges(n, 1),
        snkit.merge_edges,
        snkit.drop_duplicate_edges,
        snkit.label_components,
    ):
        result = operation(empty)
        assert len(result.nodes) == 0 and len(result.edges) == 0


def test_operations_do_not_modify_their_input():
    network = snkit.from_nodes_and_edges(
        [Point(1, 0.01), Point(3, 3)], lines([(0, 0), (2, 2)], [(0, 2), (2, 0)], [(2, 0), (2.05, 0)])
    )
    nodes, edges = network.nodes.copy(), network.edges.copy()
    snkit.merge_nodes(network, 0.1)
    snkit.link_nodes(network, 0.1)
    snkit.split_edges_at_nodes(network, 0.5)
    snkit.link_nodes_to_edges(network)
    snkit.split_edges_at_crossings(network)
    snkit.simplify_edges(network, 0.1)
    snkit.merge_edges(network)
    snkit.label_components(network)
    pd.testing.assert_frame_equal(network.nodes, nodes)
    pd.testing.assert_frame_equal(network.edges, edges)


# ---------------------------------------------------------------------------
# Lineage


def test_lineage_of_split_and_merge():
    network = net([(0, 0), (2, 2)], [(0, 2), (2, 0)])
    split, lineage = snkit.split_edges_at_crossings(network, return_lineage=True)
    assert lineage.edges.values.tolist() == [[2, 0], [3, 0], [4, 1], [5, 1]]
    # the node made at the crossing has no parent
    assert lineage.nodes["id"].tolist() == [0, 1, 2, 3]

    chain = net([(0, 0), (1, 0)], [(2, 0), (1, 0)])
    merged, lineage = snkit.merge_edges(chain, return_lineage=True)
    assert lineage.edges.values.tolist() == [[2, 0], [2, 1]]
    assert lineage.nodes["id"].tolist() == [0, 2]

    near = net([(0, 0), (1, 0)], [(1.05, 0), (2, 0)])
    merged, lineage = snkit.merge_nodes(near, 0.1, return_lineage=True)
    assert lineage.nodes.values.tolist() == [[0, 0], [1, 1], [1, 2], [3, 3]]


def test_lineage_composes():
    network = net([(0, 0), (2, 2)], [(0, 2), (2, 0)])
    split, first = snkit.split_edges_at_crossings(network, return_lineage=True)
    merged, second = snkit.merge_edges(split, keep=[False] * 5, return_lineage=True)
    both = first.then(second)
    assert set(both.edges["parent_id"]) == {0, 1}
    assert set(both.edges["id"]) == set(merged.edges["id"])


# ---------------------------------------------------------------------------
# Two or more networks


def test_combine():
    road = net([(0, 0), (1, 0)])
    rail = net([(0, 1), (1, 1)], [(1, 1), (2, 1)])
    both = valid(snkit.combine({"road": road, "rail": rail}))
    assert both.nodes["id"].tolist() == [0, 1, 2, 3, 4]
    assert both.edges["source"].tolist() == ["road", "rail", "rail"]
    assert topology(both) == [[0, 1], [2, 3], [3, 4]]
    assert snkit.combine([road, rail]).edges["source"].tolist() == [0, 1, 1]
    with pytest.raises(ValueError, match="already exists"):
        snkit.combine([both, road])


def test_combine_then_link_across_sources_only():
    road = net([(0, 0), (1, 0)])
    rail = net([(0, 0.5), (1, 0.5)])
    both = snkit.combine({"road": road, "rail": rail})
    linked = valid(snkit.link_nodes(both, tolerance=1, condition=lambda m: m.source_a != m.source_b))
    assert edge_wkt(linked)[2:] == ["LINESTRING (0 0, 0 0.5)", "LINESTRING (1 0, 1 0.5)"]


def test_combine_refuses_mixed_crs():
    a = snkit.from_edges(geopandas.GeoDataFrame(geometry=lines([(0, 0), (1, 0)]), crs="EPSG:27700"))
    b = snkit.from_edges(geopandas.GeoDataFrame(geometry=lines([(0, 0), (1, 0)]), crs="EPSG:3857"))
    with pytest.raises(ValueError, match="different CRS"):
        snkit.combine([a, b])


def test_stitch_by_position():
    west = net([(0, 0), (1, 0)], [(1, 0), (1, 1)])
    east = net([(1.001, 0), (2, 0)])
    assert len(snkit.stitch([west, east]).nodes) == 5
    whole = valid(snkit.stitch([west, east], tolerance=0.01))
    assert len(whole.nodes) == 4
    assert edge_wkt(whole)[2] == "LINESTRING (1 0, 2 0)"
    assert whole.edges["source"].tolist() == [0, 0, 1]
    assert snkit.label_components(whole).nodes["component"].nunique() == 1


def test_stitch_does_not_merge_within_one_network():
    west = net([(0, 0), (1, 0)], [(1.001, 0), (1, 1)])
    east = net([(5, 0), (6, 0)])
    assert len(snkit.stitch([west, east], tolerance=0.01).nodes) == 6


def test_stitch_on_ids_or_a_column():
    def part(ids, names, coords):
        nodes = geopandas.GeoDataFrame({"id": ids, "name": names}, geometry=[Point(c) for c in coords])
        edges = geopandas.GeoDataFrame({"from_id": ids[:1], "to_id": ids[1:]}, geometry=lines(coords))
        return snkit.from_topology(nodes, edges)

    west = part([0, 7], ["a", "border"], [(0, 0), (1, 0)])
    east = part([7, 9], ["border", "c"], [(1.2, 0), (2, 0)])
    for on in ("id", "name"):
        whole = valid(snkit.stitch([west, east], on=on, column=None))
        assert len(whole.nodes) == 3
        assert edge_wkt(whole) == ["LINESTRING (0 0, 1 0)", "LINESTRING (1 0, 2 0)"]
        assert "source" not in whole.nodes.columns


def test_set_operations_on_whole_edges():
    a = net([(0, 0), (1, 0)], [(1, 0), (2, 0)])
    b = net([(1, 0.01), (2, 0.01)], [(2, 0.01), (3, 0)])
    joined = valid(snkit.union(a, b, tolerance=0.05))
    assert edge_wkt(joined) == [
        "LINESTRING (0 0, 1 0)",
        "LINESTRING (1 0, 2 0)",
        "LINESTRING (2 0, 3 0)",
    ]
    assert edge_wkt(valid(snkit.intersection(a, b, tolerance=0.05))) == ["LINESTRING (1 0, 2 0)"]
    assert edge_wkt(valid(snkit.difference(a, b, tolerance=0.05))) == ["LINESTRING (0 0, 1 0)"]
    assert len(snkit.union(a, b).edges) == 4
    assert len(snkit.intersection(a, b).edges) == 0
    assert edge_wkt(snkit.difference(a, b)) == edge_wkt(a)


def test_set_operations_with_partial_overlap():
    a = net([(0, 0), (10, 0)])
    b = net([(4, 0.1), (14, 0.1)])
    joined = valid(snkit.union(a, b, tolerance=0.5, split=True))
    assert edge_wkt(joined) == [
        "LINESTRING (0 0, 4 0)",
        "LINESTRING (4 0, 10 0)",
        "LINESTRING (10 0, 14 0.1)",
    ]
    assert snkit.label_components(joined).nodes["component"].nunique() == 1
    shared = valid(snkit.intersection(a, b, tolerance=0.5, split=True))
    assert edge_wkt(shared) == ["LINESTRING (4 0, 10 0)"]
    rest = valid(snkit.difference(a, b, tolerance=0.5, split=True))
    assert edge_wkt(rest) == ["LINESTRING (0 0, 4 0)"]
    assert "source" not in joined.edges.columns


def test_set_operations_keep_attributes_and_isolated_nodes():
    a = snkit.from_nodes_and_edges(
        geopandas.GeoDataFrame({"name": ["p", "q"]}, geometry=[Point(5, 5), Point(9, 9)]),
        geopandas.GeoDataFrame({"road": ["A1"]}, geometry=lines([(0, 0), (1, 0)])),
    )
    b = snkit.from_nodes_and_edges([Point(5, 5)], lines([(0, 0), (1, 0)]))
    shared = valid(snkit.intersection(a, b))
    assert shared.edges["road"].tolist() == ["A1"]
    assert shared.nodes["name"].dropna().tolist() == ["p"]
    rest = valid(snkit.difference(a, b))
    assert len(rest.edges) == 0 and rest.nodes["name"].tolist() == ["q"]


# ---------------------------------------------------------------------------
# Properties, over generated networks


def random_network(seed, count=40):
    rng = np.random.default_rng(seed)
    starts = rng.uniform(0, 100, (count, 2))
    middles = starts + rng.uniform(-20, 20, (count, 2))
    ends = middles + rng.uniform(-20, 20, (count, 2))
    edges = geopandas.GeoDataFrame(
        {"cost": rng.uniform(1, 10, count)},
        geometry=[LineString(c) for c in np.stack([starts, middles, ends], axis=1)],
    )
    points = [Point(p) for p in rng.uniform(0, 100, (count // 2, 2))]
    return snkit.from_nodes_and_edges(points, edges)


def shape(network):
    """Edges and nodes as comparable sets, ignoring order, ids and direction"""
    edges = sorted(min(g.wkt, g.reverse().wkt) for g in network.edges.geometry)
    return edges, sorted(node_wkt(network))


SEEDS = range(8)


@pytest.mark.parametrize("seed", SEEDS)
def test_property_split_at_crossings(seed):
    network = random_network(seed)
    assert len(snkit.find_crossings(network)) > 0
    split, lineage = snkit.split_edges_at_crossings(network, extensive=["cost"], return_lineage=True)
    valid(split)
    assert snkit.find_crossings(split).empty
    assert total_length(split) == pytest.approx(total_length(network), rel=1e-12)
    assert split.edges["cost"].sum() == pytest.approx(network.edges["cost"].sum())
    assert set(lineage.edges["parent_id"]) == set(network.edges["id"])
    assert shape(snkit.split_edges_at_crossings(split)) == shape(split)
    # every node sits exactly on the end of each edge that names it
    degree = pd.concat([split.edges["from_id"], split.edges["to_id"]]).value_counts()
    crossings = split.nodes[~split.nodes["id"].isin(network.nodes["id"])]
    assert (degree.reindex(crossings["id"]) >= 4).all()


@pytest.mark.parametrize("seed", SEEDS)
def test_property_crossings_do_not_depend_on_order_or_direction(seed):
    network = random_network(seed)
    rng = np.random.default_rng(seed)
    edges = network.edges[["geometry"]].sample(frac=1, random_state=seed)
    flip = rng.random(len(edges)) < 0.5
    edges = geopandas.GeoDataFrame(geometry=[g.reverse() if f else g for g, f in zip(edges.geometry, flip)])
    shuffled = snkit.from_edges(edges)
    plain = snkit.from_edges(network.edges[["geometry"]])
    assert shape(snkit.split_edges_at_crossings(shuffled)) == shape(snkit.split_edges_at_crossings(plain))


@pytest.mark.parametrize("seed", SEEDS)
def test_property_link_split_merge_pipeline(seed):
    network = random_network(seed)
    linked = valid(snkit.link_nodes_to_edges(network))
    assert (pd.concat([linked.edges["from_id"], linked.edges["to_id"]]).value_counts() > 0).all()
    assert set(network.nodes["id"]) <= set(pd.concat([linked.edges["from_id"], linked.edges["to_id"]]))
    assert shape(snkit.link_nodes_to_edges(linked)) == shape(linked)

    noded = valid(snkit.split_edges_at_crossings(linked, tolerance=1e-6))
    merged = valid(snkit.merge_nodes(noded, tolerance=2.0))
    assert snkit.match_nodes(merged, tolerance=2.0).empty
    assert len(merged.nodes) <= len(noded.nodes)

    split = valid(snkit.split_edges_at_nodes(merged, tolerance=0.5))
    assert snkit.match_nodes_to_edges(split, tolerance=0.5).empty

    smooth = valid(snkit.merge_edges(noded))
    assert total_length(smooth) == pytest.approx(total_length(noded), rel=1e-12)
    assert shape(snkit.merge_edges(smooth)) == shape(smooth)
    before = snkit.label_components(noded).nodes["component"].nunique()
    after = snkit.label_components(smooth).nodes["component"].nunique()
    assert before == after


@pytest.mark.parametrize("seed", SEEDS)
def test_property_simplify_keeps_topology(seed):
    network = snkit.split_edges_at_crossings(random_network(seed))
    simple = valid(snkit.simplify_edges(network, tolerance=5))
    assert topology(simple) == topology(network)
    assert snkit.find_crossings(simple).empty
    assert (
        shapely.get_num_coordinates(simple.edges.geometry.values).sum()
        <= shapely.get_num_coordinates(network.edges.geometry.values).sum()
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_property_set_operations(seed):
    whole = snkit.split_edges_at_crossings(random_network(seed))
    edges = whole.edges[["geometry"]]
    a = snkit.from_edges(edges.iloc[: 2 * len(edges) // 3])
    b = snkit.from_edges(edges.iloc[len(edges) // 3 :])
    union = valid(snkit.union(a, b))
    shared = valid(snkit.intersection(a, b))
    rest = valid(snkit.difference(a, b))
    assert len(union.edges) == len(edges)
    assert len(shared.edges) == 2 * len(edges) // 3 - len(edges) // 3
    assert len(shared.edges) + len(rest.edges) == len(a.edges)
    assert shape(union)[0] == shape(snkit.from_edges(edges))[0]
