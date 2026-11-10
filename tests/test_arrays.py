"""Tests of networks held in arrays, of Arrow in and out, and of reading and writing files"""

import geopandas
import numpy as np
import pandas as pd
import pytest
import shapely
from shapely import LineString, MultiLineString, Point

import snkit
import snkit.io
from snkit.arrays import Frame, LineArray, PointArray
from test_api import random_network, shape

pa = pytest.importorskip("pyarrow")


def lines_table(crs="EPSG:27700"):
    return geopandas.GeoDataFrame(
        {"name": ["a", "b", "c"]},
        geometry=[LineString([(0, 0), (2, 2)]), LineString([(0, 2), (2, 0)]), LineString([(5, 5), (6, 5), (6, 6)])],
        crs=crs,
    )


def test_line_array_behaves_as_a_column():
    lines = LineArray.from_shapely(lines_table().geometry.values)
    assert len(lines) == 3 and lines[2].wkt == "LINESTRING (5 5, 6 5, 6 6)" and lines[-1] == lines[2]
    assert [g.wkt for g in lines[[2, 0]].to_shapely()] == ["LINESTRING (5 5, 6 5, 6 6)", "LINESTRING (0 0, 2 2)"]
    assert len(lines[np.array([True, False, True])]) == 2 and len(lines[1:]) == 2
    joined = LineArray._concat_same_type([lines, lines[[1]]])
    assert joined.offsets.tolist() == [0, 2, 4, 7, 9] and joined[3] == lines[1]
    assert not lines.isna().any() and lines.nbytes == 7 * 16 + 4 * 8
    with pytest.raises(TypeError):
        lines[0] = lines[1]
    with pytest.raises(ValueError, match="without geometry"):
        lines.take([0, -1], allow_fill=True)
    with pytest.raises(ValueError, match="LineStrings"):
        LineArray.from_shapely([Point(0, 0)])


def test_point_array_behaves_as_a_column():
    points = PointArray.from_shapely([Point(0, 1), Point(2, 3)])
    assert points[1] == Point(2, 3) and points[[1, 0]].xy.tolist() == [[2, 3], [0, 1]]
    assert PointArray._concat_same_type([points, points]).xy.shape == (4, 2)
    with pytest.raises(ValueError, match="Points"):
        PointArray.from_shapely([LineString([(0, 0), (1, 1)])])


def test_frame_follows_rows_through_pandas():
    network = snkit.to_arrays(snkit.from_edges(lines_table()))
    edges = network.edges
    assert isinstance(edges, Frame) and edges.crs.to_epsg() == 27700
    picked = edges[edges["name"] != "b"]
    assert [g.wkt for g in picked.geometry] == ["LINESTRING (0 0, 2 2)", "LINESTRING (5 5, 6 5, 6 6)"]
    both = pd.concat([edges, edges.iloc[[1]]], ignore_index=True)
    assert both.geometry[3] == edges.geometry[1]
    assert "LINESTRING (0 0, 2 2)" in repr(edges)


@pytest.mark.parametrize("encoding", ["WKB", "geoarrow"])
def test_from_edges_takes_arrow_and_gives_an_array_network(encoding):
    multi = geopandas.GeoDataFrame(
        {"name": ["d"]}, geometry=[MultiLineString([[(8, 8), (9, 8)], [(9, 9), (9, 10)]])], crs="EPSG:27700"
    )
    table = pd.concat([lines_table(), multi], ignore_index=True)
    network = snkit.from_edges(table.to_arrow(geometry_encoding=encoding))
    assert isinstance(network, snkit.ArrayNetwork) and snkit.validate(network) == []
    assert network.edges["name"].tolist() == ["a", "b", "c", "d", "d"]
    assert network.edges.crs.to_epsg() == 27700
    reference = snkit.from_edges(table)
    assert shape(network.to_geopandas()) == shape(reference)
    assert (
        network.edges[["id", "from_id", "to_id"]].values.tolist()
        == reference.edges[["id", "from_id", "to_id"]].values.tolist()
    )


def test_arrow_input_with_unusable_geometry():
    table = geopandas.GeoDataFrame(
        {"k": [1, 2, 3]}, geometry=[LineString([(0, 0), (1, 0)]), None, Point(3, 3)]
    ).to_arrow()
    with pytest.raises(ValueError, match="2 geometries"):
        snkit.from_edges(table)
    assert snkit.from_edges(table, invalid="drop").edges["k"].tolist() == [1]
    with pytest.raises(ValueError, match="no geometry column"):
        snkit.from_edges(pa.table({"k": [1]}))


def test_from_nodes_and_edges_and_from_topology_take_arrow():
    nodes = geopandas.GeoDataFrame({"kind": ["depot"]}, geometry=[Point(1, 1)]).to_arrow()
    edges = lines_table(None).to_arrow()
    network = snkit.from_nodes_and_edges(nodes, edges)
    assert isinstance(network, snkit.ArrayNetwork) and len(network.nodes) == 7
    assert network.nodes["kind"].iloc[0] == "depot"
    again = snkit.from_topology(*network.to_arrow())
    assert isinstance(again, snkit.ArrayNetwork) and snkit.validate(again) == []
    assert (
        again.edges[["id", "from_id", "to_id"]].values.tolist()
        == network.edges[["id", "from_id", "to_id"]].values.tolist()
    )


def pipeline(network):
    network = snkit.link_nodes_to_edges(network)
    network = snkit.split_edges_at_crossings(network, extensive=["cost"])
    network = snkit.merge_nodes(network, tolerance=1.0)
    network = snkit.split_edges_at_nodes(network, tolerance=0.2)
    network = snkit.link_nodes(network, tolerance=2.5, how="nearest")
    network = snkit.simplify_edges(snkit.merge_edges(network), tolerance=0.5)
    return snkit.label_components(snkit.drop_duplicate_edges(network))


@pytest.mark.parametrize("seed", range(5))
def test_operations_give_the_same_network_in_arrays(seed):
    tables = random_network(seed)
    arrays = snkit.to_arrays(tables)
    expected, actual = pipeline(tables), pipeline(arrays)
    assert isinstance(actual, snkit.ArrayNetwork) and not isinstance(expected, snkit.ArrayNetwork)
    assert snkit.validate(actual) == []
    converted = actual.to_geopandas()
    pd.testing.assert_frame_equal(pd.DataFrame(converted.edges), pd.DataFrame(expected.edges))
    pd.testing.assert_frame_equal(pd.DataFrame(converted.nodes), pd.DataFrame(expected.nodes))
    # the inputs are untouched, and matchers work on both forms
    assert shape(arrays.to_geopandas()) == shape(tables)
    pd.testing.assert_frame_equal(snkit.find_crossings(arrays), snkit.find_crossings(tables))
    pd.testing.assert_frame_equal(snkit.match_edges(arrays, 1.0), snkit.match_edges(tables, 1.0))


def test_operations_on_several_networks_in_arrays():
    a = snkit.to_arrays(snkit.from_edges([LineString([(0, 0), (10, 0)])]))
    b = snkit.to_arrays(snkit.from_edges([LineString([(4, 0.1), (14, 0.1)])]))
    joined = snkit.union(a, b, tolerance=0.5, split=True)
    assert isinstance(joined, snkit.ArrayNetwork)
    assert [g.wkt for g in joined.edges.geometry] == [
        "LINESTRING (0 0, 4 0)",
        "LINESTRING (4 0, 10 0)",
        "LINESTRING (10 0, 14 0.1)",
    ]
    assert isinstance(snkit.combine({"a": a, "b": b}), snkit.ArrayNetwork)
    assert isinstance(snkit.stitch([a, b], tolerance=5), snkit.ArrayNetwork)
    # one network of tables among them, and the result is tables
    assert not isinstance(snkit.combine([a, b.to_geopandas()]), snkit.ArrayNetwork)
    split, lineage = snkit.split_edges(a, pd.DataFrame({"edge": [0], "measure": [3.0]}), return_lineage=True)
    assert isinstance(split, snkit.ArrayNetwork) and lineage.edges["parent_id"].tolist() == [0, 0]


def test_array_network_crs_and_conversion():
    network = snkit.to_arrays(snkit.from_edges(lines_table()))
    expected = network.to_geopandas()
    expected.to_crs(epsg=4326)
    network.to_crs(epsg=4326)
    assert network.edges.crs.to_epsg() == network.nodes.crs.to_epsg() == 4326
    np.testing.assert_allclose(
        shapely.get_coordinates(network.to_geopandas().edges.geometry.values),
        shapely.get_coordinates(expected.edges.geometry.values),
    )
    assert snkit.validate(network) == []
    with pytest.raises(ValueError, match="different CRS"):
        network.set_crs(epsg=27700)
    network.set_crs(epsg=27700, allow_override=True)
    assert network.edges.crs.to_epsg() == 27700
    empty = snkit.ArrayNetwork()
    assert (
        len(empty.nodes) == 0
        and len(snkit.merge_edges(snkit.from_edges(pa.table(lines_table().iloc[:0].to_arrow()))).edges) == 0
    )
    with pytest.raises(ValueError, match="distance would be in degrees"):
        network.set_crs(epsg=4326, allow_override=True)
        snkit.merge_nodes(network, 1)


@pytest.mark.parametrize("encoding", ["interleaved", "separated"])
def test_arrow_out_and_back(encoding):
    network = snkit.split_edges_at_crossings(snkit.from_edges(lines_table().to_arrow()))
    nodes, edges = network.to_arrow(encoding)
    assert edges.schema.field("geometry").metadata[b"ARROW:extension:name"] == b"geoarrow.linestring"
    back = geopandas.GeoDataFrame.from_arrow(edges)
    assert back.crs.to_epsg() == 27700
    assert back.geometry.to_list() == network.to_geopandas().edges.geometry.to_list()
    assert (
        geopandas.GeoDataFrame.from_arrow(nodes).geometry.to_list() == network.to_geopandas().nodes.geometry.to_list()
    )
    # a Frame is itself Arrow data
    again = snkit.from_topology(network.nodes, network.edges)
    assert shape(again.to_geopandas()) == shape(network.to_geopandas())
    assert pa.table(network.edges).num_rows == len(network.edges)


def big_network():
    rng = np.random.default_rng(3)
    starts = rng.uniform(0, 1000, (2000, 2))
    lines = shapely.linestrings(np.stack([starts, starts + rng.uniform(-5, 5, (2000, 2))], axis=1))
    edges = geopandas.GeoDataFrame({"k": np.arange(2000)}, geometry=lines, crs="EPSG:27700")
    return snkit.to_arrays(snkit.from_edges(edges))


def test_parquet_keeps_statistics_that_let_a_box_be_read_alone(tmp_path):
    network = big_network()
    network.to_parquet(tmp_path / "nodes.parquet", tmp_path / "edges.parquet", row_group_size=100)
    groups = snkit.io.parquet_row_groups(tmp_path / "edges.parquet")
    assert len(groups) == 20 and groups["rows"].sum() == 2000 and groups.notna().all().all()
    # sorted in space, each row group covers a small part of the whole
    area = ((groups.xmax - groups.xmin) * (groups.ymax - groups.ymin)).sum()
    assert area < 4 * 1000 * 1000

    box = (100, 100, 300, 300)
    read_groups = []
    original = pa.parquet.ParquetFile.read_row_group

    def counting(self, group, *args, **kwargs):
        read_groups.append(group)
        return original(self, group, *args, **kwargs)

    pa.parquet.ParquetFile.read_row_group = counting
    try:
        part = pa.table(snkit.io.read_parquet(tmp_path / "edges.parquet", bbox=box, columns=["k"]))
    finally:
        pa.parquet.ParquetFile.read_row_group = original
    assert 0 < len(read_groups) < 8
    lines = network.to_geopandas().edges
    expected = lines[
        lines.intersects(shapely.box(*box).envelope)
        | lines.geometry.bounds.pipe(
            lambda b: (b.minx <= box[2]) & (b.maxx >= box[0]) & (b.miny <= box[3]) & (b.maxy >= box[1])
        )
    ]
    assert sorted(part["k"].to_pylist()) == sorted(expected["k"])
    assert part.column_names == ["k", "geometry"]

    # other readers understand the file
    table = geopandas.read_parquet(tmp_path / "edges.parquet")
    assert table.crs.to_epsg() == 27700 and len(table) == 2000
    assert sorted(g.wkt for g in table.geometry) == sorted(g.wkt for g in lines.geometry)

    back = snkit.read_network(tmp_path / "nodes.parquet", tmp_path / "edges.parquet")
    assert isinstance(back, snkit.ArrayNetwork) and snkit.validate(back) == []
    assert shape(back.to_geopandas()) == shape(network.to_geopandas())


def test_parquet_written_elsewhere_with_a_covering_or_without_statistics(tmp_path):
    table = lines_table()
    table.to_parquet(tmp_path / "covered.parquet", write_covering_bbox=True, row_group_size=1)
    groups = snkit.io.parquet_row_groups(tmp_path / "covered.parquet")
    assert groups[["xmin", "ymin", "xmax", "ymax"]].values.tolist() == [[0, 0, 2, 2], [0, 0, 2, 2], [5, 5, 6, 6]]
    part = snkit.from_edges(snkit.io.read_parquet(tmp_path / "covered.parquet", bbox=(4, 4, 9, 9)))
    assert part.edges["name"].tolist() == ["c"] and "bbox" not in part.edges.columns

    table.to_parquet(tmp_path / "plain.parquet")
    assert snkit.io.parquet_row_groups(tmp_path / "plain.parquet")["xmin"].isna().all()
    part = snkit.from_edges(snkit.io.read(tmp_path / "plain.parquet", bbox=(4, 4, 9, 9)))
    assert part.edges["name"].tolist() == ["c"] and part.edges.crs.to_epsg() == 27700


@pytest.mark.parametrize("driver, name", [("GPKG", "lines.gpkg"), ("FlatGeobuf", "lines.fgb")])
def test_read_other_formats_through_gdal(tmp_path, driver, name):
    lines_table().to_file(tmp_path / name, driver=driver)
    network = snkit.from_edges(snkit.io.read(tmp_path / name))
    # (a FlatGeobuf is stored in order of place, not in the order written)
    assert isinstance(network, snkit.ArrayNetwork) and sorted(network.edges["name"]) == ["a", "b", "c"]
    assert network.edges.crs.to_epsg() == 27700
    part = snkit.from_edges(snkit.io.read(tmp_path / name, bbox=(4, 4, 9, 9), columns=["name"]))
    assert part.edges["name"].tolist() == ["c"]


def test_a_query_engine_can_feed_snkit(tmp_path):
    sedonadb = pytest.importorskip("sedonadb")
    lines_table().to_parquet(tmp_path / "lines.parquet")
    session = sedonadb.connect()
    session.read_parquet(str(tmp_path / "lines.parquet")).to_view("lines")
    query = session.sql("SELECT name, geometry FROM lines WHERE ST_Length(geometry) > 2.5")
    network = snkit.split_edges_at_crossings(snkit.from_edges(query))
    assert isinstance(network, snkit.ArrayNetwork)
    assert sorted(network.edges["name"]) == ["a", "a", "b", "b"] and len(network.nodes) == 5
