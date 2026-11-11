//! Calling any function of the kernel by name, with arguments by name.
//!
//! A binding to another language need only pass a name and a table of plain
//! arrays one way, and a list of named arrays back the other: it need not
//! declare each function. The conformance cases in `conformance/kernel` are
//! written in just this form, so every binding can run them.

use std::collections::HashMap;

/// An argument or a result.
#[derive(Clone, Debug, PartialEq)]
pub enum Value {
    Number(f64),
    Bool(bool),
    /// Whole numbers: positions, counts, labels.
    Ints(Vec<i64>),
    Floats(Vec<f64>),
    Bools(Vec<bool>),
    /// Coordinates, interleaved `x0, y0, x1, y1, ...`.
    Points(Vec<f64>),
}

pub type Arguments = HashMap<String, Value>;
pub type Results = Vec<(&'static str, Value)>;

/// The functions that can be called.
pub const FUNCTIONS: &[&str] = &[
    "components",
    "group_index",
    "line_measures",
    "locate",
    "sync_ends",
    "extend_ends",
    "split",
    "segment_crossings",
    "point_pairs",
    "points_near_lines",
    "nearest_lines",
    "nearest_points",
    "simplify_lines",
    "line_overlaps",
    "hausdorff_distance",
];

struct Given<'a>(&'a Arguments);

impl Given<'_> {
    fn get(&self, name: &str) -> Result<&Value, String> {
        self.0.get(name).ok_or_else(|| format!("missing argument '{name}'"))
    }

    /// Whole numbers, however they were passed.
    fn ints(&self, name: &str) -> Result<Vec<i64>, String> {
        match self.get(name)? {
            Value::Ints(v) => Ok(v.clone()),
            Value::Floats(v) | Value::Points(v) if v.iter().all(|x| x.fract() == 0.0) => {
                Ok(v.iter().map(|&x| x as i64).collect())
            }
            _ => Err(format!("argument '{name}' must be an array of whole numbers")),
        }
    }

    fn ints_or_empty(&self, name: &str) -> Result<Vec<i64>, String> {
        if self.0.contains_key(name) {
            self.ints(name)
        } else {
            Ok(Vec::new())
        }
    }

    fn floats(&self, name: &str) -> Result<Vec<f64>, String> {
        match self.get(name)? {
            Value::Floats(v) | Value::Points(v) => Ok(v.clone()),
            Value::Ints(v) => Ok(v.iter().map(|&x| x as f64).collect()),
            _ => Err(format!("argument '{name}' must be an array of numbers")),
        }
    }

    /// Coordinates, interleaved.
    fn points(&self, name: &str) -> Result<Vec<f64>, String> {
        let flat = self.floats(name)?;
        if flat.len() % 2 == 0 {
            Ok(flat)
        } else {
            Err(format!("argument '{name}' must hold an x and a y for each point"))
        }
    }

    fn number(&self, name: &str) -> Result<f64, String> {
        match self.get(name)? {
            Value::Number(x) => Ok(*x),
            _ => Err(format!("argument '{name}' must be a number")),
        }
    }

    /// A distance that may be left out, meaning no limit.
    fn limit(&self, name: &str) -> Result<f64, String> {
        if self.0.contains_key(name) {
            self.number(name)
        } else {
            Ok(f64::INFINITY)
        }
    }

    fn flag(&self, name: &str) -> Result<bool, String> {
        match self.0.get(name) {
            None => Ok(false),
            Some(Value::Bool(b)) => Ok(*b),
            Some(_) => Err(format!("argument '{name}' must be true or false")),
        }
    }

    /// Offsets, checked against the coordinates they index.
    fn lines(&self) -> Result<(Vec<f64>, Vec<i64>), String> {
        let (coords, offsets) = (self.points("coords")?, self.ints("offsets")?);
        let ordered = offsets.windows(2).all(|w| w[0] <= w[1]);
        let within =
            offsets.first().is_none_or(|&f| f >= 0) && offsets.last().is_none_or(|&l| l as usize <= coords.len() / 2);
        if offsets.is_empty() || !ordered || !within {
            return Err("'offsets' must rise from 0 to no more than the number of coordinates".to_string());
        }
        Ok((coords, offsets))
    }
}

fn places(found: crate::nearest::Places) -> Results {
    vec![
        ("point", Value::Ints(found.point)),
        ("line", Value::Ints(found.line)),
        ("vertex", Value::Ints(found.vertex)),
        ("frac", Value::Floats(found.frac)),
        ("xy", Value::Points(found.xy)),
        ("distance", Value::Floats(found.distance)),
    ]
}

/// Call a function of the kernel by name.
///
/// Arguments have the names used in `conformance/README.md`; results come
/// back in the order given there. Positions passed in are checked to be in
/// range only where the function itself needs them to be: a binding should
/// not be handed data it has not checked.
pub fn call(function: &str, arguments: &Arguments) -> Result<Results, String> {
    let given = Given(arguments);
    Ok(match function {
        "components" => {
            let (n, a, b) = (given.number("n")? as usize, given.ints("a")?, given.ints("b")?);
            if a.len() != b.len() || a.iter().chain(&b).any(|&i| i < 0 || i as usize >= n) {
                return Err("'a' and 'b' must be of one length and name items below 'n'".to_string());
            }
            vec![("labels", Value::Ints(crate::components::components(n, &a, &b)))]
        }
        "group_index" => {
            let (group, is_first) = crate::measures::group_index(&given.ints("labels")?);
            vec![("group", Value::Ints(group)), ("is_first", Value::Bools(is_first))]
        }
        "line_measures" => {
            let (coords, offsets) = given.lines()?;
            let m = crate::measures::line_measures(&coords, &offsets);
            vec![
                ("seglen", Value::Floats(m.seglen)),
                ("measure", Value::Floats(m.measure)),
                ("length", Value::Floats(m.length)),
            ]
        }
        "locate" => {
            let (coords, offsets) = given.lines()?;
            let (vertex, frac, xy) = crate::measures::locate(
                &coords,
                &offsets,
                &given.floats("seglen")?,
                &given.floats("measure")?,
                &given.ints("line")?,
                &given.floats("at")?,
            );
            vec![
                ("vertex", Value::Ints(vertex)),
                ("frac", Value::Floats(frac)),
                ("xy", Value::Points(xy)),
            ]
        }
        "sync_ends" => {
            let (coords, offsets) = given.lines()?;
            let moved = crate::measures::sync_ends(
                &coords,
                &offsets,
                &given.points("xy")?,
                &given.ints("src")?,
                &given.ints("dst")?,
            );
            vec![("coords", Value::Points(moved))]
        }
        "extend_ends" => {
            let (coords, offsets) = given.lines()?;
            let (coords, offsets) = crate::measures::extend_ends(
                &coords,
                &offsets,
                &given.points("xy")?,
                &given.ints("src")?,
                &given.ints("dst")?,
            );
            vec![("coords", Value::Points(coords)), ("offsets", Value::Ints(offsets))]
        }
        "split" => {
            let (coords, offsets) = given.lines()?;
            let out = crate::split::split(
                &coords,
                &offsets,
                &given.ints("src")?,
                &given.ints("dst")?,
                &given.ints("cut_edge")?,
                &given.ints("cut_seg")?,
                &given.points("cut_xy")?,
                &given.ints("cut_node")?,
            );
            vec![
                ("coords", Value::Points(out.coords)),
                ("offsets", Value::Ints(out.offsets)),
                ("src", Value::Ints(out.src)),
                ("dst", Value::Ints(out.dst)),
                ("parent", Value::Ints(out.parent)),
            ]
        }
        "segment_crossings" => {
            let (coords, offsets) = given.lines()?;
            let out = crate::crossings::segment_crossings(&coords, &offsets, given.flag("end_to_end")?);
            vec![
                ("seg_a", Value::Ints(out.seg_a)),
                ("seg_b", Value::Ints(out.seg_b)),
                ("frac_a", Value::Floats(out.frac_a)),
                ("frac_b", Value::Floats(out.frac_b)),
                ("xy", Value::Points(out.xy)),
            ]
        }
        "point_pairs" => {
            let (a, b) = crate::points::point_pairs(&given.points("xy")?, given.number("tolerance")?);
            vec![("a", Value::Ints(a)), ("b", Value::Ints(b))]
        }
        "points_near_lines" => {
            let (coords, offsets) = given.lines()?;
            places(crate::nearest::points_near_lines(
                &given.points("xy")?,
                &coords,
                &offsets,
                given.number("tolerance")?,
            ))
        }
        "nearest_lines" => {
            let (coords, offsets) = given.lines()?;
            places(crate::nearest::nearest_lines(
                &given.points("xy")?,
                &given.ints_or_empty("node")?,
                &coords,
                &offsets,
                &given.ints_or_empty("src")?,
                &given.ints_or_empty("dst")?,
                given.limit("max_distance")?,
            ))
        }
        "nearest_points" => {
            let nearest = crate::nearest::nearest_points(
                &given.points("xy")?,
                &given.points("targets")?,
                given.limit("max_distance")?,
            );
            vec![("nearest", Value::Ints(nearest))]
        }
        "simplify_lines" => {
            let (coords, offsets) = given.lines()?;
            let (coords, offsets) = crate::simplify::simplify_lines(&coords, &offsets, given.number("tolerance")?);
            vec![("coords", Value::Points(coords)), ("offsets", Value::Ints(offsets))]
        }
        "line_overlaps" => {
            let (coords, offsets) = given.lines()?;
            let out = crate::overlaps::line_overlaps(&coords, &offsets, given.number("tolerance")?);
            vec![
                ("a", Value::Ints(out.a)),
                ("b", Value::Ints(out.b)),
                ("near_start", Value::Floats(out.near_start)),
                ("near_end", Value::Floats(out.near_end)),
                ("start_a", Value::Floats(out.start_a)),
                ("end_a", Value::Floats(out.end_a)),
                ("start_b", Value::Floats(out.start_b)),
                ("end_b", Value::Floats(out.end_b)),
                ("reversed", Value::Bools(out.reversed)),
                ("distance", Value::Floats(out.distance)),
            ]
        }
        "hausdorff_distance" => {
            let (coords, offsets) = given.lines()?;
            let (a, b) = (given.ints("a")?, given.ints("b")?);
            let lines = offsets.len() as i64 - 1;
            if a.len() != b.len() || a.iter().chain(&b).any(|&l| l < 0 || l >= lines) {
                return Err("'a' and 'b' must be of one length and name lines that exist".to_string());
            }
            vec![(
                "distance",
                Value::Floats(crate::overlaps::hausdorff_distance(&coords, &offsets, &a, &b)),
            )]
        }
        other => return Err(format!("no function named '{other}' in the kernel")),
    })
}
