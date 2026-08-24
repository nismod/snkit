"""Benchmark snkit topology operations on OpenStreetMap road networks.

Issue #61: measure performance on realistically large road networks.

The benchmark expects Geofabrik .osm.pbf extracts. By default it downloads:
- Oxfordshire, cropped from the England extract (small case)
- France (France Metropolitaine, i.e. mainland France; large case)

Run with:
    python benchmarks/benchmark_osm_roads.py oxfordshire
    python benchmarks/benchmark_osm_roads.py france

The OSM parsing time is reported separately from the snkit timings. The snkit
benchmark starts with highway way geometries, then measures creation of endpoint
nodes, ID assignment and topology assignment.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import geopandas as gpd
from pyrosm import OSM, get_data, get_data_by_geocoding

import snkit


DATA_DIR = Path(".benchmark-data")


def get_pbf(area: str) -> Path:
    DATA_DIR.mkdir(exist_ok=True)
    if area == "oxfordshire":
        # Download the covering Geofabrik extract and crop to the administrative
        # area returned by geocoding. This keeps the small benchmark reproducible.
        return Path(get_data_by_geocoding("Oxfordshire, United Kingdom", directory=DATA_DIR))
    if area == "france":
        # Geofabrik's France extract contains France Metropolitaine.
        return Path(get_data("france", directory=DATA_DIR))
    raise ValueError(area)


def timed(label, fn):
    start = perf_counter()
    result = fn()
    elapsed = perf_counter() - start
    print(f"{label}: {elapsed:.3f} s")
    return result, elapsed


def benchmark(area: str) -> dict:
    pbf = get_pbf(area)
    size_mb = pbf.stat().st_size / 1024**2
    print(f"dataset: {area}")
    print(f"pbf: {pbf} ({size_mb:.1f} MiB)")

    # France is several GB: use pyrosm's bounded-memory streaming reader.
    engine = "out_of_core" if area == "france" else "in_memory"
    osm = OSM(str(pbf), engine=engine, workers="auto" if area == "france" else None)

    edges, parse_seconds = timed(
        "read highway ways",
        lambda: osm.get_network(network_type="driving"),
    )
    # snkit operates on undirected geometries here; duplicate directional rows
    # from OSM are unnecessary for the topology benchmark.
    edges = gpd.GeoDataFrame(edges[["geometry"]].copy(), geometry="geometry", crs=edges.crs)
    edges = edges.drop_duplicates(subset="geometry").reset_index(drop=True)
    network = snkit.Network(edges=edges)

    network, endpoints_seconds = timed(
        "add endpoint nodes", lambda: snkit.network.add_endpoints(network)
    )
    network, ids_seconds = timed("add ids", lambda: snkit.network.add_ids(network))
    network, topology_seconds = timed(
        "add topology ids", lambda: snkit.network.add_topology(network)
    )

    result = {
        "area": area,
        "pbf_mib": round(size_mb, 1),
        "edges": len(network.edges),
        "nodes": len(network.nodes),
        "seconds": {
            "osm_read_highway_ways": parse_seconds,
            "snkit_add_endpoints": endpoints_seconds,
            "snkit_add_ids": ids_seconds,
            "snkit_add_topology": topology_seconds,
        },
    }
    print(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("area", choices=["oxfordshire", "france"])
    args = parser.parse_args()
    benchmark(args.area)


if __name__ == "__main__":
    main()
