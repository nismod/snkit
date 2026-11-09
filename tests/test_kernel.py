"""Tests of the array kernel, and of the compiled kernel against the reference"""

import numpy as np
import pytest

import snkit
import snkit._kernel as K

try:
    import snkit_kernel as native
except ImportError:
    native = None

needs_native = pytest.mark.skipif(native is None, reason="compiled kernel (snkit-kernel) is not installed")


def random_lines(seed, count=300, vertices=4):
    rng = np.random.default_rng(seed)
    steps = rng.uniform(-8, 8, (count, vertices, 2))
    # whole numbers, so that many lines touch and overlap exactly
    points = np.round(rng.uniform(0, 100, (count, 1, 2)) + np.cumsum(steps, axis=1))
    coords = points.reshape(-1, 2)
    # some repeated vertices
    coords[rng.integers(1, len(coords), 20)] = coords[rng.integers(1, len(coords), 20) - 1]
    offsets = np.arange(0, len(coords) + 1, vertices, dtype=np.int64)
    return np.ascontiguousarray(coords), offsets


def test_components():
    labels = K.PYTHON["components"](6, np.array([4, 1, 5]), np.array([1, 2, 3]))
    assert labels.tolist() == [0, 1, 1, 3, 1, 3]
    assert K.PYTHON["components"](3, np.array([], dtype=int), np.array([], dtype=int)).tolist() == [0, 1, 2]


def test_point_pairs():
    xy = np.array([[0, 0], [0.05, 0], [5, 5], [0, 0], [-0.05, -0.05]])
    for function in [K.PYTHON["point_pairs"]] + ([native.point_pairs] if native else []):
        assert [x.tolist() for x in function(xy, 0.0)] == [[0], [3]]
        assert [x.tolist() for x in function(xy, 0.06)] == [[0, 0, 1], [1, 3, 3]]


def test_segment_crossings_leaves_out_corners_and_ends():
    coords = np.array([[0, 0], [1, 0], [1, 1], [1, 1], [2, 1]], dtype=float)
    offsets = np.array([0, 3, 5])
    assert len(K.PYTHON["segment_crossings"](coords, offsets)[0]) == 0
    seg_a, seg_b, t, u, xy = K.PYTHON["segment_crossings"](coords, offsets, True)
    assert (seg_a.tolist(), seg_b.tolist(), t.tolist(), u.tolist(), xy.tolist()) == ([1], [3], [1.0], [0.0], [[1, 1]])


def test_backend_can_be_chosen():
    before = K.BACKEND
    K.use_backend("python")
    assert K.BACKEND == "python" and K.components is K.PYTHON["components"]
    with pytest.raises(ValueError):
        K.use_backend("fortran")
    if native is not None:
        K.use_backend("native")
        assert K.BACKEND == "native"
    K.use_backend(before)


@needs_native
@pytest.mark.parametrize("seed", range(10))
def test_native_components_and_point_pairs_match_reference(seed):
    rng = np.random.default_rng(seed)
    n = 500
    a, b = rng.integers(0, n, 300), rng.integers(0, n, 300)
    assert native.components(n, a, b).tolist() == K.PYTHON["components"](n, a, b).tolist()

    xy = np.round(rng.uniform(0, 30, (n, 2)), 1)
    for tolerance in (0.0, 0.1, 0.35, 2.0):
        expected = K.PYTHON["point_pairs"](xy, tolerance)
        actual = native.point_pairs(xy, tolerance)
        assert actual[0].tolist() == expected[0].tolist() and actual[1].tolist() == expected[1].tolist()


@needs_native
@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("end_to_end", [False, True])
def test_native_segment_crossings_match_reference(seed, end_to_end):
    coords, offsets = random_lines(seed)
    expected = K.PYTHON["segment_crossings"](coords, offsets, end_to_end)
    actual = native.segment_crossings(coords, offsets, end_to_end)
    assert len(expected[0]) > 100
    # the same meetings between the same segments, at the same vertices where they touch
    for want, got in zip(expected[:2], actual[:2]):
        assert got.tolist() == want.tolist()
    for want, got in zip(expected[2:], actual[2:]):
        np.testing.assert_allclose(got, want, rtol=0, atol=1e-9)
    touching = (expected[2] == 0) | (expected[2] == 1) | (expected[3] == 0) | (expected[3] == 1)
    assert touching.any() and (~touching).any()
    np.testing.assert_array_equal(actual[4][touching], expected[4][touching])


@needs_native
@pytest.mark.parametrize("seed", range(10))
def test_native_split_matches_reference(seed):
    coords, offsets = random_lines(seed, count=100)
    rng = np.random.default_rng(seed)
    m = len(offsets) - 1
    src, dst = np.arange(m) * 2, np.arange(m) * 2 + 1
    cut_edge = np.sort(rng.integers(0, m, 150))
    cut_seg = offsets[cut_edge] + rng.integers(0, 3, 150)
    order = np.lexsort((cut_seg, cut_edge))
    cut_edge, cut_seg = cut_edge[order], cut_seg[order]
    # some cuts land exactly on the vertex before them, some elsewhere
    on_vertex = rng.random(150) < 0.3
    cut_xy = np.where(on_vertex[:, None], coords[cut_seg], rng.uniform(0, 100, (150, 2)))
    cut_node = 1000 + np.arange(150)
    arguments = (coords, offsets, src, dst, cut_edge, cut_seg, cut_xy, cut_node)
    for want, got in zip(K.PYTHON["split"](*arguments), native.split(*arguments)):
        np.testing.assert_array_equal(got, want)


@needs_native
@pytest.mark.parametrize("seed", range(5))
def test_operations_give_the_same_network_on_both_kernels(seed):
    from test_api import random_network, shape

    def pipeline():
        network = random_network(seed)
        network = snkit.split_edges_at_crossings(snkit.link_nodes_to_edges(network))
        network = snkit.merge_edges(snkit.merge_nodes(network, tolerance=1.0))
        return snkit.label_components(network)

    before = K.BACKEND
    try:
        K.use_backend("python")
        reference = pipeline()
        K.use_backend("native")
        compiled = pipeline()
    finally:
        K.use_backend(before)
    assert shape(compiled) == shape(reference)
    assert (
        compiled.edges[["id", "from_id", "to_id"]].values.tolist()
        == reference.edges[["id", "from_id", "to_id"]].values.tolist()
    )
    assert compiled.nodes["component"].tolist() == reference.nodes["component"].tolist()
