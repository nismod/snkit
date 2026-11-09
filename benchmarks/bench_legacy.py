"""Time the functions of snkit.network on a synthetic network.

    python benchmarks/bench_legacy.py 10000

Used to compare these functions before and after they were rebuilt on the
array kernel. The network is the same jittered grid as bench.py.
"""

import resource
import sys
import time

import geopandas
import numpy as np
import shapely

import snkit
import snkit.network as sn

from bench import grid_lines


def timed(label, function, *args, **kwargs):
    start = time.perf_counter()
    try:
        result = function(*args, **kwargs)
    except Exception as error:  # report and carry on with what we have
        print(f"{label:<32}  failed: {type(error).__name__}: {error}")
        return None
    print(f"{label:<32}{time.perf_counter() - start:8.2f} s")
    return result


def main(target_edges):
    rng = np.random.default_rng(0)
    lines, extent = grid_lines(target_edges, rng)
    points = shapely.points(rng.uniform(0, extent - 100, (target_edges // 10, 2)))
    # a separate chain of short edges end to end, for merge_edges to join up
    steps = np.arange(target_edges // 10 + 1) * 10.0
    y = np.full(len(steps), -1000.0)
    chain = np.stack([np.stack([steps[:-1], y[:-1]], axis=1), np.stack([steps[1:], y[1:]], axis=1)], axis=1)
    lines = np.concatenate([lines, shapely.linestrings(chain)])
    edges = geopandas.GeoDataFrame({"kind": np.arange(len(lines)) % 3}, geometry=lines)
    nodes = geopandas.GeoDataFrame(geometry=points)
    network = snkit.Network(nodes=nodes, edges=edges)

    timed("snap_nodes", sn.snap_nodes, network)
    timed("round_geometries", sn.round_geometries, snkit.Network(nodes.copy(), edges.copy()), 1)
    network = timed("split_edges_at_intersections", sn.split_edges_at_intersections, network)
    print(f"  {len(network.nodes):,} nodes, {len(network.edges):,} edges")
    network = timed("add_endpoints", sn.add_endpoints, network)
    network = timed("link_nodes_to_nearest_edge", sn.link_nodes_to_nearest_edge, network)
    network = timed("split_edges_at_nodes", sn.split_edges_at_nodes, network)
    network = timed("add_ids", sn.add_ids, network)
    network = timed("add_topology", sn.add_topology, network)
    print(f"  {len(network.nodes):,} nodes, {len(network.edges):,} edges")
    timed("to_igraph", sn.to_igraph, network)
    timed("add_component_ids", sn.add_component_ids, snkit.Network(network.nodes.copy(), network.edges.copy()))
    merged = timed("merge_edges", sn.merge_edges, snkit.Network(network.nodes.copy(), network.edges.copy()))
    if merged is not None:
        print(f"  {len(merged.nodes):,} nodes, {len(merged.edges):,} edges")
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"peak memory {peak:,.0f} MiB")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10_000)
