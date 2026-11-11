//! Python bindings: numpy arrays in, numpy arrays out, with the interpreter
//! lock released while working. Coordinates are arrays of shape (n, 2).

use arrow::ffi_stream::{ArrowArrayStreamReader, FFI_ArrowArrayStream};
use arrow::record_batch::RecordBatchReader;
use numpy::{IntoPyArray, PyArray1, PyArray2, PyArrayMethods, PyReadonlyArray1, PyReadonlyArray2};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyCapsule;

use crate::geoarrow::Want;
use crate::tiles::Tiling;

type Int<'py> = PyReadonlyArray1<'py, i64>;
type Float<'py> = PyReadonlyArray1<'py, f64>;
type Points<'py> = PyReadonlyArray2<'py, f64>;
type IntOut<'py> = Bound<'py, PyArray1<i64>>;
type FloatOut<'py> = Bound<'py, PyArray1<f64>>;
type PointsOut<'py> = Bound<'py, PyArray2<f64>>;
type PlacesOut<'py> = (
    IntOut<'py>,
    IntOut<'py>,
    IntOut<'py>,
    FloatOut<'py>,
    PointsOut<'py>,
    FloatOut<'py>,
);

fn points<'py>(py: Python<'py>, flat: Vec<f64>) -> PyResult<PointsOut<'py>> {
    let n = flat.len() / 2;
    flat.into_pyarray(py).reshape([n, 2])
}

fn places<'py>(py: Python<'py>, found: crate::nearest::Places) -> PyResult<PlacesOut<'py>> {
    Ok((
        found.point.into_pyarray(py),
        found.line.into_pyarray(py),
        found.vertex.into_pyarray(py),
        found.frac.into_pyarray(py),
        points(py, found.xy)?,
        found.distance.into_pyarray(py),
    ))
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

/// Join the sets of each pair (a, b) in a forest kept in `parent`, an array of
/// unsigned 32-bit integers that starts as 0, 1, 2, ... and is changed in place.
#[pyfunction]
fn components_link<'py>(mut parent: numpy::PyReadwriteArray1<'py, u32>, a: Int<'py>, b: Int<'py>) -> PyResult<()> {
    crate::components::link(parent.as_slice_mut()?, a.as_slice()?, b.as_slice()?);
    Ok(())
}

/// Turn the forest in `parent` into labels, in place: each entry becomes the
/// lowest position in its set.
#[pyfunction]
fn components_settle(mut parent: numpy::PyReadwriteArray1<'_, u32>) -> PyResult<()> {
    crate::components::settle(parent.as_slice_mut()?);
    Ok(())
}

/// Turn component labels into consecutive group numbers, and mark the first of each group.
#[pyfunction]
fn group_index<'py>(py: Python<'py>, labels: Int<'py>) -> PyResult<(IntOut<'py>, Bound<'py, PyArray1<bool>>)> {
    let (group, is_first) = crate::measures::group_index(labels.as_slice()?);
    Ok((group.into_pyarray(py), is_first.into_pyarray(py)))
}

/// Cut edges, inserting the coordinate of a node at each cut.
#[pyfunction]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn split<'py>(
    py: Python<'py>,
    coords: Points<'py>,
    offsets: Int<'py>,
    src: Int<'py>,
    dst: Int<'py>,
    cut_edge: Int<'py>,
    cut_seg: Int<'py>,
    cut_xy: Points<'py>,
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
    coords: Points<'py>,
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
fn point_pairs<'py>(py: Python<'py>, xy: Points<'py>, tolerance: f64) -> PyResult<(IntOut<'py>, IntOut<'py>)> {
    let xy = xy.as_slice()?;
    let (a, b) = py.allow_threads(|| crate::points::point_pairs(xy, tolerance));
    Ok((a.into_pyarray(py), b.into_pyarray(py)))
}

/// For each vertex, the length of the segment starting there and the distance
/// along its line; for each line, its length.
#[pyfunction]
fn line_measures<'py>(
    py: Python<'py>,
    coords: Points<'py>,
    offsets: Int<'py>,
) -> PyResult<(FloatOut<'py>, FloatOut<'py>, FloatOut<'py>)> {
    let out = crate::measures::line_measures(coords.as_slice()?, offsets.as_slice()?);
    Ok((
        out.seglen.into_pyarray(py),
        out.measure.into_pyarray(py),
        out.length.into_pyarray(py),
    ))
}

/// Find the places given distances along lines: vertex, fraction and coordinate.
#[pyfunction]
fn locate<'py>(
    py: Python<'py>,
    coords: Points<'py>,
    offsets: Int<'py>,
    seglen: Float<'py>,
    measure: Float<'py>,
    line: Int<'py>,
    at: Float<'py>,
) -> PyResult<(IntOut<'py>, FloatOut<'py>, PointsOut<'py>)> {
    let (vertex, frac, xy) = crate::measures::locate(
        coords.as_slice()?,
        offsets.as_slice()?,
        seglen.as_slice()?,
        measure.as_slice()?,
        line.as_slice()?,
        at.as_slice()?,
    );
    Ok((vertex.into_pyarray(py), frac.into_pyarray(py), points(py, xy)?))
}

/// Move the end vertices of each edge exactly onto its end nodes.
#[pyfunction]
fn sync_ends<'py>(
    py: Python<'py>,
    coords: Points<'py>,
    offsets: Int<'py>,
    xy: Points<'py>,
    src: Int<'py>,
    dst: Int<'py>,
) -> PyResult<PointsOut<'py>> {
    let out = crate::measures::sync_ends(
        coords.as_slice()?,
        offsets.as_slice()?,
        xy.as_slice()?,
        src.as_slice()?,
        dst.as_slice()?,
    );
    points(py, out)
}

/// Add a vertex at each edge end that is not already exactly on its end node.
#[pyfunction]
fn extend_ends<'py>(
    py: Python<'py>,
    coords: Points<'py>,
    offsets: Int<'py>,
    xy: Points<'py>,
    src: Int<'py>,
    dst: Int<'py>,
) -> PyResult<(PointsOut<'py>, IntOut<'py>)> {
    let (out, out_offsets) = crate::measures::extend_ends(
        coords.as_slice()?,
        offsets.as_slice()?,
        xy.as_slice()?,
        src.as_slice()?,
        dst.as_slice()?,
    );
    Ok((points(py, out)?, out_offsets.into_pyarray(py)))
}

/// For each point, every line within tolerance, with the nearest place on it.
#[pyfunction]
fn points_near_lines<'py>(
    py: Python<'py>,
    xy: Points<'py>,
    coords: Points<'py>,
    offsets: Int<'py>,
    tolerance: f64,
) -> PyResult<PlacesOut<'py>> {
    let (xy, coords, offsets) = (xy.as_slice()?, coords.as_slice()?, offsets.as_slice()?);
    let found = py.allow_threads(|| crate::nearest::points_near_lines(xy, coords, offsets, tolerance));
    places(py, found)
}

/// For each point, the nearest line within max_distance, passing over lines
/// that begin or end at the node named for the point.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn nearest_lines<'py>(
    py: Python<'py>,
    xy: Points<'py>,
    node: Int<'py>,
    coords: Points<'py>,
    offsets: Int<'py>,
    src: Int<'py>,
    dst: Int<'py>,
    max_distance: f64,
) -> PyResult<PlacesOut<'py>> {
    let (xy, node, coords, offsets) = (
        xy.as_slice()?,
        node.as_slice()?,
        coords.as_slice()?,
        offsets.as_slice()?,
    );
    let (src, dst) = (src.as_slice()?, dst.as_slice()?);
    let found = py.allow_threads(|| crate::nearest::nearest_lines(xy, node, coords, offsets, src, dst, max_distance));
    places(py, found)
}

/// For each point, the position of the nearest target within max_distance, or -1.
#[pyfunction]
fn nearest_points<'py>(
    py: Python<'py>,
    xy: Points<'py>,
    targets: Points<'py>,
    max_distance: f64,
) -> PyResult<IntOut<'py>> {
    let (xy, targets) = (xy.as_slice()?, targets.as_slice()?);
    Ok(py
        .allow_threads(|| crate::nearest::nearest_points(xy, targets, max_distance))
        .into_pyarray(py))
}

/// Take over the Arrow stream that a Python object offers.
fn stream(source: &Bound<'_, PyAny>) -> PyResult<ArrowArrayStreamReader> {
    let capsule = source
        .call_method0("__arrow_c_stream__")
        .map_err(|_| PyTypeError::new_err("expected Arrow data: an object with an __arrow_c_stream__ method"))?;
    let capsule = capsule.downcast::<PyCapsule>()?;
    let reader = unsafe { ArrowArrayStreamReader::from_raw(capsule.pointer() as *mut FFI_ArrowArrayStream) };
    reader.map_err(|e| PyValueError::new_err(e.to_string()))
}

fn wanted(kind: &str) -> PyResult<Want> {
    match kind {
        "lines" => Ok(Want::Lines),
        "points" => Ok(Want::Points),
        "any" => Ok(Want::Any),
        _ => Err(PyValueError::new_err("kind must be 'lines', 'points' or 'any'")),
    }
}

/// Read the geometry column of a stream of Arrow record batches.
///
/// Returns the coordinates of every part, where each part starts, the row
/// each part came from, the rows with nothing usable, and the number of rows.
#[pyfunction]
#[pyo3(signature = (source, kind, column=None))]
#[allow(clippy::type_complexity)]
fn read_geometry<'py>(
    py: Python<'py>,
    source: &Bound<'py, PyAny>,
    kind: &str,
    column: Option<&str>,
) -> PyResult<(PointsOut<'py>, IntOut<'py>, IntOut<'py>, IntOut<'py>, i64)> {
    let (reader, want) = (stream(source)?, wanted(kind)?);
    let schema = reader.schema();
    let parts = py
        .allow_threads(|| crate::geoarrow::read_parts(reader, &schema, column, want))
        .map_err(PyValueError::new_err)?;
    Ok((
        points(py, parts.coords)?,
        parts.offsets.into_pyarray(py),
        parts.row.into_pyarray(py),
        parts.invalid.into_pyarray(py),
        parts.rows,
    ))
}

/// The bounding box of each row of a stream of Arrow record batches, as an
/// array of shape (rows, 4), NaN for a row with no geometry.
#[pyfunction]
#[pyo3(signature = (source, column=None))]
fn geometry_bounds<'py>(
    py: Python<'py>,
    source: &Bound<'py, PyAny>,
    column: Option<&str>,
) -> PyResult<Bound<'py, PyArray2<f64>>> {
    let reader = stream(source)?;
    let schema = reader.schema();
    let boxes = py
        .allow_threads(|| {
            crate::geoarrow::read_parts(reader, &schema, column, Want::Any).map(|p| crate::geoarrow::bounds(&p))
        })
        .map_err(PyValueError::new_err)?;
    let n = boxes.len() / 4;
    boxes.into_pyarray(py).reshape([n, 4])
}

/// The tile each point belongs to, in a tiling given as a tree of splits.
#[pyfunction]
fn tile_owners<'py>(
    py: Python<'py>,
    axis: Int<'py>,
    split: Float<'py>,
    low: Int<'py>,
    high: Int<'py>,
    xy: Points<'py>,
) -> PyResult<IntOut<'py>> {
    let tiling = Tiling {
        axis: axis.as_slice()?,
        split: split.as_slice()?,
        low: low.as_slice()?,
        high: high.as_slice()?,
    };
    Ok(crate::tiles::owners(&tiling, xy.as_slice()?).into_pyarray(py))
}

/// Every (box, tile) where a box reaches into a tile. Boxes have shape (n, 4).
#[pyfunction]
fn tile_reaches<'py>(
    py: Python<'py>,
    axis: Int<'py>,
    split: Float<'py>,
    low: Int<'py>,
    high: Int<'py>,
    boxes: PyReadonlyArray2<'py, f64>,
) -> PyResult<(IntOut<'py>, IntOut<'py>)> {
    let tiling = Tiling {
        axis: axis.as_slice()?,
        split: split.as_slice()?,
        low: low.as_slice()?,
        high: high.as_slice()?,
    };
    let (rows, tiles) = crate::tiles::reaches(&tiling, boxes.as_slice()?);
    Ok((rows.into_pyarray(py), tiles.into_pyarray(py)))
}

#[pymodule]
#[pyo3(name = "_native")]
fn native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(components, module)?)?;
    module.add_function(wrap_pyfunction!(group_index, module)?)?;
    module.add_function(wrap_pyfunction!(components_link, module)?)?;
    module.add_function(wrap_pyfunction!(components_settle, module)?)?;
    module.add_function(wrap_pyfunction!(split, module)?)?;
    module.add_function(wrap_pyfunction!(segment_crossings, module)?)?;
    module.add_function(wrap_pyfunction!(point_pairs, module)?)?;
    module.add_function(wrap_pyfunction!(line_measures, module)?)?;
    module.add_function(wrap_pyfunction!(locate, module)?)?;
    module.add_function(wrap_pyfunction!(sync_ends, module)?)?;
    module.add_function(wrap_pyfunction!(extend_ends, module)?)?;
    module.add_function(wrap_pyfunction!(points_near_lines, module)?)?;
    module.add_function(wrap_pyfunction!(nearest_lines, module)?)?;
    module.add_function(wrap_pyfunction!(nearest_points, module)?)?;
    module.add_function(wrap_pyfunction!(read_geometry, module)?)?;
    module.add_function(wrap_pyfunction!(geometry_bounds, module)?)?;
    module.add_function(wrap_pyfunction!(tile_owners, module)?)?;
    module.add_function(wrap_pyfunction!(tile_reaches, module)?)?;
    Ok(())
}
