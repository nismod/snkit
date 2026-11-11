"""Write the conformance case files.

Each case is defined below: its input and parameters, a title and a note. The
expected result is filled in by running snkit, and the case is written to
``conformance/operations/<operation>/<name>.json`` or
``conformance/kernel/<function>/<name>.json``. Files of cases that are no
longer defined are removed, so the directories always match this script.

    python conformance/generate.py

To add a case, add a call to ``op`` or ``kern`` below, run the script, and
read the file it writes: the expected result is only worth having once it
has been checked against the geometry, by eye. Then run
``python docs/make_examples.py`` to redraw the catalogue of examples.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run  # noqa: E402

CASES: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Writing


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _flat(value: Any) -> bool:
    """Whether a value is written on one line: a number, a list of numbers, a list of coordinates"""
    if _scalar(value):
        return True
    return isinstance(value, list) and all(_flat(item) for item in value)


def dumps(value: Any, indent: int = 0, in_list: bool = False) -> str:
    """JSON with sorted keys and an indent of two spaces, except that a row of
    a table (an object of plain values inside a list) and an array of numbers
    each stay on one line."""
    pad = "  " * indent
    if _flat(value):
        return json.dumps(value)
    if isinstance(value, dict):
        if not value or in_list and all(_flat(item) for item in value.values()):
            return json.dumps(value, sort_keys=True)
        items = [f"{pad}  {json.dumps(key)}: {dumps(value[key], indent + 1)}" for key in sorted(value)]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    items = [f"{pad}  {dumps(item, indent + 1, True)}" for item in value]
    return "[\n" + ",\n".join(items) + f"\n{pad}]"


def tidy(value: Any) -> Any:
    """Round floats to 12 places, so that 0.30000000000000004 is written as 0.3"""
    if isinstance(value, float):
        return round(value, 12) + 0.0
    if isinstance(value, list):
        return [tidy(item) for item in value]
    if isinstance(value, dict):
        return {key: tidy(item) for key, item in value.items()}
    return value


# ---------------------------------------------------------------------------
# Defining


def _xy(text: str) -> str:
    return " ".join(text.split())


def net(
    *lines: str,
    points: Sequence[str] = (),
    edge_attrs: Sequence[Dict[str, Any]] = (),
    node_attrs: Optional[Dict[int, Dict[str, Any]]] = None,
    first_node: int = 0,
    first_edge: int = 0,
) -> Dict[str, Any]:
    """A network from lines given as ``"x y, x y, ..."``.

    There is a node at each distinct end, numbered in order of appearance,
    then an isolated node for each of ``points``. This is worked out here, not
    by snkit, so that inputs do not depend on the code being tested.
    """
    where: Dict[str, int] = {}
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    def node(at: str, shared: bool = True) -> int:
        at = _xy(at)
        if shared and at in where:
            return where[at]
        number = first_node + len(nodes)
        nodes.append({"id": number, "geometry": f"POINT ({at})", **(node_attrs or {}).get(number, {})})
        if shared:
            where[at] = number
        return number

    for position, line in enumerate(lines):
        vertices = [_xy(v) for v in line.split(",")]
        attrs = edge_attrs[position] if position < len(edge_attrs) else {}
        edges.append(
            {
                "id": first_edge + position,
                "from_id": node(vertices[0]),
                "to_id": node(vertices[-1]),
                "geometry": f"LINESTRING ({', '.join(vertices)})",
                **attrs,
            }
        )
    for point in points:
        node(point, shared=False)
    return {"nodes": nodes, "edges": edges}


def L(line: str, **attrs: Any) -> Dict[str, Any]:
    return {"geometry": f"LINESTRING ({line})", **attrs}


def P(point: str, **attrs: Any) -> Dict[str, Any]:
    return {"geometry": f"POINT ({point})", **attrs}


def op(
    operation: str,
    name: str,
    title: str,
    note: str,
    input: Dict[str, Any],
    lineage: bool = False,
    error: bool = False,
    **parameters: Any,
) -> None:
    case = {"operation": operation, "title": title, "note": note, "parameters": parameters, "input": input}
    case["expected"] = {"error": True} if error else ({"lineage": {}} if lineage else {})
    key = f"operations/{operation}/{name}"
    assert key not in CASES, key
    CASES[key] = case


def kern(function: str, name: str, title: str, note: str, **input: Any) -> None:
    key = f"kernel/{function}/{name}"
    assert key not in CASES, key
    CASES[key] = {"function": function, "title": title, "note": note, "input": input, "expected": {}}


EMPTY: Dict[str, Any] = {"nodes": [], "edges": []}

# ===========================================================================
# Operations
# ===========================================================================

# --- from_edges ------------------------------------------------------------

op(
    "from_edges",
    "three-lines",
    "Three lines that meet",
    "A node is made at each distinct end point, numbered in order of first appearance. "
    "Lines whose ends are at exactly the same place share a node.",
    {"lines": [L("0 0, 1 0"), L("1 0, 2 0"), L("1 0, 1 1")]},
)
op(
    "from_edges",
    "near-ends-stay-apart",
    "Ends that nearly meet",
    "Without a tolerance, ends are shared only if they are exactly equal, so these two lines are not connected.",
    {"lines": [L("0 0, 1 0"), L("1.05 0, 2 0")]},
)
op(
    "from_edges",
    "tolerance",
    "Ends that nearly meet, with a tolerance",
    "Ends within the tolerance become one node at their centroid, which keeps the id of the first. "
    "The same as merge_nodes afterwards.",
    {"lines": [L("0 0, 1 0"), L("1.05 0, 2 0")]},
    tolerance=0.1,
)
op(
    "from_edges",
    "multilinestring",
    "A line in two parts",
    "A MultiLineString becomes one edge for each part, in place and in order. Each part copies the attributes.",
    {
        "lines": [
            {"geometry": "MULTILINESTRING ((0 0, 1 0), (1 0, 1 1))", "name": "A1"},
            L("3 0, 2 0", name="B2"),
        ]
    },
)
op(
    "from_edges",
    "integer-ids",
    "Ids supplied as integers",
    "A column named id that holds unique non-negative integers is used as the edge ids.",
    {"lines": [L("0 0, 1 0", id=10), L("1 0, 2 0", id=7)]},
)
op(
    "from_edges",
    "text-ids",
    "Ids supplied as text",
    "Ids that are not non-negative integers are kept as an attribute, id_original, and integer ids are generated.",
    {"lines": [L("0 0, 1 0", id="a"), L("1 0, 2 0", id="b")]},
)
op(
    "from_edges",
    "id-column",
    "Ids from a named column",
    "edge_id names the column to use as ids. It is used directly because it holds unique non-negative integers.",
    {"lines": [L("0 0, 1 0", code=5), L("1 0, 2 0", code=3)]},
    edge_id="code",
)
op(
    "from_edges",
    "invalid-dropped",
    "Unusable geometries, dropped",
    "A line of no length, an empty line and a missing geometry cannot be edges. "
    'With invalid="drop" they are left out; the edges that remain are numbered from 0.',
    {
        "lines": [
            L("0 0, 1 0", name="good"),
            L("1 1, 1 1", name="no length"),
            {"geometry": "LINESTRING EMPTY", "name": "empty"},
            {"geometry": None, "name": "missing"},
            L("1 0, 2 0", name="also good"),
        ]
    },
    invalid="drop",
)
op(
    "from_edges",
    "invalid-refused",
    "Unusable geometries, refused",
    "By default a geometry that cannot be an edge is an error.",
    {"lines": [L("0 0, 1 0"), L("1 1, 1 1")]},
    error=True,
)
op(
    "from_edges",
    "closed-line",
    "A line that ends where it starts",
    "A closed line becomes a self-loop: one node, and an edge from it to itself.",
    {"lines": [L("0 0, 2 0, 1 1, 0 0")]},
)
op(
    "from_edges",
    "z-dropped",
    "Lines with Z coordinates",
    "Z coordinates are dropped.",
    {"lines": [{"geometry": "LINESTRING Z (0 0 5, 1 0 7)"}]},
)
op(
    "from_edges",
    "empty",
    "No lines",
    "No lines give an empty network.",
    {"lines": []},
)

# --- from_nodes_and_edges --------------------------------------------------

op(
    "from_nodes_and_edges",
    "attach-within-tolerance",
    "Line ends attached to nearby nodes",
    "Each line end is attached to the nearest node within the tolerance and moved exactly onto it: "
    "nodes are anchors. An end with no node in reach gets a new node.",
    {"points": [P("0 0", name="A"), P("1.001 0", name="B")], "lines": [L("0 0, 1 0"), L("1 0, 2 0")]},
    tolerance=0.01,
)
op(
    "from_nodes_and_edges",
    "far-node-left-alone",
    "A node out of reach",
    "A node further than the tolerance from every line end is kept, unattached. Both ends get new nodes.",
    {"points": [P("1.5 0")], "lines": [L("0 0, 1 0")]},
    tolerance=0.1,
)
op(
    "from_nodes_and_edges",
    "nearest-node",
    "Two nodes in reach of one end",
    "An end with more than one node in reach is attached to the nearest.",
    {"points": [P("0.75 0"), P("1.125 0")], "lines": [L("0 0, 1 0")]},
    tolerance=0.5,
)
op(
    "from_nodes_and_edges",
    "exact",
    "No tolerance",
    "With no tolerance an end is attached only to a node at exactly the same place.",
    {"points": [P("0 0"), P("1 0.5")], "lines": [L("0 0, 1 0")]},
)
op(
    "from_nodes_and_edges",
    "node-ids",
    "Node ids supplied",
    "Integer node ids are kept, and new nodes are numbered above the highest.",
    {"points": [P("0 0", id=10), P("1 0", id=4)], "lines": [L("0 0, 1 0"), L("1 0, 1 1")]},
)
op(
    "from_nodes_and_edges",
    "collapsed-edge-dropped",
    "A line shorter than the tolerance",
    "Both ends of the short line are attached to the same node, which leaves it no length. "
    'With invalid="drop" it is left out.',
    {"points": [P("1 0")], "lines": [L("0 0, 0.9 0"), L("0.9 0, 1.1 0")]},
    tolerance=0.25,
    invalid="drop",
)

# --- from_topology ---------------------------------------------------------

op(
    "from_topology",
    "text-ids",
    "Tables that refer to each other by text ids",
    "Ids are converted to integers in order of the nodes table. The originals are kept as "
    "id_original, from_id_original and to_id_original.",
    {
        "nodes": [P("0 0", id="node_0"), P("1 0", id="node_1")],
        "edges": [L("0 0, 1 0", from_id="node_0", to_id="node_1")],
    },
)
op(
    "from_topology",
    "integer-ids",
    "Tables that refer to each other by integer ids",
    "Non-negative integer ids are used as they are. Edges have no ids here, so they are numbered from 0.",
    {
        "nodes": [P("0 0", id=5), P("1 0", id=2)],
        "edges": [L("1 0, 0 0", from_id=2, to_id=5)],
    },
)
op(
    "from_topology",
    "ends-moved-onto-nodes",
    "An edge end slightly off its node",
    "Each edge end within the tolerance of its node is moved exactly onto it.",
    {
        "nodes": [P("0 0", id=0), P("1 0", id=1)],
        "edges": [L("0 0, 0.5 0.5, 1 0.001", from_id=0, to_id=1)],
    },
    tolerance=0.01,
)
op(
    "from_topology",
    "end-too-far",
    "An edge end far from its node",
    "An edge end further than the tolerance from the node it names is an error.",
    {
        "nodes": [P("0 0", id=0), P("1 0", id=1)],
        "edges": [L("0 0, 1 0.5", from_id=0, to_id=1)],
    },
    tolerance=0.01,
    error=True,
)

# --- match_nodes -----------------------------------------------------------

op(
    "match_nodes",
    "pair",
    "One pair within tolerance",
    "Nodes 1 and 2 are exactly the tolerance apart, which counts as within it. Each pair is reported once, "
    "with the node that comes first in the nodes table as node_a.",
    net("0 0, 1 0", "1.5 0, 3 0"),
    tolerance=0.5,
)
op(
    "match_nodes",
    "three-in-a-row",
    "Three nodes in a row",
    "Neighbours are matched, but the two outer nodes are further apart than the tolerance and are not. "
    "Pairs are sorted by node_a, then node_b.",
    net(points=["0 0", "0.75 0", "1.5 0"]),
    tolerance=1,
)
op(
    "match_nodes",
    "same-place",
    "Two nodes at the same place",
    "With a tolerance of 0 only nodes at exactly the same place match.",
    net(points=["1 1", "2 1", "1 1"]),
    tolerance=0,
)

# --- match_nodes_to_edges --------------------------------------------------

op(
    "match_nodes_to_edges",
    "own-edges-and-ends",
    "Nodes are not matched to their own edges, or to the ends of others",
    "Every node here is within tolerance of some edge, but only node 4 is near the middle of an edge it is "
    "not an end of. Node 2 is nearest to the very end of edge 1, so it is near a node and not near the edge.",
    net("0 0, 2 0", "2.25 0, 4 0", points=["3 0.25"]),
    tolerance=0.5,
)
op(
    "match_nodes_to_edges",
    "nearest",
    "Nearest edge to each chosen node",
    'With how="nearest" each node chosen by the nodes mask gets one match, to its nearest edge, however far. '
    "Here the nearest place is the end of the edge, which is reported in this mode.",
    net("0 0, 2 0", "0 3, 2 3", points=["3 1", "1 2.5"]),
    how="nearest",
    nodes=[False, False, False, False, True, True],
)
op(
    "match_nodes_to_edges",
    "nearest-within",
    "Nearest edge, within a distance",
    "With a tolerance as well, a node with no edge that near has no match.",
    net("0 0, 2 0", points=["1 0.5", "1 3"]),
    how="nearest",
    tolerance=1,
)
op(
    "match_nodes_to_edges",
    "measure-along-a-bent-edge",
    "Measure along an edge with a corner",
    "The measure is the distance along the line from its start, round the corner: 2 along the first "
    "segment and 1 up the second.",
    net("0 0, 2 0, 2 2", points=["3 1"]),
    tolerance=1,
)
op(
    "match_nodes_to_edges",
    "two-edges",
    "A node near two edges",
    'With how="all" a node is matched to every edge within tolerance, nearest first.',
    net("0 0, 2 0", "0 1, 2 1", points=["1 0.25"]),
    tolerance=1,
)

# --- find_crossings --------------------------------------------------------

op(
    "find_crossings",
    "cross",
    "Two edges that cross",
    "One crossing, with the distance along each edge and the place.",
    net("0 0, 2 0", "1 -1, 1 1"),
)
op(
    "find_crossings",
    "ends-on-middle",
    "An edge that ends on the middle of another",
    "The end of edge 1 lies on edge 0, with no node of edge 0 there. This is reported like a crossing.",
    net("0 0, 2 0", "1 1, 1 0"),
)
op(
    "find_crossings",
    "shared-node",
    "Edges that meet at a shared node",
    "Edges that meet at a node they share do not cross.",
    net("0 0, 1 0", "1 0, 2 0", "1 0, 1 1"),
)
op(
    "find_crossings",
    "self-crossing",
    "An edge that crosses itself",
    "The edge is both sides of the crossing, at two different distances along itself.",
    net("0 0, 2 0, 2 1, 1 1, 1 -1"),
)
op(
    "find_crossings",
    "three-through-one-point",
    "Three edges through one point",
    "Each pair of edges is reported: three crossings at the same place.",
    net("0 0, 2 2", "0 2, 2 0", "0 1, 2 1"),
)
op(
    "find_crossings",
    "shared-stretch",
    "Edges that share a stretch of line",
    "Edges that overlap do not cross along the overlap. Only the ends of the shared stretch are reported: "
    "where edge 1 starts on edge 0, and where edge 0 ends on edge 1.",
    net("0 0, 2 0", "1 0, 3 0"),
)
op(
    "find_crossings",
    "at-a-vertex",
    "A crossing at a vertex of both edges",
    "Two edges that touch at a corner of each meet there once.",
    net("0 0, 1 1, 2 0", "0 2, 1 1, 2 2"),
)

# --- match_edges -----------------------------------------------------------

op(
    "match_edges",
    "alongside",
    "Two edges that run alongside each other for part of their length",
    "Edge 1 runs 0.1 from edge 0, from 4 to 10 along edge 0 and from 0 to 6 along itself.",
    net("0 0, 10 0", "4 0.1, 14 0.1"),
    tolerance=0.5,
)
op(
    "match_edges",
    "reversed",
    "Edges that run in opposite directions",
    "The same, with edge 1 drawn the other way: its stretch is from 4 to 10 along itself, and reversed is true.",
    net("0 0, 10 0", "14 0.1, 4 0.1"),
    tolerance=0.5,
)
op(
    "match_edges",
    "directed",
    "Opposite directions, directed",
    "With directed=true only edges running the same way match, so there is nothing here.",
    net("0 0, 10 0", "14 0.1, 4 0.1"),
    tolerance=0.5,
    directed=True,
)
op(
    "match_edges",
    "crossing-only",
    "Edges that only cross",
    "Two edges that cross are within tolerance of each other for a short way around the crossing. "
    "That stretch is shorter than min_length (by default twice the tolerance), so it is not reported.",
    net("0 0, 10 0", "5 -5, 5 5"),
    tolerance=0.5,
)
op(
    "match_edges",
    "exact-overlap",
    "Edges that lie on the same line",
    "With a tolerance of 0, only a stretch that both edges share exactly is matched.",
    net("0 0, 10 0", "4 0, 14 0"),
    tolerance=0,
)

# --- merge_nodes -----------------------------------------------------------

op(
    "merge_nodes",
    "centroid",
    "Two nodes that nearly meet",
    "Nodes 1 and 2 become one node at their centroid, with the id of the first. The ends of both edges move to it.",
    net("0 0, 1 0", "1.05 0, 2 0"),
    tolerance=0.1,
    lineage=True,
)
op(
    "merge_nodes",
    "position-first",
    "Merged node at the position of the first",
    'With position="first" the merged node sits where the first of its members was, and only the other moves.',
    net("0 0, 1 0", "1.5 0, 3 0"),
    tolerance=0.5,
    position="first",
)
op(
    "merge_nodes",
    "geometry-extend",
    "Edges extended, not moved",
    'With geometry="extend" each edge keeps its line and gains a vertex to reach the merged node.',
    net("0 0, 1 0", "1.5 0, 3 0"),
    tolerance=0.5,
    geometry="extend",
)
op(
    "merge_nodes",
    "chain",
    "Nodes merge in chains",
    "The nodes at 1, 1.5 and 2 on the y axis are each within tolerance of the next, so all three merge, "
    "although the outer two are further apart than the tolerance.",
    net("0 0, 0 1", "1 1.5, 0 1.5", "0 2, 0 3"),
    tolerance=0.5,
)
op(
    "merge_nodes",
    "max-spread",
    "A chain wider than max_spread",
    "The same chain would move its outer nodes by 0.5. With max_spread below that, the merge is refused.",
    net("0 0, 0 1", "1 1.5, 0 1.5", "0 2, 0 3"),
    tolerance=0.5,
    max_spread=0.25,
    error=True,
)
op(
    "merge_nodes",
    "short-edge-dropped",
    "A short edge between merged nodes",
    "Edge 1 joins the two nodes that merge and is no longer than the tolerance, so it is dropped.",
    net("0 0, 1 0", "1 0, 1.5 0", "1.5 0, 3 0"),
    tolerance=0.5,
    lineage=True,
)
op(
    "merge_nodes",
    "long-edge-becomes-loop",
    "A long edge between merged nodes",
    "Edge 0 joins the two nodes that merge but is longer than the tolerance, so it is kept, as a self-loop.",
    net("0 0, 0 2, 0.5 2, 0.5 0"),
    tolerance=0.5,
)
op(
    "merge_nodes",
    "attributes-agree-or-null",
    "Attributes of merged nodes",
    "By default a merged node keeps a value only where all its members agree: kind is kept, name is null.",
    net(
        points=["0 0", "0.5 0", "3 0"],
        node_attrs={
            0: {"name": "A", "kind": "stop"},
            1: {"name": "B", "kind": "stop"},
            2: {"name": "C", "kind": "depot"},
        },
    ),
    tolerance=0.5,
)
op(
    "merge_nodes",
    "attributes-agg",
    "Attributes of merged nodes, with rules",
    "agg gives a rule for each column: here the first name, the sum of load, and the list of codes.",
    net(
        points=["0 0", "0.5 0", "3 0"],
        node_attrs={
            0: {"name": "A", "load": 2, "code": "x"},
            1: {"name": "B", "load": 3, "code": "y"},
            2: {"name": "C", "load": 5, "code": "z"},
        },
    ),
    tolerance=0.5,
    agg={"name": "first", "load": "sum", "code": "list"},
)
op(
    "merge_nodes",
    "empty",
    "An empty network",
    "An empty network gives an empty network.",
    EMPTY,
    tolerance=1,
)

# --- link_nodes ------------------------------------------------------------

op(
    "link_nodes",
    "pair",
    "Two nodes that nearly meet",
    "Both nodes are kept and a straight edge is added between them, from the earlier to the later. "
    "The new edge has the next id and null attributes.",
    net("0 0, 1 0", "1.05 0, 2 0", edge_attrs=[{"name": "west"}, {"name": "east"}]),
    tolerance=0.1,
    lineage=True,
)
op(
    "link_nodes",
    "all",
    "Every pair within tolerance",
    'With how="all" (the default) every pair of nodes within tolerance is linked: all three sides of the triangle.',
    net(points=["0 0", "1 0", "1 2"]),
    tolerance=2.5,
)
op(
    "link_nodes",
    "nearest",
    "Each node to its nearest only",
    'With how="nearest" each node is linked to its nearest neighbour within tolerance. '
    "Nodes 0 and 1 choose each other and node 2 chooses node 1, so the long side is left out.",
    net(points=["0 0", "1 0", "1 2"]),
    tolerance=2.5,
    how="nearest",
)
op(
    "link_nodes",
    "already-linked",
    "Nodes that already share an edge",
    "Nodes 0 and 1 are within tolerance but already have an edge between them, so no edge is added there. "
    "Nodes 1 and 2 are linked.",
    net("0 0, 1 0", "1.5 0, 3 0"),
    tolerance=1,
)
op(
    "link_nodes",
    "same-place",
    "Nodes at the same place",
    "Nodes at exactly the same place are not linked: the edge would have no length.",
    {
        "nodes": [
            {"id": 0, "geometry": "POINT (0 0)"},
            {"id": 1, "geometry": "POINT (1 0)"},
            {"id": 2, "geometry": "POINT (1 0)"},
            {"id": 3, "geometry": "POINT (2 0)"},
        ],
        "edges": [
            {"id": 0, "from_id": 0, "to_id": 1, "geometry": "LINESTRING (0 0, 1 0)"},
            {"id": 1, "from_id": 2, "to_id": 3, "geometry": "LINESTRING (1 0, 2 0)"},
        ],
    },
    tolerance=0.5,
)

# --- split_edges -----------------------------------------------------------

op(
    "split_edges",
    "one-cut",
    "One cut",
    "The edge is cut 1 along. A node is made at the cut, and both pieces get new ids.",
    net("0 0, 4 0"),
    locations=[{"edge": 0, "measure": 1}],
    lineage=True,
)
op(
    "split_edges",
    "several-cuts",
    "Several cuts on one edge",
    "Cuts need not be given in order. The pieces are in order along the edge and take its place in the "
    "edges table; the new nodes are numbered in the order the cuts were given.",
    net("0 0, 4 0", "4 0, 4 2"),
    locations=[{"edge": 0, "measure": 3}, {"edge": 0, "measure": 1}],
)
op(
    "split_edges",
    "at-a-named-node",
    "A cut at an existing node",
    "A location that names a node puts that node at the cut, and the edge bends to pass through it. "
    "No node is created.",
    net("0 0, 4 0", points=["2 0.5"]),
    locations=[{"edge": 0, "measure": 2, "node": 2}],
)
op(
    "split_edges",
    "measure-round-a-corner",
    "A cut on an edge with a corner",
    "The measure runs along the line: 3 along is 1 up the second segment. A cut exactly at a vertex (2 along) "
    "does not repeat the vertex.",
    net("0 0, 2 0, 2 2"),
    locations=[{"edge": 0, "measure": 3}, {"edge": 0, "measure": 2}],
)
op(
    "split_edges",
    "tolerance-near-end",
    "A cut close to an end",
    "A cut within the tolerance of an end of the edge is not made, so no very short edge is created.",
    net("0 0, 4 0"),
    locations=[{"edge": 0, "measure": 0.25}, {"edge": 0, "measure": 2}],
    tolerance=0.5,
)
op(
    "split_edges",
    "extensive",
    "Attributes of the pieces",
    "Pieces copy the attributes of the edge. A column named in extensive is shared out in proportion to length.",
    net("0 0, 4 0", edge_attrs=[{"name": "A1", "cost": 8}]),
    locations=[{"edge": 0, "measure": 1}],
    extensive=["cost"],
)
op(
    "split_edges",
    "self-loop",
    "A cut on a self-loop",
    "A loop cut once becomes two edges between its node and the new node.",
    net("0 0, 2 0, 2 2, 0 2, 0 0"),
    locations=[{"edge": 0, "measure": 4}],
)

# --- split_edges_at_nodes --------------------------------------------------

op(
    "split_edges_at_nodes",
    "near-node",
    "A node close to an edge",
    "The edge is split at the node and bends to pass through it. The node does not move.",
    net("0 0, 2 0", points=["1 0.01"]),
    tolerance=0.05,
    lineage=True,
)
op(
    "split_edges_at_nodes",
    "move-node",
    "Moving the node, not the edge",
    'With move="node" the node is moved onto the edge, which keeps its line.',
    net("0 0, 2 0", points=["1 0.01"]),
    tolerance=0.05,
    move="node",
)
op(
    "split_edges_at_nodes",
    "exact",
    "A node exactly on an edge",
    "With no tolerance, only a node exactly on the line splits it. Node 3, just off the line, does not.",
    net("0 0, 4 0", points=["1 0", "3 0.25"]),
)
op(
    "split_edges_at_nodes",
    "on-a-vertex",
    "A node exactly on a vertex",
    "The edge is split at its corner. The vertex is not repeated.",
    net("0 0, 1 1, 2 0", points=["1 1"]),
)
op(
    "split_edges_at_nodes",
    "several-nodes",
    "Several nodes along one edge",
    "The edge is cut at each node, and the pieces are in order along it whatever the order of the nodes.",
    net("0 0, 4 0", points=["3 0", "1 0", "2 0"]),
)
op(
    "split_edges_at_nodes",
    "near-an-end",
    "A node close to the end of an edge",
    "Node 2 is within tolerance of the edge, but the nearest place on it is its end. "
    "That is a node near a node, which is for merge_nodes: the edge is not split.",
    net("0 0, 2 0", points=["2.25 0"]),
    tolerance=0.5,
)
op(
    "split_edges_at_nodes",
    "end-of-another-edge",
    "The end of one edge on the middle of another",
    "Node 2, the start of edge 1, lies on edge 0. Edge 0 is split there, which connects the two.",
    net("0 0, 2 0", "1 0, 1 1"),
)

# --- link_nodes_to_edges ---------------------------------------------------

op(
    "link_nodes_to_edges",
    "nearest",
    "A node off the network",
    "The node is projected onto its nearest edge. The edge is split there with a new node, and a new edge "
    "joins the node to it. The projected position is shared exactly by all three edges.",
    net("0 0, 2 0", points=["1 1"]),
    lineage=True,
)
op(
    "link_nodes_to_edges",
    "all-within",
    "Every edge within a distance",
    'With how="all" the node is linked to every edge within max_distance: here to both.',
    net("0 0, 2 0", "0 2, 2 2", points=["1 0.5"]),
    how="all",
    max_distance=2,
)
op(
    "link_nodes_to_edges",
    "max-distance",
    "Nearest, but not too far",
    "Node 2 is within max_distance of the edge and is linked. Node 3 is not, and is left alone.",
    net("0 0, 4 0", points=["1 0.5", "3 2"]),
    max_distance=1,
)
op(
    "link_nodes_to_edges",
    "beyond-the-end",
    "A node beyond the end of an edge",
    "The nearest place on the edge is its end, so the node is linked to the node already there and "
    "the edge is not split.",
    net("0 0, 2 0", points=["3 1"]),
)
op(
    "link_nodes_to_edges",
    "tolerance-near-end",
    "A projection close to an end",
    "The node projects onto the edge 0.25 from its end. That is within the tolerance, so the node is linked "
    "to the end node and no short edge is made.",
    net("0 0, 2 0", points=["1.75 1"]),
    tolerance=0.5,
)
op(
    "link_nodes_to_edges",
    "no-link",
    "Moving the node onto the edge",
    "With link=false the node is moved to the projected position and the edge is split at it. No edge is added.",
    net("0 0, 2 0", points=["1 1"]),
    link=False,
)
op(
    "link_nodes_to_edges",
    "chosen-nodes",
    "Choosing which nodes to link",
    "By default only nodes with no edges are linked. Here the nodes mask chooses node 3, the loose end of "
    "edge 1. It is linked to the nearest edge that it is not already an end of.",
    net("0 0, 4 0", "2 2, 2 1"),
    nodes=[False, False, False, True],
)
op(
    "link_nodes_to_edges",
    "shared-projection",
    "Two nodes that project to the same place",
    "Both nodes project onto the edge at the same place, and share one new node there.",
    net("0 0, 2 0", points=["1 1", "1 -1"]),
)
op(
    "link_nodes_to_edges",
    "on-the-edge",
    "A node already on the edge",
    "A node exactly on the edge needs no linking edge: the edge is split at the node.",
    net("0 0, 2 0", points=["1 0"]),
)
op(
    "link_nodes_to_edges",
    "extensive",
    "Attributes of the pieces and of the link",
    "Pieces of the split edge copy its attributes, with the extensive column shared by length. "
    "The linking edge is new and has null attributes.",
    net("0 0, 4 0", points=["1 1"], edge_attrs=[{"name": "A1", "cost": 8}]),
    extensive=["cost"],
)

# --- split_edges_at_crossings ----------------------------------------------

op(
    "split_edges_at_crossings",
    "cross",
    "Two edges that cross",
    "A node is made at the crossing and both edges are split there. All four pieces get new ids.",
    net("0 0, 2 2", "0 2, 2 0"),
    lineage=True,
)
op(
    "split_edges_at_crossings",
    "ends-on-middle",
    "An edge that ends on the middle of another",
    "Edge 0 is split at the node where edge 1 ends. No node is created, and edge 1 is unchanged.",
    net("0 0, 2 0", "1 1, 1 0"),
)
op(
    "split_edges_at_crossings",
    "tolerance-near-end",
    "A crossing close to an end",
    "Edge 1 crosses edge 0 only 0.25 short of its own end. With a tolerance of 0.5 the crossing uses that "
    "end node: edge 0 is split and bent to pass through it, and no short edge is made.",
    net("0 0, 4 0", "2 2, 2 -0.25"),
    tolerance=0.5,
)
op(
    "split_edges_at_crossings",
    "no-tolerance-near-end",
    "A crossing close to an end, with no tolerance",
    "The same network with no tolerance: a node is made at the crossing, leaving a short edge beyond it.",
    net("0 0, 4 0", "2 2, 2 -0.25"),
)
op(
    "split_edges_at_crossings",
    "three-through-one-point",
    "Three edges through one point",
    "The three crossings are at the same place and share one new node. Each edge is split in two.",
    net("0 0, 2 2", "0 2, 2 0", "0 1, 2 1"),
)
op(
    "split_edges_at_crossings",
    "self-crossing",
    "An edge that crosses itself",
    "The edge is cut twice at the crossing, giving three pieces. The middle piece is a loop.",
    net("0 0, 2 0, 2 1, 1 1, 1 -1"),
)
op(
    "split_edges_at_crossings",
    "at-a-vertex",
    "A crossing at a vertex of both edges",
    "Both edges are split at the corner where they touch. The vertex is not repeated.",
    net("0 0, 1 1, 2 0", "0 2, 1 1, 2 2"),
)
op(
    "split_edges_at_crossings",
    "shared-stretch",
    "Edges that share a stretch of line",
    "Each edge is split where the other ends on it. The shared stretch is left as two edges between the "
    "same nodes, which drop_duplicate_edges can then remove.",
    net("0 0, 2 0", "1 0, 3 0"),
)
op(
    "split_edges_at_crossings",
    "several-on-one-edge",
    "Several crossings on one edge",
    "Edge 0 is crossed twice and becomes three pieces, in order along it.",
    net("0 0, 4 0", "3 -1, 3 1", "1 -1, 1 1"),
)
op(
    "split_edges_at_crossings",
    "extensive",
    "Attributes of the pieces",
    "Pieces copy the attributes of their edge. A column named in extensive is shared out in proportion to length.",
    net(
        "0 0, 4 0",
        "1 -1, 1 1",
        edge_attrs=[{"name": "A1", "cost": 8}, {"name": "B2", "cost": 3}],
    ),
    extensive=["cost"],
)
op(
    "split_edges_at_crossings",
    "nothing-to-split",
    "Edges that meet only at nodes",
    "Edges that share a node, parallel edges between the same nodes and a self-loop do not cross: "
    "the network is returned unchanged.",
    net("0 0, 2 0", "0 0, 1 1, 2 0", "2 0, 3 1, 3 -1, 2 0"),
)
op(
    "split_edges_at_crossings",
    "single-edge",
    "A single edge",
    "One straight edge has nothing to cross.",
    net("0 0, 1 0"),
)
op(
    "split_edges_at_crossings",
    "empty",
    "An empty network",
    "An empty network gives an empty network.",
    EMPTY,
)

# --- simplify_edges --------------------------------------------------------

op(
    "simplify_edges",
    "nearly-straight",
    "A vertex that hardly matters",
    "The middle vertex is 0.001 off the straight line between the ends, less than the tolerance, so it is removed.",
    net("0 0, 1 0.001, 2 0"),
    tolerance=0.01,
)
op(
    "simplify_edges",
    "corner-kept",
    "A vertex that matters",
    "The corner at (2 1) is further than the tolerance from the simplified line and is kept. "
    "The vertex at (1 0.5) lies on the simplified line and is removed. The ends never move.",
    net("0 0, 1 0.5, 2 1, 4 0"),
    tolerance=0.25,
)
op(
    "simplify_edges",
    "no-new-crossing",
    "Simplifying must not create a crossing",
    "Removing the bump from edge 0 would make it cross edge 1, which it goes around. So edge 0 keeps its shape.",
    net("0 0, 2 0.5, 4 0", "2 -1, 2 0.25"),
    tolerance=1,
)
op(
    "simplify_edges",
    "self-loop",
    "A self-loop",
    "A loop is simplified like any other edge, and stays a loop.",
    net("0 0, 1 0.001, 2 0, 2 2, 0 2, 0 0"),
    tolerance=0.01,
)

# --- merge_edges -----------------------------------------------------------

op(
    "merge_edges",
    "chain",
    "Two edges through a node of degree 2",
    "The two edges become one, with a new id, and the node between them is removed. Edge 1 ran the other way "
    "and is reversed, so the merged edge runs in the direction of the earliest.",
    net("0 0, 1 0", "2 0, 1 0"),
    lineage=True,
)
op(
    "merge_edges",
    "junction",
    "Chains stop at junctions",
    "Node 2 has three edges and is kept. The two edges of the chain leading to it are merged; "
    "the merged edge takes the place of its earliest member in the table.",
    net("0 0, 1 0", "1 0, 2 0", "2 0, 3 1", "2 0, 3 -1"),
)
op(
    "merge_edges",
    "by",
    "Only where attributes agree",
    'With by=["kind"] edges are merged only where they have the same kind. Node 1 joins two roads and is '
    "removed; node 2 joins a road and a track and is kept.",
    net(
        "0 0, 1 0",
        "1 0, 2 0",
        "2 0, 3 0",
        edge_attrs=[{"kind": "road"}, {"kind": "road"}, {"kind": "track"}],
    ),
    by=["kind"],
)
op(
    "merge_edges",
    "keep",
    "Keeping chosen nodes",
    "keep is a mask over the nodes table. Node 1 has two edges but is kept, so only the edges through node 2 merge.",
    net("0 0, 1 0", "1 0, 2 0", "2 0, 3 0"),
    keep=[False, True, False, False],
)
op(
    "merge_edges",
    "directed",
    "Respecting direction",
    "With directed=true edges are merged only through a node with one edge in and one out. "
    "Node 1 is such a node. At node 2 both edges arrive, so it is kept.",
    net("0 0, 1 0", "1 0, 2 0", "3 0, 2 0"),
    directed=True,
)
op(
    "merge_edges",
    "undirected",
    "Ignoring direction",
    "The same network without directed: all three edges merge, and the last is reversed.",
    net("0 0, 1 0", "1 0, 2 0", "3 0, 2 0"),
)
op(
    "merge_edges",
    "ring",
    "A closed ring",
    "Every node of the ring has two edges. The ring becomes a single self-loop that keeps one node: "
    "the start of its earliest edge.",
    net("0 0, 2 0", "2 0, 1 1", "1 1, 0 0"),
)
op(
    "merge_edges",
    "loops-and-parallel-edges",
    "A self-loop and parallel edges",
    "Node 0 has degree 2, but both ends belong to one edge, the loop, so nothing is merged through it. "
    "The two parallel edges are a ring of two edges and become a loop on node 1.",
    net("0 0, 1 1, -1 1, 0 0", "3 0, 5 0", "3 0, 4 1, 5 0"),
)
op(
    "merge_edges",
    "attributes-agree-or-null",
    "Attributes of a merged edge",
    "By default a merged edge keeps a value only where all its members agree: kind is kept, name and cost are null.",
    net(
        "0 0, 1 0",
        "1 0, 2 0",
        edge_attrs=[{"name": "A1", "kind": "road", "cost": 2}, {"name": "B2", "kind": "road", "cost": 3}],
    ),
)
op(
    "merge_edges",
    "attributes-agg",
    "Attributes of a merged edge, with rules",
    "agg gives a rule for each column: here the first name, the sum of cost and the largest speed.",
    net(
        "0 0, 1 0",
        "1 0, 2 0",
        edge_attrs=[{"name": "A1", "cost": 2, "speed": 30}, {"name": "B2", "cost": 3, "speed": 50}],
    ),
    agg={"name": "first", "cost": "sum", "speed": "max"},
)
op(
    "merge_edges",
    "single-edge",
    "A single edge",
    "Nothing to merge: the network is returned unchanged.",
    net("0 0, 1 0"),
)

# --- drop_duplicate_edges --------------------------------------------------

op(
    "drop_duplicate_edges",
    "same-line",
    "The same line drawn twice",
    "Edge 1 joins the same nodes as edge 0 along the same line, in the other direction and with an extra "
    "vertex. It duplicates edge 0 and is dropped: the earlier edge is the one kept.",
    net("0 0, 2 0", "2 0, 1 0, 0 0"),
    lineage=True,
)
op(
    "drop_duplicate_edges",
    "directed",
    "Opposite directions, directed",
    "With directed=true an edge running the other way is not a duplicate. Edge 2 runs the same way as edge 0 "
    "and is dropped.",
    net("0 0, 2 0", "2 0, 0 0", "0 0, 2 0"),
    directed=True,
)
op(
    "drop_duplicate_edges",
    "parallel-edges-kept",
    "Different routes between the same nodes",
    "Edges 0 and 1 join the same nodes but by different lines, so both are kept.",
    net("0 0, 2 0", "0 0, 1 1, 2 0"),
)
op(
    "drop_duplicate_edges",
    "tolerance",
    "Nearly the same line",
    "Edge 1 strays 0.25 from edge 0, within the tolerance, and is dropped. Edge 2 strays 1 and is kept.",
    net("0 0, 2 0", "0 0, 1 0.25, 2 0", "0 0, 1 1, 2 0"),
    tolerance=0.5,
)
op(
    "drop_duplicate_edges",
    "self-loops",
    "The same loop drawn twice",
    "Two loops on one node along the same line, drawn in opposite directions, are duplicates.",
    net("0 0, 2 0, 1 1, 0 0", "0 0, 1 1, 2 0, 0 0"),
)

# --- label_components ------------------------------------------------------

op(
    "label_components",
    "two-parts",
    "Two connected parts and an isolated node",
    "Nodes and edges get a component column. Parts are numbered from 0 in order of their first node.",
    net("0 0, 1 0", "1 0, 2 0", "0 2, 1 2", points=["2 2"]),
)
op(
    "label_components",
    "column",
    "Naming the column",
    "column sets the name of the column added. Edges that cross without a node are not connected.",
    net("0 0, 2 2", "0 2, 2 0"),
    column="part",
)
op(
    "label_components",
    "empty",
    "An empty network",
    "An empty network gives an empty network.",
    EMPTY,
)

# --- combine ---------------------------------------------------------------

op(
    "combine",
    "two-networks",
    "Two networks side by side",
    "The networks are placed in one table, in order, without being connected, even where they touch. "
    "The first keeps its ids; ids of the second are shifted to follow on. A source column names "
    "the network each feature came from.",
    {"networks": {"rail": net("0 0, 1 0"), "road": net("1 0, 1 1", "1 1, 2 1")}},
)
op(
    "combine",
    "column",
    "Naming the source column, and attributes",
    "column names the column added. An attribute that only one network has is null for the other.",
    {
        "networks": {
            "a": net("0 0, 1 0", edge_attrs=[{"lanes": 2}]),
            "b": net("0 1, 1 1", edge_attrs=[{"gauge": "narrow"}]),
        }
    },
    column="network",
)
op(
    "combine",
    "no-column",
    "No source column",
    "With column=null no column is added. Ids follow on from the highest id before, not from the count.",
    {"networks": {"a": net("0 0, 1 0", first_node=5, first_edge=3), "b": net("0 1, 1 1")}},
    column=None,
)

# --- stitch ----------------------------------------------------------------

op(
    "stitch",
    "shared-node",
    "Two networks that share a node on the cut",
    "The node at (1 0) is in both networks and becomes one node, with the id it has in the first. "
    "Other ids are as for combine.",
    {"networks": {"a_west": net("0 0, 1 0"), "b_east": net("1 0, 2 0")}},
)
op(
    "stitch",
    "tolerance",
    "Nodes that nearly meet on the cut",
    "With a tolerance, nodes of different networks that close are one node. It takes the position it has "
    "in the first network, and the edge of the second moves to it.",
    {"networks": {"a_west": net("0 0, 1 0"), "b_east": net("1.25 0, 2 0")}},
    tolerance=0.5,
)
op(
    "stitch",
    "not-within-one-network",
    "Close nodes within one network",
    "Only nodes of different networks are joined. The two nodes of the first network are within tolerance "
    "of each other but stay apart.",
    {"networks": {"a_west": net("0 0, 0.25 0"), "b_east": net("3 0, 4 0")}},
    tolerance=0.5,
)
op(
    "stitch",
    "on-id",
    "Matching nodes by id",
    'With on="id" nodes with the same id in different networks are the same node, wherever they are. '
    "Node 1 of the second network is node 1 of the first, and its edge moves to the first's position.",
    {
        "networks": {
            "a_west": net("0 0, 1 0"),
            "b_east": {
                "nodes": [{"id": 1, "geometry": "POINT (1 0.25)"}, {"id": 7, "geometry": "POINT (2 0)"}],
                "edges": [{"id": 0, "from_id": 1, "to_id": 7, "geometry": "LINESTRING (1 0.25, 2 0)"}],
            },
        }
    },
    on="id",
)
op(
    "stitch",
    "on-column",
    "Matching nodes by a column",
    "on names a column: nodes of different networks with the same value in it are the same node. "
    "Nodes with a null value are never matched.",
    {
        "networks": {
            "a_west": net("0 0, 1 0", node_attrs={0: {"code": None}, 1: {"code": "X"}}),
            "b_east": net("1 0.25, 2 0", node_attrs={0: {"code": "X"}, 1: {"code": None}}),
        }
    },
    on="code",
    column=None,
)

# --- union, intersection, difference ---------------------------------------

WHOLE = {"networks": {"a": net("0 0, 1 0", "1 0, 2 0"), "b": net("1 0, 2 0", "2 0, 3 0")}}
NEAR = {"networks": {"a": net("0 0, 1 0", "1 0, 2 0"), "b": net("1 0.25, 2 0.25", "2 0.25, 3 0.25")}}
PARTIAL = {"networks": {"a": net("0 0, 10 0"), "b": net("4 0.1, 14 0.1")}}
ATTRS = {
    "networks": {
        "a": net("0 0, 1 0", points=["5 0", "6 0"], edge_attrs=[{"name": "a's"}]),
        "b": net("1 0, 0 0", points=["5 0"], edge_attrs=[{"name": "b's"}]),
    }
}

op(
    "union",
    "shared-edge",
    "Two networks with an edge in common",
    "The edge from (1 0) to (2 0) is in both and is kept once, as a's. b's other edge is added, "
    "with ids shifted to follow a's.",
    WHOLE,
)
op(
    "union",
    "tolerance",
    "Nearly the same edge",
    "With a tolerance, b's nodes within reach of a's are the same nodes, at a's positions, and b's first edge "
    "is the same as a's second. b's remaining edge is moved to start at a's node.",
    NEAR,
    tolerance=0.5,
)
op(
    "union",
    "no-tolerance",
    "Nearly the same edge, with no tolerance",
    "With no tolerance nothing matches, and the union is both networks side by side.",
    NEAR,
)
op(
    "union",
    "split",
    "Edges that partly overlap",
    "With split=true each edge is first split where the other starts or stops running alongside it. "
    "The shared stretch is kept once with a's geometry; b's remainder is joined to a's end node.",
    PARTIAL,
    tolerance=0.5,
    split=True,
)
op(
    "union",
    "attributes-and-isolated-nodes",
    "Attributes and isolated nodes",
    "A shared edge keeps a's attributes and direction. An isolated node in both is kept once.",
    ATTRS,
)

op(
    "intersection",
    "shared-edge",
    "Two networks with an edge in common",
    "Only a's edge that is also in b is kept, with its end nodes.",
    WHOLE,
)
op(
    "intersection",
    "tolerance",
    "Nearly the same edge",
    "With a tolerance, a's second edge matches b's first, and is kept at a's position.",
    NEAR,
    tolerance=0.5,
)
op(
    "intersection",
    "split",
    "Edges that partly overlap",
    "With split=true, the stretch of a that b runs alongside.",
    PARTIAL,
    tolerance=0.5,
    split=True,
)
op(
    "intersection",
    "attributes-and-isolated-nodes",
    "Attributes and isolated nodes",
    "The shared edge has a's attributes. Of a's isolated nodes, the one that is also in b is kept.",
    ATTRS,
)
op(
    "intersection",
    "nothing-shared",
    "Nothing in common",
    "Networks that only touch at a node share no edge, and the node is used by an edge of a, so it is not "
    "an isolated node in common either: the result is empty.",
    {"networks": {"a": net("0 0, 1 0"), "b": net("1 0, 2 0")}},
)

op(
    "difference",
    "shared-edge",
    "Two networks with an edge in common",
    "Only a's edge that is not in b is kept, with its end nodes.",
    WHOLE,
)
op(
    "difference",
    "tolerance",
    "Nearly the same edge",
    "With a tolerance, a's second edge matches b's first and is removed.",
    NEAR,
    tolerance=0.5,
)
op(
    "difference",
    "split",
    "Edges that partly overlap",
    "With split=true, the stretch of a that b does not run alongside.",
    PARTIAL,
    tolerance=0.5,
    split=True,
)
op(
    "difference",
    "attributes-and-isolated-nodes",
    "Attributes and isolated nodes",
    "a's only edge is in b, so no edge is left. Of a's isolated nodes, the one that is not in b is kept.",
    ATTRS,
)

# ===========================================================================
# Kernel
# ===========================================================================

# --- components ------------------------------------------------------------

kern(
    "components",
    "two-groups",
    "Two linked groups and a single item",
    "Each item is labelled with the lowest position in its group.",
    n=5,
    a=[0, 3],
    b=[1, 4],
)
kern(
    "components",
    "chain",
    "A chain given out of order",
    "Links join up into one group whatever order they come in and whichever way round each is given.",
    n=4,
    a=[3, 2],
    b=[2, 1],
)
kern(
    "components",
    "no-links",
    "No links",
    "Every item is its own group.",
    n=3,
    a=[],
    b=[],
)
kern(
    "components",
    "self-link-and-repeat",
    "A repeated link and a link from an item to itself",
    "Neither changes the grouping.",
    n=3,
    a=[1, 2, 0],
    b=[1, 0, 2],
)

# --- group_index -----------------------------------------------------------

kern(
    "group_index",
    "three-groups",
    "Labels to consecutive numbers",
    "Groups are numbered from 0 in order of their first item, and the first item of each is marked.",
    labels=[0, 0, 2, 3, 3],
)
kern(
    "group_index",
    "interleaved",
    "Groups whose items are interleaved",
    "Numbering follows the first item of each group, not the order of the labels.",
    labels=[0, 1, 0, 1, 4],
)
kern(
    "group_index",
    "empty",
    "No items",
    "Empty arrays out.",
    labels=[],
)

# --- line_measures ---------------------------------------------------------

kern(
    "line_measures",
    "one-line",
    "A line with a corner",
    "For each vertex, the length of the segment that starts there (0 at the last) and the distance along "
    "the line; and the length of the line.",
    coords=[[0, 0], [3, 0], [3, 4]],
    offsets=[0, 3],
)
kern(
    "line_measures",
    "two-lines",
    "Two lines",
    "Measures start again at 0 for each line.",
    coords=[[0, 0], [1, 0], [0, 0], [0, 2], [2, 2]],
    offsets=[0, 2, 5],
)
kern(
    "line_measures",
    "no-lines",
    "No lines",
    "Empty arrays out.",
    coords=[],
    offsets=[0],
)

# --- locate ----------------------------------------------------------------

_SEGLEN, _MEASURE = [3.0, 4.0, 0.0], [0.0, 3.0, 7.0]
kern(
    "locate",
    "along-a-line",
    "Places along a line with a corner",
    "Each place is given as the vertex that starts its segment, the fraction along that segment, and the "
    "coordinate. seglen and measure are the outputs of line_measures.",
    coords=[[0, 0], [3, 0], [3, 4]],
    offsets=[0, 3],
    seglen=_SEGLEN,
    measure=_MEASURE,
    line=[0, 0],
    at=[1.5, 5],
)
kern(
    "locate",
    "ends-and-vertex",
    "The start, a vertex, and the end",
    "A place exactly at an interior vertex is given as the start of the segment that leaves it (fraction 0). "
    "The end of the line is the end of its last segment (fraction 1).",
    coords=[[0, 0], [3, 0], [3, 4]],
    offsets=[0, 3],
    seglen=_SEGLEN,
    measure=_MEASURE,
    line=[0, 0, 0],
    at=[0, 3, 7],
)
kern(
    "locate",
    "second-line",
    "A place on the second of two lines",
    "Vertex positions count along the whole coordinate array, so the answer for line 1 starts from its offset.",
    coords=[[0, 0], [1, 0], [0, 0], [0, 2], [2, 2]],
    offsets=[0, 2, 5],
    seglen=[1.0, 0.0, 2.0, 2.0, 0.0],
    measure=[0.0, 1.0, 0.0, 2.0, 4.0],
    line=[1, 0],
    at=[3, 0.25],
)

# --- sync_ends -------------------------------------------------------------

kern(
    "sync_ends",
    "move-ends",
    "Ends moved onto their nodes",
    "The first and last vertex of the edge are replaced by the positions of its end nodes. "
    "Vertices between are untouched.",
    coords=[[0.25, 0], [1, 1], [2, 0.25]],
    offsets=[0, 3],
    xy=[[0, 0], [2, 0]],
    src=[0],
    dst=[1],
)
kern(
    "sync_ends",
    "two-edges",
    "Two edges to one node",
    "Both edges are moved to end exactly on the node they share. Ends already in place stay as they are.",
    coords=[[0, 0], [0.75, 0], [1.25, 0], [2, 0]],
    offsets=[0, 2, 4],
    xy=[[0, 0], [1, 0], [2, 0]],
    src=[0, 1],
    dst=[1, 2],
)

# --- extend_ends -----------------------------------------------------------

kern(
    "extend_ends",
    "extend-both",
    "Both ends extended",
    "Where an end is not on its node a vertex is added at the node, and the original line is kept whole.",
    coords=[[0.25, 0], [1, 1], [2, 0.25]],
    offsets=[0, 3],
    xy=[[0, 0], [2, 0]],
    src=[0],
    dst=[1],
)
kern(
    "extend_ends",
    "one-end",
    "Only the ends that need it",
    "The first edge is already on its nodes and is unchanged. The second gains a vertex at its start, "
    "and offsets move along to match.",
    coords=[[0, 0], [1, 0], [1.25, 0], [2, 0]],
    offsets=[0, 2, 4],
    xy=[[0, 0], [1, 0], [2, 0]],
    src=[0, 1],
    dst=[1, 2],
)

# --- split -----------------------------------------------------------------

kern(
    "split",
    "one-cut",
    "One cut",
    "The edge is cut on its only segment at (1 0), where node 2 goes. The two pieces share that coordinate, "
    "and each names the edge it was cut from.",
    coords=[[0, 0], [4, 0]],
    offsets=[0, 2],
    src=[0],
    dst=[1],
    cut_edge=[0],
    cut_seg=[0],
    cut_xy=[[1, 0]],
    cut_node=[2],
)
kern(
    "split",
    "two-cuts-and-an-uncut-edge",
    "Two cuts on one edge, and an edge left alone",
    "Cuts are given in order along the edge. cut_seg is the position, in the whole coordinate array, of the "
    "vertex that starts the segment cut. Pieces take the place of their edge; the second edge follows unchanged.",
    coords=[[0, 0], [2, 0], [2, 2], [5, 5], [6, 5]],
    offsets=[0, 3, 5],
    src=[0, 2],
    dst=[1, 3],
    cut_edge=[0, 0],
    cut_seg=[0, 1],
    cut_xy=[[1, 0], [2, 1]],
    cut_node=[4, 5],
)
kern(
    "split",
    "on-a-vertex",
    "A cut on an existing vertex",
    "A cut at a coordinate that is already a vertex of the edge does not repeat it.",
    coords=[[0, 0], [1, 1], [2, 0]],
    offsets=[0, 3],
    src=[0],
    dst=[1],
    cut_edge=[0],
    cut_seg=[1],
    cut_xy=[[1, 1]],
    cut_node=[2],
)
kern(
    "split",
    "off-the-line",
    "A cut at a coordinate off the line",
    "The coordinate given is inserted as it is, so the edge bends to pass through it.",
    coords=[[0, 0], [2, 0]],
    offsets=[0, 2],
    src=[0],
    dst=[1],
    cut_edge=[0],
    cut_seg=[0],
    cut_xy=[[1, 0.25]],
    cut_node=[2],
)

# --- segment_crossings -----------------------------------------------------

kern(
    "segment_crossings",
    "cross",
    "Two segments that cross",
    "One meeting: the two segments, each named by the position of the vertex where it starts, the fraction "
    "along each, and the coordinate.",
    coords=[[0, 0], [2, 2], [0, 2], [2, 0]],
    offsets=[0, 2, 4],
)
kern(
    "segment_crossings",
    "touch",
    "A segment that ends on another",
    "The meeting is exactly at the end of the second segment: its fraction is exactly 1 and the coordinate "
    "is that end's own.",
    coords=[[0, 0], [4, 0], [1, 1], [1, 0]],
    offsets=[0, 2, 4],
)
kern(
    "segment_crossings",
    "end-to-end",
    "Lines that meet end to end",
    "Left out by default, like the vertex shared by successive segments of one line.",
    coords=[[0, 0], [1, 0], [1, 0], [2, 1]],
    offsets=[0, 2, 4],
)
kern(
    "segment_crossings",
    "end-to-end-wanted",
    "Lines that meet end to end, asked for",
    "With end_to_end set, the place where the two lines meet at an end of each is reported.",
    coords=[[0, 0], [1, 0], [1, 0], [2, 1]],
    offsets=[0, 2, 4],
    end_to_end=True,
)
kern(
    "segment_crossings",
    "end-on-a-vertex",
    "A line that ends on a vertex of another",
    "The second line starts at the corner of the first. That place is on two segments of the first line, "
    "and a meeting is given for each: at the end of one (fraction 1) and the start of the next (fraction 0).",
    coords=[[0, 0], [1, 0], [1, 1], [1, 0], [2, 0]],
    offsets=[0, 3, 5],
)
kern(
    "segment_crossings",
    "overlap",
    "Segments that overlap along a line",
    "Segments that share a stretch give a meeting for each end of one lying on the other: here the start of "
    "the second on the first, and the end of the first on the second.",
    coords=[[0, 0], [2, 0], [1, 0], [3, 0]],
    offsets=[0, 2, 4],
)

# --- point_pairs -----------------------------------------------------------

kern(
    "point_pairs",
    "within",
    "Pairs within a distance",
    "Each pair once, lower position first, sorted. A pair exactly the tolerance apart is included.",
    xy=[[0, 0], [1, 0], [1, 0.5], [3, 0]],
    tolerance=1,
)
kern(
    "point_pairs",
    "exact",
    "Points at the same place",
    "With a tolerance of 0 only points at exactly the same place pair up.",
    xy=[[1, 1], [2, 1], [1, 1]],
    tolerance=0,
)
kern(
    "point_pairs",
    "none",
    "No pairs",
    "Empty arrays out.",
    xy=[[0, 0], [3, 0]],
    tolerance=1,
)

# --- points_near_lines -----------------------------------------------------

kern(
    "points_near_lines",
    "one-line",
    "Points beside a line",
    "Point 0 is within tolerance of the line; its nearest place is half way along the first segment. "
    "Point 1 is too far away.",
    xy=[[1, 0.5], [1, 3]],
    coords=[[0, 0], [2, 0], [2, 2]],
    offsets=[0, 3],
    tolerance=1,
)
kern(
    "points_near_lines",
    "two-lines",
    "A point near two lines",
    "Every line within tolerance is reported, sorted by line and not by distance.",
    xy=[[1, 0.75]],
    coords=[[0, 0], [2, 0], [0, 1], [2, 1]],
    offsets=[0, 2, 4],
    tolerance=1,
)
kern(
    "points_near_lines",
    "beyond-the-end",
    "A point beyond the end of a line",
    "The nearest place is the end of the line itself. It is given as the last vertex of the line with "
    "fraction 0, although no segment starts there.",
    xy=[[3, 0]],
    coords=[[0, 0], [2, 0]],
    offsets=[0, 2],
    tolerance=1,
)

# --- nearest_lines ---------------------------------------------------------

kern(
    "nearest_lines",
    "nearest",
    "The nearest line to each point",
    "One answer for each point, however far away the line is.",
    xy=[[1, 0.25], [1, 5]],
    coords=[[0, 0], [2, 0], [0, 1], [2, 1]],
    offsets=[0, 2, 4],
)
kern(
    "nearest_lines",
    "max-distance",
    "Within a distance",
    "A point with no line within max_distance is left out.",
    xy=[[1, 0.25], [1, 5]],
    coords=[[0, 0], [2, 0], [0, 1], [2, 1]],
    offsets=[0, 2, 4],
    max_distance=1,
)
kern(
    "nearest_lines",
    "skip-own-lines",
    "Passing over a node's own lines",
    "The point is node 1, an end of line 0. With node, src and dst given, line 0 is passed over and the "
    "nearest other line is found.",
    xy=[[2, 0]],
    coords=[[0, 0], [2, 0], [0, 1], [4, 1]],
    offsets=[0, 2, 4],
    node=[1],
    src=[0, 2],
    dst=[1, 3],
)

# --- nearest_points --------------------------------------------------------

kern(
    "nearest_points",
    "nearest",
    "The nearest target to each point",
    "The position of the nearest target, however far away.",
    xy=[[0, 0], [5, 0]],
    targets=[[1, 0], [3, 0], [9, 0]],
)
kern(
    "nearest_points",
    "max-distance",
    "Within a distance",
    "A point with no target within max_distance gets -1. A target exactly at max_distance counts.",
    xy=[[0, 0], [5, 0]],
    targets=[[1, 0], [9, 0]],
    max_distance=1,
)
kern(
    "nearest_points",
    "tie",
    "Two targets equally near",
    "The earliest is chosen.",
    xy=[[1, 0]],
    targets=[[2, 0], [0, 0], [1, 1]],
)


# ---------------------------------------------------------------------------


def _networks(case: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = case["input"]
    if case["operation"] in run.CREATION:
        return []
    return list(data["networks"].values()) if "networks" in data else [data]


def build(key: str, case: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in the expected result of a case by running it"""
    import snkit

    case = dict(case)
    if "function" in case:
        case["expected"] = tidy(run.run_kernel_case(case))
        return case
    for network in _networks(case):
        problems = snkit.validate(run.network_from_json(network))
        assert not problems, f"{key}: input is not a valid network: {problems}"
    wants_error = bool(case["expected"].get("error"))
    actual = run.run_operation_case(case)
    if wants_error:
        assert actual.get("error"), f"{key}: expected an error"
        return case
    assert not actual.get("error"), f"{key}: {actual.get('message')}"
    case["expected"] = tidy(actual)
    if "nodes" in actual:
        problems = snkit.validate(run.network_from_json(actual))
        assert not problems, f"{key}: result is not a valid network: {problems}"
    return case


def main() -> None:
    written = set()
    for key, case in CASES.items():
        path = run.ROOT / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(build(key, case)) + "\n", encoding="utf-8")
        written.add(path)
    for tier in run.TIERS:
        for path in (run.ROOT / tier).glob("*/*.json"):
            if path not in written:
                path.unlink()
        for folder in (run.ROOT / tier).iterdir():
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
    print(f"wrote {len(written)} cases")


if __name__ == "__main__":
    main()
