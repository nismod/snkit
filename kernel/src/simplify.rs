//! Lines with fewer vertices, no further than a tolerance from the original.

use rayon::prelude::*;

type Point = [f64; 2];

/// Simplify every line with the Douglas-Peucker algorithm.
///
/// The first and last vertex of a line are always kept. Between two kept
/// vertices, the vertex farthest from the straight segment joining them is
/// kept if it is farther than `tolerance`, and the two sides are then
/// treated the same way; otherwise every vertex between them is dropped. So
/// no dropped vertex is farther than `tolerance` from the simplified line,
/// and a `tolerance` of 0 drops only vertices that lie exactly on it.
///
/// Distances are measured to the segment, not to the endless line through
/// it, and among vertices equally far the earliest is kept: these are the
/// choices GEOS makes, and the vertices kept are those that
/// `shapely.simplify(..., preserve_topology=False)` keeps.
///
/// A line that would be left with no length is returned unchanged. That can
/// only be a line that ends where it starts, with no vertex farther than
/// `tolerance` from that place: a small closed ring, or a line that goes out
/// and back. A line of fewer than three vertices is unchanged.
///
/// Returns new `coords` and `offsets`, with as many lines, in the same order.
///
/// Lines are worked on in parallel. Memory: one byte per input vertex, and
/// the output, written once.
pub fn simplify_lines(coords: &[f64], offsets: &[i64], tolerance: f64) -> (Vec<f64>, Vec<i64>) {
    // whether to keep each vertex, from the first vertex of the first line
    let base = offsets.first().map_or(0, |&first| first as usize);
    let mut keep = vec![true; offsets.last().map_or(0, |&last| last as usize) - base];
    // a piece of `keep` for each line, so that lines can be worked on in parallel
    let mut pieces = Vec::with_capacity(offsets.len().saturating_sub(1));
    let mut rest = &mut keep[..];
    for line in offsets.windows(2) {
        let (piece, others) = rest.split_at_mut((line[1] - line[0]) as usize);
        pieces.push((line[0] as usize, piece));
        rest = others;
    }
    pieces
        .into_par_iter()
        .with_min_len(256)
        .for_each_init(Vec::new, |stack, (first, keep)| {
            simplify_line(&coords[2 * first..2 * (first + keep.len())], tolerance, keep, stack)
        });

    let kept = keep.iter().filter(|&&k| k).count();
    let mut out = Vec::with_capacity(2 * kept);
    let mut out_offsets = Vec::with_capacity(offsets.len());
    for (v, _) in keep.iter().enumerate().filter(|(_, &k)| k) {
        out.extend_from_slice(&coords[2 * (base + v)..2 * (base + v) + 2]);
    }
    // each new offset is the number of vertices kept before the old one
    let mut before = 0;
    let mut done = 0;
    for &offset in offsets {
        before += keep[done..offset as usize - base].iter().filter(|&&k| k).count();
        done = offset as usize - base;
        out_offsets.push(before as i64);
    }
    (out, out_offsets)
}

/// Mark the vertices of one line to keep. `stack` is scratch space.
fn simplify_line(coords: &[f64], tolerance: f64, keep: &mut [bool], stack: &mut Vec<(usize, usize)>) {
    let n = keep.len();
    if n < 3 {
        return;
    }
    let point = |v: usize| -> Point { [coords[2 * v], coords[2 * v + 1]] };
    stack.clear();
    stack.push((0, n - 1));
    let mut dropped_all = false;
    while let Some((i, j)) = stack.pop() {
        if i + 1 >= j {
            continue;
        }
        let (a, b) = (point(i), point(j));
        let (mut farthest, mut most) = (i, -1.0);
        for k in i + 1..j {
            let distance = distance_to_segment(point(k), a, b);
            if distance > most {
                (farthest, most) = (k, distance);
            }
        }
        if most <= tolerance {
            keep[i + 1..j].fill(false);
            dropped_all = (i, j) == (0, n - 1);
        } else {
            stack.push((farthest, j));
            stack.push((i, farthest));
        }
    }
    // only the two ends are left, and they are one place: a line with no length
    if dropped_all && point(0) == point(n - 1) {
        keep.fill(true);
    }
}

/// The distance from a point to a segment, computed as GEOS computes it so
/// that the same vertex is found to be the farthest.
fn distance_to_segment(p: Point, a: Point, b: Point) -> f64 {
    let far = |q: Point| ((p[0] - q[0]) * (p[0] - q[0]) + (p[1] - q[1]) * (p[1] - q[1])).sqrt();
    if a == b {
        return far(a);
    }
    let d = [b[0] - a[0], b[1] - a[1]];
    let len2 = d[0] * d[0] + d[1] * d[1];
    let r = ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / len2;
    if r <= 0.0 {
        return far(a);
    }
    if r >= 1.0 {
        return far(b);
    }
    let s = ((a[1] - p[1]) * d[0] - (a[0] - p[0]) * d[1]) / len2;
    s.abs() * len2.sqrt()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vertices_within_tolerance_are_dropped() {
        // line 0 has a small kink and a large one; line 1 is two vertices
        let coords = [0.0, 0.0, 1.0, 0.1, 2.0, 0.0, 3.0, 2.0, 4.0, 0.0, 9.0, 9.0, 9.0, 8.0];
        let offsets = [0, 5, 7];
        let (simple, simple_offsets) = simplify_lines(&coords, &offsets, 0.5);
        assert_eq!(simple, vec![0.0, 0.0, 2.0, 0.0, 3.0, 2.0, 4.0, 0.0, 9.0, 9.0, 9.0, 8.0]);
        assert_eq!(simple_offsets, vec![0, 4, 6]);
        // a larger tolerance leaves only the ends; none at all leaves everything
        assert_eq!(simplify_lines(&coords, &offsets, 2.0).1, vec![0, 2, 4]);
        assert_eq!(
            simplify_lines(&coords, &offsets, 0.0),
            (coords.to_vec(), offsets.to_vec())
        );
    }

    #[test]
    fn zero_tolerance_drops_vertices_exactly_on_the_line() {
        let coords = [0.0, 0.0, 1.0, 0.0, 2.0, 0.0, 2.0, 5.0];
        let (simple, offsets) = simplify_lines(&coords, &[0, 4], 0.0);
        assert_eq!(simple, vec![0.0, 0.0, 2.0, 0.0, 2.0, 5.0]);
        assert_eq!(offsets, vec![0, 3]);
    }

    #[test]
    fn distance_is_to_the_segment_not_the_endless_line() {
        // the middle vertex is on the line through the ends, but well beyond the far end
        let coords = [0.0, 0.0, 5.0, 0.0, 1.0, 0.0];
        assert_eq!(simplify_lines(&coords, &[0, 3], 1.0).1, vec![0, 3]);
        assert_eq!(simplify_lines(&coords, &[0, 3], 4.0).1, vec![0, 2]);
    }

    #[test]
    fn a_closed_line_keeps_its_shape_or_is_left_alone() {
        // a square, starting and ending at the origin
        let square = [0.0, 0.0, 4.0, 0.0, 4.0, 4.0, 0.0, 4.0, 0.0, 0.0];
        // the far corner is kept, and then the corners either side of it
        assert_eq!(simplify_lines(&square, &[0, 5], 1.0).0, square.to_vec());
        assert_eq!(
            simplify_lines(&square, &[0, 5], 3.0).0,
            vec![0.0, 0.0, 4.0, 4.0, 0.0, 0.0]
        );
        // every vertex is within tolerance of the start: the line would have no length
        assert_eq!(simplify_lines(&square, &[0, 5], 6.0), (square.to_vec(), vec![0, 5]));
    }

    #[test]
    fn empty_input_and_offsets_that_start_late() {
        assert_eq!(simplify_lines(&[], &[0], 1.0), (vec![], vec![0]));
        assert_eq!(simplify_lines(&[], &[], 1.0), (vec![], vec![]));
        let coords = [7.0, 7.0, 0.0, 0.0, 1.0, 0.0, 2.0, 0.0];
        let (simple, offsets) = simplify_lines(&coords, &[1, 4], 0.5);
        assert_eq!(simple, vec![0.0, 0.0, 2.0, 0.0]);
        assert_eq!(offsets, vec![0, 2]);
    }
}
