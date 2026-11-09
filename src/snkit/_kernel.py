"""Array kernel for spatial network operations.

Everything here takes and returns plain numpy arrays. There are no tables, no
attributes and no geometry objects.

This module is the reference implementation. The same functions are
implemented in Rust in the ``kernel`` directory of the repository, as the
package ``snkit-kernel``. If that package is installed, the functions listed in
``NATIVE`` are taken from it: they give the same results, faster and in less
memory. Set the environment variable ``SNKIT_KERNEL=python`` to use this module
regardless, or ``SNKIT_KERNEL=native`` to fail if the compiled kernel is
missing. ``snkit._kernel.BACKEND`` says which is in use.

A network is represented by:

- ``xy``: node coordinates, ``float64[n, 2]``
- ``src``, ``dst``: for each edge, the position of its end nodes in ``xy``
- ``coords``, ``offsets``: edge geometries as one coordinate array
  ``float64[k, 2]`` and ``int64[m + 1]`` offsets, so that edge ``e`` has
  vertices ``coords[offsets[e]:offsets[e + 1]]`` (the GeoArrow layout)
"""

from __future__ import annotations

import os
from typing import Any, List, Tuple

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]


def components(n: int, a: IntArray, b: IntArray) -> IntArray:
    """Label connected components of ``n`` items linked by pairs ``(a, b)``.

    Each item is labelled with the lowest position in its component.
    """
    labels = np.arange(n, dtype=np.int64)
    if len(a) == 0:
        return labels
    while True:
        low = np.minimum(labels[a], labels[b])
        new = labels.copy()
        np.minimum.at(new, a, low)
        np.minimum.at(new, b, low)
        new = new[new]
        if np.array_equal(new, labels):
            return labels
        labels = new


def group_index(labels: IntArray) -> Tuple[IntArray, BoolArray]:
    """Turn component labels into consecutive group numbers.

    Returns the group number of each item, and a mask of the first item of
    each group. Groups are numbered in order of their first item.
    """
    is_first = labels == np.arange(len(labels))
    return (np.cumsum(is_first) - 1)[labels], is_first


def vertex_edge(offsets: IntArray) -> IntArray:
    """Edge position of each vertex"""
    return np.repeat(np.arange(len(offsets) - 1), np.diff(offsets))


def segment_lengths(coords: FloatArray, offsets: IntArray) -> FloatArray:
    """Length of the segment starting at each vertex (0 at the last vertex of an edge)"""
    seglen = np.zeros(len(coords))
    if len(coords) > 1:
        delta = coords[1:] - coords[:-1]
        seglen[:-1] = np.hypot(delta[:, 0], delta[:, 1])
    if len(offsets) > 1:
        seglen[offsets[1:] - 1] = 0
    return seglen


def running_length(seglen: FloatArray) -> FloatArray:
    """Total segment length before each vertex, over all edges (non-decreasing)"""
    running = np.zeros(len(seglen))
    if len(seglen) > 1:
        running[1:] = np.cumsum(seglen[:-1])
    return running


def measures(running: FloatArray, offsets: IntArray) -> FloatArray:
    """Distance along its own edge of each vertex"""
    if len(offsets) < 2:
        return running.copy()
    return running - np.repeat(running[offsets[:-1]], np.diff(offsets))


def locate_segment(running: FloatArray, offsets: IntArray, edge: IntArray, measure: FloatArray) -> IntArray:
    """Vertex position at the start of the segment containing each measure"""
    target = running[offsets[edge]] + measure
    seg = np.searchsorted(running, target, side="right") - 1
    return np.clip(seg, offsets[edge], offsets[edge + 1] - 2)


def sync_ends(coords: FloatArray, offsets: IntArray, xy: FloatArray, src: IntArray, dst: IntArray) -> FloatArray:
    """Move the end vertices of each edge exactly onto its end nodes"""
    coords = coords.copy()
    if len(src):
        coords[offsets[:-1]] = xy[src]
        coords[offsets[1:] - 1] = xy[dst]
    return coords


def extend_ends(
    coords: FloatArray, offsets: IntArray, xy: FloatArray, src: IntArray, dst: IntArray
) -> Tuple[FloatArray, IntArray]:
    """Add a vertex at each edge end that is not already exactly on its end node"""
    if len(src) == 0:
        return coords, offsets
    at_start = offsets[:-1]
    at_end = offsets[1:]
    add_start = (coords[at_start] != xy[src]).any(axis=1)
    add_end = (coords[at_end - 1] != xy[dst]).any(axis=1)
    # ends are listed before starts so that, where one edge's end and the next
    # edge's start insert at the same position, they land in the right order
    where = np.concatenate([at_end[add_end], at_start[add_start]])
    values = np.concatenate([xy[dst][add_end], xy[src][add_start]])
    new_coords = np.insert(coords, where, values, axis=0)
    counts = np.diff(offsets) + add_start + add_end
    new_offsets = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
    return new_coords, new_offsets


def split(
    coords: FloatArray,
    offsets: IntArray,
    src: IntArray,
    dst: IntArray,
    cut_edge: IntArray,
    cut_seg: IntArray,
    cut_xy: FloatArray,
    cut_node: IntArray,
) -> Tuple[FloatArray, IntArray, IntArray, IntArray, IntArray]:
    """Cut edges, inserting the coordinate of a node at each cut.

    Cuts must be sorted by edge and then by position along the edge.
    ``cut_seg`` is the vertex position at the start of the segment to cut.

    Returns new ``coords``, ``offsets``, ``src``, ``dst`` and, for each new
    edge, the position of the edge it was cut from. Pieces of an edge are in
    order along it and take its place in the edge order.
    """
    m = len(src)
    k = len(cut_edge)
    insert_at = cut_seg + 1
    # each cut coordinate appears twice: the end of one piece, the start of the next
    new_coords = np.insert(coords, np.repeat(insert_at, 2), np.repeat(cut_xy, 2, axis=0), axis=0)
    first_copy = insert_at + 2 * np.arange(k)
    cuts_before = np.searchsorted(cut_edge, np.arange(m + 1), side="left")
    new_offsets = np.sort(np.concatenate([offsets + 2 * cuts_before, first_copy + 1]))

    counts = np.bincount(cut_edge, minlength=m)
    parent = np.repeat(np.arange(m), 1 + counts)
    new_src = src[parent].copy()
    new_dst = dst[parent].copy()
    piece_before_cut = cut_edge + np.arange(k)
    new_dst[piece_before_cut] = cut_node
    new_src[piece_before_cut + 1] = cut_node

    # a cut that lands on an existing vertex leaves a repeated coordinate: drop it,
    # but only within cut edges and never reducing a piece below two vertices
    repeat = np.zeros(len(new_coords), dtype=bool)
    repeat[1:] = (new_coords[1:] == new_coords[:-1]).all(axis=1)
    repeat[new_offsets[:-1]] = False
    repeat &= counts[parent[vertex_edge(new_offsets)]] > 0
    keep = ~repeat
    piece_size = np.add.reduceat(keep.astype(np.int64), new_offsets[:-1])
    keep[new_offsets[:-1][piece_size < 2] + 1] = True
    piece_size = np.add.reduceat(keep.astype(np.int64), new_offsets[:-1])
    new_coords = new_coords[keep]
    new_offsets = np.concatenate([[0], np.cumsum(piece_size)]).astype(np.int64)
    return new_coords, new_offsets, new_src, new_dst, parent


def _cross(a: FloatArray, b: FloatArray) -> FloatArray:
    return a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]


def segment_events(
    p: FloatArray, p2: FloatArray, q: FloatArray, q2: FloatArray
) -> Tuple[IntArray, FloatArray, FloatArray, FloatArray]:
    """Find where pairs of segments ``p-p2`` and ``q-q2`` meet.

    Returns, for each meeting: the pair it belongs to, the fraction along the
    first segment, the fraction along the second, and the coordinate. A pair
    that crosses gives one meeting. A pair that touches gives one for each end
    of one segment lying on the other, located exactly at that end (fraction
    exactly 0 or 1, coordinate exactly the end's own).

    Decisions use floating-point orientation tests; a native kernel should use
    exact predicates here.
    """
    r = p2 - p
    s = q2 - q
    o1 = _cross(s, p - q)
    o2 = _cross(s, p2 - q)
    o3 = _cross(r, q - p)
    o4 = _cross(r, q2 - p)
    proper = (np.sign(o1) * np.sign(o2) < 0) & (np.sign(o3) * np.sign(o4) < 0)

    idx = np.flatnonzero(proper)
    t = np.clip(o1[idx] / (o1[idx] - o2[idx]), 0, 1)
    u = np.clip(o3[idx] / (o3[idx] - o4[idx]), 0, 1)
    found: List[Tuple[Any, Any, Any, Any]] = [(idx, t, u, p[idx] + t[:, None] * r[idx])]

    def on_segment(point: FloatArray, a: FloatArray, b: FloatArray, orient: FloatArray) -> BoolArray:
        inside = (point >= np.minimum(a, b)).all(axis=1) & (point <= np.maximum(a, b)).all(axis=1)
        return (orient == 0) & inside & ~proper  # type: ignore[no-any-return]

    def fraction(point: FloatArray, a: FloatArray, b: FloatArray, direction: FloatArray) -> FloatArray:
        frac = np.clip(
            ((point - a) * direction).sum(axis=1) / (direction * direction).sum(axis=1),
            0,
            1,
        )
        frac[(point == a).all(axis=1)] = 0
        frac[(point == b).all(axis=1)] = 1
        return frac  # type: ignore[no-any-return]

    for point, own_fraction, hit in (
        (p, 0.0, on_segment(p, q, q2, o1)),
        (p2, 1.0, on_segment(p2, q, q2, o2)),
    ):
        idx = np.flatnonzero(hit)
        other = fraction(point[idx], q[idx], q2[idx], s[idx])
        found.append((idx, np.full(len(idx), own_fraction), other, point[idx]))
    for point, own_fraction, hit in (
        (q, 0.0, on_segment(q, p, p2, o3)),
        (q2, 1.0, on_segment(q2, p, p2, o4)),
    ):
        idx = np.flatnonzero(hit)
        other = fraction(point[idx], p[idx], p2[idx], r[idx])
        found.append((idx, other, np.full(len(idx), own_fraction), point[idx]))

    return (
        np.concatenate([f[0] for f in found]),
        np.concatenate([f[1] for f in found]),
        np.concatenate([f[2] for f in found]),
        np.concatenate([f[3] for f in found]),
    )


def segment_crossings(
    coords: FloatArray, offsets: IntArray, end_to_end: bool = False
) -> Tuple[IntArray, IntArray, FloatArray, FloatArray, FloatArray]:
    """Find every place where two segments of the given lines meet.

    Returns, for each meeting: the two segments (each named by the vertex
    position where it starts, the lower first), the fraction along each, and
    the coordinate. See :func:`segment_events` for what counts as a meeting.
    Segments of zero length are ignored.

    Two kinds of meeting are left out, because on a clean network they are
    nearly all there is to find: the vertex shared by two successive segments
    of one line, and, unless ``end_to_end`` is set, places where two lines
    meet at an end of each.

    Each pair is put into a fixed form (each segment running from its lesser
    end, the lesser segment first) before the meeting is computed, so that the
    coordinate found does not depend on the order of the lines or the
    direction they run.

    This reference implementation borrows its spatial index from Shapely.
    """
    import shapely

    none = np.zeros(0, dtype=np.int64)
    is_start = np.ones(len(coords), dtype=bool)
    if len(offsets) > 1:
        is_start[offsets[1:] - 1] = False
    start = np.flatnonzero(is_start & (segment_lengths(coords, offsets) > 0))
    if len(start) == 0:
        return none, none, np.zeros(0), np.zeros(0), np.zeros((0, 2))
    p, p2 = coords[start], coords[start + 1]
    segments = shapely.linestrings(np.stack([p, p2], axis=1))
    i, j = shapely.STRtree(segments).query(segments, predicate="intersects")
    once = i < j
    i, j = i[once], j[once]
    flip = (p2[:, 0] < p[:, 0]) | ((p2[:, 0] == p[:, 0]) & (p2[:, 1] < p[:, 1]))
    low = np.where(flip[:, None], p2, p)
    high = np.where(flip[:, None], p, p2)
    key = np.concatenate([low, high], axis=1)
    swap = np.zeros(len(i), dtype=bool)
    undecided = np.ones(len(i), dtype=bool)
    for column in range(4):
        swap |= undecided & (key[i, column] > key[j, column])
        undecided &= key[i, column] == key[j, column]
    first, second = np.where(swap, j, i), np.where(swap, i, j)
    pair, t, u, xy = segment_events(low[first], high[first], low[second], high[second])
    t = np.where(flip[first[pair]], 1 - t, t)
    u = np.where(flip[second[pair]], 1 - u, u)
    t, u = np.where(swap[pair], u, t), np.where(swap[pair], t, u)
    seg_a, seg_b = start[i[pair]], start[j[pair]]

    # where both lines have a vertex: drop the shared vertex of successive
    # segments of one line and, unless wanted, lines meeting end to end
    line = vertex_edge(offsets)
    is_end = np.zeros(len(coords), dtype=bool)
    is_end[offsets[:-1]] = True
    is_end[offsets[1:] - 1] = True
    va, vb = seg_a + (t == 1), seg_b + (u == 1)
    both = ((t == 0) | (t == 1)) & ((u == 0) | (u == 1))
    drop = both & (va == vb) & (line[va] == line[vb])
    if not end_to_end:
        drop |= both & is_end[va] & is_end[vb]
    keep = ~drop
    seg_a, seg_b, t, u, xy = seg_a[keep], seg_b[keep], t[keep], u[keep], xy[keep]
    order = np.lexsort((u, t, seg_b, seg_a))
    seg_a, seg_b, t, u, xy = seg_a[order], seg_b[order], t[order], u[order], xy[order]
    # two segments touching vertex to vertex are found from both sides
    first = np.ones(len(seg_a), dtype=bool)
    first[1:] = (seg_a[1:] != seg_a[:-1]) | (seg_b[1:] != seg_b[:-1]) | (t[1:] != t[:-1]) | (u[1:] != u[:-1])
    return seg_a[first], seg_b[first], t[first], u[first], xy[first]


def point_pairs(xy: FloatArray, tolerance: float) -> Tuple[IntArray, IntArray]:
    """Find all pairs of points no further apart than ``tolerance``.

    Each pair is returned once, lower position first, sorted.

    This reference implementation borrows its spatial index from Shapely.
    """
    import shapely

    if len(xy) < 2:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    points = shapely.points(xy)
    a, b = shapely.STRtree(points).query(points, predicate="dwithin", distance=tolerance)
    once = a < b
    a, b = a[once], b[once]
    order = np.lexsort((b, a))
    return a[order].astype(np.int64), b[order].astype(np.int64)


# ---------------------------------------------------------------------------
# Choice of implementation

NATIVE = ("components", "split", "segment_crossings", "point_pairs")
PYTHON = {name: globals()[name] for name in NATIVE}
BACKEND = "python"


def _contiguous(array: Any, dtype: Any) -> Any:
    return np.ascontiguousarray(array, dtype=dtype)


def use_backend(name: str) -> None:
    """Choose the implementation of the kernel: ``"python"`` or ``"native"``"""
    global BACKEND
    if name == "python":
        globals().update(PYTHON)
        BACKEND = "python"
        return
    if name != "native":
        raise ValueError("backend must be 'python' or 'native'")
    import snkit_kernel as native

    def components(n: int, a: IntArray, b: IntArray) -> IntArray:
        return native.components(n, _contiguous(a, np.int64), _contiguous(b, np.int64))  # type: ignore[no-any-return]

    def split(*arrays: Any) -> Any:
        kinds = (float, np.int64, np.int64, np.int64, np.int64, np.int64, float, np.int64)
        return native.split(*(_contiguous(a, kind) for a, kind in zip(arrays, kinds)))

    def segment_crossings(coords: FloatArray, offsets: IntArray, end_to_end: bool = False) -> Any:
        return native.segment_crossings(_contiguous(coords, float), _contiguous(offsets, np.int64), end_to_end)

    def point_pairs(xy: FloatArray, tolerance: float) -> Any:
        return native.point_pairs(_contiguous(xy, float).reshape(-1, 2), float(tolerance))

    for function in (components, split, segment_crossings, point_pairs):
        function.__doc__ = PYTHON[function.__name__].__doc__
        globals()[function.__name__] = function
    BACKEND = "native"


_wanted = os.environ.get("SNKIT_KERNEL", "")
if _wanted == "native":
    use_backend("native")
elif _wanted != "python":
    try:
        use_backend("native")
    except ImportError:
        pass
