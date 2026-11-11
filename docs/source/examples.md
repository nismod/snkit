# Examples

Every operation, on networks small enough to check by eye. Each example is one of the
conformance cases in the `conformance` directory of the repository: a data file giving an
input, parameters and the expected result, which the tests run. The figures and this page
are drawn from those files by `docs/make_examples.py`, so they cannot drift apart.

How to read a figure:

- The input is on the left and the expected result on the right, at the same scale. The
  call is written underneath.
- A dot is a node, with its id beside it. A ring is a node that the operation created.
- A line is an edge, with its id in a box and an arrow showing its direction, from
  `from_id` to `to_id`. Each edge in a panel has its own colour, so the pieces of a split
  edge can be told apart. Colours do not carry over from input to result: follow the ids.
  An edge that lies along another is dashed, so that both show.
- Attributes are not drawn. Where a case has them, they are in tables under the figure.

## Creating a network

From lines, or points and lines, to nodes and edges that refer to each other.

### `from_edges`

#### Three lines that meet

A node is made at each distinct end point, numbered in order of first appearance. Lines whose ends are at exactly the same place share a node.

![from_edges: Three lines that meet](_static/examples/from_edges.three-lines.svg)

Case file: `conformance/operations/from_edges/three-lines.json`

#### Ends that nearly meet

Without a tolerance, ends are shared only if they are exactly equal, so these two lines are not connected.

![from_edges: Ends that nearly meet](_static/examples/from_edges.near-ends-stay-apart.svg)

Case file: `conformance/operations/from_edges/near-ends-stay-apart.json`

#### Ends that nearly meet, with a tolerance

Ends within the tolerance become one node at their centroid, which keeps the id of the first. The same as merge_nodes afterwards.

![from_edges: Ends that nearly meet, with a tolerance](_static/examples/from_edges.tolerance.svg)

Case file: `conformance/operations/from_edges/tolerance.json`

#### A line in two parts

A MultiLineString becomes one edge for each part, in place and in order. Each part copies the attributes.

![from_edges: A line in two parts](_static/examples/from_edges.multilinestring.svg)

Input lines:

| row | name |
| --- | --- |
| 0 | A1 |
| 1 | B2 |

Expected edges:

| id | name |
| --- | --- |
| 0 | A1 |
| 1 | A1 |
| 2 | B2 |

Case file: `conformance/operations/from_edges/multilinestring.json`

#### Ids supplied as integers

A column named id that holds unique non-negative integers is used as the edge ids.

![from_edges: Ids supplied as integers](_static/examples/from_edges.integer-ids.svg)

Case file: `conformance/operations/from_edges/integer-ids.json`

#### Ids supplied as text

Ids that are not non-negative integers are kept as an attribute, id_original, and integer ids are generated.

![from_edges: Ids supplied as text](_static/examples/from_edges.text-ids.svg)

Expected edges:

| id | id_original |
| --- | --- |
| 0 | a |
| 1 | b |

Case file: `conformance/operations/from_edges/text-ids.json`

#### Ids from a named column

edge_id names the column to use as ids. It is used directly because it holds unique non-negative integers.

![from_edges: Ids from a named column](_static/examples/from_edges.id-column.svg)

Input lines:

| row | code |
| --- | --- |
| 0 | 5 |
| 1 | 3 |

Case file: `conformance/operations/from_edges/id-column.json`

#### Unusable geometries, dropped

A line of no length, an empty line and a missing geometry cannot be edges. With invalid="drop" they are left out; the edges that remain are numbered from 0.

![from_edges: Unusable geometries, dropped](_static/examples/from_edges.invalid-dropped.svg)

Input lines:

| row | name |
| --- | --- |
| 0 | good |
| 1 | no length |
| 2 | empty |
| 3 | missing |
| 4 | also good |

Expected edges:

| id | name |
| --- | --- |
| 0 | good |
| 1 | also good |

Case file: `conformance/operations/from_edges/invalid-dropped.json`

#### Unusable geometries, refused

By default a geometry that cannot be an edge is an error.

![from_edges: Unusable geometries, refused](_static/examples/from_edges.invalid-refused.svg)

Case file: `conformance/operations/from_edges/invalid-refused.json`

#### A line that ends where it starts

A closed line becomes a self-loop: one node, and an edge from it to itself.

![from_edges: A line that ends where it starts](_static/examples/from_edges.closed-line.svg)

Case file: `conformance/operations/from_edges/closed-line.json`

#### Lines with Z coordinates

Z coordinates are dropped.

![from_edges: Lines with Z coordinates](_static/examples/from_edges.z-dropped.svg)

Case file: `conformance/operations/from_edges/z-dropped.json`

#### No lines

No lines give an empty network.

![from_edges: No lines](_static/examples/from_edges.empty.svg)

Case file: `conformance/operations/from_edges/empty.json`

### `from_nodes_and_edges`

#### Line ends attached to nearby nodes

Each line end is attached to the nearest node within the tolerance and moved exactly onto it: nodes are anchors. An end with no node in reach gets a new node.

![from_nodes_and_edges: Line ends attached to nearby nodes](_static/examples/from_nodes_and_edges.attach-within-tolerance.svg)

Input points:

| row | name |
| --- | --- |
| 0 | A |
| 1 | B |

Expected nodes:

| id | name |
| --- | --- |
| 0 | A |
| 1 | B |
| 2 |  |

Case file: `conformance/operations/from_nodes_and_edges/attach-within-tolerance.json`

#### A node out of reach

A node further than the tolerance from every line end is kept, unattached. Both ends get new nodes.

![from_nodes_and_edges: A node out of reach](_static/examples/from_nodes_and_edges.far-node-left-alone.svg)

Case file: `conformance/operations/from_nodes_and_edges/far-node-left-alone.json`

#### Two nodes in reach of one end

An end with more than one node in reach is attached to the nearest.

![from_nodes_and_edges: Two nodes in reach of one end](_static/examples/from_nodes_and_edges.nearest-node.svg)

Case file: `conformance/operations/from_nodes_and_edges/nearest-node.json`

#### No tolerance

With no tolerance an end is attached only to a node at exactly the same place.

![from_nodes_and_edges: No tolerance](_static/examples/from_nodes_and_edges.exact.svg)

Case file: `conformance/operations/from_nodes_and_edges/exact.json`

#### Node ids supplied

Integer node ids are kept, and new nodes are numbered above the highest.

![from_nodes_and_edges: Node ids supplied](_static/examples/from_nodes_and_edges.node-ids.svg)

Case file: `conformance/operations/from_nodes_and_edges/node-ids.json`

#### A line shorter than the tolerance

Both ends of the short line are attached to the same node, which leaves it no length. With invalid="drop" it is left out.

![from_nodes_and_edges: A line shorter than the tolerance](_static/examples/from_nodes_and_edges.collapsed-edge-dropped.svg)

Case file: `conformance/operations/from_nodes_and_edges/collapsed-edge-dropped.json`

### `from_topology`

#### Tables that refer to each other by text ids

Ids are converted to integers in order of the nodes table. The originals are kept as id_original, from_id_original and to_id_original.

![from_topology: Tables that refer to each other by text ids](_static/examples/from_topology.text-ids.svg)

Expected nodes:

| id | id_original |
| --- | --- |
| 0 | node_0 |
| 1 | node_1 |

Expected edges:

| id | from_id_original | to_id_original |
| --- | --- | --- |
| 0 | node_0 | node_1 |

Case file: `conformance/operations/from_topology/text-ids.json`

#### Tables that refer to each other by integer ids

Non-negative integer ids are used as they are. Edges have no ids here, so they are numbered from 0.

![from_topology: Tables that refer to each other by integer ids](_static/examples/from_topology.integer-ids.svg)

Case file: `conformance/operations/from_topology/integer-ids.json`

#### An edge end slightly off its node

Each edge end within the tolerance of its node is moved exactly onto it.

![from_topology: An edge end slightly off its node](_static/examples/from_topology.ends-moved-onto-nodes.svg)

Case file: `conformance/operations/from_topology/ends-moved-onto-nodes.json`

#### An edge end far from its node

An edge end further than the tolerance from the node it names is an error.

![from_topology: An edge end far from its node](_static/examples/from_topology.end-too-far.svg)

Case file: `conformance/operations/from_topology/end-too-far.json`

## Matchers

Matchers find things and change nothing. Each figure shows the network with the matches marked, and the table of matches is below it.

### `match_nodes`

#### One pair within tolerance

Nodes 1 and 2 are exactly the tolerance apart, which counts as within it. Each pair is reported once, with the node that comes first in the nodes table as node_a.

![match_nodes: One pair within tolerance](_static/examples/match_nodes.pair.svg)

| node_a | node_b | distance |
| --- | --- | --- |
| 1 | 2 | 0.5 |

Case file: `conformance/operations/match_nodes/pair.json`

#### Three nodes in a row

Neighbours are matched, but the two outer nodes are further apart than the tolerance and are not. Pairs are sorted by node_a, then node_b.

![match_nodes: Three nodes in a row](_static/examples/match_nodes.three-in-a-row.svg)

| node_a | node_b | distance |
| --- | --- | --- |
| 0 | 1 | 0.75 |
| 1 | 2 | 0.75 |

Case file: `conformance/operations/match_nodes/three-in-a-row.json`

#### Two nodes at the same place

With a tolerance of 0 only nodes at exactly the same place match.

![match_nodes: Two nodes at the same place](_static/examples/match_nodes.same-place.svg)

| node_a | node_b | distance |
| --- | --- | --- |
| 0 | 2 | 0 |

Case file: `conformance/operations/match_nodes/same-place.json`

### `match_nodes_to_edges`

#### Nodes are not matched to their own edges, or to the ends of others

Every node here is within tolerance of some edge, but only node 4 is near the middle of an edge it is not an end of. Node 2 is nearest to the very end of edge 1, so it is near a node and not near the edge.

![match_nodes_to_edges: Nodes are not matched to their own edges, or to the ends of others](_static/examples/match_nodes_to_edges.own-edges-and-ends.svg)

| node | edge | measure | x | y | distance |
| --- | --- | --- | --- | --- | --- |
| 4 | 1 | 0.75 | 3 | 0 | 0.25 |

Case file: `conformance/operations/match_nodes_to_edges/own-edges-and-ends.json`

#### Nearest edge to each chosen node

With how="nearest" each node chosen by the nodes mask gets one match, to its nearest edge, however far. Here the nearest place is the end of the edge, which is reported in this mode.

![match_nodes_to_edges: Nearest edge to each chosen node](_static/examples/match_nodes_to_edges.nearest.svg)

| node | edge | measure | x | y | distance |
| --- | --- | --- | --- | --- | --- |
| 4 | 0 | 2 | 2 | 0 | 1.41421 |
| 5 | 1 | 1 | 1 | 3 | 0.5 |

Case file: `conformance/operations/match_nodes_to_edges/nearest.json`

#### Nearest edge, within a distance

With a tolerance as well, a node with no edge that near has no match.

![match_nodes_to_edges: Nearest edge, within a distance](_static/examples/match_nodes_to_edges.nearest-within.svg)

| node | edge | measure | x | y | distance |
| --- | --- | --- | --- | --- | --- |
| 2 | 0 | 1 | 1 | 0 | 0.5 |

Case file: `conformance/operations/match_nodes_to_edges/nearest-within.json`

#### Measure along an edge with a corner

The measure is the distance along the line from its start, round the corner: 2 along the first segment and 1 up the second.

![match_nodes_to_edges: Measure along an edge with a corner](_static/examples/match_nodes_to_edges.measure-along-a-bent-edge.svg)

| node | edge | measure | x | y | distance |
| --- | --- | --- | --- | --- | --- |
| 2 | 0 | 3 | 2 | 1 | 1 |

Case file: `conformance/operations/match_nodes_to_edges/measure-along-a-bent-edge.json`

#### A node near two edges

With how="all" a node is matched to every edge within tolerance, nearest first.

![match_nodes_to_edges: A node near two edges](_static/examples/match_nodes_to_edges.two-edges.svg)

| node | edge | measure | x | y | distance |
| --- | --- | --- | --- | --- | --- |
| 4 | 0 | 1 | 1 | 0 | 0.25 |
| 4 | 1 | 1 | 1 | 1 | 0.75 |

Case file: `conformance/operations/match_nodes_to_edges/two-edges.json`

### `find_crossings`

#### Two edges that cross

One crossing, with the distance along each edge and the place.

![find_crossings: Two edges that cross](_static/examples/find_crossings.cross.svg)

| edge_a | measure_a | edge_b | measure_b | x | y |
| --- | --- | --- | --- | --- | --- |
| 0 | 1 | 1 | 1 | 1 | 0 |

Case file: `conformance/operations/find_crossings/cross.json`

#### An edge that ends on the middle of another

The end of edge 1 lies on edge 0, with no node of edge 0 there. This is reported like a crossing.

![find_crossings: An edge that ends on the middle of another](_static/examples/find_crossings.ends-on-middle.svg)

| edge_a | measure_a | edge_b | measure_b | x | y |
| --- | --- | --- | --- | --- | --- |
| 0 | 1 | 1 | 1 | 1 | 0 |

Case file: `conformance/operations/find_crossings/ends-on-middle.json`

#### Edges that meet at a shared node

Edges that meet at a node they share do not cross.

![find_crossings: Edges that meet at a shared node](_static/examples/find_crossings.shared-node.svg)

No matches.

Case file: `conformance/operations/find_crossings/shared-node.json`

#### An edge that crosses itself

The edge is both sides of the crossing, at two different distances along itself.

![find_crossings: An edge that crosses itself](_static/examples/find_crossings.self-crossing.svg)

| edge_a | measure_a | edge_b | measure_b | x | y |
| --- | --- | --- | --- | --- | --- |
| 0 | 1 | 0 | 5 | 1 | 0 |

Case file: `conformance/operations/find_crossings/self-crossing.json`

#### Three edges through one point

Each pair of edges is reported: three crossings at the same place.

![find_crossings: Three edges through one point](_static/examples/find_crossings.three-through-one-point.svg)

| edge_a | measure_a | edge_b | measure_b | x | y |
| --- | --- | --- | --- | --- | --- |
| 0 | 1.41421 | 1 | 1.41421 | 1 | 1 |
| 0 | 1.41421 | 2 | 1 | 1 | 1 |
| 1 | 1.41421 | 2 | 1 | 1 | 1 |

Case file: `conformance/operations/find_crossings/three-through-one-point.json`

#### Edges that share a stretch of line

Edges that overlap do not cross along the overlap. Only the ends of the shared stretch are reported: where edge 1 starts on edge 0, and where edge 0 ends on edge 1.

![find_crossings: Edges that share a stretch of line](_static/examples/find_crossings.shared-stretch.svg)

| edge_a | measure_a | edge_b | measure_b | x | y |
| --- | --- | --- | --- | --- | --- |
| 0 | 1 | 1 | 0 | 1 | 0 |
| 0 | 2 | 1 | 1 | 2 | 0 |

Case file: `conformance/operations/find_crossings/shared-stretch.json`

#### A crossing at a vertex of both edges

Two edges that touch at a corner of each meet there once.

![find_crossings: A crossing at a vertex of both edges](_static/examples/find_crossings.at-a-vertex.svg)

| edge_a | measure_a | edge_b | measure_b | x | y |
| --- | --- | --- | --- | --- | --- |
| 0 | 1.41421 | 1 | 1.41421 | 1 | 1 |

Case file: `conformance/operations/find_crossings/at-a-vertex.json`

### `match_edges`

#### Two edges that run alongside each other for part of their length

Edge 1 runs 0.1 from edge 0, from 4 to 10 along edge 0 and from 0 to 6 along itself.

![match_edges: Two edges that run alongside each other for part of their length](_static/examples/match_edges.alongside.svg)

| edge_a | start_a | end_a | edge_b | start_b | end_b | reversed | distance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 4 | 10 | 1 | 0 | 6 | false | 0.1 |

Case file: `conformance/operations/match_edges/alongside.json`

#### Edges that run in opposite directions

The same, with edge 1 drawn the other way: its stretch is from 4 to 10 along itself, and reversed is true.

![match_edges: Edges that run in opposite directions](_static/examples/match_edges.reversed.svg)

| edge_a | start_a | end_a | edge_b | start_b | end_b | reversed | distance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 4 | 10 | 1 | 4 | 10 | true | 0.1 |

Case file: `conformance/operations/match_edges/reversed.json`

#### Opposite directions, directed

With directed=true only edges running the same way match, so there is nothing here.

![match_edges: Opposite directions, directed](_static/examples/match_edges.directed.svg)

No matches.

Case file: `conformance/operations/match_edges/directed.json`

#### Edges that only cross

Two edges that cross are within tolerance of each other for a short way around the crossing. That stretch is shorter than min_length (by default twice the tolerance), so it is not reported.

![match_edges: Edges that only cross](_static/examples/match_edges.crossing-only.svg)

No matches.

Case file: `conformance/operations/match_edges/crossing-only.json`

#### Edges that lie on the same line

With a tolerance of 0, only a stretch that both edges share exactly is matched.

![match_edges: Edges that lie on the same line](_static/examples/match_edges.exact-overlap.svg)

| edge_a | start_a | end_a | edge_b | start_b | end_b | reversed | distance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 4 | 10 | 1 | 0 | 6 | false | 0 |

Case file: `conformance/operations/match_edges/exact-overlap.json`

## Nodes close together

Merge them, or keep them and link them.

### `merge_nodes`

#### Two nodes that nearly meet

Nodes 1 and 2 become one node at their centroid, with the id of the first. The ends of both edges move to it.

![merge_nodes: Two nodes that nearly meet](_static/examples/merge_nodes.centroid.svg)

Case file: `conformance/operations/merge_nodes/centroid.json`

#### Merged node at the position of the first

With position="first" the merged node sits where the first of its members was, and only the other moves.

![merge_nodes: Merged node at the position of the first](_static/examples/merge_nodes.position-first.svg)

Case file: `conformance/operations/merge_nodes/position-first.json`

#### Edges extended, not moved

With geometry="extend" each edge keeps its line and gains a vertex to reach the merged node.

![merge_nodes: Edges extended, not moved](_static/examples/merge_nodes.geometry-extend.svg)

Case file: `conformance/operations/merge_nodes/geometry-extend.json`

#### Nodes merge in chains

The nodes at 1, 1.5 and 2 on the y axis are each within tolerance of the next, so all three merge, although the outer two are further apart than the tolerance.

![merge_nodes: Nodes merge in chains](_static/examples/merge_nodes.chain.svg)

Case file: `conformance/operations/merge_nodes/chain.json`

#### A chain wider than max_spread

The same chain would move its outer nodes by 0.5. With max_spread below that, the merge is refused.

![merge_nodes: A chain wider than max_spread](_static/examples/merge_nodes.max-spread.svg)

Case file: `conformance/operations/merge_nodes/max-spread.json`

#### A short edge between merged nodes

Edge 1 joins the two nodes that merge and is no longer than the tolerance, so it is dropped.

![merge_nodes: A short edge between merged nodes](_static/examples/merge_nodes.short-edge-dropped.svg)

Case file: `conformance/operations/merge_nodes/short-edge-dropped.json`

#### A long edge between merged nodes

Edge 0 joins the two nodes that merge but is longer than the tolerance, so it is kept, as a self-loop.

![merge_nodes: A long edge between merged nodes](_static/examples/merge_nodes.long-edge-becomes-loop.svg)

Case file: `conformance/operations/merge_nodes/long-edge-becomes-loop.json`

#### Attributes of merged nodes

By default a merged node keeps a value only where all its members agree: kind is kept, name is null.

![merge_nodes: Attributes of merged nodes](_static/examples/merge_nodes.attributes-agree-or-null.svg)

Input nodes:

| id | kind | name |
| --- | --- | --- |
| 0 | stop | A |
| 1 | stop | B |
| 2 | depot | C |

Expected nodes:

| id | kind | name |
| --- | --- | --- |
| 0 | stop |  |
| 2 | depot | C |

Case file: `conformance/operations/merge_nodes/attributes-agree-or-null.json`

#### Attributes of merged nodes, with rules

agg gives a rule for each column: here the first name, the sum of load, and the list of codes.

![merge_nodes: Attributes of merged nodes, with rules](_static/examples/merge_nodes.attributes-agg.svg)

Input nodes:

| id | code | load | name |
| --- | --- | --- | --- |
| 0 | x | 2 | A |
| 1 | y | 3 | B |
| 2 | z | 5 | C |

Expected nodes:

| id | code | load | name |
| --- | --- | --- | --- |
| 0 | x, y | 5 | A |
| 2 | z | 5 | C |

Case file: `conformance/operations/merge_nodes/attributes-agg.json`

#### An empty network

An empty network gives an empty network.

![merge_nodes: An empty network](_static/examples/merge_nodes.empty.svg)

Case file: `conformance/operations/merge_nodes/empty.json`

### `link_nodes`

#### Two nodes that nearly meet

Both nodes are kept and a straight edge is added between them, from the earlier to the later. The new edge has the next id and null attributes.

![link_nodes: Two nodes that nearly meet](_static/examples/link_nodes.pair.svg)

Input edges:

| id | name |
| --- | --- |
| 0 | west |
| 1 | east |

Expected edges:

| id | name |
| --- | --- |
| 0 | west |
| 1 | east |
| 2 |  |

Case file: `conformance/operations/link_nodes/pair.json`

#### Every pair within tolerance

With how="all" (the default) every pair of nodes within tolerance is linked: all three sides of the triangle.

![link_nodes: Every pair within tolerance](_static/examples/link_nodes.all.svg)

Case file: `conformance/operations/link_nodes/all.json`

#### Each node to its nearest only

With how="nearest" each node is linked to its nearest neighbour within tolerance. Nodes 0 and 1 choose each other and node 2 chooses node 1, so the long side is left out.

![link_nodes: Each node to its nearest only](_static/examples/link_nodes.nearest.svg)

Case file: `conformance/operations/link_nodes/nearest.json`

#### Nodes that already share an edge

Nodes 0 and 1 are within tolerance but already have an edge between them, so no edge is added there. Nodes 1 and 2 are linked.

![link_nodes: Nodes that already share an edge](_static/examples/link_nodes.already-linked.svg)

Case file: `conformance/operations/link_nodes/already-linked.json`

#### Nodes at the same place

Nodes at exactly the same place are not linked: the edge would have no length.

![link_nodes: Nodes at the same place](_static/examples/link_nodes.same-place.svg)

Case file: `conformance/operations/link_nodes/same-place.json`

## Splitting and linking

Operations that cut edges, at places given, at nodes, or where edges cross.

### `split_edges`

#### One cut

The edge is cut 1 along. A node is made at the cut, and both pieces get new ids.

![split_edges: One cut](_static/examples/split_edges.one-cut.svg)

Case file: `conformance/operations/split_edges/one-cut.json`

#### Several cuts on one edge

Cuts need not be given in order. The pieces are in order along the edge and take its place in the edges table; the new nodes are numbered in the order the cuts were given.

![split_edges: Several cuts on one edge](_static/examples/split_edges.several-cuts.svg)

Case file: `conformance/operations/split_edges/several-cuts.json`

#### A cut at an existing node

A location that names a node puts that node at the cut, and the edge bends to pass through it. No node is created.

![split_edges: A cut at an existing node](_static/examples/split_edges.at-a-named-node.svg)

Case file: `conformance/operations/split_edges/at-a-named-node.json`

#### A cut on an edge with a corner

The measure runs along the line: 3 along is 1 up the second segment. A cut exactly at a vertex (2 along) does not repeat the vertex.

![split_edges: A cut on an edge with a corner](_static/examples/split_edges.measure-round-a-corner.svg)

Case file: `conformance/operations/split_edges/measure-round-a-corner.json`

#### A cut close to an end

A cut within the tolerance of an end of the edge is not made, so no very short edge is created.

![split_edges: A cut close to an end](_static/examples/split_edges.tolerance-near-end.svg)

Case file: `conformance/operations/split_edges/tolerance-near-end.json`

#### Attributes of the pieces

Pieces copy the attributes of the edge. A column named in extensive is shared out in proportion to length.

![split_edges: Attributes of the pieces](_static/examples/split_edges.extensive.svg)

Input edges:

| id | cost | name |
| --- | --- | --- |
| 0 | 8 | A1 |

Expected edges:

| id | cost | name |
| --- | --- | --- |
| 1 | 2 | A1 |
| 2 | 6 | A1 |

Case file: `conformance/operations/split_edges/extensive.json`

#### A cut on a self-loop

A loop cut once becomes two edges between its node and the new node.

![split_edges: A cut on a self-loop](_static/examples/split_edges.self-loop.svg)

Case file: `conformance/operations/split_edges/self-loop.json`

### `split_edges_at_nodes`

#### A node close to an edge

The edge is split at the node and bends to pass through it. The node does not move.

![split_edges_at_nodes: A node close to an edge](_static/examples/split_edges_at_nodes.near-node.svg)

Case file: `conformance/operations/split_edges_at_nodes/near-node.json`

#### Moving the node, not the edge

With move="node" the node is moved onto the edge, which keeps its line.

![split_edges_at_nodes: Moving the node, not the edge](_static/examples/split_edges_at_nodes.move-node.svg)

Case file: `conformance/operations/split_edges_at_nodes/move-node.json`

#### A node exactly on an edge

With no tolerance, only a node exactly on the line splits it. Node 3, just off the line, does not.

![split_edges_at_nodes: A node exactly on an edge](_static/examples/split_edges_at_nodes.exact.svg)

Case file: `conformance/operations/split_edges_at_nodes/exact.json`

#### A node exactly on a vertex

The edge is split at its corner. The vertex is not repeated.

![split_edges_at_nodes: A node exactly on a vertex](_static/examples/split_edges_at_nodes.on-a-vertex.svg)

Case file: `conformance/operations/split_edges_at_nodes/on-a-vertex.json`

#### Several nodes along one edge

The edge is cut at each node, and the pieces are in order along it whatever the order of the nodes.

![split_edges_at_nodes: Several nodes along one edge](_static/examples/split_edges_at_nodes.several-nodes.svg)

Case file: `conformance/operations/split_edges_at_nodes/several-nodes.json`

#### A node close to the end of an edge

Node 2 is within tolerance of the edge, but the nearest place on it is its end. That is a node near a node, which is for merge_nodes: the edge is not split.

![split_edges_at_nodes: A node close to the end of an edge](_static/examples/split_edges_at_nodes.near-an-end.svg)

Case file: `conformance/operations/split_edges_at_nodes/near-an-end.json`

#### The end of one edge on the middle of another

Node 2, the start of edge 1, lies on edge 0. Edge 0 is split there, which connects the two.

![split_edges_at_nodes: The end of one edge on the middle of another](_static/examples/split_edges_at_nodes.end-of-another-edge.svg)

Case file: `conformance/operations/split_edges_at_nodes/end-of-another-edge.json`

### `link_nodes_to_edges`

#### A node off the network

The node is projected onto its nearest edge. The edge is split there with a new node, and a new edge joins the node to it. The projected position is shared exactly by all three edges.

![link_nodes_to_edges: A node off the network](_static/examples/link_nodes_to_edges.nearest.svg)

Case file: `conformance/operations/link_nodes_to_edges/nearest.json`

#### Every edge within a distance

With how="all" the node is linked to every edge within max_distance: here to both.

![link_nodes_to_edges: Every edge within a distance](_static/examples/link_nodes_to_edges.all-within.svg)

Case file: `conformance/operations/link_nodes_to_edges/all-within.json`

#### Nearest, but not too far

Node 2 is within max_distance of the edge and is linked. Node 3 is not, and is left alone.

![link_nodes_to_edges: Nearest, but not too far](_static/examples/link_nodes_to_edges.max-distance.svg)

Case file: `conformance/operations/link_nodes_to_edges/max-distance.json`

#### A node beyond the end of an edge

The nearest place on the edge is its end, so the node is linked to the node already there and the edge is not split.

![link_nodes_to_edges: A node beyond the end of an edge](_static/examples/link_nodes_to_edges.beyond-the-end.svg)

Case file: `conformance/operations/link_nodes_to_edges/beyond-the-end.json`

#### A projection close to an end

The node projects onto the edge 0.25 from its end. That is within the tolerance, so the node is linked to the end node and no short edge is made.

![link_nodes_to_edges: A projection close to an end](_static/examples/link_nodes_to_edges.tolerance-near-end.svg)

Case file: `conformance/operations/link_nodes_to_edges/tolerance-near-end.json`

#### Moving the node onto the edge

With link=false the node is moved to the projected position and the edge is split at it. No edge is added.

![link_nodes_to_edges: Moving the node onto the edge](_static/examples/link_nodes_to_edges.no-link.svg)

Case file: `conformance/operations/link_nodes_to_edges/no-link.json`

#### Choosing which nodes to link

By default only nodes with no edges are linked. Here the nodes mask chooses node 3, the loose end of edge 1. It is linked to the nearest edge that it is not already an end of.

![link_nodes_to_edges: Choosing which nodes to link](_static/examples/link_nodes_to_edges.chosen-nodes.svg)

Case file: `conformance/operations/link_nodes_to_edges/chosen-nodes.json`

#### Two nodes that project to the same place

Both nodes project onto the edge at the same place, and share one new node there.

![link_nodes_to_edges: Two nodes that project to the same place](_static/examples/link_nodes_to_edges.shared-projection.svg)

Case file: `conformance/operations/link_nodes_to_edges/shared-projection.json`

#### A node already on the edge

A node exactly on the edge needs no linking edge: the edge is split at the node.

![link_nodes_to_edges: A node already on the edge](_static/examples/link_nodes_to_edges.on-the-edge.svg)

Case file: `conformance/operations/link_nodes_to_edges/on-the-edge.json`

#### Attributes of the pieces and of the link

Pieces of the split edge copy its attributes, with the extensive column shared by length. The linking edge is new and has null attributes.

![link_nodes_to_edges: Attributes of the pieces and of the link](_static/examples/link_nodes_to_edges.extensive.svg)

Input edges:

| id | cost | name |
| --- | --- | --- |
| 0 | 8 | A1 |

Expected edges:

| id | cost | name |
| --- | --- | --- |
| 1 | 2 | A1 |
| 2 | 6 | A1 |
| 3 |  |  |

Case file: `conformance/operations/link_nodes_to_edges/extensive.json`

### `split_edges_at_crossings`

#### Two edges that cross

A node is made at the crossing and both edges are split there. All four pieces get new ids.

![split_edges_at_crossings: Two edges that cross](_static/examples/split_edges_at_crossings.cross.svg)

Case file: `conformance/operations/split_edges_at_crossings/cross.json`

#### An edge that ends on the middle of another

Edge 0 is split at the node where edge 1 ends. No node is created, and edge 1 is unchanged.

![split_edges_at_crossings: An edge that ends on the middle of another](_static/examples/split_edges_at_crossings.ends-on-middle.svg)

Case file: `conformance/operations/split_edges_at_crossings/ends-on-middle.json`

#### A crossing close to an end

Edge 1 crosses edge 0 only 0.25 short of its own end. With a tolerance of 0.5 the crossing uses that end node: edge 0 is split and bent to pass through it, and no short edge is made.

![split_edges_at_crossings: A crossing close to an end](_static/examples/split_edges_at_crossings.tolerance-near-end.svg)

Case file: `conformance/operations/split_edges_at_crossings/tolerance-near-end.json`

#### A crossing close to an end, with no tolerance

The same network with no tolerance: a node is made at the crossing, leaving a short edge beyond it.

![split_edges_at_crossings: A crossing close to an end, with no tolerance](_static/examples/split_edges_at_crossings.no-tolerance-near-end.svg)

Case file: `conformance/operations/split_edges_at_crossings/no-tolerance-near-end.json`

#### Three edges through one point

The three crossings are at the same place and share one new node. Each edge is split in two.

![split_edges_at_crossings: Three edges through one point](_static/examples/split_edges_at_crossings.three-through-one-point.svg)

Case file: `conformance/operations/split_edges_at_crossings/three-through-one-point.json`

#### An edge that crosses itself

The edge is cut twice at the crossing, giving three pieces. The middle piece is a loop.

![split_edges_at_crossings: An edge that crosses itself](_static/examples/split_edges_at_crossings.self-crossing.svg)

Case file: `conformance/operations/split_edges_at_crossings/self-crossing.json`

#### A crossing at a vertex of both edges

Both edges are split at the corner where they touch. The vertex is not repeated.

![split_edges_at_crossings: A crossing at a vertex of both edges](_static/examples/split_edges_at_crossings.at-a-vertex.svg)

Case file: `conformance/operations/split_edges_at_crossings/at-a-vertex.json`

#### Edges that share a stretch of line

Each edge is split where the other ends on it. The shared stretch is left as two edges between the same nodes, which drop_duplicate_edges can then remove.

![split_edges_at_crossings: Edges that share a stretch of line](_static/examples/split_edges_at_crossings.shared-stretch.svg)

Case file: `conformance/operations/split_edges_at_crossings/shared-stretch.json`

#### Several crossings on one edge

Edge 0 is crossed twice and becomes three pieces, in order along it.

![split_edges_at_crossings: Several crossings on one edge](_static/examples/split_edges_at_crossings.several-on-one-edge.svg)

Case file: `conformance/operations/split_edges_at_crossings/several-on-one-edge.json`

#### Attributes of the pieces

Pieces copy the attributes of their edge. A column named in extensive is shared out in proportion to length.

![split_edges_at_crossings: Attributes of the pieces](_static/examples/split_edges_at_crossings.extensive.svg)

Input edges:

| id | cost | name |
| --- | --- | --- |
| 0 | 8 | A1 |
| 1 | 3 | B2 |

Expected edges:

| id | cost | name |
| --- | --- | --- |
| 2 | 2 | A1 |
| 3 | 6 | A1 |
| 4 | 1.5 | B2 |
| 5 | 1.5 | B2 |

Case file: `conformance/operations/split_edges_at_crossings/extensive.json`

#### Edges that meet only at nodes

Edges that share a node, parallel edges between the same nodes and a self-loop do not cross: the network is returned unchanged.

![split_edges_at_crossings: Edges that meet only at nodes](_static/examples/split_edges_at_crossings.nothing-to-split.svg)

Case file: `conformance/operations/split_edges_at_crossings/nothing-to-split.json`

#### A single edge

One straight edge has nothing to cross.

![split_edges_at_crossings: A single edge](_static/examples/split_edges_at_crossings.single-edge.svg)

Case file: `conformance/operations/split_edges_at_crossings/single-edge.json`

#### An empty network

An empty network gives an empty network.

![split_edges_at_crossings: An empty network](_static/examples/split_edges_at_crossings.empty.svg)

Case file: `conformance/operations/split_edges_at_crossings/empty.json`

## Tidying edges

Fewer vertices, fewer edges.

### `simplify_edges`

#### A vertex that hardly matters

The middle vertex is 0.001 off the straight line between the ends, less than the tolerance, so it is removed.

![simplify_edges: A vertex that hardly matters](_static/examples/simplify_edges.nearly-straight.svg)

Case file: `conformance/operations/simplify_edges/nearly-straight.json`

#### A vertex that matters

The corner at (2 1) is further than the tolerance from the simplified line and is kept. The vertex at (1 0.5) lies on the simplified line and is removed. The ends never move.

![simplify_edges: A vertex that matters](_static/examples/simplify_edges.corner-kept.svg)

Case file: `conformance/operations/simplify_edges/corner-kept.json`

#### Simplifying must not create a crossing

Removing the bump from edge 0 would make it cross edge 1, which it goes around. So edge 0 keeps its shape.

![simplify_edges: Simplifying must not create a crossing](_static/examples/simplify_edges.no-new-crossing.svg)

Case file: `conformance/operations/simplify_edges/no-new-crossing.json`

#### A self-loop

A loop is simplified like any other edge, and stays a loop.

![simplify_edges: A self-loop](_static/examples/simplify_edges.self-loop.svg)

Case file: `conformance/operations/simplify_edges/self-loop.json`

### `merge_edges`

#### Two edges through a node of degree 2

The two edges become one, with a new id, and the node between them is removed. Edge 1 ran the other way and is reversed, so the merged edge runs in the direction of the earliest.

![merge_edges: Two edges through a node of degree 2](_static/examples/merge_edges.chain.svg)

Case file: `conformance/operations/merge_edges/chain.json`

#### Chains stop at junctions

Node 2 has three edges and is kept. The two edges of the chain leading to it are merged; the merged edge takes the place of its earliest member in the table.

![merge_edges: Chains stop at junctions](_static/examples/merge_edges.junction.svg)

Case file: `conformance/operations/merge_edges/junction.json`

#### Only where attributes agree

With by=["kind"] edges are merged only where they have the same kind. Node 1 joins two roads and is removed; node 2 joins a road and a track and is kept.

![merge_edges: Only where attributes agree](_static/examples/merge_edges.by.svg)

Input edges:

| id | kind |
| --- | --- |
| 0 | road |
| 1 | road |
| 2 | track |

Expected edges:

| id | kind |
| --- | --- |
| 3 | road |
| 2 | track |

Case file: `conformance/operations/merge_edges/by.json`

#### Keeping chosen nodes

keep is a mask over the nodes table. Node 1 has two edges but is kept, so only the edges through node 2 merge.

![merge_edges: Keeping chosen nodes](_static/examples/merge_edges.keep.svg)

Case file: `conformance/operations/merge_edges/keep.json`

#### Respecting direction

With directed=true edges are merged only through a node with one edge in and one out. Node 1 is such a node. At node 2 both edges arrive, so it is kept.

![merge_edges: Respecting direction](_static/examples/merge_edges.directed.svg)

Case file: `conformance/operations/merge_edges/directed.json`

#### Ignoring direction

The same network without directed: all three edges merge, and the last is reversed.

![merge_edges: Ignoring direction](_static/examples/merge_edges.undirected.svg)

Case file: `conformance/operations/merge_edges/undirected.json`

#### A closed ring

Every node of the ring has two edges. The ring becomes a single self-loop that keeps one node: the start of its earliest edge.

![merge_edges: A closed ring](_static/examples/merge_edges.ring.svg)

Case file: `conformance/operations/merge_edges/ring.json`

#### A self-loop and parallel edges

Node 0 has degree 2, but both ends belong to one edge, the loop, so nothing is merged through it. The two parallel edges are a ring of two edges and become a loop on node 1.

![merge_edges: A self-loop and parallel edges](_static/examples/merge_edges.loops-and-parallel-edges.svg)

Case file: `conformance/operations/merge_edges/loops-and-parallel-edges.json`

#### Attributes of a merged edge

By default a merged edge keeps a value only where all its members agree: kind is kept, name and cost are null.

![merge_edges: Attributes of a merged edge](_static/examples/merge_edges.attributes-agree-or-null.svg)

Input edges:

| id | cost | kind | name |
| --- | --- | --- | --- |
| 0 | 2 | road | A1 |
| 1 | 3 | road | B2 |

Expected edges:

| id | cost | kind | name |
| --- | --- | --- | --- |
| 2 |  | road |  |

Case file: `conformance/operations/merge_edges/attributes-agree-or-null.json`

#### Attributes of a merged edge, with rules

agg gives a rule for each column: here the first name, the sum of cost and the largest speed.

![merge_edges: Attributes of a merged edge, with rules](_static/examples/merge_edges.attributes-agg.svg)

Input edges:

| id | cost | name | speed |
| --- | --- | --- | --- |
| 0 | 2 | A1 | 30 |
| 1 | 3 | B2 | 50 |

Expected edges:

| id | cost | name | speed |
| --- | --- | --- | --- |
| 2 | 5 | A1 | 50 |

Case file: `conformance/operations/merge_edges/attributes-agg.json`

#### A single edge

Nothing to merge: the network is returned unchanged.

![merge_edges: A single edge](_static/examples/merge_edges.single-edge.svg)

Case file: `conformance/operations/merge_edges/single-edge.json`

### `drop_duplicate_edges`

#### The same line drawn twice

Edge 1 joins the same nodes as edge 0 along the same line, in the other direction and with an extra vertex. It duplicates edge 0 and is dropped: the earlier edge is the one kept.

![drop_duplicate_edges: The same line drawn twice](_static/examples/drop_duplicate_edges.same-line.svg)

Case file: `conformance/operations/drop_duplicate_edges/same-line.json`

#### Opposite directions, directed

With directed=true an edge running the other way is not a duplicate. Edge 2 runs the same way as edge 0 and is dropped.

![drop_duplicate_edges: Opposite directions, directed](_static/examples/drop_duplicate_edges.directed.svg)

Case file: `conformance/operations/drop_duplicate_edges/directed.json`

#### Different routes between the same nodes

Edges 0 and 1 join the same nodes but by different lines, so both are kept.

![drop_duplicate_edges: Different routes between the same nodes](_static/examples/drop_duplicate_edges.parallel-edges-kept.svg)

Case file: `conformance/operations/drop_duplicate_edges/parallel-edges-kept.json`

#### Nearly the same line

Edge 1 strays 0.25 from edge 0, within the tolerance, and is dropped. Edge 2 strays 1 and is kept.

![drop_duplicate_edges: Nearly the same line](_static/examples/drop_duplicate_edges.tolerance.svg)

Case file: `conformance/operations/drop_duplicate_edges/tolerance.json`

#### The same loop drawn twice

Two loops on one node along the same line, drawn in opposite directions, are duplicates.

![drop_duplicate_edges: The same loop drawn twice](_static/examples/drop_duplicate_edges.self-loops.svg)

Case file: `conformance/operations/drop_duplicate_edges/self-loops.json`

## Connected parts

### `label_components`

#### Two connected parts and an isolated node

Nodes and edges get a component column. Parts are numbered from 0 in order of their first node.

![label_components: Two connected parts and an isolated node](_static/examples/label_components.two-parts.svg)

Expected nodes:

| id | component |
| --- | --- |
| 0 | 0 |
| 1 | 0 |
| 2 | 0 |
| 3 | 1 |
| 4 | 1 |
| 5 | 2 |

Expected edges:

| id | component |
| --- | --- |
| 0 | 0 |
| 1 | 0 |
| 2 | 1 |

Case file: `conformance/operations/label_components/two-parts.json`

#### Naming the column

column sets the name of the column added. Edges that cross without a node are not connected.

![label_components: Naming the column](_static/examples/label_components.column.svg)

Expected nodes:

| id | part |
| --- | --- |
| 0 | 0 |
| 1 | 0 |
| 2 | 1 |
| 3 | 1 |

Expected edges:

| id | part |
| --- | --- |
| 0 | 0 |
| 1 | 1 |

Case file: `conformance/operations/label_components/column.json`

#### An empty network

An empty network gives an empty network.

![label_components: An empty network](_static/examples/label_components.empty.svg)

Case file: `conformance/operations/label_components/empty.json`

## Several networks

Each input network has a panel of its own. Edges are matched between networks, never within one.

### `combine`

#### Two networks side by side

The networks are placed in one table, in order, without being connected, even where they touch. The first keeps its ids; ids of the second are shifted to follow on. A source column names the network each feature came from.

![combine: Two networks side by side](_static/examples/combine.two-networks.svg)

Expected nodes:

| id | source |
| --- | --- |
| 0 | rail |
| 1 | rail |
| 2 | road |
| 3 | road |
| 4 | road |

Expected edges:

| id | source |
| --- | --- |
| 0 | rail |
| 1 | road |
| 2 | road |

Case file: `conformance/operations/combine/two-networks.json`

#### Naming the source column, and attributes

column names the column added. An attribute that only one network has is null for the other.

![combine: Naming the source column, and attributes](_static/examples/combine.column.svg)

Input `a` edges:

| id | lanes |
| --- | --- |
| 0 | 2 |

Input `b` edges:

| id | gauge |
| --- | --- |
| 0 | narrow |

Expected nodes:

| id | network |
| --- | --- |
| 0 | a |
| 1 | a |
| 2 | b |
| 3 | b |

Expected edges:

| id | gauge | lanes | network |
| --- | --- | --- | --- |
| 0 |  | 2 | a |
| 1 | narrow |  | b |

Case file: `conformance/operations/combine/column.json`

#### No source column

With column=null no column is added. Ids follow on from the highest id before, not from the count.

![combine: No source column](_static/examples/combine.no-column.svg)

Case file: `conformance/operations/combine/no-column.json`

### `stitch`

#### Two networks that share a node on the cut

The node at (1 0) is in both networks and becomes one node, with the id it has in the first. Other ids are as for combine.

![stitch: Two networks that share a node on the cut](_static/examples/stitch.shared-node.svg)

Expected nodes:

| id | source |
| --- | --- |
| 0 | a_west |
| 1 | a_west |
| 3 | b_east |

Expected edges:

| id | source |
| --- | --- |
| 0 | a_west |
| 1 | b_east |

Case file: `conformance/operations/stitch/shared-node.json`

#### Nodes that nearly meet on the cut

With a tolerance, nodes of different networks that close are one node. It takes the position it has in the first network, and the edge of the second moves to it.

![stitch: Nodes that nearly meet on the cut](_static/examples/stitch.tolerance.svg)

Expected nodes:

| id | source |
| --- | --- |
| 0 | a_west |
| 1 | a_west |
| 3 | b_east |

Expected edges:

| id | source |
| --- | --- |
| 0 | a_west |
| 1 | b_east |

Case file: `conformance/operations/stitch/tolerance.json`

#### Close nodes within one network

Only nodes of different networks are joined. The two nodes of the first network are within tolerance of each other but stay apart.

![stitch: Close nodes within one network](_static/examples/stitch.not-within-one-network.svg)

Expected nodes:

| id | source |
| --- | --- |
| 0 | a_west |
| 1 | a_west |
| 2 | b_east |
| 3 | b_east |

Expected edges:

| id | source |
| --- | --- |
| 0 | a_west |
| 1 | b_east |

Case file: `conformance/operations/stitch/not-within-one-network.json`

#### Matching nodes by id

With on="id" nodes with the same id in different networks are the same node, wherever they are. Node 1 of the second network is node 1 of the first, and its edge moves to the first's position.

![stitch: Matching nodes by id](_static/examples/stitch.on-id.svg)

Expected nodes:

| id | source |
| --- | --- |
| 0 | a_west |
| 1 | a_west |
| 9 | b_east |

Expected edges:

| id | source |
| --- | --- |
| 0 | a_west |
| 1 | b_east |

Case file: `conformance/operations/stitch/on-id.json`

#### Matching nodes by a column

on names a column: nodes of different networks with the same value in it are the same node. Nodes with a null value are never matched.

![stitch: Matching nodes by a column](_static/examples/stitch.on-column.svg)

Input `a_west` nodes:

| id | code |
| --- | --- |
| 0 |  |
| 1 | X |

Input `b_east` nodes:

| id | code |
| --- | --- |
| 0 | X |
| 1 |  |

Expected nodes:

| id | code |
| --- | --- |
| 0 |  |
| 1 | X |
| 3 |  |

Case file: `conformance/operations/stitch/on-column.json`

### `union`

#### Two networks with an edge in common

The edge from (1 0) to (2 0) is in both and is kept once, as a's. b's other edge is added, with ids shifted to follow a's.

![union: Two networks with an edge in common](_static/examples/union.shared-edge.svg)

Case file: `conformance/operations/union/shared-edge.json`

#### Nearly the same edge

With a tolerance, b's nodes within reach of a's are the same nodes, at a's positions, and b's first edge is the same as a's second. b's remaining edge is moved to start at a's node.

![union: Nearly the same edge](_static/examples/union.tolerance.svg)

Case file: `conformance/operations/union/tolerance.json`

#### Nearly the same edge, with no tolerance

With no tolerance nothing matches, and the union is both networks side by side.

![union: Nearly the same edge, with no tolerance](_static/examples/union.no-tolerance.svg)

Case file: `conformance/operations/union/no-tolerance.json`

#### Edges that partly overlap

With split=true each edge is first split where the other starts or stops running alongside it. The shared stretch is kept once with a's geometry; b's remainder is joined to a's end node.

![union: Edges that partly overlap](_static/examples/union.split.svg)

Case file: `conformance/operations/union/split.json`

#### Attributes and isolated nodes

A shared edge keeps a's attributes and direction. An isolated node in both is kept once.

![union: Attributes and isolated nodes](_static/examples/union.attributes-and-isolated-nodes.svg)

Input `a` edges:

| id | name |
| --- | --- |
| 0 | a's |

Input `b` edges:

| id | name |
| --- | --- |
| 0 | b's |

Expected edges:

| id | name |
| --- | --- |
| 0 | a's |

Case file: `conformance/operations/union/attributes-and-isolated-nodes.json`

### `intersection`

#### Two networks with an edge in common

Only a's edge that is also in b is kept, with its end nodes.

![intersection: Two networks with an edge in common](_static/examples/intersection.shared-edge.svg)

Case file: `conformance/operations/intersection/shared-edge.json`

#### Nearly the same edge

With a tolerance, a's second edge matches b's first, and is kept at a's position.

![intersection: Nearly the same edge](_static/examples/intersection.tolerance.svg)

Case file: `conformance/operations/intersection/tolerance.json`

#### Edges that partly overlap

With split=true, the stretch of a that b runs alongside.

![intersection: Edges that partly overlap](_static/examples/intersection.split.svg)

Case file: `conformance/operations/intersection/split.json`

#### Attributes and isolated nodes

The shared edge has a's attributes. Of a's isolated nodes, the one that is also in b is kept.

![intersection: Attributes and isolated nodes](_static/examples/intersection.attributes-and-isolated-nodes.svg)

Input `a` edges:

| id | name |
| --- | --- |
| 0 | a's |

Input `b` edges:

| id | name |
| --- | --- |
| 0 | b's |

Expected edges:

| id | name |
| --- | --- |
| 0 | a's |

Case file: `conformance/operations/intersection/attributes-and-isolated-nodes.json`

#### Nothing in common

Networks that only touch at a node share no edge, and the node is used by an edge of a, so it is not an isolated node in common either: the result is empty.

![intersection: Nothing in common](_static/examples/intersection.nothing-shared.svg)

Case file: `conformance/operations/intersection/nothing-shared.json`

### `difference`

#### Two networks with an edge in common

Only a's edge that is not in b is kept, with its end nodes.

![difference: Two networks with an edge in common](_static/examples/difference.shared-edge.svg)

Case file: `conformance/operations/difference/shared-edge.json`

#### Nearly the same edge

With a tolerance, a's second edge matches b's first and is removed.

![difference: Nearly the same edge](_static/examples/difference.tolerance.svg)

Case file: `conformance/operations/difference/tolerance.json`

#### Edges that partly overlap

With split=true, the stretch of a that b does not run alongside.

![difference: Edges that partly overlap](_static/examples/difference.split.svg)

Case file: `conformance/operations/difference/split.json`

#### Attributes and isolated nodes

a's only edge is in b, so no edge is left. Of a's isolated nodes, the one that is not in b is kept.

![difference: Attributes and isolated nodes](_static/examples/difference.attributes-and-isolated-nodes.svg)

Input `a` edges:

| id | name |
| --- | --- |
| 0 | a's |

Input `b` edges:

| id | name |
| --- | --- |
| 0 | b's |

Case file: `conformance/operations/difference/attributes-and-isolated-nodes.json`

## Kernel cases

A second set of cases, in `conformance/kernel`, pins down the functions of the array kernel
on plain arrays. They have no figures. `conformance/README.md` sets out the format of both
sets.
