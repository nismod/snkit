"""The array kernel, as called from Python.

The kernel does the heavy work of every operation. It takes and returns flat
arrays - there are no tables, no attributes and no geometry objects - and is
written in Rust (the ``kernel`` directory of the repository), compiled into
this package as ``snkit._native``. The functions here only make sure each
array has the type and layout the kernel expects.

A network is represented by:

- ``xy``: node coordinates, ``float64[n, 2]``
- ``src``, ``dst``: for each edge, the position of its end nodes in ``xy``
- ``coords``, ``offsets``: edge geometries as one coordinate array
  ``float64[k, 2]`` and ``int64[m + 1]`` offsets, so that edge ``e`` has
  vertices ``coords[offsets[e]:offsets[e + 1]]`` (the GeoArrow layout)
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

import numpy as np
import numpy.typing as npt

from snkit import _native

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]
Places = Tuple[IntArray, IntArray, IntArray, FloatArray, FloatArray, FloatArray]
Overlaps = Tuple[
    IntArray, IntArray, FloatArray, FloatArray, FloatArray, FloatArray, FloatArray, FloatArray, BoolArray, FloatArray
]


def _ints(array: Any) -> IntArray:
    return np.ascontiguousarray(array, dtype=np.int64)


def _floats(array: Any) -> FloatArray:
    return np.ascontiguousarray(array, dtype=np.float64)


def _points(array: Any) -> FloatArray:
    return np.ascontiguousarray(array, dtype=np.float64).reshape(-1, 2)


def components(n: int, a: Any, b: Any) -> IntArray:
    """Label connected components of ``n`` items linked by pairs ``(a, b)``.

    Each item is labelled with the lowest position in its component.
    """
    return _native.components(int(n), _ints(a), _ints(b))  # type: ignore[no-any-return]


def group_index(labels: Any) -> Tuple[IntArray, BoolArray]:
    """Turn component labels into consecutive group numbers.

    Returns the group number of each item, and a mask of the first item of
    each group. Groups are numbered in order of their first item.
    """
    return _native.group_index(_ints(labels))  # type: ignore[no-any-return]


def line_measures(coords: Any, offsets: Any) -> Tuple[FloatArray, FloatArray, FloatArray]:
    """Lengths along lines.

    Returns, for each vertex, the length of the segment starting there (0 at
    the last vertex of a line) and the distance along its line; and for each
    line, its length.
    """
    return _native.line_measures(_points(coords), _ints(offsets))  # type: ignore[no-any-return]


def locate(
    coords: Any, offsets: Any, seglen: Any, measure: Any, line: Any, at: Any
) -> Tuple[IntArray, FloatArray, FloatArray]:
    """Find the places given distances ``at`` along given lines.

    Returns the vertex that starts the segment each place is on, the fraction
    of the way along that segment, and the coordinate.
    """
    return _native.locate(  # type: ignore[no-any-return]
        _points(coords), _ints(offsets), _floats(seglen), _floats(measure), _ints(line), _floats(at)
    )


def sync_ends(coords: Any, offsets: Any, xy: Any, src: Any, dst: Any) -> FloatArray:
    """Move the end vertices of each edge exactly onto its end nodes"""
    return _native.sync_ends(_points(coords), _ints(offsets), _points(xy), _ints(src), _ints(dst))  # type: ignore[no-any-return]


def extend_ends(coords: Any, offsets: Any, xy: Any, src: Any, dst: Any) -> Tuple[FloatArray, IntArray]:
    """Add a vertex at each edge end that is not already exactly on its end node"""
    return _native.extend_ends(_points(coords), _ints(offsets), _points(xy), _ints(src), _ints(dst))  # type: ignore[no-any-return]


def split(
    coords: Any, offsets: Any, src: Any, dst: Any, cut_edge: Any, cut_seg: Any, cut_xy: Any, cut_node: Any
) -> Tuple[FloatArray, IntArray, IntArray, IntArray, IntArray]:
    """Cut edges, inserting the coordinate of a node at each cut.

    Cuts must be sorted by edge and then by position along the edge.
    ``cut_seg`` is the vertex position at the start of the segment to cut.

    Returns new ``coords``, ``offsets``, ``src``, ``dst`` and, for each new
    edge, the position of the edge it was cut from. Pieces of an edge are in
    order along it and take its place in the edge order. A cut that lands on
    an existing vertex does not repeat it.
    """
    return _native.split(  # type: ignore[no-any-return]
        _points(coords),
        _ints(offsets),
        _ints(src),
        _ints(dst),
        _ints(cut_edge),
        _ints(cut_seg),
        _points(cut_xy),
        _ints(cut_node),
    )


def segment_crossings(
    coords: Any, offsets: Any, end_to_end: bool = False
) -> Tuple[IntArray, IntArray, FloatArray, FloatArray, FloatArray]:
    """Find every place where two segments of the given lines meet.

    Returns, for each meeting: the two segments (each named by the vertex
    position where it starts, the lower first), the fraction along each, and
    the coordinate. A pair that crosses gives one meeting. A pair that touches
    gives one for each end of one segment lying on the other, located exactly
    at that end (fraction exactly 0 or 1, coordinate exactly the end's own).
    Segments of zero length are ignored.

    Two kinds of meeting are left out: the vertex shared by two successive
    segments of one line, and, unless ``end_to_end`` is set, places where two
    lines meet at an end of each.

    Whether segments meet is decided with exact predicates. Each pair is put
    into a fixed order and direction before a crossing is computed, so the
    coordinate does not depend on the order of the lines or the way they run.
    """
    return _native.segment_crossings(_points(coords), _ints(offsets), bool(end_to_end))  # type: ignore[no-any-return]


def point_pairs(xy: Any, tolerance: float) -> Tuple[IntArray, IntArray]:
    """Find all pairs of points no further apart than ``tolerance``.

    Each pair is returned once, lower position first, sorted.
    """
    return _native.point_pairs(_points(xy), float(tolerance))  # type: ignore[no-any-return]


def points_near_lines(xy: Any, coords: Any, offsets: Any, tolerance: float) -> Places:
    """For each point, every line within ``tolerance``, with the nearest place on it.

    Returns, for each match: the point, the line, the vertex that starts the
    segment the place is on, the fraction along that segment, the coordinate
    of the place and its distance from the point. Sorted by point, then line.
    """
    return _native.points_near_lines(_points(xy), _points(coords), _ints(offsets), float(tolerance))  # type: ignore[no-any-return]


def nearest_lines(
    xy: Any,
    coords: Any,
    offsets: Any,
    max_distance: Optional[float] = None,
    node: Optional[Any] = None,
    src: Optional[Any] = None,
    dst: Optional[Any] = None,
) -> Places:
    """For each point, the nearest line, with the nearest place on it.

    Returns the same arrays as :func:`points_near_lines`. A point with no line
    within ``max_distance`` is left out.

    If ``node`` names a node for each point, lines that begin or end at that
    node (by ``src`` and ``dst``) are passed over, so that a node is not
    matched to its own edges.
    """
    none = np.zeros(0, dtype=np.int64)
    return _native.nearest_lines(  # type: ignore[no-any-return]
        _points(xy),
        none if node is None else _ints(node),
        _points(coords),
        _ints(offsets),
        none if src is None else _ints(src),
        none if dst is None else _ints(dst),
        np.inf if max_distance is None else float(max_distance),
    )


def nearest_points(xy: Any, targets: Any, max_distance: Optional[float] = None) -> IntArray:
    """For each point, the position of the nearest of ``targets``, or -1 if
    there is none within ``max_distance``. Among targets equally near, the earliest."""
    return _native.nearest_points(  # type: ignore[no-any-return]
        _points(xy), _points(targets), np.inf if max_distance is None else float(max_distance)
    )


def simplify_lines(coords: Any, offsets: Any, tolerance: float) -> Tuple[FloatArray, IntArray]:
    """Simplify every line with the Douglas-Peucker algorithm.

    Returns new ``coords`` and ``offsets``. The ends of a line are kept, and
    so is any vertex further than ``tolerance`` from the line through the
    kept vertices either side of it: the vertices that
    ``shapely.simplify(lines, tolerance, preserve_topology=False)`` keeps.

    A line that would be left with no length (one that ends where it starts
    and never goes further than ``tolerance`` from there) is unchanged.
    """
    return _native.simplify_lines(_points(coords), _ints(offsets), float(tolerance))  # type: ignore[no-any-return]


def line_overlaps(coords: Any, offsets: Any, tolerance: float) -> Overlaps:
    """Find the stretches where one line runs within ``tolerance`` of another.

    For each pair of lines the stretches are of the earlier line, ``a``. They
    are exact: a stretch starts and ends where ``a`` is ``tolerance`` from
    ``b``, or at an end of ``a``. With a tolerance of 0 they are where the two
    lines lie exactly on top of each other.

    Returns ten arrays with a value for each stretch, sorted by the first
    three: ``a`` and ``b``, the positions of the lines; ``near_start`` and
    ``near_end``, the stretch as distances along ``a``; ``start_a``,
    ``end_a``, ``start_b`` and ``end_b``, the intervals of ``a`` and ``b``
    that face each other, found by moving each end of the stretch to the
    nearest place on ``b`` and from there to the nearest place on ``a``;
    ``reversed``, whether the lines run opposite ways there; and ``distance``,
    the furthest that ``a`` strays from ``b`` between ``start_a`` and
    ``end_a``, measured at those places, at the vertices of ``a`` between
    them, and at the ends of the stretch where they lie between them.

    The facing intervals of lines that merely cross have no length: leaving
    out intervals too short to matter is for the caller.
    """
    return _native.line_overlaps(_points(coords), _ints(offsets), float(tolerance))  # type: ignore[no-any-return]


def hausdorff_distance(coords: Any, offsets: Any, a: Any, b: Any) -> FloatArray:
    """The discrete Hausdorff distance between pairs of lines, given by position.

    The larger of: the furthest any vertex of line ``a`` is from line ``b``,
    and the furthest any vertex of ``b`` is from ``a``, as
    ``shapely.hausdorff_distance`` gives.
    """
    return _native.hausdorff_distance(_points(coords), _ints(offsets), _ints(a), _ints(b))  # type: ignore[no-any-return]
