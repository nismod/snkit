"""Array kernel for spatial network operations.

Everything here takes and returns plain numpy arrays. There are no tables, no
attributes and no geometry objects, so that this module is the part to port to
another language.

A network is represented by:

- ``xy``: node coordinates, ``float64[n, 2]``
- ``src``, ``dst``: for each edge, the position of its end nodes in ``xy``
- ``coords``, ``offsets``: edge geometries as one coordinate array
  ``float64[k, 2]`` and ``int64[m + 1]`` offsets, so that edge ``e`` has
  vertices ``coords[offsets[e]:offsets[e + 1]]`` (the GeoArrow layout)
"""

from __future__ import annotations

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
    t = o1[idx] / (o1[idx] - o2[idx])
    u = o3[idx] / (o3[idx] - o4[idx])
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
