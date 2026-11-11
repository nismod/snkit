"""Run the conformance cases against snkit.

The cases are JSON files under ``conformance/operations`` and
``conformance/kernel``; their format is set out in ``conformance/README.md``.
This module loads them, runs each against the Python implementation, and
compares what comes back with what the case expects.

    from run import load_cases, run_case, compare

    for name, case in load_cases().items():
        problems = compare(run_case(case), case["expected"])
        assert not problems, name

Run as a script, it runs every case and lists those that fail.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
TIERS = ("operations", "kernel")

# floats closer than this are the same
TOLERANCE = 1e-9

ID_COLUMNS = ("id", "from_id", "to_id")
GEOMETRY = "geometry"

CREATION = ("from_edges", "from_nodes_and_edges", "from_topology")
MATCHERS = ("match_nodes", "match_nodes_to_edges", "find_crossings", "match_edges")
MANY_NETWORKS = ("combine", "stitch")
TWO_NETWORKS = ("union", "intersection", "difference")

# the name of each output of each kernel function, in the order it is returned
KERNEL_OUTPUTS = {
    "components": ("labels",),
    "group_index": ("group", "is_first"),
    "line_measures": ("seglen", "measure", "length"),
    "locate": ("vertex", "frac", "xy"),
    "sync_ends": ("coords",),
    "extend_ends": ("coords", "offsets"),
    "split": ("coords", "offsets", "src", "dst", "parent"),
    "segment_crossings": ("seg_a", "seg_b", "frac_a", "frac_b", "xy"),
    "point_pairs": ("a", "b"),
    "points_near_lines": ("point", "line", "vertex", "frac", "xy", "distance"),
    "nearest_lines": ("point", "line", "vertex", "frac", "xy", "distance"),
    "nearest_points": ("nearest",),
    "simplify_lines": ("coords", "offsets"),
    "line_overlaps": (
        "a",
        "b",
        "near_start",
        "near_end",
        "start_a",
        "end_a",
        "start_b",
        "end_b",
        "reversed",
        "distance",
    ),
    "hausdorff_distance": ("distance",),
}


# ---------------------------------------------------------------------------
# Loading


def load_cases(tier: Optional[str] = None, root: Path = ROOT) -> Dict[str, Dict[str, Any]]:
    """Read the case files.

    Returns a dict from the name of each case - its path without the
    extension, such as ``operations/merge_nodes/chain`` - to its content,
    sorted by name. ``tier`` limits it to ``"operations"`` or ``"kernel"``.
    """
    cases = {}
    for name in TIERS if tier is None else (tier,):
        for path in sorted((root / name).glob("*/*.json")):
            with open(path, encoding="utf-8") as file:
                cases[path.relative_to(root).with_suffix("").as_posix()] = json.load(file)
    return dict(sorted(cases.items()))


# ---------------------------------------------------------------------------
# Between JSON and snkit


def _columns(rows: List[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for row in rows:
        names.extend(key for key in row if key != GEOMETRY and key not in names)
    return names


def table_from_json(rows: List[Dict[str, Any]], ids: Any = ()) -> Any:
    """A GeoDataFrame from a list of rows. A key missing from a row is null."""
    import geopandas
    import numpy as np
    import pandas as pd
    import shapely

    data = {name: [row.get(name) for row in rows] for name in _columns(rows)}
    table = pd.DataFrame(data, index=range(len(rows)))
    for name in ids:
        values = data.get(name, [])
        table[name] = np.asarray(values, dtype="uint64")
    wkt = [row.get(GEOMETRY) for row in rows]
    geometry = shapely.from_wkt(np.asarray(wkt, dtype=object)) if rows else []
    return geopandas.GeoDataFrame(table, geometry=geopandas.GeoSeries(geometry, index=table.index))


def network_from_json(data: Dict[str, Any]) -> Any:
    """A topological network from ``{"nodes": [...], "edges": [...]}``"""
    import snkit

    return snkit.Network(
        table_from_json(data.get("nodes", []), ("id",)),
        table_from_json(data.get("edges", []), ID_COLUMNS),
    )


def plain(value: Any) -> Any:
    """A value as JSON can hold it: null for anything missing, lists for arrays"""
    import numpy as np

    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if math.isnan(value) else float(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, np.ndarray)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    try:  # pandas.NA, NaT
        import pandas as pd

        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    raise TypeError(f"cannot write {value!r} as JSON")


def table_to_json(table: Any) -> List[Dict[str, Any]]:
    """Rows of a table of nodes or edges, with geometry as WKT"""
    import shapely

    wkt = shapely.to_wkt(table.geometry.values, rounding_precision=12, trim=True)
    names = [name for name in table.columns if name != table.geometry.name]
    rows = []
    for position in range(len(table)):
        row = {name: plain(table[name].iloc[position]) for name in names}
        row[GEOMETRY] = str(wkt[position])
        rows.append(row)
    return rows


def network_to_json(network: Any) -> Dict[str, Any]:
    return {"nodes": table_to_json(network.nodes), "edges": table_to_json(network.edges)}


def matches_to_json(matches: Any) -> Dict[str, Any]:
    names = list(matches.columns)
    rows = [{name: plain(matches[name].iloc[position]) for name in names} for position in range(len(matches))]
    return {"matches": rows}


def lineage_to_json(lineage: Any) -> Dict[str, Any]:
    return {
        kind: sorted([int(i), int(p)] for i, p in zip(table["id"], table["parent_id"]))
        for kind, table in (("nodes", lineage.nodes), ("edges", lineage.edges))
    }


def _parameters(case: Dict[str, Any]) -> Dict[str, Any]:
    import pandas as pd

    parameters = dict(case.get("parameters", {}))
    if "locations" in parameters:
        rows = parameters["locations"]
        names = ["edge", "measure"] + [name for name in _columns(rows) if name not in ("edge", "measure")]
        parameters["locations"] = pd.DataFrame({name: [row.get(name) for row in rows] for name in names})
    return parameters


# ---------------------------------------------------------------------------
# Running


def run_operation_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """Run an operation-level case; return what it gives, shaped like ``expected``.

    If the operation refuses its input the result is ``{"error": true}``, with
    the message alongside.
    """
    import snkit

    name = case["operation"]
    function = getattr(snkit, name)
    parameters = _parameters(case)
    data = case["input"]
    wants_lineage = "lineage" in case.get("expected", {})
    try:
        if name == "from_edges":
            return network_to_json(function(table_from_json(data["lines"]), **parameters))
        if name == "from_nodes_and_edges":
            return network_to_json(
                function(table_from_json(data.get("points", [])), table_from_json(data["lines"]), **parameters)
            )
        if name == "from_topology":
            return network_to_json(
                function(table_from_json(data["nodes"]), table_from_json(data["edges"]), **parameters)
            )
        if name in MATCHERS:
            return matches_to_json(function(network_from_json(data), **parameters))
        if name in MANY_NETWORKS or name in TWO_NETWORKS:
            networks = {key: network_from_json(data["networks"][key]) for key in sorted(data["networks"])}
            if name in TWO_NETWORKS:
                return network_to_json(function(networks["a"], networks["b"], **parameters))
            return network_to_json(function(networks, **parameters))
        network = network_from_json(data)
        if wants_lineage:
            result, lineage = function(network, return_lineage=True, **parameters)
            return {**network_to_json(result), "lineage": lineage_to_json(lineage)}
        return network_to_json(function(network, **parameters))
    except ValueError as error:
        return {"error": True, "message": str(error)}


def run_kernel_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """Run a kernel-level case; return its outputs by name"""
    import numpy as np

    from snkit import _kernel

    name = case["function"]
    result = getattr(_kernel, name)(**case["input"])
    if isinstance(result, np.ndarray):
        result = (result,)
    return {output: plain(value) for output, value in zip(KERNEL_OUTPUTS[name], result)}


def run_case(case: Dict[str, Any]) -> Dict[str, Any]:
    return run_kernel_case(case) if "function" in case else run_operation_case(case)


# ---------------------------------------------------------------------------
# Comparing


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def parse_wkt(text: str) -> Any:
    """A WKT point or line as its kind and a list of coordinates"""
    import shapely

    geometry = shapely.from_wkt(text)
    return [geometry.geom_type, [list(xy) for xy in shapely.get_coordinates(geometry).tolist()]]


def compare(actual: Any, expected: Any, where: str = "") -> List[str]:
    """List the differences between a result and what was expected (none if they agree).

    Integers, strings, booleans and structure must be equal. Other numbers
    must be within ``TOLERANCE``. Geometry is compared by its coordinates, not
    as text. Null, NaN and a key that is absent are all the same thing. An
    expected error is met by any error.
    """
    here = where or "result"
    if isinstance(expected, dict) and expected.get("error"):
        return [] if isinstance(actual, dict) and actual.get("error") else [f"{here}: expected an error"]
    if isinstance(actual, dict) and actual.get("error") and "message" in actual:
        return [f"{here}: unexpected error: {actual['message']}"]
    if _missing(expected) or _missing(actual):
        return [] if _missing(expected) and _missing(actual) else [f"{here}: {actual!r} != {expected!r}"]
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{here}: {actual!r} is not an object"]
        problems = []
        for key in sorted(set(expected) | set(actual)):
            a, e = actual.get(key), expected.get(key)
            if key == GEOMETRY and isinstance(a, str) and isinstance(e, str):
                a, e = parse_wkt(a), parse_wkt(e)
            problems += compare(a, e, f"{where}.{key}" if where else key)
        return problems
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{here}: {actual!r} is not a list"]
        if len(actual) != len(expected):
            return [f"{here}: {len(actual)} items, expected {len(expected)}"]
        problems = []
        for position, (a, e) in enumerate(zip(actual, expected)):
            problems += compare(a, e, f"{where}[{position}]")
        return problems
    if isinstance(expected, bool) or isinstance(actual, bool) or isinstance(expected, str) or isinstance(actual, str):
        same = type(actual) is type(expected) and actual == expected
    elif isinstance(expected, int) and isinstance(actual, int):
        same = actual == expected
    else:
        same = abs(float(actual) - float(expected)) <= TOLERANCE
    return [] if same else [f"{here}: {actual!r} != {expected!r}"]


def main() -> int:
    failed = 0
    cases = load_cases()
    for name, case in cases.items():
        problems = compare(run_case(case), case["expected"])
        if problems:
            failed += 1
            print(f"FAIL {name}")
            for problem in problems:
                print(f"     {problem}")
    print(f"{len(cases) - failed} of {len(cases)} cases pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
