//! Where lines run alongside each other, and how far apart whole lines are.

use rayon::prelude::*;
use robust::{orient2d, Coord};

use crate::measures::{line_measures, place};
use crate::nearest::{nearest_on_segment, Point, Segments};
use crate::rtree::Queue;

/// Stretches where one line runs near another. For stretch `k`: the two
/// lines, `a[k] < b[k]`; the stretch of `a` that is near `b`, from
/// `near_start` to `near_end` along `a`; the two intervals that face each
/// other, from `start_a` to `end_a` along `a` and from `start_b` to `end_b`
/// along `b`; whether the lines run opposite ways there; and how far the
/// interval of `a` strays from `b`. All places are distances along a line.
#[derive(Default)]
pub struct Overlaps {
    pub a: Vec<i64>,
    pub b: Vec<i64>,
    pub near_start: Vec<f64>,
    pub near_end: Vec<f64>,
    pub start_a: Vec<f64>,
    pub end_a: Vec<f64>,
    pub start_b: Vec<f64>,
    pub end_b: Vec<f64>,
    pub reversed: Vec<bool>,
    pub distance: Vec<f64>,
}

/// One stretch: the lines, then the pairs of places in the order of `Overlaps`.
type Stretch = (u32, u32, [f64; 2], [f64; 2], [f64; 2], bool, f64);

const CHUNK: usize = 1024;

/// Find, for every pair of lines, the stretches where the earlier line (`a`)
/// runs within `tolerance` of the later one (`b`).
///
/// The part of `a` near `b` is worked out exactly, segment by segment: the
/// places within `tolerance` of one segment of `b` form a convex shape (a
/// rectangle with a half disc on each end), so the part of one segment of `a`
/// inside it is a single interval, found by solving for where the segment
/// enters and leaves. The intervals from every segment of `b` are put
/// together along `a`, joining any that touch or overlap, to give the
/// stretches `near_start..near_end`. A stretch with no length (where the
/// lines only touch at the full tolerance) is left out.
///
/// With a `tolerance` of 0 a stretch is where the two lines lie exactly on
/// top of each other, decided with exact predicates: lines that only cross
/// or touch at a point give nothing.
///
/// Each stretch is then turned into two intervals that face each other. Its
/// two ends are moved to the nearest places on `b`, which gives
/// `start_b..end_b`, and those places are moved back to the nearest places on
/// `a`, which gives `start_a..end_a`. So where `a` carries on past the end of
/// `b`, the interval of `a` stops level with the end of `b`. Where a line is
/// equally near at two places, the earlier along it is taken. The intervals
/// can be shorter than the stretch, and have no length where the lines only
/// cross: it is for the caller to leave out those too short to matter.
///
/// `reversed` says that the lines run opposite ways along the stretch.
/// `distance` is the farthest that `a` strays from `b` between `start_a` and
/// `end_a`, measured at those two places, at the vertices of `a` between
/// them, and at the ends of the stretch if they lie between them.
///
/// A line is not compared with itself. Stretches are sorted by `a`, then
/// `b`, then `near_start`.
///
/// Lines are worked on in parallel. Memory: 44 bytes per segment for the
/// index and 16 bytes per vertex for distances along lines; for each thread,
/// 24 bytes for each pair of segments near each other on the line being
/// worked on; and the stretches found.
pub fn line_overlaps(coords: &[f64], offsets: &[i64], tolerance: f64) -> Overlaps {
    let lines = Lines::new(coords, offsets, tolerance);
    let found: Vec<Vec<Stretch>> = (0..offsets.len().saturating_sub(1))
        .into_par_iter()
        .chunks(CHUNK)
        .map(|chunk| {
            let mut out = Vec::new();
            let (mut stack, mut queue, mut near) = (Vec::new(), Queue::new(), Vec::new());
            for a in chunk {
                lines.near(a, tolerance, &mut stack, &mut near);
                for &(b, from, to) in &near {
                    out.push(lines.facing(a, b as usize, from, to, &mut queue));
                }
            }
            out
        })
        .collect();

    let total = found.iter().map(Vec::len).sum();
    let mut out = Overlaps::default();
    for column in [&mut out.a, &mut out.b] {
        column.reserve_exact(total);
    }
    for column in [
        &mut out.near_start,
        &mut out.near_end,
        &mut out.start_a,
        &mut out.end_a,
        &mut out.start_b,
        &mut out.end_b,
        &mut out.distance,
    ] {
        column.reserve_exact(total);
    }
    out.reversed.reserve_exact(total);
    for (a, b, near, on_a, on_b, reversed, distance) in found.into_iter().flatten() {
        out.a.push(a as i64);
        out.b.push(b as i64);
        out.near_start.push(near[0]);
        out.near_end.push(near[1]);
        out.start_a.push(on_a[0]);
        out.end_a.push(on_a[1]);
        out.start_b.push(on_b[0]);
        out.end_b.push(on_b[1]);
        out.reversed.push(reversed);
        out.distance.push(distance);
    }
    out
}

/// Lines, with an index over their segments and distances along them.
struct Lines<'a> {
    segments: Segments<'a>,
    offsets: &'a [i64],
    seglen: Vec<f64>,
    measure: Vec<f64>,
    /// The segments of line `l` are `first[l]..first[l + 1]`.
    first: Vec<u32>,
    /// How far to look in the index for the nearest place on a line, before looking along all of it.
    reach: f64,
}

impl<'a> Lines<'a> {
    fn new(coords: &'a [f64], offsets: &'a [i64], tolerance: f64) -> Self {
        let segments = Segments::new(coords, offsets);
        let measures = line_measures(coords, offsets);
        let mut first = vec![0u32; offsets.len().max(1)];
        for &line in &segments.line {
            first[line as usize + 1] += 1;
        }
        for l in 1..first.len() {
            first[l] += first[l - 1];
        }
        // a little further than the tolerance, to allow for rounding
        let largest = coords.iter().fold(0.0f64, |most, c| most.max(c.abs()));
        Lines {
            segments,
            offsets,
            seglen: measures.seglen,
            measure: measures.measure,
            first,
            reach: tolerance + 1e-9 * largest,
        }
    }

    fn vertex(&self, v: usize) -> Point {
        [self.segments.coords[2 * v], self.segments.coords[2 * v + 1]]
    }

    /// The distance along its line of the place a fraction along a segment.
    /// An end of a segment has exactly the distance of the vertex there.
    fn along(&self, segment: u32, frac: f64) -> f64 {
        let v = self.segments.start[segment as usize] as usize;
        self.measure[v] + frac * self.seglen[v]
    }

    /// The coordinate of the place a distance along a line.
    fn at(&self, line: usize, distance: f64) -> Point {
        let (first, last) = (self.offsets[line] as usize, self.offsets[line + 1] as usize - 1);
        let v = (first + self.measure[first..=last].partition_point(|&m| m <= distance))
            .saturating_sub(1)
            .clamp(first, last - 1);
        let frac = if self.seglen[v] > 0.0 {
            ((distance - self.measure[v]) / self.seglen[v]).clamp(0.0, 1.0)
        } else {
            0.0
        };
        place(self.segments.coords, v, frac)
    }

    /// The stretches of line `a` within `tolerance` of each later line: that
    /// line, and where the stretch starts and ends along `a`. Sorted.
    fn near(&self, a: usize, tolerance: f64, stack: &mut Vec<usize>, near: &mut Vec<(u32, f64, f64)>) {
        near.clear();
        for segment in self.first[a]..self.first[a + 1] {
            let (p, q) = self.segments.ends(segment);
            let query = [
                p[0].min(q[0]) - tolerance,
                p[1].min(q[1]) - tolerance,
                p[0].max(q[0]) + tolerance,
                p[1].max(q[1]) + tolerance,
            ];
            self.segments.tree.search(&query, stack, |other| {
                let b = self.segments.line[other as usize];
                if b as usize > a {
                    let (c, d) = self.segments.ends(other);
                    if let Some((from, to)) = near_interval(p, q, c, d, tolerance) {
                        near.push((b, self.along(segment, from), self.along(segment, to)));
                    }
                }
            });
        }
        near.sort_unstable_by(|x, y| x.0.cmp(&y.0).then(x.1.total_cmp(&y.1)).then(x.2.total_cmp(&y.2)));
        // join intervals that touch or overlap, and drop what has no length
        let mut kept = 0;
        let mut current: Option<(u32, f64, f64)> = None;
        for i in 0..near.len() {
            let next = near[i];
            if let Some(open) = current.as_mut().filter(|open| open.0 == next.0 && next.1 <= open.2) {
                open.2 = open.2.max(next.2);
            } else if let Some(done) = current.replace(next).filter(|done| done.2 > done.1) {
                near[kept] = done;
                kept += 1;
            }
        }
        if let Some(done) = current.filter(|done| done.2 > done.1) {
            near[kept] = done;
            kept += 1;
        }
        near.truncate(kept);
    }

    /// The nearest place on a line to a point: the distance along the line,
    /// the coordinate, and the distance from the point. Where the line is
    /// equally near at two places, the earlier. The line must have length.
    fn nearest(&self, line: usize, p: Point, queue: &mut Queue) -> (f64, Point, f64) {
        let on_line = |segment: u32| {
            (self.segments.line[segment as usize] as usize == line).then(|| self.segments.nearest_place(segment, p).2)
        };
        let segment = match self.segments.tree.nearest(p, self.reach, queue, on_line) {
            Some((segment, _)) => segment,
            // the line is not that close: look along all of it
            None => {
                let mut best = (self.first[line], f64::INFINITY);
                for segment in self.first[line]..self.first[line + 1] {
                    let distance = self.segments.nearest_place(segment, p).2;
                    if distance < best.1 {
                        best = (segment, distance);
                    }
                }
                best.0
            }
        };
        let (frac, xy, distance) = self.segments.nearest_place(segment, p);
        (self.along(segment, frac), xy, distance)
    }

    /// Turn a stretch of `a` near `b` into intervals of each that face each other.
    fn facing(&self, a: usize, b: usize, from: f64, to: f64, queue: &mut Queue) -> Stretch {
        let ends = [self.at(a, from), self.at(a, to)];
        // each end of the stretch, moved onto b, and from there back onto a
        let on_b = ends.map(|p| self.nearest(b, p, queue));
        let on_a = on_b.map(|(_, q, _)| self.nearest(a, q, queue));
        let reversed = (on_b[0].0 > on_b[1].0) != (on_a[0].0 > on_a[1].0);
        let (low, high) = (on_a[0].0.min(on_a[1].0), on_a[0].0.max(on_a[1].0));

        let mut distance = 0.0f64;
        for (_, p, _) in on_a {
            distance = distance.max(self.nearest(b, p, queue).2);
        }
        for (at, (_, _, gap)) in [from, to].into_iter().zip(on_b) {
            if low <= at && at <= high {
                distance = distance.max(gap);
            }
        }
        let (first, end) = (self.offsets[a] as usize, self.offsets[a + 1] as usize);
        let inside = first + self.measure[first..end].partition_point(|&m| m < low);
        for v in (inside..end).take_while(|&v| self.measure[v] <= high) {
            distance = distance.max(self.nearest(b, self.vertex(v), queue).2);
        }
        (
            a as u32,
            b as u32,
            [from, to],
            [low, high],
            [on_b[0].0.min(on_b[1].0), on_b[0].0.max(on_b[1].0)],
            reversed,
            distance,
        )
    }
}

/// The part of the segment from `p` to `q` that is within `tolerance` of the
/// segment from `c` to `d`, as fractions along `p`-`q`, if any of it is.
/// Neither segment may have zero length.
///
/// With a tolerance of 0 this is the part of `p`-`q` that lies along `c`-`d`,
/// decided exactly; segments that are not in line with each other give nothing.
fn near_interval(p: Point, q: Point, c: Point, d: Point, tolerance: f64) -> Option<(f64, f64)> {
    let along = [q[0] - p[0], q[1] - p[1]];
    let (from, to) = if tolerance > 0.0 {
        // the places within tolerance of c-d are a rectangle about it and a disc
        // about each end; together they are convex, so the parts of p-q inside
        // each make up one interval
        let other = [d[0] - c[0], d[1] - c[1]];
        let offset = [p[0] - c[0], p[1] - c[1]];
        let length = other[0].hypot(other[1]);
        let mut inside = (f64::NEG_INFINITY, f64::INFINITY);
        // between the ends of c-d, measured along it
        clip(
            &mut inside,
            offset[0] * other[0] + offset[1] * other[1],
            along[0] * other[0] + along[1] * other[1],
            0.0,
            length * length,
        );
        // no further than tolerance to either side of it
        clip(
            &mut inside,
            other[0] * offset[1] - other[1] * offset[0],
            other[0] * along[1] - other[1] * along[0],
            -tolerance * length,
            tolerance * length,
        );
        let mut hull = (f64::INFINITY, f64::NEG_INFINITY);
        for piece in [
            Some(inside),
            in_disc(p, along, c, tolerance),
            in_disc(p, along, d, tolerance),
        ] {
            if let Some((from, to)) = piece.filter(|(from, to)| from <= to) {
                hull = (hull.0.min(from), hull.1.max(to));
            }
        }
        hull
    } else {
        let side = |r: Point| {
            orient2d(
                Coord { x: p[0], y: p[1] },
                Coord { x: q[0], y: q[1] },
                Coord { x: r[0], y: r[1] },
            )
        };
        if side(c) != 0.0 || side(d) != 0.0 {
            return None;
        }
        // all four ends are on one line: place c and d along p-q by the
        // coordinate that changes most, which is exact where ends coincide
        let axis = usize::from(along[1].abs() > along[0].abs());
        let (at_c, at_d) = ((c[axis] - p[axis]) / along[axis], (d[axis] - p[axis]) / along[axis]);
        (at_c.min(at_d), at_c.max(at_d))
    };
    let (from, to) = (from.max(0.0), to.min(1.0));
    (from <= to).then_some((from, to))
}

/// Narrow an interval of `t` to where `low <= start + t * rate <= high`.
fn clip(interval: &mut (f64, f64), start: f64, rate: f64, low: f64, high: f64) {
    if rate == 0.0 {
        if start < low || start > high {
            *interval = (f64::INFINITY, f64::NEG_INFINITY);
        }
        return;
    }
    let (one, other) = ((low - start) / rate, (high - start) / rate);
    *interval = (interval.0.max(one.min(other)), interval.1.min(one.max(other)));
}

/// Where the endless line from `p` in the direction `along` is within `radius` of `centre`.
fn in_disc(p: Point, along: Point, centre: Point, radius: f64) -> Option<(f64, f64)> {
    let offset = [p[0] - centre[0], p[1] - centre[1]];
    let a = along[0] * along[0] + along[1] * along[1];
    let b = along[0] * offset[0] + along[1] * offset[1];
    let c = offset[0] * offset[0] + offset[1] * offset[1] - radius * radius;
    let root = b * b - a * c;
    (root >= 0.0).then(|| ((-b - root.sqrt()) / a, (-b + root.sqrt()) / a))
}

/// The discrete Hausdorff distance between pairs of lines, given by position.
///
/// This is the larger of two distances: the farthest that any vertex of line
/// `a` is from line `b`, and the farthest that any vertex of `b` is from `a`.
/// Only vertices are measured from (though to anywhere on the other line), as
/// GEOS does by default, so this can be less than the true Hausdorff distance
/// where a long segment bows away from the other line. A line with no
/// vertices gives a distance that is not a number.
///
/// Pairs are worked on in parallel, each by comparing every vertex of one
/// line with every segment of the other. Memory: the output only.
pub fn hausdorff_distance(coords: &[f64], offsets: &[i64], a: &[i64], b: &[i64]) -> Vec<f64> {
    let line = |l: i64| &coords[2 * offsets[l as usize] as usize..2 * offsets[l as usize + 1] as usize];
    a.par_iter()
        .zip(b.par_iter())
        .with_min_len(64)
        .map(|(&a, &b)| {
            let (a, b) = (line(a), line(b));
            if a.is_empty() || b.is_empty() {
                return f64::NAN;
            }
            farthest(a, b).max(farthest(b, a))
        })
        .collect()
}

/// The farthest that any vertex of one line is from another line.
fn farthest(from: &[f64], to: &[f64]) -> f64 {
    let mut most = 0.0f64;
    for p in from.chunks_exact(2) {
        let p = [p[0], p[1]];
        let mut least = (to[0] - p[0]).hypot(to[1] - p[1]);
        for segment in to.windows(4).step_by(2) {
            if least <= most {
                break; // this vertex cannot be the farthest
            }
            least = least.min(nearest_on_segment(p, [segment[0], segment[1]], [segment[2], segment[3]]).2);
        }
        most = most.max(least);
    }
    most
}

#[cfg(test)]
mod tests {
    use super::*;

    fn close(found: &[f64], expected: &[f64]) {
        assert_eq!(found.len(), expected.len(), "{found:?} is not {expected:?}");
        for (f, e) in found.iter().zip(expected) {
            assert!((f - e).abs() < 1e-12, "{found:?} is not {expected:?}");
        }
    }

    #[test]
    fn part_of_a_segment_near_another() {
        let (p, q) = ([0.0, 0.0], [10.0, 0.0]);
        // alongside, a little way off: level with the far segment, and a bit more round its start
        let (from, to) = near_interval(p, q, [4.0, 0.3], [14.0, 0.3], 0.5).unwrap();
        close(&[from, to], &[0.36, 1.0]);
        // a segment standing off to one side, its near end 1 away: only the disc about that end reaches
        let (from, to) = near_interval(p, q, [5.0, 1.0], [5.0, 4.0], 2.0).unwrap();
        close(&[from, to], &[0.5 - 0.03f64.sqrt(), 0.5 + 0.03f64.sqrt()]);
        // crossing at right angles: the width of the rectangle
        let (from, to) = near_interval(p, q, [5.0, -5.0], [5.0, 5.0], 0.5).unwrap();
        close(&[from, to], &[0.45, 0.55]);
        // exactly the tolerance away all along, and too far away
        assert_eq!(near_interval(p, q, [0.0, 1.0], [10.0, 1.0], 1.0), Some((0.0, 1.0)));
        assert_eq!(near_interval(p, q, [0.0, 1.5], [10.0, 1.5], 1.0), None);
        assert_eq!(near_interval(p, q, [12.0, 0.0], [15.0, 0.0], 1.0), None);
    }

    #[test]
    fn part_of_a_segment_exactly_on_another() {
        let (p, q) = ([0.0, 0.0], [3.0, 6.0]);
        assert_eq!(near_interval(p, q, [1.0, 2.0], [4.0, 8.0], 0.0), Some((1.0 / 3.0, 1.0)));
        assert_eq!(near_interval(p, q, [4.0, 8.0], [-1.0, -2.0], 0.0), Some((0.0, 1.0)));
        // touching end to end, crossing, and in line but apart
        assert_eq!(near_interval(p, q, [3.0, 6.0], [4.0, 8.0], 0.0), Some((1.0, 1.0)));
        assert_eq!(near_interval(p, q, [0.0, 4.0], [2.0, 0.0], 0.0), None);
        assert_eq!(near_interval(p, q, [4.0, 8.0], [5.0, 10.0], 0.0), None);
    }

    #[test]
    fn lines_alongside_each_other() {
        // b starts 4 along a, 0.1 to one side, and carries on past its end
        let coords = [0.0, 0.0, 10.0, 0.0, 4.0, 0.1, 14.0, 0.1];
        let found = line_overlaps(&coords, &[0, 2, 4], 0.5);
        assert_eq!((found.a, found.b), (vec![0], vec![1]));
        // a comes within reach of the start of b a little before it is level with it
        close(&found.near_start, &[4.0 - 0.24f64.sqrt()]);
        close(&found.near_end, &[10.0]);
        close(&[found.start_a[0], found.end_a[0]], &[4.0, 10.0]);
        close(&[found.start_b[0], found.end_b[0]], &[0.0, 6.0]);
        assert_eq!(found.reversed, vec![false]);
        close(&found.distance, &[0.1]);

        // the same with b running the other way
        let coords = [0.0, 0.0, 10.0, 0.0, 14.0, 0.1, 4.0, 0.1];
        let found = line_overlaps(&coords, &[0, 2, 4], 0.5);
        close(&[found.start_a[0], found.end_a[0]], &[4.0, 10.0]);
        close(&[found.start_b[0], found.end_b[0]], &[4.0, 10.0]);
        assert_eq!(found.reversed, vec![true]);
    }

    #[test]
    fn lines_that_only_cross_face_each_other_at_one_place() {
        let coords = [0.0, 0.0, 10.0, 0.0, 5.0, -5.0, 5.0, 5.0];
        let found = line_overlaps(&coords, &[0, 2, 4], 0.5);
        close(&[found.near_start[0], found.near_end[0]], &[4.5, 5.5]);
        close(&[found.start_a[0], found.end_a[0]], &[5.0, 5.0]);
        close(&[found.start_b[0], found.end_b[0]], &[5.0, 5.0]);
        assert!(line_overlaps(&coords, &[0, 2, 4], 0.0).a.is_empty());
    }

    #[test]
    fn a_line_that_leaves_and_comes_back_gives_two_stretches() {
        // a runs along b, goes off up a side road and round a block, and comes back
        let a = [0.0, 0.0, 4.0, 0.0, 4.0, 5.0, 6.0, 5.0, 6.0, 0.0, 10.0, 0.0];
        let b = [0.0, 0.5, 10.0, 0.5];
        let coords = [a.as_slice(), b.as_slice()].concat();
        let found = line_overlaps(&coords, &[0, 6, 8], 1.0);
        assert_eq!((found.a, found.b), (vec![0, 0], vec![1, 1]));
        close(&found.near_start, &[0.0, 14.5]);
        close(&found.near_end, &[5.5, 20.0]);
        // b crosses the side road half a unit up it
        close(&found.start_a, &[0.0, 15.5]);
        close(&found.end_a, &[4.5, 20.0]);
        close(&found.start_b, &[0.0, 6.0]);
        close(&found.end_b, &[4.0, 10.0]);
        assert_eq!(found.reversed, vec![false, false]);
        close(&found.distance, &[0.5, 0.5]);
    }

    #[test]
    fn exact_overlap_across_vertices() {
        // a: three segments along the x axis; b: lies on a from 1 to 5, then turns away; c: crosses both
        let a = [0.0, 0.0, 2.0, 0.0, 4.0, 0.0, 6.0, 0.0];
        let b = [1.0, 0.0, 3.0, 0.0, 5.0, 0.0, 5.0, 3.0];
        let c = [2.0, -1.0, 2.0, 1.0];
        let coords = [a.as_slice(), b.as_slice(), c.as_slice()].concat();
        let found = line_overlaps(&coords, &[0, 4, 8, 10], 0.0);
        assert_eq!((found.a, found.b), (vec![0], vec![1]));
        assert_eq!((found.near_start, found.near_end), (vec![1.0], vec![5.0]));
        assert_eq!((found.start_a, found.end_a), (vec![1.0], vec![5.0]));
        assert_eq!((found.start_b, found.end_b), (vec![0.0], vec![4.0]));
        assert_eq!(found.distance, vec![0.0]);
    }

    #[test]
    fn no_lines_and_lines_of_no_length() {
        assert!(line_overlaps(&[], &[0], 1.0).a.is_empty());
        assert!(line_overlaps(&[], &[], 1.0).a.is_empty());
        let coords = [1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 3.0, 1.0];
        assert!(line_overlaps(&coords, &[0, 2, 4], 0.5).a.is_empty());
    }

    #[test]
    fn hausdorff_takes_the_larger_of_the_two_ways() {
        // line 0 is flat; line 1 rises to a peak 3 above it; line 2 is a short part of line 0;
        // line 3 is a single place
        let coords = [
            0.0, 0.0, 4.0, 0.0, // 0
            0.0, 1.0, 2.0, 3.0, 4.0, 1.0, // 1
            0.0, 0.0, 1.0, 0.0, // 2
            4.0, 3.0, 4.0, 3.0, // 3
        ];
        let offsets = [0, 2, 5, 7, 9, 9];
        let found = hausdorff_distance(&coords, &offsets, &[0, 1, 0, 2, 0, 0], &[1, 0, 2, 0, 3, 0]);
        assert_eq!(found, vec![3.0, 3.0, 3.0, 3.0, 5.0, 0.0]);
        assert!(hausdorff_distance(&coords, &offsets, &[0], &[4])[0].is_nan());
        assert!(hausdorff_distance(&coords, &offsets, &[], &[]).is_empty());
    }
}
