"""Time the main operations on a synthetic network.

    python benchmarks/bench.py 100000
    python benchmarks/bench.py 100000 --arrays

With ``--arrays`` the network is held in arrays (an ArrayNetwork) instead of
in GeoDataFrames.

builds a network of roughly that many edges: long straight lines forming a
grid, so that every junction must be found as a crossing, plus scattered
points to connect.
"""

import resource
import sys
import time

import numpy as np
import shapely

import snkit


def grid_lines(target_edges, rng):
    """Jittered grid of long lines which, once split at crossings, has about target_edges edges"""
    n = int(np.sqrt(target_edges / 2)) + 1
    at = np.arange(n) * 100.0 + rng.uniform(-10, 10, n)
    low, high = np.full(n, -50.0), np.full(n, n * 100.0 - 50)
    across = np.stack([np.stack([low, at], axis=1), np.stack([high, at], axis=1)], axis=1)
    up = np.stack([np.stack([at, low], axis=1), np.stack([at, high], axis=1)], axis=1)
    return shapely.linestrings(np.concatenate([across, up])), n * 100.0


def timed(label, function, *args, **kwargs):
    start = time.perf_counter()
    result = function(*args, **kwargs)
    print(f"{label:<28}{time.perf_counter() - start:8.2f} s")
    return result


def main(target_edges, arrays=False):
    rng = np.random.default_rng(0)
    lines, extent = grid_lines(target_edges, rng)
    points = shapely.points(rng.uniform(0, extent - 100, (target_edges // 10, 2)))

    if arrays:
        # hand the lines and points over as Arrow, so that the network is held in arrays throughout
        import geopandas

        lines = geopandas.GeoDataFrame(geometry=lines).to_arrow(geometry_encoding="geoarrow")
        points = geopandas.GeoDataFrame(geometry=points).to_arrow(geometry_encoding="geoarrow")
    network = timed("from_nodes_and_edges", snkit.from_nodes_and_edges, points, lines)
    network = timed("split_edges_at_crossings", snkit.split_edges_at_crossings, network)
    print(f"  {len(network.nodes):,} nodes, {len(network.edges):,} edges")
    network = timed("link_nodes_to_edges", snkit.link_nodes_to_edges, network)
    network = timed("merge_nodes", snkit.merge_nodes, network, tolerance=5.0)
    network = timed("split_edges_at_nodes", snkit.split_edges_at_nodes, network, tolerance=1.0)
    network = timed("merge_edges", snkit.merge_edges, network)
    network = timed("simplify_edges", snkit.simplify_edges, network, tolerance=1.0)
    network = timed("label_components", snkit.label_components, network)
    timed("validate", snkit.validate, network)
    print(f"  {len(network.nodes):,} nodes, {len(network.edges):,} edges")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"peak memory {peak:,.0f} MiB")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100_000, "--arrays" in sys.argv)
