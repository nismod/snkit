"""Tests of building a network tile by tile, against building it in memory"""

import geopandas
import numpy as np
import pytest
import shapely
from shapely import LineString, MultiLineString

import snkit
import snkit.io
from snkit.tiled import Tiling, _sorted_in_space

pa = pytest.importorskip("pyarrow")


def random_lines(seed, count=1500, reach=8.0, extent=300.0):
    rng = np.random.default_rng(seed)
    # crowded towards one corner, so that even tiles would be very uneven
    start = rng.uniform(0, 1, (count, 1, 2)) ** 2 * extent
    points = start + np.cumsum(rng.uniform(-reach, reach, (count, 3, 2)), axis=1)
    return geopandas.GeoDataFrame(
        {"name": np.arange(count).astype(str), "lanes": rng.integers(1, 4, count)},
        geometry=shapely.linestrings(points),
        crs="EPSG:27700",
    )


def canonical(network):
    """Edges with their attributes, and nodes, in a form that does not depend on order or ids"""
    network = network.to_geopandas() if isinstance(network, snkit.ArrayNetwork) else network
    edges = sorted(
        (min(g.wkt, g.reverse().wkt), name, lanes)
        for g, name, lanes in zip(network.edges.geometry, network.edges["name"], network.edges["lanes"])
    )
    return edges, sorted(p.wkt for p in network.nodes.geometry)


def in_memory(lines, crossings=True):
    network = snkit.from_edges(lines)
    return snkit.split_edges_at_crossings(network) if crossings else network


def test_tiling_gives_every_place_one_tile():
    rng = np.random.default_rng(0)
    sample = rng.uniform(0, 1, (5000, 2)) ** 3 * 100
    tiling = Tiling.plan(sample, total=50_000, max_per_tile=2_000)
    owners = tiling.owners(sample)
    counts = np.bincount(owners, minlength=tiling.count) * 10
    assert tiling.count >= 25 and counts.max() <= 2_000 and counts.min() >= 500
    # a box holding a place reaches that place's tile, and a small box reaches few tiles
    boxes = np.column_stack([sample - 0.01, sample + 0.01])
    row, tile = tiling.reaches(boxes)
    assert (np.bincount(row) >= 1).all() and len(row) < 1.2 * len(sample)
    reached = set(zip(row.tolist(), tile.tolist()))
    assert all((i, t) in reached for i, t in enumerate(owners.tolist()))
    whole = tiling.reaches(np.array([[-1e9, -1e9, 1e9, 1e9]]))
    assert sorted(whole[1].tolist()) == list(range(tiling.count))

    one = Tiling.plan(sample, total=10, max_per_tile=100)
    assert one.count == 1 and one.owners(sample[:3]).tolist() == [0, 0, 0]
    same = Tiling.plan(np.ones((100, 2)), total=1000, max_per_tile=10)
    assert same.count == 1  # places that coincide cannot be divided


@pytest.mark.parametrize("seed, max_tile_edges", [(0, 100), (1, 40), (2, 400), (3, 5000)])
def test_tiled_build_matches_building_in_memory(tmp_path, seed, max_tile_edges):
    lines = random_lines(seed)
    lines.to_parquet(tmp_path / "lines.parquet")
    built = snkit.build_network(tmp_path / "lines.parquet", tmp_path / "out", max_tile_edges=max_tile_edges)
    expected = in_memory(lines)
    assert (built.node_count, built.edge_count) == (len(expected.nodes), len(expected.edges))
    assert built.tiles == (1 if max_tile_edges == 5000 else built.tiles) and (built.tiles > 3 or max_tile_edges > 1000)

    network = built.read()
    assert isinstance(network, snkit.ArrayNetwork) and snkit.validate(network) == []
    assert canonical(network) == canonical(expected)
    assert network.edges.crs.to_epsg() == 27700
    assert network.nodes["id"].tolist() == list(range(built.node_count))
    assert snkit.find_crossings(network).empty
    assert not list(tmp_path.glob("snkit-*"))


def test_tiled_build_of_long_and_awkward_lines(tmp_path):
    lines = random_lines(4, count=600)
    # lines that run through many tiles, lines that end on others, lines that share ends, a line crossing itself
    extra = geopandas.GeoDataFrame(
        {"name": ["long", "diagonal", "tee", "shared", "loop"], "lanes": [9, 9, 9, 9, 9]},
        geometry=[
            LineString([(-10, 150), (310, 150)]),
            LineString([(-10, -10), (310, 310)]),
            LineString([(100, 150), (100, 200)]),
            LineString([(310, 150), (310, 310)]),
            LineString([(200, 20), (220, 40), (220, 20), (200, 40)]),
        ],
        crs=lines.crs,
    )
    lines = geopandas.GeoDataFrame(np.concatenate([lines.values, extra.values]), columns=lines.columns, crs=lines.crs)
    lines = lines.astype({"lanes": int}).set_geometry("geometry")
    lines.to_parquet(tmp_path / "lines.parquet")
    built = snkit.build_network(tmp_path / "lines.parquet", tmp_path / "out", max_tile_edges=50)
    assert built.tiles > 8 and built.largest_tile < 200
    assert canonical(built.read()) == canonical(in_memory(lines))


def test_tiled_build_without_splitting_at_crossings(tmp_path):
    lines = random_lines(5, count=400)
    lines.to_parquet(tmp_path / "lines.parquet")
    built = snkit.build_network(
        tmp_path / "lines.parquet", tmp_path / "out", max_tile_edges=50, split_at_crossings=False
    )
    assert built.edge_count == 400
    assert canonical(built.read()) == canonical(in_memory(lines, crossings=False))


def test_tiled_build_plans_from_statistics_of_a_sorted_file(tmp_path, monkeypatch):
    lines = random_lines(6)
    snkit.io.write_parquet(
        snkit.from_edges(lines.to_arrow()).edges[["name", "lanes", "geometry"]],
        tmp_path / "sorted.parquet",
        row_group_size=100,
    )
    assert _sorted_in_space(snkit.io.parquet_row_groups(tmp_path / "sorted.parquet"))
    lines.to_parquet(tmp_path / "plain.parquet", row_group_size=100)
    assert not _sorted_in_space(snkit.io.parquet_row_groups(tmp_path / "plain.parquet"))

    # with statistics to plan from, nothing is copied to scratch before partitioning
    staged = []
    original = snkit.tiled._Scratch.add
    monkeypatch.setattr(
        snkit.tiled._Scratch, "add", lambda self, kind, *a: (staged.append(kind), original(self, kind, *a))[1]
    )
    built = snkit.build_network(tmp_path / "sorted.parquet", tmp_path / "out", max_tile_edges=100)
    assert "stage" not in staged and built.tiles > 8 and built.largest_tile < 400
    assert canonical(built.read()) == canonical(in_memory(lines))

    # the output is itself sorted in space, tile by tile, and can be read in part
    groups = snkit.io.parquet_row_groups(built.edges)
    assert len(groups) > 8 and _sorted_in_space(groups)
    box = (0, 0, 60, 60)
    part = built.read(bbox=box)
    assert snkit.validate(part) == [] and 0 < len(part.edges) < built.edge_count / 2
    whole = built.read().to_geopandas().edges
    bounds = whole.geometry.bounds
    inside = (bounds.minx <= box[2]) & (bounds.maxx >= box[0]) & (bounds.miny <= box[3]) & (bounds.maxy >= box[1])
    assert sorted(part.edges["id"]) == sorted(whole["id"][inside])


def test_tiled_build_from_a_stream_and_from_other_formats(tmp_path):
    lines = random_lines(7, count=500)
    expected = canonical(in_memory(lines))
    stream = snkit.io.reader(lines.to_arrow(geometry_encoding="geoarrow"))
    built = snkit.build_network(stream, tmp_path / "from_stream", max_tile_edges=60)
    assert canonical(built.read()) == expected

    lines.to_file(tmp_path / "lines.gpkg", driver="GPKG")
    built = snkit.build_network(tmp_path / "lines.gpkg", tmp_path / "from_gpkg", max_tile_edges=60, workdir=tmp_path)
    assert canonical(built.read()) == expected and built.read().edges.crs.to_epsg() == 27700


def test_tiled_build_from_a_query(tmp_path):
    sedonadb = pytest.importorskip("sedonadb")
    lines = random_lines(8, count=500)
    lines.to_parquet(tmp_path / "lines.parquet")
    session = sedonadb.connect()
    session.read_parquet(str(tmp_path / "lines.parquet")).to_view("lines")
    built = snkit.build_network(session.sql("SELECT * FROM lines WHERE lanes > 1"), tmp_path / "out", max_tile_edges=60)
    assert canonical(built.read()) == canonical(in_memory(lines[lines.lanes > 1]))


def test_tiled_build_handles_parts_bad_rows_and_names_in_use(tmp_path):
    lines = geopandas.GeoDataFrame(
        {"id": ["x", "y", "z", "w"], "name": list("abcd"), "lanes": [1, 2, 3, 4]},
        geometry=[
            LineString([(0, 0), (2, 2)]),
            MultiLineString([[(0, 2), (2, 0)], [(5, 5), (6, 5)]]),
            None,
            LineString([(1, 1), (1, 1)]),
        ],
    )
    lines.to_parquet(tmp_path / "lines.parquet")
    with pytest.raises(ValueError, match="2 geometries"):
        snkit.build_network(tmp_path / "lines.parquet", tmp_path / "out")
    assert not list(tmp_path.glob("snkit-*"))
    built = snkit.build_network(tmp_path / "lines.parquet", tmp_path / "out", invalid="drop", workdir=tmp_path)
    network = built.read()
    assert (built.node_count, built.edge_count) == (7, 5)
    assert sorted(network.edges["id_original"]) == ["x", "x", "y", "y", "y"]
    assert canonical(network) == canonical(in_memory(lines.rename(columns={"id": "ref"}).iloc[:2]))

    lines.iloc[2:].to_parquet(tmp_path / "nothing.parquet")
    with pytest.raises(ValueError, match="no lines"):
        snkit.build_network(tmp_path / "nothing.parquet", tmp_path / "out2", invalid="drop")
