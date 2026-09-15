"""Tests for public API variants and defensive geometry paths."""

from unittest.mock import Mock, patch

import pandas as pd
import pytest
from geopandas import GeoDataFrame
from pandas.testing import assert_frame_equal
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, Point

import snkit
from snkit import network


def test_network_crs_operations():
    nodes = GeoDataFrame(geometry=[Point(0, 0)], crs="EPSG:4326")
    edges = GeoDataFrame(geometry=[LineString([(0, 0), (1, 0)])], crs="EPSG:4326")
    net = snkit.Network(nodes, edges)

    net.to_crs(epsg=3857)
    assert net.nodes.crs.to_epsg() == 3857
    assert net.edges.crs.to_epsg() == 3857

    net.set_crs(epsg=4326, allow_override=True)
    assert net.nodes.crs.to_epsg() == 4326
    assert net.edges.crs.to_epsg() == 4326


@pytest.mark.parametrize(
    ("nodes_layer", "edges_layer", "expected_nodes", "expected_edges"),
    [(None, "edges", 0, 1), ("nodes", None, 1, 0)],
)
def test_read_file_can_skip_a_layer(tmp_path, nodes_layer, edges_layer, expected_nodes, expected_edges):
    net = snkit.Network(
        GeoDataFrame(geometry=[Point(0, 0)]),
        GeoDataFrame(geometry=[LineString([(0, 0), (1, 0)])]),
    )
    path = tmp_path / "network.gpkg"
    net.to_file(path, driver="GPKG")

    result = network.read_file(path, nodes_layer=nodes_layer, edges_layer=edges_layer)

    assert len(result.nodes) == expected_nodes
    assert len(result.edges) == expected_edges


def test_get_endpoints_handles_multilines_and_missing_geometries():
    edges = GeoDataFrame(
        geometry=[
            MultiLineString([[(0, 0), (1, 0)], [(2, 0), (3, 0)]]),
            None,
        ]
    )

    endpoints = network.get_endpoints(snkit.Network(edges=edges))

    assert endpoints.geometry.to_list() == [Point(0, 0), Point(1, 0), Point(2, 0), Point(3, 0)]


def test_split_multilinestrings_rejects_non_line_geometry():
    net = snkit.Network(edges=GeoDataFrame(geometry=[Point(0, 0)]))

    with pytest.raises(ValueError, match="should only be LineString"):
        network.split_multilinestrings(net)


def test_merge_multilinestring_variants():
    connected = MultiLineString([[(0, 0), (1, 0)], [(1, 0), (2, 0)]])
    ring = MultiLineString(
        [[(0, 0), (1, 0)], [(1, 0), (0.5, 1)], [(0.5, 1), (0, 0)]]
    )
    line = LineString([(0, 0), (1, 0)])

    assert network.merge_multilinestring(connected) == LineString([(0, 0), (1, 0), (2, 0)])
    assert network.merge_multilinestring(ring) == ring
    assert network.merge_multilinestring(line) is line

    broken = Mock()
    broken.geom_type = "MultiLineString"
    with patch.object(network, "linemerge", side_effect=RuntimeError):
        assert network.merge_multilinestring(broken).is_empty


def test_link_nodes_to_nearest_edge_and_condition():
    nodes = GeoDataFrame({"kind": ["link", "skip"]}, geometry=[Point(0.1, 1), Point(0.2, 1.5)])
    edges = GeoDataFrame(geometry=[LineString([(0, 0), (0, 2)])])
    net = snkit.Network(nodes, edges)

    linked = network.link_nodes_to_nearest_edge(net, condition=lambda node, _: node.kind == "link")

    assert len(linked.nodes) == 3
    assert Point(0, 1) in linked.nodes.geometry.to_list()
    assert len(linked.edges) == 3


def test_link_nodes_within_respects_condition():
    nodes = GeoDataFrame(geometry=[Point(0.1, 1)])
    edges = GeoDataFrame(geometry=[LineString([(0, 0), (0, 2)])])
    net = snkit.Network(nodes, edges)

    unchanged = network.link_nodes_to_edges_within(net, 0.2, condition=lambda *_: False)

    assert_frame_equal(unchanged.nodes, nodes)
    assert_frame_equal(unchanged.edges, edges)


def test_merge_edges_collapses_degree_two_path():
    points = [Point(x, 0) for x in range(4)]
    nodes = GeoDataFrame({"id": ["a", "b", "c", "d"]}, geometry=points)
    edges = GeoDataFrame(
        {"id": ["e1", "e2", "e3"], "kind": ["road"] * 3},
        geometry=[LineString(points[i : i + 2]) for i in range(3)],
    )
    net = network.add_topology(snkit.Network(nodes, edges))

    merged = network.merge_edges(net, by=["kind"])

    assert {"a", "d"}.issubset(merged.nodes.id)
    assert "c" not in merged.nodes.id.to_list()
    assert len(merged.edges) == 1
    assert merged.edges.iloc[0].geometry.length == 3
    assert {merged.edges.iloc[0].from_id, merged.edges.iloc[0].to_id} == {"a", "d"}


def test_spatial_query_helpers_and_empty_geometry():
    lines = GeoDataFrame(geometry=[LineString([(0, 0), (0, 2)]), LineString([(5, 0), (5, 2)])])
    nodes = GeoDataFrame(geometry=[Point(0, 0), Point(5, 0)])

    assert len(network.edges_within(Point(0.1, 1), lines, 0.2)) == 1
    assert len(network.edges_intersecting(LineString([(-1, 1), (1, 1)]), lines)) == 1
    assert len(network.nodes_intersecting(LineString([(0, 0), (1, 0)]), nodes)) == 1
    assert network.intersects(GeometryCollection(), lines).empty


def test_intersection_endpoints_for_all_supported_geometries():
    geometries = GeometryCollection(
        [
            Point(0, 0),
            LineString([(1, 0), (2, 0)]),
            MultiPoint([(3, 0), (4, 0)]),
            MultiLineString([[(5, 0), (6, 0)]]),
            GeometryCollection(),
        ]
    )

    result = network.intersection_endpoints(geometries)

    assert result == [Point(x, 0) for x in range(7)]


def test_split_edge_at_empty_points_returns_original_edge():
    edge = GeoDataFrame({"name": ["edge"]}, geometry=[LineString([(0, 0), (1, 0)])]).iloc[0]

    result = network.split_edge_at_points(edge, MultiPoint([]))

    assert len(result) == 1
    assert result.iloc[0]["name"] == "edge"
    assert result.iloc[0].geometry == edge.geometry


def test_snap_line_and_add_vertex_variants():
    line = LineString([(0, 0), (1, 0), (2, 0)])

    assert network.snap_line(line, Point(1, 1), tolerance=0.1) == line
    assert network.snap_line(line, MultiPoint([(0.5, 0), (1.5, 1)]), tolerance=0.1) == LineString(
        [(0, 0), (0.5, 0), (1, 0), (2, 0)]
    )
    assert network.add_vertex(line, Point(0, 0)) is line
    assert network.add_vertex(line, Point(-1, 0)) == LineString([(0, 0), (-1, 0), (1, 0), (2, 0)])
    assert network.add_vertex(line, Point(3, 0)) == LineString([(0, 0), (1, 0), (3, 0), (2, 0)])
    assert network.add_vertex(line, Point(0.75, 0)) == LineString([(0, 0), (0.75, 0), (1, 0), (2, 0)])
    assert network.nearest_vertex_idx_on_line(Point(1.1, 0), line) == 1
    assert network.nearest_point_on_line(Point(0.5, 1), line) == Point(0.5, 0)


def _graph_network():
    nodes = GeoDataFrame({"id": ["a", "b"]}, geometry=[Point(0, 0), Point(0, 2)])
    edges = GeoDataFrame(
        {"from_id": ["a"], "to_id": ["b"], "cost": [7]},
        geometry=[LineString([(0, 0), (0, 2)])],
    )
    return snkit.Network(nodes, edges)


def test_to_networkx_directed_with_custom_weight():
    graph = network.to_networkx(_graph_network(), directed=True, weight_col="cost")

    assert graph.is_directed()
    assert graph["a"]["b"][0]["weight"] == 7


def test_to_igraph_variants():
    default = network.to_igraph(_graph_network())
    weighted = network.to_igraph(_graph_network(), directed=True, weight_col="cost")

    assert default.vs["name"] == ["a", "b"]
    assert default.vs["x"] == [0.0, 0.0]
    assert default.es["weight"] == [2.0]
    assert weighted.is_directed()
    assert weighted.es["weight"] == [7]


def test_optional_graph_backends_raise_clear_errors(monkeypatch):
    monkeypatch.setattr(network, "USE_NX", False)
    with pytest.raises(ImportError, match="networkx"):
        network.to_networkx(_graph_network())
    with pytest.raises(ImportError, match="networkx"):
        network.get_connected_components(_graph_network())

    monkeypatch.setattr(network, "USE_IGRAPH", False)
    with pytest.raises(ImportError, match="igraph"):
        network.to_igraph(_graph_network())


def test_geometry_column_name_falls_back_for_plain_dataframe():
    assert network.geometry_column_name(pd.DataFrame()) == "geometry"
