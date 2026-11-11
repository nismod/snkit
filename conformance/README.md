# Conformance cases

Small cases that pin down what each operation of snkit does, as data. Each case is one JSON
file: an input, some parameters and the expected result. They are not Python, so an
implementation or binding in any language can run the same cases, and they are small enough
to check by eye. They are drawn, one figure a case, in the documentation page
`docs/source/examples.md`.

There are two tiers:

- `operations/<operation>/<case>.json` - the public operations, on networks given as tables
  of nodes and edges;
- `kernel/<function>/<case>.json` - the functions of the array kernel
  (`src/snkit/_kernel.py`), on plain arrays. These are for bindings to the kernel from other
  languages.

| File | Does |
| --- | --- |
| `run.py` | Loads the cases, runs them against the Python package and compares. `python conformance/run.py` runs them all. |
| `generate.py` | Writes every case file from definitions in Python. |
| `../tests/test_conformance.py` | Runs every case as a test. |
| `../docs/make_examples.py` | Draws the figures and writes the documentation page. |

## The files

Every file is UTF-8 JSON with keys sorted and an indent of two spaces. Two things are kept
on one line each so that a file reads as tables: a row of a table (a node, an edge, a match,
a location) and an array of numbers or coordinates.

All cases have:

| Key | Meaning |
| --- | --- |
| `title` | A short name for the case. |
| `note` | A sentence or two on what it shows. |
| `input` | What the operation or function is given. |
| `expected` | What it must return. |

## Operation cases

```json
{
  "operation": "split_edges_at_crossings",
  "title": "Two edges that cross",
  "note": "A node is made at the crossing and both edges are split there. All four pieces get new ids.",
  "parameters": {},
  "input": {"nodes": [...], "edges": [...]},
  "expected": {"nodes": [...], "edges": [...]}
}
```

`operation` is the name of a public function of snkit. `parameters` are its keyword
arguments, as JSON values. An argument left out takes its default.

### Networks

A network is `{"nodes": [...], "edges": [...]}`.

- A node is `{"id": 0, "geometry": "POINT (0 0)"}`.
- An edge is `{"id": 0, "from_id": 0, "to_id": 1, "geometry": "LINESTRING (0 0, 1 0)"}`.

`id`, `from_id` and `to_id` are non-negative integers. `geometry` is WKT. Every other key is
an attribute of the feature; its value may be a number, a string, a boolean, null, or (in
results of the `list` rule for merged attributes) a list. A key that is absent from a row is
the same as a null value. Coordinates have no CRS and are planar.

Rows are in table order, and order matters: results are deterministic, so the expected
nodes and edges are listed in the order the operation must return them.

### Input, by kind of operation

| Operations | `input` |
| --- | --- |
| `from_edges` | `{"lines": [...]}` |
| `from_nodes_and_edges` | `{"points": [...], "lines": [...]}` |
| `from_topology` | `{"nodes": [...], "edges": [...]}`: tables that are not yet a network, with ids of any type |
| `combine`, `stitch` | `{"networks": {name: network, ...}}` |
| `union`, `intersection`, `difference` | `{"networks": {"a": network, "b": network}}` |
| everything else | a network |

Lines and points for the creation functions are rows of `geometry` and attributes, such as
`{"geometry": "LINESTRING (0 0, 1 0)", "name": "A1"}`. Here a geometry may also be a
`MULTILINESTRING`, have Z coordinates, be empty, or be null, since dealing with those is
part of what creation does. An `id` key in these rows is an ordinary column, which creation
may or may not use as ids.

Where there are several networks they are taken in order of their names, sorted (which is
the order they have in the file). For `combine` and `stitch` the networks are passed by
name, so the names appear in the `source` column of the result. For the set operations the
first argument is `a` and the second is `b`.

### Parameters that are not plain values

| Parameter | Of | Written as |
| --- | --- | --- |
| `locations` | `split_edges` | A list of rows, `{"edge": 0, "measure": 1.5}` or `{"edge": 0, "measure": 1.5, "node": 3}`: the id of the edge, the distance along it, and optionally the id of an existing node to put at the cut. |
| `keep` | `merge_edges` | A list of booleans, one for each node in table order. |
| `nodes` | `link_nodes_to_edges`, `match_nodes_to_edges` | A list of booleans, one for each node in table order. |
| `agg` | `merge_nodes`, `merge_edges` | An object from column name to the name of a rule: `first`, `sum`, `min`, `max`, `mean`, `list`. |
| `by`, `extensive` | several | A list of column names. |

A `condition` is a function of the match table and cannot be written in JSON, so no case
uses one, and neither is a function given as an `agg` rule. Those are tested in Python
only (`tests/test_api.py`). `return_lineage` is never among the parameters: see below.

### Expected result

| Operations | `expected` |
| --- | --- |
| `match_nodes`, `match_nodes_to_edges`, `find_crossings`, `match_edges` | `{"matches": [...]}`: the rows of the match table, in order, each an object from column name to value |
| all others | a network, `{"nodes": [...], "edges": [...]}` |
| any, where the input must be refused | `{"error": true}` |

Attributes of the result are part of what is expected: a new feature has its attributes
null, pieces of a split edge copy them, and so on.

**Lineage.** Where `expected` also has a `lineage` key, the operation is to be run asking
for lineage (`return_lineage=True` in Python), and must give these pairs:

```json
"lineage": {
  "nodes": [[0, 0], [1, 1], [1, 2], [3, 3]],
  "edges": [[0, 0], [1, 1]]
}
```

Each pair is `[id, parent_id]`: a feature of the result and a feature of the input it came
from. The pairs are sorted, by id and then parent. A feature that is entirely new has no
pair.

**Errors.** `{"error": true}` means the operation must refuse the input, in whatever way
the language reports an error. The message is not part of the case.

## Kernel cases

```json
{
  "function": "line_measures",
  "title": "A line with a corner",
  "note": "...",
  "input": {"coords": [[0, 0], [3, 0], [3, 4]], "offsets": [0, 3]},
  "expected": {"seglen": [3.0, 4.0, 0.0], "measure": [0.0, 3.0, 7.0], "length": [7.0]}
}
```

`input` gives the arguments by name, as in `src/snkit/_kernel.py`; an argument left out
takes its default. `expected` gives the outputs by the names below. Everything is a
number, a boolean or an array of them. Coordinates are arrays of `[x, y]` pairs. Positions
(of nodes, edges, lines, points and vertices) count from 0; a vertex position counts along
the whole coordinate array, not within its line.

A set of lines is two arrays: `coords`, the vertices of all lines one after another, and
`offsets`, with one more entry than there are lines, so that line `i` has the vertices
`coords[offsets[i]]` up to but not including `coords[offsets[i + 1]]`.

| Function | Arguments | Outputs, in order |
| --- | --- | --- |
| `components` | `n`, `a`, `b` | `labels` |
| `group_index` | `labels` | `group`, `is_first` |
| `line_measures` | `coords`, `offsets` | `seglen`, `measure`, `length` |
| `locate` | `coords`, `offsets`, `seglen`, `measure`, `line`, `at` | `vertex`, `frac`, `xy` |
| `sync_ends` | `coords`, `offsets`, `xy`, `src`, `dst` | `coords` |
| `extend_ends` | `coords`, `offsets`, `xy`, `src`, `dst` | `coords`, `offsets` |
| `split` | `coords`, `offsets`, `src`, `dst`, `cut_edge`, `cut_seg`, `cut_xy`, `cut_node` | `coords`, `offsets`, `src`, `dst`, `parent` |
| `segment_crossings` | `coords`, `offsets`, `end_to_end` (default false) | `seg_a`, `seg_b`, `frac_a`, `frac_b`, `xy` |
| `point_pairs` | `xy`, `tolerance` | `a`, `b` |
| `points_near_lines` | `xy`, `coords`, `offsets`, `tolerance` | `point`, `line`, `vertex`, `frac`, `xy`, `distance` |
| `nearest_lines` | `xy`, `coords`, `offsets`, `max_distance` (default none), `node`, `src`, `dst` (default none) | `point`, `line`, `vertex`, `frac`, `xy`, `distance` |
| `nearest_points` | `xy`, `targets`, `max_distance` (default none) | `nearest` |

What each output means is in the docstrings of `src/snkit/_kernel.py`. The functions of
`snkit._native` that read Arrow streams have no cases here.

## Comparing a result with what is expected

- Structure must be the same: the same rows in the same order, arrays of the same length.
- Integers (ids, positions, counts), strings and booleans must be equal.
- Other numbers must be within `1e-9` of each other. Expected values are written rounded to
  12 decimal places.
- Geometry is compared as numbers, not as text: the same kind of geometry, the same number
  of vertices, each coordinate within `1e-9`. Do not compare WKT strings.
- Null, NaN and an absent key are all the same thing, and equal each other.
- An expected error is met by any error.

`run.compare(actual, expected)` does this and returns a list of differences.

## Running and adding cases

```sh
python conformance/run.py            # run every case, list failures
python -m pytest tests/test_conformance.py
python conformance/generate.py       # rewrite every case file
python docs/make_examples.py         # redraw the figures and the documentation page
```

Cases are defined in `generate.py`: an input written out by hand, parameters, a title and
a note. The script fills in `expected` by running snkit and writes the file. Running it
again reproduces the files byte for byte, and a test checks that.

The expected result of every case here has been checked by reasoning about the geometry,
not just accepted from the code. Keep to that when adding one: make the case
small, with round coordinates, run the script, then read the file and check it. If the
result is not what the design document (`docs/source/design.md`) leads you to expect, that
is a finding to report, not a case to add.
