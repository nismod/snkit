//! Reading geometry from Arrow record batches into the kernel's flat arrays.
//!
//! The geometry column may be WKB (binary, large binary or binary view) or a
//! native GeoArrow encoding: points as a struct of `x`, `y` or as a fixed-size
//! list, lines as a list of either, multi-part lines as a list of lists.
//! Extra dimensions are dropped. Any producer of Arrow batches will do: a
//! file reader, a query engine, another language.

use arrow::array::{
    Array, ArrayRef, AsArray, BinaryArray, BinaryViewArray, Float64Array, GenericListArray, LargeBinaryArray,
    OffsetSizeTrait, RecordBatch,
};
use arrow::datatypes::{DataType, Float64Type, Schema};
use arrow::error::ArrowError;

/// What to read the geometry as.
#[derive(Clone, Copy, PartialEq)]
pub enum Want {
    /// Lines of two or more vertices and some length; multi-part lines give one line per part.
    Lines,
    /// Single points.
    Points,
    /// Anything made of points or lines, for measuring its extent.
    Any,
}

/// Geometry read from a stream: each part's vertices, and which row it came from.
#[derive(Default)]
pub struct Parts {
    /// Interleaved coordinates of all parts.
    pub coords: Vec<f64>,
    /// Where each part starts in `coords` (counted in vertices), with a final end.
    pub offsets: Vec<i64>,
    /// The row each part came from.
    pub row: Vec<i64>,
    /// Rows with nothing usable: null, empty, of another kind, or a line of no length.
    pub invalid: Vec<i64>,
    /// Number of rows read.
    pub rows: i64,
}

impl Parts {
    fn new() -> Self {
        Parts {
            offsets: vec![0],
            ..Default::default()
        }
    }

    /// Finish the part whose vertices were just pushed, or discard it.
    /// Returns whether it was kept.
    fn close(&mut self, row: i64, want: Want) -> bool {
        let start = *self.offsets.last().unwrap() as usize;
        let n = self.coords.len() / 2 - start;
        let part = &self.coords[2 * start..];
        let finite = part.iter().all(|v| v.is_finite());
        let ok = finite
            && match want {
                Want::Points => n == 1,
                Want::Any => n >= 1,
                Want::Lines => n >= 2 && part.chunks_exact(2).any(|p| p != &part[..2]),
            };
        if ok {
            self.offsets.push((start + n) as i64);
            self.row.push(row);
        } else {
            self.coords.truncate(2 * start);
        }
        ok
    }
}

/// Find the geometry column: the one named, or else the first that says it
/// is GeoArrow, or else one with a usual name.
pub fn geometry_column(schema: &Schema, name: Option<&str>) -> Result<usize, String> {
    if let Some(name) = name {
        return schema.index_of(name).map_err(|_| format!("no column named '{name}'"));
    }
    let tagged = schema.fields().iter().position(|field| {
        field
            .metadata()
            .get("ARROW:extension:name")
            .is_some_and(|ext| ext.starts_with("geoarrow.") || ext == "ogc.wkb")
    });
    tagged
        .or_else(|| {
            ["geometry", "geom", "wkb_geometry"]
                .iter()
                .find_map(|n| schema.index_of(n).ok())
        })
        .ok_or_else(|| "no geometry column found: name it with column=".to_string())
}

/// Read the geometry column of every batch.
pub fn read_parts(
    batches: impl Iterator<Item = Result<RecordBatch, ArrowError>>,
    schema: &Schema,
    column: Option<&str>,
    want: Want,
) -> Result<Parts, String> {
    let index = geometry_column(schema, column)?;
    let mut parts = Parts::new();
    for batch in batches {
        let batch = batch.map_err(|e| e.to_string())?;
        decode(batch.column(index), want, &mut parts)?;
    }
    Ok(parts)
}

/// The bounding box of each row, as `[min_x, min_y, max_x, max_y]`, NaN for a row with no geometry.
pub fn bounds(parts: &Parts) -> Vec<f64> {
    let mut boxes = vec![f64::NAN; 4 * parts.rows as usize];
    for (k, &row) in parts.row.iter().enumerate() {
        let b = &mut boxes[4 * row as usize..4 * row as usize + 4];
        for p in parts.coords[2 * parts.offsets[k] as usize..2 * parts.offsets[k + 1] as usize].chunks_exact(2) {
            // f64::min ignores NaN, so the first vertex replaces it
            b[0] = b[0].min(p[0]);
            b[1] = b[1].min(p[1]);
            b[2] = b[2].max(p[0]);
            b[3] = b[3].max(p[1]);
        }
    }
    boxes
}

fn decode(array: &ArrayRef, want: Want, parts: &mut Parts) -> Result<(), String> {
    let base = parts.rows;
    parts.rows += array.len() as i64;
    let wkb = |bytes: Option<&[u8]>, row: i64, parts: &mut Parts| {
        let before = parts.row.len();
        if bytes.is_none_or(|b| read_wkb(b, row, want, parts).is_none()) || parts.row.len() == before {
            // a geometry is all or nothing: undo any parts already taken from it
            parts.row.truncate(before);
            parts.offsets.truncate(before + 1);
            parts.coords.truncate(2 * *parts.offsets.last().unwrap() as usize);
            parts.invalid.push(row);
        }
    };
    match array.data_type() {
        DataType::Binary => {
            let a: &BinaryArray = array.as_binary();
            (0..a.len()).for_each(|i| wkb(a.is_valid(i).then(|| a.value(i)), base + i as i64, parts));
        }
        DataType::LargeBinary => {
            let a: &LargeBinaryArray = array.as_binary();
            (0..a.len()).for_each(|i| wkb(a.is_valid(i).then(|| a.value(i)), base + i as i64, parts));
        }
        DataType::BinaryView => {
            let a: &BinaryViewArray = array.as_binary_view();
            (0..a.len()).for_each(|i| wkb(a.is_valid(i).then(|| a.value(i)), base + i as i64, parts));
        }
        DataType::List(_) => native_lists(array.as_list::<i32>(), base, want, parts)?,
        DataType::LargeList(_) => native_lists(array.as_list::<i64>(), base, want, parts)?,
        DataType::Struct(_) | DataType::FixedSizeList(_, _) => {
            let points = Coords::new(array)?;
            for i in 0..array.len() {
                let row = base + i as i64;
                if array.is_valid(i) && want != Want::Lines {
                    parts.coords.extend_from_slice(&points.get(i));
                    if parts.close(row, want) {
                        continue;
                    }
                }
                parts.invalid.push(row);
            }
        }
        other => return Err(format!("cannot read geometry from a column of type {other}")),
    }
    Ok(())
}

/// A native coordinate array: a struct of `x`, `y` arrays, or a fixed-size list of numbers.
enum Coords<'a> {
    Separated(&'a Float64Array, &'a Float64Array),
    Interleaved(&'a Float64Array, usize),
}

impl<'a> Coords<'a> {
    fn new(array: &'a ArrayRef) -> Result<Self, String> {
        let numbers = |a: &'a ArrayRef| {
            a.as_primitive_opt::<Float64Type>()
                .ok_or_else(|| "coordinates must be 64-bit floats".to_string())
        };
        match array.data_type() {
            DataType::Struct(fields) if fields.len() >= 2 => {
                let s = array.as_struct();
                Ok(Coords::Separated(numbers(s.column(0))?, numbers(s.column(1))?))
            }
            DataType::FixedSizeList(_, size) if *size >= 2 => {
                let list = array.as_fixed_size_list();
                Ok(Coords::Interleaved(numbers(list.values())?, *size as usize))
            }
            other => Err(format!("cannot read coordinates from a column of type {other}")),
        }
    }

    fn get(&self, i: usize) -> [f64; 2] {
        match self {
            Coords::Separated(x, y) => [x.value(i), y.value(i)],
            Coords::Interleaved(values, size) => [values.value(i * size), values.value(i * size + 1)],
        }
    }
}

/// Lines as lists of coordinates, or multi-part lines as lists of those.
fn native_lists<O: OffsetSizeTrait>(
    list: &GenericListArray<O>,
    base: i64,
    want: Want,
    parts: &mut Parts,
) -> Result<(), String> {
    let values = list.values();
    let offsets = list.value_offsets();
    let nested = matches!(values.data_type(), DataType::List(_) | DataType::LargeList(_));
    for i in 0..list.len() {
        let row = base + i as i64;
        let (from, to) = (offsets[i].as_usize(), offsets[i + 1].as_usize());
        let before = parts.row.len();
        if list.is_valid(i) && want != Want::Points {
            if nested {
                // each inner list is one part of this row
                let inner = values.slice(from, to - from);
                let mut sub = Parts::new();
                match inner.data_type() {
                    DataType::List(_) => native_lists(inner.as_list::<i32>(), 0, want, &mut sub)?,
                    _ => native_lists(inner.as_list::<i64>(), 0, want, &mut sub)?,
                }
                if sub.invalid.is_empty() {
                    for k in 0..sub.row.len() {
                        parts.coords.extend_from_slice(
                            &sub.coords[2 * sub.offsets[k] as usize..2 * sub.offsets[k + 1] as usize],
                        );
                        parts.close(row, want);
                    }
                }
            } else {
                let coords = Coords::new(values)?;
                (from..to).for_each(|v| parts.coords.extend_from_slice(&coords.get(v)));
                parts.close(row, want);
            }
        }
        if parts.row.len() == before {
            parts.invalid.push(row);
        }
    }
    Ok(())
}

/// Read one WKB geometry, appending its parts. `None` if it is malformed or not wanted.
fn read_wkb(bytes: &[u8], row: i64, want: Want, parts: &mut Parts) -> Option<()> {
    let mut at = 0;
    read_wkb_at(bytes, &mut at, row, want, parts, 0)
}

fn read_wkb_at(bytes: &[u8], at: &mut usize, row: i64, want: Want, parts: &mut Parts, depth: u8) -> Option<()> {
    let little = *bytes.get(*at)? == 1;
    *at += 1;
    let u32_at = |at: &mut usize| -> Option<u32> {
        let b: [u8; 4] = bytes.get(*at..*at + 4)?.try_into().ok()?;
        *at += 4;
        Some(if little {
            u32::from_le_bytes(b)
        } else {
            u32::from_be_bytes(b)
        })
    };
    let f64_at = |at: &mut usize| -> Option<f64> {
        let b: [u8; 8] = bytes.get(*at..*at + 8)?.try_into().ok()?;
        *at += 8;
        Some(if little {
            f64::from_le_bytes(b)
        } else {
            f64::from_be_bytes(b)
        })
    };
    let mut code = u32_at(at)?;
    // extended WKB marks extra dimensions and a reference system in the high bits; ISO adds thousands
    let mut dims = 2 + usize::from(code & 0x8000_0000 != 0) + usize::from(code & 0x4000_0000 != 0);
    if code & 0x2000_0000 != 0 {
        *at += 4;
    }
    code &= 0xffff;
    if code >= 1000 {
        dims = if code >= 3000 { 4 } else { 3 };
        code %= 1000;
    }
    let vertex = |at: &mut usize, parts: &mut Parts| -> Option<()> {
        let (x, y) = (f64_at(at)?, f64_at(at)?);
        *at += 8 * (dims - 2);
        parts.coords.extend_from_slice(&[x, y]);
        Some(())
    };
    match code {
        1 if want != Want::Lines => {
            vertex(at, parts)?;
            parts.close(row, want).then_some(())
        }
        2 if want != Want::Points => {
            let n = u32_at(at)? as usize;
            if bytes.len() < *at + n * dims * 8 {
                return None;
            }
            for _ in 0..n {
                vertex(at, parts)?;
            }
            parts.close(row, want).then_some(())
        }
        4 | 5 | 7 if depth == 0 && (want == Want::Any || (code == 5 && want == Want::Lines)) => {
            let n = u32_at(at)?;
            for _ in 0..n {
                read_wkb_at(bytes, at, row, want, parts, 1)?;
            }
            Some(())
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use arrow::array::{BinaryBuilder, FixedSizeListArray, ListArray, StructArray};
    use arrow::buffer::OffsetBuffer;
    use arrow::datatypes::Field;
    use std::sync::Arc;

    fn wkb_line(points: &[[f64; 2]], z: bool) -> Vec<u8> {
        let mut out = vec![1u8];
        out.extend_from_slice(&(if z { 1002u32 } else { 2u32 }).to_le_bytes());
        out.extend_from_slice(&(points.len() as u32).to_le_bytes());
        for p in points {
            out.extend_from_slice(&p[0].to_le_bytes());
            out.extend_from_slice(&p[1].to_le_bytes());
            if z {
                out.extend_from_slice(&9.0f64.to_le_bytes());
            }
        }
        out
    }

    fn read(array: ArrayRef, want: Want) -> Parts {
        let mut parts = Parts::new();
        decode(&array, want, &mut parts).unwrap();
        parts
    }

    #[test]
    fn wkb_lines_with_nulls_extra_dimensions_and_parts() {
        let mut multi = vec![1u8];
        multi.extend_from_slice(&5u32.to_le_bytes());
        multi.extend_from_slice(&2u32.to_le_bytes());
        multi.extend(wkb_line(&[[5.0, 5.0], [6.0, 5.0]], false));
        multi.extend(wkb_line(&[[7.0, 5.0], [8.0, 5.0], [9.0, 5.0]], false));
        let mut point = vec![1u8];
        point.extend_from_slice(&1u32.to_le_bytes());
        point.extend_from_slice(&1.0f64.to_le_bytes());
        point.extend_from_slice(&2.0f64.to_le_bytes());

        let mut builder = BinaryBuilder::new();
        builder.append_value(wkb_line(&[[0.0, 0.0], [1.0, 0.0]], false));
        builder.append_null();
        builder.append_value(wkb_line(&[[0.0, 1.0], [1.0, 1.0], [2.0, 2.0]], true));
        builder.append_value(&multi);
        builder.append_value(&point);
        builder.append_value(wkb_line(&[[3.0, 3.0], [3.0, 3.0]], false)); // no length
        let array: ArrayRef = Arc::new(builder.finish());

        let lines = read(array.clone(), Want::Lines);
        assert_eq!(lines.offsets, vec![0, 2, 5, 7, 10]);
        assert_eq!(lines.row, vec![0, 2, 3, 3]);
        assert_eq!(lines.invalid, vec![1, 4, 5]);
        assert_eq!(&lines.coords[4..10], &[0.0, 1.0, 1.0, 1.0, 2.0, 2.0]);

        let points = read(array.clone(), Want::Points);
        assert_eq!((points.row, points.coords), (vec![4], vec![1.0, 2.0]));

        let any = read(array, Want::Any);
        assert_eq!(any.invalid, vec![1]);
        let boxes = bounds(&any);
        assert_eq!(&boxes[12..16], &[5.0, 5.0, 9.0, 5.0]);
        assert!(boxes[4].is_nan());
    }

    #[test]
    fn native_lines_separated_and_interleaved() {
        let x = Arc::new(Float64Array::from(vec![0.0, 1.0, 5.0, 6.0, 7.0])) as ArrayRef;
        let y = Arc::new(Float64Array::from(vec![0.0, 0.5, 5.0, 5.0, 8.0])) as ArrayRef;
        let fields = vec![
            Arc::new(Field::new("x", DataType::Float64, false)),
            Arc::new(Field::new("y", DataType::Float64, false)),
        ];
        let coords = StructArray::new(fields.into(), vec![x, y], None);
        let item = Arc::new(Field::new("vertices", coords.data_type().clone(), false));
        let offsets = OffsetBuffer::new(vec![0i32, 2, 2, 5].into());
        let separated: ArrayRef = Arc::new(ListArray::new(item, offsets.clone(), Arc::new(coords), None));
        let lines = read(separated, Want::Lines);
        assert_eq!(
            (lines.offsets.clone(), lines.row.clone(), lines.invalid.clone()),
            (vec![0, 2, 5], vec![0, 2], vec![1])
        );
        assert_eq!(lines.coords, vec![0.0, 0.0, 1.0, 0.5, 5.0, 5.0, 6.0, 5.0, 7.0, 8.0]);

        let flat = Arc::new(Float64Array::from(lines.coords.clone())) as ArrayRef;
        let pair = Arc::new(Field::new("xy", DataType::Float64, false));
        let interleaved = FixedSizeListArray::new(pair, 2, flat, None);
        let item = Arc::new(Field::new("vertices", interleaved.data_type().clone(), false));
        let array: ArrayRef = Arc::new(ListArray::new(item, offsets, Arc::new(interleaved.clone()), None));
        assert_eq!(read(array, Want::Lines).coords, lines.coords);

        let points = read(Arc::new(interleaved), Want::Points);
        assert_eq!(points.row, vec![0, 1, 2, 3, 4]);
        assert_eq!(points.coords, lines.coords);
    }
}
