# Design: a spatial network operations API

**Status: draft for discussion.** Nothing described here under "proposed" is implemented
yet. This document sets out the concepts, a proposed Python API with small examples, and a
plan for testing, performance and implementation in other languages. It builds on what
`snkit` already does and on the open issues it references (`#NN`).

## 1. The idea in brief

Every operation in scope - cleaning one network or combining several - can be expressed as
two steps:

1. **Match**: find geometric relationships, approximately, within a stated tolerance. The
   result is a plain table of candidates (this node is near that node; this node projects
   onto that edge at this position; these two edges cross here; these two edges run
   alongside each other over these intervals).
2. **Edit**: apply a small set of topological changes, exactly. Split an edge at a position,
   merge a set of nodes, join a chain of edges, add or remove nodes and edges.

The geometry is only consulted to *decide* what to do. Once decided, the edit is made on the
topology, and the geometry is updated to agree with it. The library never has to ask
afterwards "is this point on that line?" - a question floating-point geometry cannot answer
reliably (see section 6).

This gives a small kernel - **four matchers and five edits** - from which the whole
user-facing API is composed. The table between the two steps is ordinary data, so it can be
inspected, filtered by any condition the user likes, and passed across a language boundary.

Operations on two networks need no extra machinery: they are the same matchers run between
networks rather than within one, followed by the same edits.

## 2. Vocabulary and data model

| Term | Meaning |
| --- | --- |
| **node** | A point with an identity. Edges begin and end at nodes. |
| **edge** | A line with an identity, running from one node to another. |
| **vertex** | A coordinate along an edge's line. Interior vertices give the edge its shape and are *not* nodes. |
| **location** | A position on an edge: `(edge, measure)`, where measure is the distance along the line from its start. |
| **tolerance** | A distance, in CRS units, below which two positions may be treated as the same place. |

A `Network` is two tables, as now:

- `nodes`: `id`, point `geometry`, any other attributes
- `edges`: `id`, `from_id`, `to_id`, linestring `geometry`, any other attributes

### States of a dataset

Data arrives in one of three states. Creation functions move it to the third; every other
operation requires the third and preserves it.

| State | What you have | Example source |
| --- | --- | --- |
| **Lines** | Edge geometries only | A roads shapefile |
| **Unlinked** | Node points and edge lines, with no references between them | Substations and power lines from separate layers |
| **Topological** | Edges refer to their end nodes by id, and the geometry agrees | Output of any operation in this API |

### Invariants of a topological network

`validate(network)` checks these and reports each violation; every operation guarantees
them on output.

1. Node ids are unique; edge ids are unique.
2. Each node geometry is a non-empty Point. Each edge geometry is a non-empty LineString
   with at least two vertices (never a MultiLineString).
3. Every `from_id` and `to_id` refers to an existing node.
4. The first vertex of each edge **is exactly** the position of its `from` node and the last
   vertex **is exactly** the position of its `to` node (bit-for-bit, not "within 1e-9").
5. Nodes and edges share one CRS.

Deliberately allowed: self-loops, parallel edges between the same pair of nodes, isolated
nodes, and edges that cross without a node (a bridge over a road is not a junction).

Invariant 4 is the important one. Once it holds, connectivity is read from ids, never
re-derived from coordinates.

### Named properties

Cleaning operations establish further properties. They are not required of every network,
but each is checkable, and each operation documents which it establishes and which it may
break.

| Property | Meaning | Established by |
| --- | --- | --- |
| nodes distinct | No two nodes within tolerance | `merge_nodes` |
| nodes split edges | No node lies within tolerance of the interior of an edge | `split_edges_at_nodes` |
| noded | Edges meet only at nodes | `split_edges_at_crossings` |
| no pseudo-nodes | No node of degree 2 | `merge_edges` |

### Conventions

- **Functions are pure.** They return a new `Network` and never modify their input. (Today
  `round_geometries`, `merge_edges` and `add_component_ids` modify the input in place.)
- **Edges are oriented.** Vertex order runs from `from` to `to`. Whether that orientation
  *means* anything (one-way flow) is the user's business; operations that would lose it take
  a `directed` flag.
- **Nodes are anchors.** When a node and an edge must be made to agree, the edge's line is
  adjusted to pass through the node, not the reverse, unless asked otherwise. Nodes carry
  identity that other datasets may share; vertices do not.
- **Results are deterministic.** Output order and generated ids depend only on the input
  order and parameters, so results can be compared across runs and across implementations.
- **Lineage is always available.** Every operation can return, alongside the network, which
  input features each output feature came from (section 5).

## 3. The kernel

### Matchers

Each returns a table. With one network it matches the network against itself; with two it
matches across them. All take a `tolerance`.

| Matcher | Finds | Table columns |
| --- | --- | --- |
| `match_nodes` | Nodes near other nodes | `node_a`, `node_b`, `distance` |
| `match_nodes_to_edges` | Nodes near edges they are not an end of, or each node's nearest such edge | `node`, `edge`, `measure`, `x`, `y`, `distance` |
| `find_crossings` | Places where two edges cross away from a shared node | `edge_a`, `measure_a`, `edge_b`, `measure_b`, `x`, `y` |
| `match_edges` | Stretches where two edges run within tolerance of each other | `edge_a`, `start_a`, `end_a`, `edge_b`, `start_b`, `end_b`, `reversed`, `distance` |

`x`, `y` is the single computed position that both sides of the match will share. It is
computed once, here, and reused by the edit.

### Edits

| Edit | Does | Notes |
| --- | --- | --- |
| `add_nodes` / `add_edges` | Insert features | New edges name their end nodes by id. |
| `remove_nodes` / `remove_edges` | Delete features | Removing a node removes its edges, or refuses. |
| `split_edges(locations)` | Cut edges at locations, creating a node at each cut, or using a named existing node | All cuts on one edge are made in a single pass. |
| `merge_nodes(groups)` | Replace each group of nodes with one node | Incident edges are re-pointed; zero-length results are dropped. |
| `merge_edges(paths)` | Replace each chain of edges with one edge | Reverses member lines as needed so vertices run in order. |

Two smaller edits complete the set: `move_nodes` (carrying incident edge ends with them) and
`set_edge_geometries` (new shape, same end points), which simplification uses.

### How the user-facing operations decompose

| Operation | Match | Edit | Today in snkit |
| --- | --- | --- | --- |
| `merge_nodes` | nodes ↔ nodes | merge nodes | - (`#11`) |
| `link_nodes` | nodes ↔ nodes | add edges | - (`#8`) |
| `split_edges_at_nodes` | nodes ↔ edges, within tolerance | split edges at existing nodes | `split_edges_at_nodes` |
| `link_nodes_to_edges` | nodes ↔ edges, nearest or within distance | split edges, add edges | `link_nodes_to_nearest_edge`, `link_nodes_to_edges_within` |
| `split_edges_at_crossings` | edge crossings | split both edges at a shared new node | `split_edges_at_intersections` |
| `merge_edges` | (graph walk: chains through degree-2 nodes) | merge edges | `merge_edges` |
| `simplify_edges` | (per-edge) | set edge geometries | - |
| `drop_duplicate_edges` | edges ↔ edges | remove edges | - (`#31`) |
| `union`, `intersection`, `difference` | nodes ↔ nodes, edges ↔ edges across networks | split, merge, remove | - (`#62`) |

Each composite also accepts a `condition`, applied to the match table before editing. That
covers `#58` (only split crossings between edges on the same level), `#19` (only link to an
edge the node does not already touch - this is the matcher's default) and similar requests
without a new function for each.

## 4. Proposed Python API, with examples

Coordinates below are written as WKT. `net(...)` stands for building a small network from
the listed lines.

### 4.1 Creating a network

**From lines.** A node is created at each distinct end point.

```python
network = snkit.from_edges(lines)
```

```text
lines                         nodes              edges
LINESTRING (0 0, 1 0)         node_0 (0 0)       edge_0  node_0 → node_1
LINESTRING (1 0, 2 0)    →    node_1 (1 0)       edge_1  node_1 → node_2
LINESTRING (1 0, 1 1)         node_2 (2 0)       edge_2  node_1 → node_3
                              node_3 (1 1)
```

End points are shared only if exactly equal. To join ends that nearly meet, pass
`tolerance` (equivalent to `merge_nodes` afterwards).

**From unlinked nodes and lines.** Each line end is attached to an existing node within
`tolerance`; ends with no such node get a new one.

```python
network = snkit.from_nodes_and_edges(nodes, lines, tolerance=0.01)
```

```text
nodes               lines                         nodes              edges
A (0 0)             LINESTRING (0 0, 1 0)         A (0 0)            (0 0, 1.001 0)  A → B
B (1.001 0)         LINESTRING (1 0, 2 0)    →    B (1.001 0)        (1.001 0, 2 0)  B → node_0
                                                  node_0 (2 0)
```

The line ends moved to node `B`: nodes are anchors. This replaces `add_endpoints` followed
by `add_topology`, which today attaches each end to the nearest node *however far away it
is*.

MultiLineStrings are split into one edge per part on the way in; empty and zero-length
geometries are rejected or dropped according to an `invalid=` option.

### 4.2 Merging nodes that are close together

```python
network = snkit.merge_nodes(network, tolerance=0.1)
```

```text
before                                    after
n0 (0 0)  n1 (1 0)  n2 (1.05 0)  n3 (2 0)     n0 (0 0)  n1 (1.025 0)  n3 (2 0)
e0 (0 0, 1 0)       n0 → n1               e0 (0 0, 1.025 0)   n0 → n1
e1 (1.05 0, 2 0)    n2 → n3               e1 (1.025 0, 2 0)   n1 → n3
```

Options:

- `position="centroid" | "first"`, or a column giving priority: where the merged node sits.
- `geometry="move" | "extend"`: move each incident edge's end vertex to the merged
  position, or keep the original line intact and add a short final segment to reach it.
- An edge whose two ends merge into the same node and whose length is under tolerance is
  dropped; a longer one is kept as a self-loop.

### 4.3 Linking nodes that are close together

The alternative to merging: keep both nodes and add an edge between them.

```python
network = snkit.link_nodes(network, tolerance=0.1)
```

```text
before                           after
n1 (1 0)   n2 (1.05 0)      →    n1, n2 unchanged, plus edge (1 0, 1.05 0)  n1 → n2
```

Options: `how="all" | "nearest"`; `condition` (for example, only link nodes in different
connected components, or only nodes of degree 1).

### 4.4 Splitting edges at nearby nodes

```python
network = snkit.split_edges_at_nodes(network, tolerance=0.05)
```

```text
before                               after
n0 (0 0)   n1 (2 0)   n2 (1 0.01)    nodes unchanged
e0 (0 0, 2 0)  n0 → n1          →    e0 (0 0, 1 0.01)   n0 → n2
                                     e1 (1 0.01, 2 0)   n2 → n1
```

The line bends by at most `tolerance` to pass through `n2`; `n2` does not move. With
`move="node"` the node is moved onto the line instead.

### 4.5 Projecting nodes onto the network

```python
network = snkit.link_nodes_to_edges(network, how="nearest")          # or
network = snkit.link_nodes_to_edges(network, how="all", max_distance=50)
```

```text
before                           after
n0 (0 0)  n1 (2 0)  p (1 1)      n0, n1, p, plus node_0 (1 0)
e0 (0 0, 2 0)  n0 → n1      →    e0 (0 0, 1 0)   n0 → node_0
                                 e1 (1 0, 2 0)   node_0 → n1
                                 e2 (1 1, 1 0)   p → node_0
```

The projected position `(1 0)` is computed once and written into all three lines, so they
meet exactly. Options: `nodes=` a mask choosing which nodes to project (default: nodes of
degree 0); `condition`; `link=False` to move the node onto the edge and split, without
adding a connecting edge.

### 4.6 Splitting edges where they cross

```python
network = snkit.split_edges_at_crossings(network)
```

```text
before                           after
e0 (0 0, 2 2)                    node_4 (1 1) added
e1 (0 2, 2 0)               →    (0 0, 1 1)  (1 1, 2 2)  (0 2, 1 1)  (1 1, 2 0)
```

Options: `condition` over the crossings table, for example
`lambda x: x.level_a == x.level_b`; `tolerance`, so that a crossing close to an existing
node uses that node rather than creating a tiny edge beside it. Self-crossings of a single
edge are found too, and are split by default.

### 4.7 Simplifying edge geometries

```python
network = snkit.simplify_edges(network, tolerance=0.01)
```

```text
e0 (0 0, 1 0.001, 2 0)   →   e0 (0 0, 2 0)
```

End vertices never move, so topology is untouched. Simplification must not introduce a
crossing that was not there before: a simplified line that would newly cross another is
left at its previous shape.

### 4.8 Merging edges through degree-2 nodes

```python
network = snkit.merge_edges(network, by=["road_class"])
```

```text
before                               after
n0 (0 0)  n1 (1 0)  n2 (2 0)         n0, n2
e0 (0 0, 1 0)  n0 → n1          →    e0 (0 0, 1 0, 2 0)  n0 → n2
e1 (2 0, 1 0)  n2 → n1
```

`e1` was reversed to join the chain. Options: `by` - only merge edges whose values in these
columns agree (`#33`); `keep` - a mask of degree-2 nodes to retain (a substation on a
line); `directed=True` - only merge through a node with one edge in and one out, never
reversing. A closed ring of degree-2 nodes keeps one node.

### 4.9 Two or more networks

**Combine** places networks side by side without connecting them, recording where each
feature came from and making ids unique.

```python
both = snkit.combine({"road": roads, "rail": rail})    # adds a `source` column
```

Every single-network operation then works across sources through `condition`. For example,
to add transfer links between nearby road and rail nodes, and nothing else:

```python
both = snkit.link_nodes(both, tolerance=100, condition=lambda m: m.source_a != m.source_b)
```

**Stitch** is the common case of `#62`: networks that were cut apart (by tile, by country)
and share nodes on the cut.

```python
whole = snkit.stitch([west, east], tolerance=0.001)    # or on="id" to match nodes by id
```

**Set operations** need a rule for when two features are "the same". Either by key
(`on="id"`) or by geometry (`tolerance=`): two nodes match if they are within tolerance, and
two edges match if they run within tolerance of each other between matched ends.

```python
snkit.union(a, b, tolerance=0.5)           # everything, with matched features kept once
snkit.intersection(a, b, tolerance=0.5)    # the parts of a that are also in b
snkit.difference(a, b, tolerance=0.5)      # the parts of a that are not in b
```

Set operations are decided on edges. A node is kept if a kept edge uses it; isolated nodes
follow the same rule as edges.

**Approximate edge matching** is where edges overlap only partly, so they must be split
before they can be compared one-to-one.

```python
matches = snkit.match_edges(a, b, tolerance=0.5)
```

```text
a:  e0 (0 0, 10 0)
b:  f0 (4 0.1, 14 0.1)

matches:  edge_a  start_a  end_a  edge_b  start_b  end_b  reversed  distance
          e0      4        10     f0      0        6      False     0.1
```

`union(a, b, tolerance=0.5, split=True)` then splits both edges at the ends of the matched
stretch, merges the matched nodes, and keeps one copy of the shared middle:

```text
(0 0, 4 0)    (4 0, 10 0)    (10 0, 14 0.1)
 from a        in both        from b
```

With `keep="a"` (the default) the shared stretch takes `a`'s geometry and `b`'s attributes
are joined on with a suffix.

Options on `match_edges`: `min_length` (default twice the tolerance, so that two roads that
merely cross are not reported as overlapping for a short stretch around the crossing);
`max_angle`; `directed`.

This handles the same feature drawn twice at similar detail. It does not attempt harder
conflation - a dual carriageway against a single centreline, or networks at very different
levels of generalisation. Those are left to the user through the match table, and to
related tools such as `neatnet`.

## 5. Attributes, ids and lineage

**Lineage.** Any operation called with `return_lineage=True` also returns two tables:

- nodes: `id`, `parent_id`
- edges: `id`, `parent_id`, `parent_start`, `parent_end`, `reversed`

These are many-to-many: a split gives one parent several children; a merge gives one child
several parents. Lineage is what the kernel actually computes - attribute handling is built
on top of it, and it answers `#20` in general.

**Attributes on split.** Children copy the parent's attributes. Columns named in
`extensive=[...]` (a cost, a count - quantities that belong to the whole edge) are shared
out in proportion to length.

**Attributes on merge.** Per-column rule via `agg={column: rule}`; rules are `first`, `sum`,
`min`, `max`, `mean` (length-weighted for edges), `list`. The default keeps a value only
when all members agree, and otherwise leaves it null - never a silently wrong value.

**Ids.** Existing ids are kept wherever a feature survives unchanged. New features get
generated ids that cannot collide with existing ones. When an edge is split, the first
piece keeps the parent's id only if `keep_ids=True`; by default all pieces get new ids, and
lineage records the parent.

## 6. Robust and approximate geometry

### The problem, measured

The obvious way to connect a point to a line is: project the point onto the line, then
split the line at the projected point. With Shapely 2.2 / GEOS 3.14 on random segments:

- projecting a point onto the interior of a segment and testing whether the result
  intersects the segment: **0 of 2,599** succeed, and `shapely.ops.split` leaves all 2,599
  lines unsplit;
- computing the crossing point of two segments and testing whether it lies on both:
  **0 of 2,267** succeed.

Neither is a bug. The exact answer is usually not representable in floating point, so the
nearest representable point is very slightly off the line. `snkit` currently works around
this by buffering by `1e-9`, re-finding lines near each new point, and inserting a vertex
at the nearest position - then attaching edge ends to whichever node is nearest. It works,
but it is the slowest part of the library and its failure modes are silent.

### The approach

1. **Carry locations, not points.** A matcher reports *which edge* and *where along it*
   (internally: segment index and fraction along that segment). The edit inserts the
   computed coordinate as a vertex into that segment and cuts there. There is nothing to
   look up afterwards, so nothing can fail to be found.
2. **Compute each shared position once.** A crossing point is computed once and the
   identical coordinate is written into both edges and the new node. Invariant 4 then holds
   by construction.
3. **One explicit tolerance, no hidden ones.** `tolerance=0` means exact: only coincident
   coordinates match. There is no built-in `1e-9`.
4. **Snap to what exists before creating something new.** A cut within tolerance of an
   existing node uses that node. Cuts within tolerance of each other on one edge share a
   node. So no operation creates an edge shorter than its tolerance.
5. **Decide with robust tests, construct with ordinary arithmetic.** "Do these segments
   cross?" uses exact orientation predicates, so the decision is consistent whichever way
   round it is asked. The crossing coordinate itself is rounded, which is harmless given
   (2).

### Known hard cases and the stance on each

| Case | Stance |
| --- | --- |
| **Tolerance is not transitive.** A within tolerance of B, and B of C, does not put A within tolerance of C. | `merge_nodes` groups by chains (`A-B-C` all merge) by default: simple and order-independent. It reports the widest group, and `max_spread=` bounds it. |
| **Moving a line can create a new crossing.** Bending an edge to a node, or inserting a rounded crossing point, shifts it very slightly. | The shift is bounded by the tolerance. Cleaning operations are run to a fixed point: applying one twice gives the same result as once, and this is tested. An optional coordinate grid (`precision=`) gives the stronger guarantee of snap-rounding. |
| **Edges that overlap along a stretch** rather than crossing at a point. | Not a crossing. `find_crossings` reports only the ends of the shared stretch; `match_edges` handles the overlap. |
| **Degenerate input**: empty or null geometry, zero-length lines, repeated vertices, multi-part lines, rings. | Dealt with once, at creation, under an explicit option. Afterwards the invariants exclude them. |
| **Geographic coordinates.** A tolerance in degrees is a different distance east-west than north-south. | Operations taking a distance raise on a geographic CRS, with a pointer to `to_crs` and `estimate_utm_crs` (`#18`). Geodesic distance in the kernel is a later option. |
| **Z coordinates.** | Carried through and interpolated at cuts. Matching is 2D; `condition` can compare Z or a level attribute. |

## 7. Testing

- **Worked examples as tests.** Every example in section 4 is a test, and the same examples
  form the user documentation.
- **Shared conformance cases.** Each case is a small file: operation, parameters, input
  nodes and edges as WKT, expected output. They are data, not Python, so every
  implementation in any language runs the same cases. This is the cross-language contract.
- **Property-based tests** over generated networks:
  - invariants hold after every operation;
  - cleaning operations are idempotent;
  - results do not depend on the order of input rows, nor (when undirected) on edge
    direction;
  - splitting and merging conserve total length; `extensive` attributes conserve their sum;
  - `merge_edges` after `split_edges_at_nodes` on a clean network returns the original.
- **Degenerate inputs**, each with a named expected behaviour: empty network, single edge,
  self-loop, parallel edges, ring, self-crossing edge, node exactly on a vertex, crossing
  exactly at an end point, three edges through one point.
- **Benchmarks** tracked over time (`#61`): a synthetic grid and a real extract, at about
  1 thousand, 100 thousand and 1 million edges.

## 8. Performance and other languages

### Why the current code is slow

- Python loops over rows, with a spatial query per row (`add_topology`,
  `link_nodes_to_nearest_edge`, `split_edges_at_intersections`).
- A new GeoDataFrame built per edge when splitting.
- Topology rebuilt from geometry after each step, by nearest-node search.
- Whole-table scans per node: `node_connectivity_degree` and the chain walk in
  `merge_edges` are quadratic.
- `nearest_vertex_idx_on_line` measures the distance to every vertex for every split point.

### The plan

**A kernel over flat arrays.** The kernel sees only:

- node coordinates: one `float64` array, two columns;
- edge ends: two integer arrays indexing into nodes;
- edge geometry: one coordinate array plus an offsets array (the GeoArrow linestring
  layout).

It never sees attributes. Matchers return index arrays; edits return new arrays plus
lineage as index arrays. The host language then moves attributes with a single `take` per
table. This one decision gives:

- every operation as a few bulk passes: index build, bulk query, sort, scatter;
- zero-copy exchange with anything that speaks Arrow (GeoPandas, R `sf`/`geoarrow`,
  DuckDB, JavaScript);
- a narrow interface to reimplement: arrays in, arrays out, no object model.

**Targets.** Every operation runs in `O((n + k) log n)` for `n` features and `k` matches.
No Python-level loop over features. All cuts on an edge made in one pass. Graph steps
(degree, components, chains) use integer arrays, not table scans. A working target: clean a
1-million-edge network in tens of seconds on a laptop.

**Stages.**

1. *Reference implementation in Python*, on the array kernel, using Shapely 2's bulk
   functions (`STRtree.query` with `dwithin`, `line_locate_point`, ragged-array
   conversion) and NumPy. This settles the semantics and should already remove most of the
   slowness listed above.
2. *Conformance cases and benchmarks* written against it.
3. *Native kernel* for whichever operations the benchmarks show need it, behind the same
   array interface. Recommended: Rust, for its Arrow and spatial-index libraries and for
   straightforward bindings to Python (PyO3), R (extendr) and the browser (WebAssembly).
   The alternative from `#77`, building on the GEOS C API, is attractive for noding
   (`GEOSNode`), but GEOS returns noded linework without saying which input each piece came
   from, and lineage is the thing this design depends on.
4. *Other language front ends* are then thin: table in, kernel call, `take`, table out -
   validated by the conformance cases.

**Parallelism** comes after the above, by partitioning space into tiles with a
tolerance-wide overlap, replacing the current `SNKIT_PROCESSES` chunking.

## 9. Migration from the current API

The `Network` class, `read_file`/`to_file`, and the graph converters stay. Existing
functions keep working as thin wrappers with deprecation notices where the name or
behaviour changes:

| Current | Proposed |
| --- | --- |
| `add_endpoints`, `add_ids`, `add_topology` | `from_edges`, `from_nodes_and_edges` |
| `split_multilinestrings`, `round_geometries` | options at creation (`precision=`) |
| `snap_nodes` | `split_edges_at_nodes(move="node")` |
| `split_edges_at_nodes` | same name; now creates topology directly |
| `split_edges_at_intersections` | `split_edges_at_crossings` |
| `link_nodes_to_nearest_edge`, `link_nodes_to_edges_within` | `link_nodes_to_edges(how=...)` |
| `merge_edges` | same name; `by`, `keep`, `directed` |
| `get_connected_components`, `add_component_ids` | unchanged, without requiring networkx |

## 10. Open questions

Each has a recommendation, taken as the working assumption above.

1. **Where does this live?** New modules inside `snkit`, released as 2.0, with the old
   functions as wrappers - rather than a separate package.
2. **Is `tolerance` required?** Yes for operations whose whole purpose is approximate
   (`merge_nodes`, `link_nodes`, `match_edges`); default `0` elsewhere.
3. **Default node position on merge?** Centroid. The alternative, `first`, is
   order-dependent unless a priority column is given.
4. **Column names.** Fixed as `id`, `from_id`, `to_id` rather than configurable per call
   (today `id_col` is honoured in some functions and hard-coded in others).
5. **Id type.** Keep whatever the user supplies; generate strings (`node_12`) for new
   features, as now. Integer ids would be faster but are a visible change.
6. **Directed networks.** A per-call `directed` flag where it matters, rather than a
   property stored on the `Network`.
7. **Kernel language.** Rust, decided only after stage 2 shows what needs it.
8. **Scope of edge matching.** Same-detail overlap only, as in section 4.9; anything harder
   stays outside the library.

## Related work

Names and semantics above were chosen with these in mind:

- **PostGIS Topology** (ISO SQL/MM): a small set of exact topological edits
  (`ST_ModEdgeSplit`, `ST_ModEdgeHeal`, ...) under tolerance-based loading - the closest
  precedent for the match/edit separation.
- **GEOS / JTS**: noding, snap-rounding and precision models.
- **GRASS `v.clean` and `v.net`**: break, snap, remove dangles, merge lines, connect points.
- **pgRouting**: `pgr_nodeNetwork`, `pgr_createTopology`.
- **sfnetworks** (R): subdivision, smoothing of pseudo-nodes, blending points into a
  network.
- **OSMnx**: `simplify_graph`, `consolidate_intersections`.
- **neatnet**, **momepy**, **spaghetti**: street-network simplification and analysis.
