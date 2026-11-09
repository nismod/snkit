"""Time and measure the array kernel alone, with no tables or geometry objects.

    python benchmarks/bench_kernel.py 10000000

Builds that many random three-segment lines, arranged so that each crosses
about one other, then finds the crossings, cuts the lines there, labels
connected components and looks for nodes close together. Everything stays in
flat arrays, which is how a large network should be handled.
"""

import resource
import sys
import time

import numpy as np

import snkit._kernel as K


def peak_mib():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def timed(label, function, *args):
    start = time.perf_counter()
    result = function(*args)
    print(f"{label:<22}{time.perf_counter() - start:8.2f} s   peak {peak_mib():8,.0f} MiB")
    return result


def cuts(first_node, seg_a, seg_b, t, u, xy):
    """A new node at each crossing, cutting both lines there"""
    node = first_node + np.arange(len(seg_a))
    seg = np.concatenate([seg_a, seg_b])
    order = np.lexsort((np.concatenate([t, u]), seg))
    return seg[order] // 4, seg[order], np.concatenate([xy, xy])[order], np.concatenate([node, node])[order]


def main(lines):
    rng = np.random.default_rng(0)
    step = 10.0
    # about one crossing per line: area grows with the number of lines
    side = np.sqrt(lines * 9 * step * step * 2 / np.pi)
    coords = np.cumsum(rng.uniform(-step, step, (lines, 4, 2)), axis=1) + rng.uniform(0, side, (lines, 1, 2))
    coords = np.ascontiguousarray(coords.reshape(-1, 2))
    offsets = np.arange(0, len(coords) + 1, 4, dtype=np.int64)
    # a node at each end of each line
    src, dst = np.arange(lines) * 2, np.arange(lines) * 2 + 1
    size = coords.nbytes / 2**20
    print(f"kernel: {K.BACKEND}; {lines:,} lines, {len(coords):,} vertices; input arrays {size:,.0f} MiB")

    seg_a, seg_b, t, u, xy = timed("segment_crossings", K.segment_crossings, coords, offsets)
    print(f"  {len(seg_a):,} crossings")

    cut_edge, cut_seg, cut_xy, cut_node = timed("prepare cuts", cuts, 2 * lines, seg_a, seg_b, t, u, xy)
    del seg_a, seg_b, t, u
    out_coords, out_offsets, out_src, out_dst, parent = timed(
        "split", K.split, coords, offsets, src, dst, cut_edge, cut_seg, cut_xy, cut_node
    )
    edges = len(out_src)
    nodes = 2 * lines + len(xy)
    print(f"  {nodes:,} nodes, {edges:,} edges")
    del coords, cut_edge, cut_seg, cut_xy, cut_node
    labels = timed("components", K.components, nodes, out_src, out_dst)
    print(f"  {len(np.unique(labels)):,} connected parts")
    node_xy = np.empty((nodes, 2))
    node_xy[out_src] = out_coords[out_offsets[:-1]]
    node_xy[out_dst] = out_coords[out_offsets[1:] - 1]
    a, b = timed("point_pairs", K.point_pairs, node_xy, step / 100)
    print(f"  {len(a):,} pairs of nodes within {step / 100}")
    print(f"peak memory {peak_mib():,.0f} MiB, {peak_mib() * 2**20 / edges:,.0f} bytes per edge")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000)
