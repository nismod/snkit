"""Benchmark snkit topology operations on OpenStreetMap highway ways.

The input files are the current Geofabrik Oxfordshire and metropolitan-France
extracts.  Downloads are cached in ``.benchmark-data`` and are deliberately not
included in any measured interval.

Run both cases, writing machine-readable results, with::

    python benchmarks/benchmark_osm_roads.py all --output benchmarks/osm-results.json
"""

from __future__ import annotations

import argparse
import json
import platform
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any, TypeVar
from urllib.request import urlopen

import geopandas as gpd

import snkit


DATA_DIR = Path(".benchmark-data")
EXTRACTS = {
    "oxfordshire": "https://download.geofabrik.de/europe/united-kingdom/england/oxfordshire-latest.osm.pbf",
    # Geofabrik describes this extract as France métropolitaine.
    "france": "https://download.geofabrik.de/europe/france-latest.osm.pbf",
}
T = TypeVar("T")


def download(area: str, data_dir: Path = DATA_DIR) -> Path:
    """Return a cached extract, downloading it atomically when absent."""
    url = EXTRACTS[area]
    data_dir.mkdir(parents=True, exist_ok=True)
    destination = data_dir / url.rsplit("/", 1)[-1]
    if destination.exists():
        return destination

    partial = destination.with_suffix(destination.suffix + ".part")
    print(f"download: {url}", flush=True)
    try:
        with urlopen(url) as response, partial.open("wb") as output:  # noqa: S310
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return destination


def read_highway_ways(pbf: Path) -> gpd.GeoDataFrame:
    """Read highway geometries from GDAL's OSM ``lines`` layer."""
    edges = gpd.read_file(
        pbf,
        layer="lines",
        columns=[],
        where="highway IS NOT NULL",
        engine="pyogrio",
    )
    # OSM relations can contribute non-linear geometry to the lines layer.
    edges = edges.loc[edges.geometry.notna() & edges.geom_type.isin(["LineString", "MultiLineString"])]
    return edges.reset_index(drop=True)


def timed(label: str, function: Callable[[], T]) -> tuple[T, float]:
    start = perf_counter()
    result = function()
    elapsed = perf_counter() - start
    print(f"{label}: {elapsed:.3f} s", flush=True)
    return result, elapsed


def benchmark(area: str, pbf: Path | None = None) -> dict[str, Any]:
    pbf = pbf or download(area)
    size_mib = pbf.stat().st_size / 1024**2
    print(f"\ndataset: {area}\npbf: {pbf} ({size_mib:.1f} MiB)", flush=True)

    edges, read_seconds = timed("read highway ways", lambda: read_highway_ways(pbf))
    network = snkit.Network(edges=edges)
    network, endpoints_seconds = timed("create endpoint nodes", lambda: snkit.network.add_endpoints(network))
    network, ids_seconds = timed("add IDs", lambda: snkit.network.add_ids(network))
    network, topology_seconds = timed("add topology IDs", lambda: snkit.network.add_topology(network))

    result = {
        "area": area,
        "source": EXTRACTS[area],
        "pbf_mib": round(size_mib, 1),
        "edges": len(network.edges),
        "nodes": len(network.nodes),
        "seconds": {
            "read_highway_ways": read_seconds,
            "create_endpoint_nodes": endpoints_seconds,
            "add_ids": ids_seconds,
            "add_topology_ids": topology_seconds,
        },
    }
    print(json.dumps(result, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("area", choices=[*EXTRACTS, "all"])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    areas = list(EXTRACTS) if args.area == "all" else [args.area]
    results = [benchmark(area, download(area, args.data_dir)) for area in areas]
    report = {
        "system": {"platform": platform.platform(), "python": platform.python_version()},
        "results": results,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
