"""Time and measure building a network out of core.

    python benchmarks/bench_tiled.py make 10000000 lines.parquet
    python benchmarks/bench_tiled.py build lines.parquet out --max-tile-edges 250000

``make`` writes a file of random three-segment lines, a hundred times as dense
at one side as at the other, without holding them all in memory. ``build`` runs
snkit.build_network on a file and reports the time and the most memory used.
Run them separately so that the memory reported is that of building alone.
``components`` and ``merge`` run the operations on a network already built:

    python benchmarks/bench_tiled.py components out labelled
    python benchmarks/bench_tiled.py merge out merged 0.5
"""

import argparse
import resource
import time

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import snkit
from snkit.arrays import LineArray
from snkit.io import geo_metadata, geometry_array


def make(lines, path, chunk=500_000):
    rng = np.random.default_rng(0)
    step = 10.0
    side = np.sqrt(lines * 9 * step * step * 2 / np.pi)
    writer = None
    for start in range(0, lines, chunk):
        n = min(chunk, lines - start)
        # lines thin out along x, a hundred times as dense at one side as at the other
        place = rng.uniform(0, 1, (n, 1, 2))
        place[:, :, 0] = -np.log(1 - place[:, :, 0] * 0.99) / np.log(100)
        coords = place * side + np.cumsum(rng.uniform(-step, step, (n, 4, 2)), axis=1)
        geometry, field = geometry_array(LineArray(coords.reshape(-1, 2), np.arange(0, 4 * n + 1, 4)), "separated")
        table = pa.Table.from_arrays(
            [pa.array(np.arange(start, start + n)), pa.array(rng.integers(1, 5, n)), geometry],
            schema=pa.schema([pa.field("ref", pa.int64()), pa.field("lanes", pa.int64()), field]),
        ).replace_schema_metadata({b"geo": geo_metadata("lines", None)})
        writer = writer or pq.ParquetWriter(path, table.schema)
        writer.write_table(table, row_group_size=100_000)
    writer.close()
    print(f"wrote {lines:,} lines to {path}")


def report(built, start):
    seconds = time.perf_counter() - start
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"{built.node_count:,} nodes, {built.edge_count:,} edges")
    print(f"{seconds:,.0f} s, peak memory {peak:,.0f} MiB")


def components(network, destination):
    start = time.perf_counter()
    report(snkit.tiled.label_components(network, destination), start)


def merge(network, destination, tolerance, workdir, workers):
    start = time.perf_counter()
    report(snkit.tiled.merge_nodes(network, destination, tolerance, workdir=workdir, workers=workers), start)


def build(source, destination, max_tile_edges, workdir, workers=1):
    start = time.perf_counter()
    built = snkit.build_network(source, destination, max_tile_edges=max_tile_edges, workdir=workdir, workers=workers)
    seconds = time.perf_counter() - start
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"{built.node_count:,} nodes, {built.edge_count:,} edges, in {built.tiles:,} tiles")
    print(f"most edges reaching into one tile: {built.largest_tile:,}")
    print(f"{seconds:,.0f} s, peak memory {peak:,.0f} MiB")
    if workers > 1:
        each = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
        print(f"and up to {each:,.0f} MiB in each of {workers} worker processes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    making = commands.add_parser("make")
    making.add_argument("lines", type=int)
    making.add_argument("path")
    building = commands.add_parser("build")
    building.add_argument("source")
    building.add_argument("destination")
    building.add_argument("--max-tile-edges", type=int, default=250_000)
    building.add_argument("--workdir", default=None)
    building.add_argument("--workers", type=int, default=1)
    labelling = commands.add_parser("components")
    labelling.add_argument("network")
    labelling.add_argument("destination")
    merging = commands.add_parser("merge")
    merging.add_argument("network")
    merging.add_argument("destination")
    merging.add_argument("tolerance", type=float)
    merging.add_argument("--workdir", default=None)
    merging.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.command == "make":
        make(args.lines, args.path)
    elif args.command == "components":
        components(args.network, args.destination)
    elif args.command == "merge":
        merge(args.network, args.destination, args.tolerance, args.workdir, args.workers)
    else:
        build(args.source, args.destination, args.max_tile_edges, args.workdir, args.workers)
