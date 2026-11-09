//! Python bindings: numpy arrays in, numpy arrays out, with the interpreter
//! lock released while working.

use numpy::{IntoPyArray, PyArray1, PyArray2, PyArrayMethods, PyReadonlyArray1, PyReadonlyArray2};
use pyo3::prelude::*;

type Int<'py> = PyReadonlyArray1<'py, i64>;
type IntOut<'py> = Bound<'py, PyArray1<i64>>;
type FloatOut<'py> = Bound<'py, PyArray1<f64>>;
type PointsOut<'py> = Bound<'py, PyArray2<f64>>;

fn points<'py>(py: Python<'py>, flat: Vec<f64>) -> PyResult<PointsOut<'py>> {
    let n = flat.len() / 2;
    flat.into_pyarray(py).reshape([n, 2])
}

/// Label connected components of n items linked by pairs (a, b), each with
/// the lowest position in its component.
#[pyfunction]
fn components<'py>(py: Python<'py>, n: usize, a: Int<'py>, b: Int<'py>) -> PyResult<IntOut<'py>> {
    let (a, b) = (a.as_slice()?, b.as_slice()?);
    Ok(py
        .allow_threads(|| crate::components::components(n, a, b))
        .into_pyarray(py))
}

/// Cut edges, inserting the coordinate of a node at each cut.
#[pyfunction]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn split<'py>(
    py: Python<'py>,
    coords: PyReadonlyArray2<'py, f64>,
    offsets: Int<'py>,
    src: Int<'py>,
    dst: Int<'py>,
    cut_edge: Int<'py>,
    cut_seg: Int<'py>,
    cut_xy: PyReadonlyArray2<'py, f64>,
    cut_node: Int<'py>,
) -> PyResult<(PointsOut<'py>, IntOut<'py>, IntOut<'py>, IntOut<'py>, IntOut<'py>)> {
    let (coords, offsets, src, dst) = (
        coords.as_slice()?,
        offsets.as_slice()?,
        src.as_slice()?,
        dst.as_slice()?,
    );
    let (cut_edge, cut_seg, cut_xy, cut_node) = (
        cut_edge.as_slice()?,
        cut_seg.as_slice()?,
        cut_xy.as_slice()?,
        cut_node.as_slice()?,
    );
    let out = py.allow_threads(|| crate::split::split(coords, offsets, src, dst, cut_edge, cut_seg, cut_xy, cut_node));
    Ok((
        points(py, out.coords)?,
        out.offsets.into_pyarray(py),
        out.src.into_pyarray(py),
        out.dst.into_pyarray(py),
        out.parent.into_pyarray(py),
    ))
}

/// Find every place where two segments of the given lines meet.
#[pyfunction]
#[allow(clippy::type_complexity)]
fn segment_crossings<'py>(
    py: Python<'py>,
    coords: PyReadonlyArray2<'py, f64>,
    offsets: Int<'py>,
    end_to_end: bool,
) -> PyResult<(IntOut<'py>, IntOut<'py>, FloatOut<'py>, FloatOut<'py>, PointsOut<'py>)> {
    let (coords, offsets) = (coords.as_slice()?, offsets.as_slice()?);
    let out = py.allow_threads(|| crate::crossings::segment_crossings(coords, offsets, end_to_end));
    Ok((
        out.seg_a.into_pyarray(py),
        out.seg_b.into_pyarray(py),
        out.frac_a.into_pyarray(py),
        out.frac_b.into_pyarray(py),
        points(py, out.xy)?,
    ))
}

/// Find all pairs of points no further apart than tolerance.
#[pyfunction]
fn point_pairs<'py>(
    py: Python<'py>,
    xy: PyReadonlyArray2<'py, f64>,
    tolerance: f64,
) -> PyResult<(IntOut<'py>, IntOut<'py>)> {
    let xy = xy.as_slice()?;
    let (a, b) = py.allow_threads(|| crate::points::point_pairs(xy, tolerance));
    Ok((a.into_pyarray(py), b.into_pyarray(py)))
}

#[pymodule]
fn snkit_kernel(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(components, module)?)?;
    module.add_function(wrap_pyfunction!(split, module)?)?;
    module.add_function(wrap_pyfunction!(segment_crossings, module)?)?;
    module.add_function(wrap_pyfunction!(point_pairs, module)?)?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
