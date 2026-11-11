//! Which lines, and which points, are near each point.

use rayon::prelude::*;

use crate::rtree::{Box2, PackedRTree, Queue};

/// Places on lines: for match `k`, the point, the line, the vertex starting
/// the segment the place is on, the fraction along that segment, the
/// coordinate of the place and its distance from the point.
#[derive(Default)]
pub struct Places {
    pub point: Vec<i64>,
    pub line: Vec<i64>,
    pub vertex: Vec<i64>,
    pub frac: Vec<f64>,
    pub xy: Vec<f64>,
    pub distance: Vec<f64>,
}

pub(crate) type Point = [f64; 2];
type Place = (u32, u32, f64, Point, f64);

/// The segments of a set of lines, with an index over them. Segments of zero
/// length are left out.
pub(crate) struct Segments<'a> {
    pub coords: &'a [f64],
    /// For each segment: the vertex it starts at, and the line it is part of.
    pub start: Vec<u32>,
    pub line: Vec<u32>,
    pub tree: PackedRTree,
}

/// The nearest place to a point on the segment from `a` to `b`: fraction along, coordinate, distance.
/// At an end of the segment the fraction is exactly 0 or 1 and the coordinate the end's own.
/// A segment of no length is taken at its start.
pub(crate) fn nearest_on_segment(p: Point, a: Point, b: Point) -> (f64, Point, f64) {
    let d = [b[0] - a[0], b[1] - a[1]];
    let t = ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / (d[0] * d[0] + d[1] * d[1]);
    let (t, xy) = if t >= 1.0 {
        (1.0, b)
    } else if t > 0.0 {
        (t, [a[0] + t * d[0], a[1] + t * d[1]])
    } else {
        // also where the segment has no length, and the fraction is not a number
        (0.0, a)
    };
    (t, xy, (xy[0] - p[0]).hypot(xy[1] - p[1]))
}

impl<'a> Segments<'a> {
    pub fn new(coords: &'a [f64], offsets: &[i64]) -> Self {
        assert!(
            coords.len() / 2 <= u32::MAX as usize,
            "more than 2^32 vertices: divide the network first"
        );
        let (mut start, mut line, mut boxes) = (Vec::new(), Vec::new(), Vec::<Box2>::new());
        for (l, ends) in offsets.windows(2).enumerate() {
            for v in ends[0] as usize..(ends[1] as usize).saturating_sub(1) {
                let (p, q) = (
                    [coords[2 * v], coords[2 * v + 1]],
                    [coords[2 * v + 2], coords[2 * v + 3]],
                );
                if p != q {
                    start.push(v as u32);
                    line.push(l as u32);
                    boxes.push([p[0].min(q[0]), p[1].min(q[1]), p[0].max(q[0]), p[1].max(q[1])]);
                }
            }
        }
        Segments {
            coords,
            start,
            line,
            tree: PackedRTree::new(&boxes),
        }
    }

    /// The nearest place on a segment to a point: fraction along, coordinate, distance.
    /// At an end of the segment the fraction is exactly 0 or 1 and the coordinate the end's own.
    pub fn nearest_place(&self, segment: u32, p: Point) -> (f64, Point, f64) {
        let (a, b) = self.ends(segment);
        nearest_on_segment(p, a, b)
    }

    /// The two ends of a segment.
    pub fn ends(&self, segment: u32) -> (Point, Point) {
        let v = self.start[segment as usize] as usize;
        (
            [self.coords[2 * v], self.coords[2 * v + 1]],
            [self.coords[2 * v + 2], self.coords[2 * v + 3]],
        )
    }

    /// Name a place by vertex and fraction, the end of a segment being the start of the next.
    fn place(&self, segment: u32, frac: f64, xy: Point, distance: f64) -> Place {
        let v = self.start[segment as usize];
        let (v, frac) = if frac == 1.0 { (v + 1, 0.0) } else { (v, frac) };
        (self.line[segment as usize], v, frac, xy, distance)
    }
}

fn collect(found: Vec<Vec<(u32, Place)>>) -> Places {
    let total = found.iter().map(Vec::len).sum();
    let mut out = Places {
        point: Vec::with_capacity(total),
        line: Vec::with_capacity(total),
        vertex: Vec::with_capacity(total),
        frac: Vec::with_capacity(total),
        xy: Vec::with_capacity(2 * total),
        distance: Vec::with_capacity(total),
    };
    for (point, (line, vertex, frac, xy, distance)) in found.into_iter().flatten() {
        out.point.push(point as i64);
        out.line.push(line as i64);
        out.vertex.push(vertex as i64);
        out.frac.push(frac);
        out.xy.extend_from_slice(&xy);
        out.distance.push(distance);
    }
    out
}

const CHUNK: usize = 4096;

/// For each point, every line within `tolerance` of it, with the nearest
/// place on that line. Sorted by point, then line. Where a line is equally
/// near at two places, the earlier along the line is given.
pub fn points_near_lines(xy: &[f64], coords: &[f64], offsets: &[i64], tolerance: f64) -> Places {
    let segments = Segments::new(coords, offsets);
    let found = (0..xy.len() / 2)
        .into_par_iter()
        .chunks(CHUNK)
        .map(|points| {
            let mut out = Vec::new();
            let (mut stack, mut hits) = (Vec::new(), Vec::<(u32, f64, u32, f64, Point)>::new());
            for i in points {
                let p = [xy[2 * i], xy[2 * i + 1]];
                hits.clear();
                let query = [p[0] - tolerance, p[1] - tolerance, p[0] + tolerance, p[1] + tolerance];
                segments.tree.search(&query, &mut stack, |segment| {
                    let (frac, place, distance) = segments.nearest_place(segment, p);
                    if distance <= tolerance {
                        hits.push((segments.line[segment as usize], distance, segment, frac, place));
                    }
                });
                hits.sort_unstable_by(|a, b| a.0.cmp(&b.0).then(a.1.total_cmp(&b.1)).then(a.2.cmp(&b.2)));
                hits.dedup_by_key(|hit| hit.0);
                for &(_, distance, segment, frac, place) in &hits {
                    out.push((i as u32, segments.place(segment, frac, place, distance)));
                }
            }
            out
        })
        .collect();
    collect(found)
}

/// For each point, the nearest line no further than `max_distance`, with the
/// nearest place on it. A point with no such line is left out.
///
/// `node` may name, for each point, a node of the network: lines that begin
/// or end at that node (by `src` and `dst`) are then passed over, so that a
/// node is not matched to its own edges. Pass empty slices to consider every line.
pub fn nearest_lines(
    xy: &[f64],
    node: &[i64],
    coords: &[f64],
    offsets: &[i64],
    src: &[i64],
    dst: &[i64],
    max_distance: f64,
) -> Places {
    let segments = Segments::new(coords, offsets);
    let found = (0..xy.len() / 2)
        .into_par_iter()
        .chunks(CHUNK)
        .map(|points| {
            let mut out = Vec::new();
            let mut queue = Queue::new();
            for i in points {
                let p = [xy[2 * i], xy[2 * i + 1]];
                let own = node.get(i).copied().unwrap_or(-1);
                let nearest = segments.tree.nearest(p, max_distance, &mut queue, |segment| {
                    let line = segments.line[segment as usize] as usize;
                    if own >= 0 && (src[line] == own || dst[line] == own) {
                        return None;
                    }
                    Some(segments.nearest_place(segment, p).2)
                });
                if let Some((segment, _)) = nearest {
                    let (frac, place, distance) = segments.nearest_place(segment, p);
                    out.push((i as u32, segments.place(segment, frac, place, distance)));
                }
            }
            out
        })
        .collect();
    collect(found)
}

/// For each point, the position of the nearest of `targets` no further than
/// `max_distance`, or -1. Among targets equally near, the earliest.
pub fn nearest_points(xy: &[f64], targets: &[f64], max_distance: f64) -> Vec<i64> {
    let boxes: Vec<Box2> = targets.chunks_exact(2).map(|t| [t[0], t[1], t[0], t[1]]).collect();
    let tree = PackedRTree::new(&boxes);
    let found: Vec<Vec<i64>> = (0..xy.len() / 2)
        .into_par_iter()
        .chunks(CHUNK)
        .map(|points| {
            let mut queue = Queue::new();
            points
                .into_iter()
                .map(|i| {
                    let p = [xy[2 * i], xy[2 * i + 1]];
                    let far = |t: u32| Some((targets[2 * t as usize] - p[0]).hypot(targets[2 * t as usize + 1] - p[1]));
                    tree.nearest(p, max_distance, &mut queue, far)
                        .map_or(-1, |(target, _)| target as i64)
                })
                .collect()
        })
        .collect();
    found.into_iter().flatten().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    // line 0: (0,0)-(4,0)-(4,4), from node 0 to node 1; line 1: (0,2)-(3,2), from node 2 to node 3
    const COORDS: [f64; 10] = [0.0, 0.0, 4.0, 0.0, 4.0, 4.0, 0.0, 2.0, 3.0, 2.0];
    const OFFSETS: [i64; 3] = [0, 3, 5];

    #[test]
    fn lines_within_tolerance() {
        let found = points_near_lines(&[2.0, 1.0, 9.0, 9.0, 4.5, 2.0], &COORDS, &OFFSETS, 1.0);
        assert_eq!(found.point, vec![0, 0, 2]);
        assert_eq!(found.line, vec![0, 1, 0]);
        assert_eq!(found.vertex, vec![0, 3, 1]);
        assert_eq!(found.frac, vec![0.5, 2.0 / 3.0, 0.5]);
        assert_eq!(found.xy, vec![2.0, 0.0, 2.0, 2.0, 4.0, 2.0]);
        assert_eq!(found.distance, vec![1.0, 1.0, 0.5]);
    }

    #[test]
    fn a_place_on_a_vertex_is_named_by_that_vertex() {
        let found = points_near_lines(&[5.0, -1.0, 4.0, 5.0], &COORDS, &OFFSETS, 2.0);
        assert_eq!(
            (found.line, found.vertex, found.frac),
            (vec![0, 0], vec![1, 2], vec![0.0, 0.0])
        );
        assert_eq!(found.xy, vec![4.0, 0.0, 4.0, 4.0]);
    }

    #[test]
    fn nearest_line_passing_over_own_edges() {
        let points = [0.0, 0.0, 3.5, 2.0, 50.0, 50.0];
        let any = nearest_lines(&points, &[], &COORDS, &OFFSETS, &[], &[], 10.0);
        assert_eq!(
            (any.point, any.line, any.distance),
            (vec![0, 1], vec![0, 0], vec![0.0, 0.5])
        );
        // the first point is node 0, an end of line 0, so its nearest other line is line 1
        let other = nearest_lines(
            &points,
            &[0, -1, -1],
            &COORDS,
            &OFFSETS,
            &[0, 2],
            &[1, 3],
            f64::INFINITY,
        );
        assert_eq!(
            (other.point, other.line, other.vertex),
            (vec![0, 1, 2], vec![1, 0, 0], vec![3, 1, 2])
        );
        assert_eq!(other.distance[0], 2.0);
    }

    #[test]
    fn nearest_point_with_ties_and_limits() {
        let targets = [0.0, 0.0, 2.0, 0.0, 2.0, 0.0];
        assert_eq!(
            nearest_points(&[1.0, 0.0, 1.9, 0.0, 9.0, 0.0], &targets, 5.0),
            vec![0, 1, -1]
        );
        assert_eq!(nearest_points(&[1.0, 0.0], &[], 5.0), vec![-1]);
    }
}
