"""Tests of the array kernel, against answers worked out the slow way"""

import numpy as np
import pytest
import shapely

import snkit._kernel as K

SEEDS = range(8)


def random_lines(seed, count=200, vertices=4, whole=False):
    """Random lines as (coords, offsets). With whole=True coordinates are whole
    numbers, so that many lines touch and overlap exactly."""
    rng = np.random.default_rng(seed)
    points = rng.uniform(0, 100, (count, 1, 2)) + np.cumsum(rng.uniform(-8, 8, (count, vertices, 2)), axis=1)
    if whole:
        points = np.round(points)
    coords = np.ascontiguousarray(points.reshape(-1, 2))
    return coords, np.arange(0, len(coords) + 1, vertices, dtype=np.int64)


def as_shapely(coords, offsets):
    return shapely.from_ragged_array(shapely.GeometryType.LINESTRING, coords, (offsets,))


def test_components():
    assert K.components(6, [4, 1, 5], [1, 2, 3]).tolist() == [0, 1, 1, 3, 1, 3]
    assert K.components(3, [], []).tolist() == [0, 1, 2]
    assert K.components(0, [], []).tolist() == []


@pytest.mark.parametrize("seed", SEEDS)
def test_components_against_repeated_relabelling(seed):
    rng = np.random.default_rng(seed)
    n = 400
    a, b = rng.integers(0, n, 250), rng.integers(0, n, 250)
    labels = np.arange(n)
    for _ in range(n):  # spread the lowest label along every link until nothing changes
        low = np.minimum(labels[a], labels[b])
        np.minimum.at(labels, a, low)
        np.minimum.at(labels, b, low)
    assert K.components(n, a, b).tolist() == labels.tolist()


def test_group_index():
    group, is_first = K.group_index([0, 1, 1, 0, 4])
    assert group.tolist() == [0, 1, 1, 0, 2]
    assert is_first.tolist() == [True, True, False, False, True]


def test_line_measures_and_locate():
    coords = np.array([[0, 0], [3, 0], [3, 4], [10, 10], [10, 12]], dtype=float)
    offsets = [0, 3, 5]
    seglen, measure, length = K.line_measures(coords, offsets)
    assert seglen.tolist() == [3, 4, 0, 2, 0]
    assert measure.tolist() == [0, 3, 7, 0, 2]
    assert length.tolist() == [7, 2]
    vertex, frac, xy = K.locate(coords, offsets, seglen, measure, [0, 0, 0, 0, 1, 1], [0, 1.5, 3, 7, 1, 99])
    assert vertex.tolist() == [0, 0, 1, 1, 3, 3]
    assert frac.tolist() == [0, 0.5, 0, 1, 0.5, 1]
    assert xy.tolist() == [[0, 0], [1.5, 0], [3, 0], [3, 4], [10, 11], [10, 12]]


@pytest.mark.parametrize("seed", SEEDS)
def test_measures_and_locate_against_shapely(seed):
    coords, offsets = random_lines(seed)
    lines = as_shapely(coords, offsets)
    seglen, measure, length = K.line_measures(coords, offsets)
    np.testing.assert_allclose(length, shapely.length(lines), rtol=1e-12)
    rng = np.random.default_rng(seed)
    line = rng.integers(0, len(lines), 500)
    at = rng.uniform(0, 1, 500) * length[line]
    vertex, frac, xy = K.locate(coords, offsets, seglen, measure, line, at)
    expected = shapely.get_coordinates(shapely.line_interpolate_point(lines[line], at))
    np.testing.assert_allclose(xy, expected, atol=1e-9)
    np.testing.assert_allclose(measure[vertex] + frac * seglen[vertex], at, atol=1e-9)
    assert ((vertex >= offsets[line]) & (vertex < offsets[line + 1] - 1)).all()


def test_ends_follow_nodes():
    coords = np.array([[0, 0], [3, 0], [3, 4], [10, 10], [10, 12]], dtype=float)
    xy = np.array([[0, 0.5], [3, 4], [10, 10], [10, 13]])
    moved = K.sync_ends(coords, [0, 3, 5], xy, [0, 2], [1, 3])
    assert moved.tolist() == [[0, 0.5], [3, 0], [3, 4], [10, 10], [10, 13]]
    extended, offsets = K.extend_ends(coords, [0, 3, 5], xy, [0, 2], [1, 3])
    assert offsets.tolist() == [0, 4, 7]
    assert extended.tolist() == [[0, 0.5], [0, 0], [3, 0], [3, 4], [10, 10], [10, 12], [10, 13]]


def slow_split(coords, offsets, src, dst, cut_edge, cut_seg, cut_xy, cut_node):
    """Cut edges one at a time, with lists"""
    pieces, new_src, new_dst, parent = [], [], [], []
    for e in range(len(src)):
        vertices = [tuple(c) for c in coords[offsets[e] : offsets[e + 1]]]
        cuts = [k for k in range(len(cut_edge)) if cut_edge[k] == e]
        if not cuts:
            pieces.append(vertices)
        else:
            piece, start = [], src[e]
            for v, vertex in enumerate(vertices, start=offsets[e]):
                piece.append(vertex)
                for k in cuts:
                    if cut_seg[k] == v:
                        piece.append(tuple(cut_xy[k]))
                        pieces.append(piece)
                        new_src.append(start)
                        new_dst.append(cut_node[k])
                        parent.append(e)
                        piece, start = [tuple(cut_xy[k])], cut_node[k]
            pieces.append(piece)
            # no vertex twice running, but never fewer than two
            for i in range(len(pieces) - len(cuts) - 1, len(pieces)):
                kept = [p for j, p in enumerate(pieces[i]) if j == 0 or p != pieces[i][j - 1]]
                pieces[i] = kept if len(kept) > 1 else kept * 2
        new_src.append(src[e] if not cuts else start)
        new_dst.append(dst[e])
        parent.append(e)
    return pieces, new_src, new_dst, parent


@pytest.mark.parametrize("seed", SEEDS)
def test_split_against_cutting_one_edge_at_a_time(seed):
    coords, offsets = random_lines(seed, count=60, whole=True)
    rng = np.random.default_rng(seed)
    m = len(offsets) - 1
    src, dst = np.arange(m) * 2, np.arange(m) * 2 + 1
    cut_edge = rng.integers(0, m, 80)
    cut_seg = offsets[cut_edge] + rng.integers(0, 3, 80)
    order = np.lexsort((cut_seg, cut_edge))
    cut_edge, cut_seg = cut_edge[order], cut_seg[order]
    # some cuts land exactly on the vertex before them, some elsewhere
    on_vertex = rng.random(80) < 0.3
    cut_xy = np.where(on_vertex[:, None], coords[cut_seg], rng.uniform(0, 100, (80, 2)))
    cut_node = 1000 + np.arange(80)
    arguments = (coords, offsets, src, dst, cut_edge, cut_seg, cut_xy, cut_node)

    new_coords, new_offsets, new_src, new_dst, parent = K.split(*arguments)
    pieces, want_src, want_dst, want_parent = slow_split(*arguments)
    got = [[tuple(c) for c in new_coords[a:b]] for a, b in zip(new_offsets[:-1], new_offsets[1:])]
    assert got == pieces
    assert (new_src.tolist(), new_dst.tolist(), parent.tolist()) == (want_src, want_dst, want_parent)


def test_point_pairs():
    xy = np.array([[0, 0], [0.05, 0], [5, 5], [0, 0], [-0.05, -0.05]])
    assert [x.tolist() for x in K.point_pairs(xy, 0.0)] == [[0], [3]]
    assert [x.tolist() for x in K.point_pairs(xy, 0.06)] == [[0, 0, 1], [1, 3, 3]]
    assert [len(x) for x in K.point_pairs(xy[:1], 1.0)] == [0, 0]


@pytest.mark.parametrize("seed", SEEDS)
def test_point_pairs_against_all_pairs(seed):
    rng = np.random.default_rng(seed)
    xy = np.round(rng.uniform(0, 30, (400, 2)), 1) - 15
    apart = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
    for tolerance in (0.0, 0.1, 0.35, 2.0):
        a, b = np.nonzero(np.triu(apart <= tolerance, k=1))
        found = K.point_pairs(xy, tolerance)
        assert (found[0].tolist(), found[1].tolist()) == (a.tolist(), b.tolist())


def test_nearest_points():
    targets = [[0, 0], [2, 0], [2, 0]]
    assert K.nearest_points([[1, 0], [1.9, 0], [9, 0]], targets, 5).tolist() == [0, 1, -1]
    assert K.nearest_points([[1, 0]], np.empty((0, 2))).tolist() == [-1]


@pytest.mark.parametrize("seed", SEEDS)
def test_nearest_points_against_all_pairs(seed):
    rng = np.random.default_rng(seed)
    xy, targets = rng.uniform(0, 50, (300, 2)), np.round(rng.uniform(0, 50, (500, 2)))
    apart = np.hypot(xy[:, None, 0] - targets[None, :, 0], xy[:, None, 1] - targets[None, :, 1])
    assert K.nearest_points(xy, targets).tolist() == apart.argmin(axis=1).tolist()
    limited = np.where(apart.min(axis=1) <= 1.0, apart.argmin(axis=1), -1)
    assert K.nearest_points(xy, targets, 1.0).tolist() == limited.tolist()


@pytest.mark.parametrize("seed", SEEDS)
def test_points_near_lines_against_all_pairs(seed):
    coords, offsets = random_lines(seed)
    lines = as_shapely(coords, offsets)
    xy = np.random.default_rng(seed).uniform(0, 100, (150, 2))
    apart = shapely.distance(shapely.points(xy)[:, None], lines[None, :])
    tolerance = 3.0
    point, line, vertex, frac, place, distance = K.points_near_lines(xy, coords, offsets, tolerance)
    want_point, want_line = np.nonzero(apart <= tolerance)
    assert len(point) > 100
    assert (point.tolist(), line.tolist()) == (want_point.tolist(), want_line.tolist())
    np.testing.assert_allclose(distance, apart[point, line], atol=1e-9)
    np.testing.assert_allclose(np.hypot(*(place - xy[point]).T), distance, atol=1e-12)
    # the place is on the line, at the vertex and fraction given
    np.testing.assert_allclose(shapely.distance(shapely.points(place), lines[line]), 0, atol=1e-9)
    np.testing.assert_allclose(coords[vertex] + frac[:, None] * (coords[vertex + 1] - coords[vertex]), place, atol=1e-9)
    assert ((vertex >= offsets[line]) & (vertex < offsets[line + 1])).all()


@pytest.mark.parametrize("seed", SEEDS)
def test_nearest_lines_against_all_pairs(seed):
    coords, offsets = random_lines(seed)
    lines = as_shapely(coords, offsets)
    m = len(lines)
    xy = np.random.default_rng(seed).uniform(0, 100, (150, 2))
    apart = shapely.distance(shapely.points(xy)[:, None], lines[None, :])

    point, line, _, _, _, distance = K.nearest_lines(xy, coords, offsets)
    assert point.tolist() == list(range(len(xy)))
    np.testing.assert_allclose(distance, apart.min(axis=1), atol=1e-9)
    np.testing.assert_allclose(apart[point, line], apart.min(axis=1), atol=1e-9)

    point, line, _, _, _, distance = K.nearest_lines(xy, coords, offsets, 2.0)
    assert point.tolist() == np.flatnonzero(apart.min(axis=1) <= 2.0).tolist()

    # each point is a node, and some lines begin or end there: those are passed over
    src, dst = np.arange(m) % len(xy), (np.arange(m) * 7 + 3) % len(xy)
    own = (src[None, :] == np.arange(len(xy))[:, None]) | (dst[None, :] == np.arange(len(xy))[:, None])
    others = np.where(own, np.inf, apart)
    point, line, _, _, _, distance = K.nearest_lines(xy, coords, offsets, None, np.arange(len(xy)), src, dst)
    np.testing.assert_allclose(distance, others.min(axis=1), atol=1e-9)
    assert not own[point, line].any()


def test_segment_crossings_kinds():
    cross = np.array([[0, 0], [2, 2], [0, 2], [2, 0]], dtype=float)
    seg_a, seg_b, t, u, xy = K.segment_crossings(cross, [0, 2, 4])
    assert (seg_a.tolist(), seg_b.tolist(), t.tolist(), u.tolist(), xy.tolist()) == ([0], [2], [0.5], [0.5], [[1, 1]])
    touch = np.array([[0, 0], [2, 0], [1, 0], [1, 1]], dtype=float)
    seg_a, seg_b, t, u, xy = K.segment_crossings(touch, [0, 2, 4])
    assert (t.tolist(), u.tolist(), xy.tolist()) == ([0.5], [0.0], [[1, 0]])
    # a corner, and two lines meeting end to end, are left out unless asked for
    corner = np.array([[0, 0], [1, 0], [1, 1], [1, 1], [2, 1]], dtype=float)
    assert len(K.segment_crossings(corner, [0, 3, 5])[0]) == 0
    seg_a, seg_b, t, u, xy = K.segment_crossings(corner, [0, 3, 5], True)
    assert (seg_a.tolist(), seg_b.tolist(), t.tolist(), u.tolist(), xy.tolist()) == ([1], [3], [1.0], [0.0], [[1, 1]])
    assert len(K.segment_crossings(np.empty((0, 2)), [0])[0]) == 0


@pytest.mark.parametrize("seed", SEEDS)
def test_segment_crossings_against_all_pairs(seed):
    coords, offsets = random_lines(seed)
    starts = np.setdiff1d(np.arange(len(coords)), offsets[1:] - 1)
    segments = shapely.linestrings(np.stack([coords[starts], coords[starts + 1]], axis=1))
    meets = shapely.intersects(segments[:, None], segments[None, :])
    i, j = np.nonzero(np.triu(meets, k=1))
    successive = (starts[j] - starts[i] == 1) & (starts[i] // 4 == starts[j] // 4)
    i, j = i[~successive], j[~successive]

    seg_a, seg_b, t, u, xy = K.segment_crossings(coords, offsets)
    assert len(seg_a) > 100
    assert (seg_a.tolist(), seg_b.tolist()) == (starts[i].tolist(), starts[j].tolist())
    expected = shapely.get_coordinates(shapely.intersection(segments[i], segments[j]))
    np.testing.assert_allclose(xy, expected, atol=1e-9)
    np.testing.assert_allclose(coords[seg_a] + t[:, None] * (coords[seg_a + 1] - coords[seg_a]), xy, atol=1e-9)
    np.testing.assert_allclose(coords[seg_b] + u[:, None] * (coords[seg_b + 1] - coords[seg_b]), xy, atol=1e-9)


@pytest.mark.parametrize("seed", SEEDS)
def test_segment_crossings_where_lines_touch(seed):
    coords, offsets = random_lines(seed, whole=True)
    seg_a, seg_b, t, u, xy = K.segment_crossings(coords, offsets, True)
    at_vertex_a, at_vertex_b = (t == 0) | (t == 1), (u == 0) | (u == 1)
    assert (at_vertex_a | at_vertex_b).sum() > 20 and (~at_vertex_a & ~at_vertex_b).sum() > 20
    # where a line has a vertex at the meeting, the coordinate is exactly that vertex
    np.testing.assert_array_equal(xy[at_vertex_a], coords[seg_a + (t == 1)][at_vertex_a])
    np.testing.assert_array_equal(xy[at_vertex_b], coords[seg_b + (u == 1)][at_vertex_b])
    # every meeting is on both segments, and each is reported once
    segments_a = shapely.linestrings(np.stack([coords[seg_a], coords[seg_a + 1]], axis=1))
    segments_b = shapely.linestrings(np.stack([coords[seg_b], coords[seg_b + 1]], axis=1))
    points = shapely.points(xy)
    assert (shapely.distance(points, segments_a) < 1e-9).all() and (shapely.distance(points, segments_b) < 1e-9).all()
    assert len(set(zip(seg_a.tolist(), seg_b.tolist(), t.tolist(), u.tolist()))) == len(seg_a)


@pytest.mark.parametrize("seed", SEEDS)
def test_segment_crossings_do_not_depend_on_order_or_direction(seed):
    coords, offsets = random_lines(seed)
    lines = coords.reshape(-1, 4, 2)
    rng = np.random.default_rng(seed)
    shuffled = lines[rng.permutation(len(lines))]
    flip = rng.random(len(lines)) < 0.5
    shuffled[flip] = shuffled[flip, ::-1]
    before = K.segment_crossings(coords, offsets)[4]
    after = K.segment_crossings(shuffled.reshape(-1, 2), offsets)[4]
    assert sorted(map(tuple, before)) == sorted(map(tuple, after))
