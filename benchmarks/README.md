# OpenStreetMap road benchmark

This benchmark addresses issue #61 using the current Geofabrik extracts for
Oxfordshire and metropolitan France. It reads every way in GDAL's OSM `lines`
layer whose `highway` field is set. It then independently times creating unique
endpoint nodes, assigning node/edge IDs, and assigning edge topology IDs.

## Run

```console
uv sync --extra benchmark
uv run python benchmarks/benchmark_osm_roads.py all \
  --output benchmarks/osm-results.json
```

Downloads can be retried safely after a failure (incomplete downloads are
discarded), cached under `.benchmark-data`, and excluded from the timings. The
JSON output records exact source URLs, PBF sizes, platform and Python version
alongside node/edge counts and timings.

For an already downloaded or otherwise supplied extract, invoke the Python API
with `benchmark(area, pbf_path)`. This is useful on compute hosts where data is
staged separately.
