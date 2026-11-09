//! Where line segments meet.

use rayon::prelude::*;
use robust::{orient2d, Coord};

use crate::rtree::{Box2, PackedRTree};

/// Places where pairs of segments meet. For meeting `k`: the two segments
/// (each named by the vertex position where it starts), the fraction along
/// each, and the coordinate.
#[derive(Default)]
pub struct Crossings {
    pub seg_a: Vec<i64>,
    pub seg_b: Vec<i64>,
    pub frac_a: Vec<f64>,
    pub frac_b: Vec<f64>,
    pub xy: Vec<f64>,
}

type Point = [f64; 2];

/// Two segments, the fraction along each, and the coordinate.
type Meeting = (u32, u32, f64, f64, Point);

/// Find every place where two segments of the given lines meet.
///
/// A pair that crosses gives one meeting. A pair that touches gives one for
/// each end of one segment lying on the other, located exactly at that end
/// (fraction exactly 0 or 1, coordinate exactly the end's own). Segments of
/// zero length are ignored. `seg_a < seg_b` always; meetings are sorted and
/// each is reported once.
///
/// Whether segments meet is decided with exact orientation predicates, so the
/// answer does not depend on which way round the question is put. Each pair is
/// also put into a fixed order and direction before the coordinate of a
/// crossing is computed, so that coordinate does not depend on the order of
/// the input or the direction of the lines.
///
/// Two kinds of meeting are left out, because on a clean network they are
/// nearly all there is to find: the vertex shared by two successive segments
/// of one line, and, unless `end_to_end` is set, places where two lines meet
/// at an end of each.
///
/// The work is done tile by tile. The area is divided into a grid of tiles
/// holding about `TILE_SEGMENTS` segments each; a segment belongs to every
/// tile it passes through, and a meeting is reported by the tile its
/// coordinate falls in, so it is found exactly once. Tiles are searched in
/// parallel, each with a small index of its own that is thrown away
/// afterwards.
///
/// Memory: 4 bytes per segment and 4 per segment-in-tile for the whole input,
/// about 70 bytes per segment for each tile being worked on, plus the
/// meetings found.
pub fn segment_crossings(coords: &[f64], offsets: &[i64], end_to_end: bool) -> Crossings {
    let point = |v: usize| -> Point { [coords[2 * v], coords[2 * v + 1]] };
    // each segment by the vertex it starts at
    let mut starts: Vec<u32> = Vec::new();
    let mut extent = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
    assert!(
        coords.len() / 2 <= u32::MAX as usize,
        "more than 2^32 vertices: divide the network first"
    );
    for edge in offsets.windows(2) {
        for v in edge[0] as usize..edge[1] as usize {
            let p = point(v);
            extent = [
                extent[0].min(p[0]),
                extent[1].min(p[1]),
                extent[2].max(p[0]),
                extent[3].max(p[1]),
            ];
            if v + 1 < edge[1] as usize && p != point(v + 1) {
                starts.push(v as u32);
            }
        }
    }
    let grid = Grid::new(extent, starts.len());

    // which segments are in each tile: count, then fill
    let mut tile_start = vec![0u32; grid.tiles() + 1];
    for &v in &starts {
        grid.tiles_of(point(v as usize), point(v as usize + 1), |tile| {
            tile_start[tile + 1] += 1
        });
    }
    for tile in 0..grid.tiles() {
        tile_start[tile + 1] += tile_start[tile];
    }
    let mut members = vec![0u32; tile_start[grid.tiles()] as usize];
    let mut next = tile_start.clone();
    for &v in &starts {
        grid.tiles_of(point(v as usize), point(v as usize + 1), |tile| {
            members[next[tile] as usize] = v;
            next[tile] += 1;
        });
    }
    drop(next);
    drop(starts);

    let found: Vec<Vec<Meeting>> = (0..grid.tiles())
        .into_par_iter()
        .map(|tile| {
            let segments = &members[tile_start[tile] as usize..tile_start[tile + 1] as usize];
            let mut out = Vec::new();
            if segments.len() < 2 {
                return out;
            }
            let boxes: Vec<Box2> = segments
                .iter()
                .map(|&v| {
                    let (p, q) = (point(v as usize), point(v as usize + 1));
                    [p[0].min(q[0]), p[1].min(q[1]), p[0].max(q[0]), p[1].max(q[1])]
                })
                .collect();
            let tree = PackedRTree::new(&boxes);
            let mut stack = Vec::new();
            let mut hits: Vec<u32> = Vec::new();
            for (i, &a) in segments.iter().enumerate() {
                hits.clear();
                tree.search(&boxes[i], &mut stack, |j| {
                    if j as usize > i {
                        hits.push(j);
                    }
                });
                let a = a as usize;
                for &j in &hits {
                    let b = segments[j as usize] as usize;
                    meetings(point(a), point(a + 1), point(b), point(b + 1), |t, u, xy| {
                        if grid.tile_of(xy) != tile {
                            return; // another tile reports this one
                        }
                        if (t == 0.0 || t == 1.0) && (u == 0.0 || u == 1.0) {
                            // both lines have a vertex here
                            let (va, vb) = (a + usize::from(t == 1.0), b + usize::from(u == 1.0));
                            let (line_a, end_a) = locate(offsets, va);
                            let (line_b, end_b) = locate(offsets, vb);
                            if (va == vb && line_a == line_b) || (end_a && end_b && !end_to_end) {
                                return;
                            }
                        }
                        out.push((a as u32, b as u32, t, u, xy));
                    });
                }
            }
            out
        })
        .collect();

    let total = found.iter().map(Vec::len).sum();
    let mut result = Crossings {
        seg_a: Vec::with_capacity(total),
        seg_b: Vec::with_capacity(total),
        frac_a: Vec::with_capacity(total),
        frac_b: Vec::with_capacity(total),
        xy: Vec::with_capacity(2 * total),
    };
    let mut all: Vec<Meeting> = found.into_iter().flatten().collect();
    all.sort_unstable_by(|x, y| {
        (x.0, x.1)
            .cmp(&(y.0, y.1))
            .then(x.2.total_cmp(&y.2))
            .then(x.3.total_cmp(&y.3))
    });
    // two segments touching vertex to vertex are found from both sides
    all.dedup_by(|x, y| (x.0, x.1, x.2, x.3) == (y.0, y.1, y.2, y.3));
    for (a, b, t, u, xy) in all {
        result.seg_a.push(a as i64);
        result.seg_b.push(b as i64);
        result.frac_a.push(t);
        result.frac_b.push(u);
        result.xy.extend_from_slice(&xy);
    }
    result
}

/// Aim for this many segments in each tile.
const TILE_SEGMENTS: usize = 16384;

/// A grid of tiles over the extent of the input.
struct Grid {
    origin: Point,
    size: Point,
    columns: usize,
    rows: usize,
    /// Slack when deciding which tiles a segment passes through, far larger
    /// than any rounding in a computed coordinate and far smaller than a tile.
    slack: f64,
}

impl Grid {
    fn new(extent: Box2, segments: usize) -> Self {
        let (width, height) = ((extent[2] - extent[0]).max(0.0), (extent[3] - extent[1]).max(0.0));
        let wanted = (segments / TILE_SEGMENTS).max(1) as f64;
        let (mut columns, mut rows) = (1usize, 1usize);
        if width > 0.0 && height > 0.0 {
            columns = ((wanted * width / height).sqrt().round() as usize).max(1);
            rows = ((wanted / columns as f64).round() as usize).max(1);
        } else if width > 0.0 {
            columns = wanted as usize;
        } else if height > 0.0 {
            rows = wanted as usize;
        }
        let reach = extent.iter().fold(width.max(height), |m, v| m.max(v.abs()));
        Grid {
            origin: [extent[0], extent[1]],
            size: [
                (width / columns as f64).max(f64::MIN_POSITIVE),
                (height / rows as f64).max(f64::MIN_POSITIVE),
            ],
            columns,
            rows,
            slack: if reach.is_finite() { reach * 1e-9 } else { 0.0 },
        }
    }

    fn tiles(&self) -> usize {
        self.columns * self.rows
    }

    fn column(&self, x: f64) -> usize {
        (((x - self.origin[0]) / self.size[0]).floor().max(0.0) as usize).min(self.columns - 1)
    }

    fn row(&self, y: f64) -> usize {
        (((y - self.origin[1]) / self.size[1]).floor().max(0.0) as usize).min(self.rows - 1)
    }

    fn tile_of(&self, p: Point) -> usize {
        self.row(p[1]) * self.columns + self.column(p[0])
    }

    /// Call `visit` with every tile that the segment `p-q` passes through
    /// (or passes within `slack` of). Row by row, so that a long slanting
    /// segment is not given every tile of its bounding box.
    fn tiles_of(&self, p: Point, q: Point, mut visit: impl FnMut(usize)) {
        let (low_y, high_y) = (p[1].min(q[1]), p[1].max(q[1]));
        let slope = (q[0] - p[0]) / (q[1] - p[1]);
        for row in self.row(low_y - self.slack)..=self.row(high_y + self.slack) {
            let (mut from_x, mut to_x) = (p[0].min(q[0]), p[0].max(q[0]));
            if slope.is_finite() && self.rows > 1 {
                // the part of the segment inside this row
                let bottom = (self.origin[1] + row as f64 * self.size[1] - self.slack).clamp(low_y, high_y);
                let top = (self.origin[1] + (row + 1) as f64 * self.size[1] + self.slack).clamp(low_y, high_y);
                let (x1, x2) = (p[0] + (bottom - p[1]) * slope, p[0] + (top - p[1]) * slope);
                from_x = from_x.max(x1.min(x2));
                to_x = to_x.min(x1.max(x2));
            }
            for column in self.column(from_x - self.slack)..=self.column(to_x + self.slack) {
                visit(row * self.columns + column);
            }
        }
    }
}

/// Which line a vertex belongs to, and whether it is an end of that line.
fn locate(offsets: &[i64], vertex: usize) -> (usize, bool) {
    let line = offsets.partition_point(|&start| start as usize <= vertex) - 1;
    (
        line,
        vertex == offsets[line] as usize || vertex + 1 == offsets[line + 1] as usize,
    )
}

fn orient(a: Point, b: Point, c: Point) -> f64 {
    orient2d(
        Coord { x: a[0], y: a[1] },
        Coord { x: b[0], y: b[1] },
        Coord { x: c[0], y: c[1] },
    )
}

/// Report where segment `p-p2` meets segment `q-q2`, as (fraction along the
/// first, fraction along the second, coordinate).
fn meetings(p: Point, p2: Point, q: Point, q2: Point, mut report: impl FnMut(f64, f64, Point)) {
    // put the pair into a fixed form: each segment running from its lesser
    // end, the lesser segment first
    let flip_p = p2 < p;
    let flip_q = q2 < q;
    let (a, a2) = if flip_p { (p2, p) } else { (p, p2) };
    let (b, b2) = if flip_q { (q2, q) } else { (q, q2) };
    let swap = (a, a2) > (b, b2);
    let (a, a2, b, b2) = if swap { (b, b2, a, a2) } else { (a, a2, b, b2) };
    let mut emit = |t: f64, u: f64, xy: Point| {
        let (t, u) = if swap { (u, t) } else { (t, u) };
        report(if flip_p { 1.0 - t } else { t }, if flip_q { 1.0 - u } else { u }, xy);
    };

    // which side of b-b2 the ends of a-a2 lie, and the reverse
    let o1 = orient(b, b2, a);
    let o2 = orient(b, b2, a2);
    let o3 = orient(a, a2, b);
    let o4 = orient(a, a2, b2);
    if o1 * o2 < 0.0 && o3 * o4 < 0.0 {
        // Where they cross is computed with ordinary arithmetic, written out
        // so that every implementation of this kernel gets the same bits.
        let cross = |d: Point, from: Point, to: Point| d[0] * (to[1] - from[1]) - d[1] * (to[0] - from[0]);
        let (r, s) = ([a2[0] - a[0], a2[1] - a[1]], [b2[0] - b[0], b2[1] - b[1]]);
        let (n1, n2) = (cross(s, b, a), cross(s, b, a2));
        let (n3, n4) = (cross(r, a, b), cross(r, a, b2));
        let t = (n1 / (n1 - n2)).clamp(0.0, 1.0);
        let u = (n3 / (n3 - n4)).clamp(0.0, 1.0);
        emit(t, u, [a[0] + t * (a2[0] - a[0]), a[1] + t * (a2[1] - a[1])]);
        return;
    }
    if o1 == 0.0 && within(a, b, b2) {
        emit(0.0, fraction(a, b, b2), a);
    }
    if o2 == 0.0 && within(a2, b, b2) {
        emit(1.0, fraction(a2, b, b2), a2);
    }
    if o3 == 0.0 && within(b, a, a2) {
        emit(fraction(b, a, a2), 0.0, b);
    }
    if o4 == 0.0 && within(b2, a, a2) {
        emit(fraction(b2, a, a2), 1.0, b2);
    }
}

/// Is a point, known to be in line with a segment, between its ends?
fn within(point: Point, a: Point, b: Point) -> bool {
    (0..2).all(|k| point[k] >= a[k].min(b[k]) && point[k] <= a[k].max(b[k]))
}

/// How far along `a-b` a point on it lies, exactly 0 or 1 at the ends.
fn fraction(point: Point, a: Point, b: Point) -> f64 {
    if point == b {
        return 1.0;
    }
    if point == a {
        return 0.0;
    }
    let d = [b[0] - a[0], b[1] - a[1]];
    (((point[0] - a[0]) * d[0] + (point[1] - a[1]) * d[1]) / (d[0] * d[0] + d[1] * d[1])).clamp(0.0, 1.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(lines: &[&[f64]]) -> Vec<(i64, i64, f64, f64, f64, f64)> {
        let mut coords = Vec::new();
        let mut offsets = vec![0i64];
        for line in lines {
            coords.extend_from_slice(line);
            offsets.push((coords.len() / 2) as i64);
        }
        let c = segment_crossings(&coords, &offsets, false);
        (0..c.seg_a.len())
            .map(|k| {
                (
                    c.seg_a[k],
                    c.seg_b[k],
                    c.frac_a[k],
                    c.frac_b[k],
                    c.xy[2 * k],
                    c.xy[2 * k + 1],
                )
            })
            .collect()
    }

    #[test]
    fn a_crossing() {
        let found = run(&[&[0.0, 0.0, 2.0, 2.0], &[0.0, 2.0, 2.0, 0.0]]);
        assert_eq!(found, vec![(0, 2, 0.5, 0.5, 1.0, 1.0)]);
    }

    #[test]
    fn an_end_on_the_middle_of_another() {
        let found = run(&[&[0.0, 0.0, 2.0, 0.0], &[1.0, 0.0, 1.0, 1.0]]);
        assert_eq!(found, vec![(0, 2, 0.5, 0.0, 1.0, 0.0)]);
    }

    #[test]
    fn ends_meeting_and_corners_are_left_out() {
        let lines: [&[f64]; 2] = [&[0.0, 0.0, 1.0, 0.0, 1.0, 1.0], &[1.0, 1.0, 2.0, 1.0]];
        assert!(run(&lines).is_empty());
        let coords = [0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 1.0, 1.0, 2.0, 1.0];
        let all = segment_crossings(&coords, &[0, 3, 5], true);
        assert_eq!((all.seg_a, all.seg_b), (vec![1], vec![3]));
    }

    #[test]
    fn tiles_find_what_one_index_finds() {
        // enough segments for several tiles; compare with brute force over all pairs
        let mut state = 99u64;
        let mut next = || {
            state = state
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        let lines = 3 * TILE_SEGMENTS;
        let mut coords = Vec::new();
        let mut offsets = vec![0i64];
        for k in 0..lines {
            // mostly short lines, a few very long ones
            let reach = if k % 500 == 0 { 400.0 } else { 3.0 };
            let (x, y) = (next() * 400.0, next() * 400.0);
            coords.extend_from_slice(&[x, y, x + (next() - 0.5) * reach, y + (next() - 0.5) * reach]);
            offsets.push((coords.len() / 2) as i64);
        }
        let tiled = segment_crossings(&coords, &offsets, false);
        assert!(Grid::new([0.0, 0.0, 400.0, 400.0], lines).tiles() > 1);

        let point = |v: usize| [coords[2 * v], coords[2 * v + 1]];
        let boxes: Vec<Box2> = (0..lines)
            .map(|k| {
                let (p, q) = (point(2 * k), point(2 * k + 1));
                [p[0].min(q[0]), p[1].min(q[1]), p[0].max(q[0]), p[1].max(q[1])]
            })
            .collect();
        let tree = PackedRTree::new(&boxes);
        let mut expected = Vec::new();
        let mut stack = Vec::new();
        for i in 0..lines {
            let mut hits = Vec::new();
            tree.search(&boxes[i], &mut stack, |j| hits.push(j as usize));
            hits.sort_unstable();
            for j in hits.into_iter().filter(|&j| j > i) {
                meetings(
                    point(2 * i),
                    point(2 * i + 1),
                    point(2 * j),
                    point(2 * j + 1),
                    |t, u, _| {
                        expected.push((2 * i as i64, 2 * j as i64, t, u));
                    },
                );
            }
        }
        expected.sort_by(|x, y| x.partial_cmp(y).unwrap());
        let got: Vec<_> = (0..tiled.seg_a.len())
            .map(|k| (tiled.seg_a[k], tiled.seg_b[k], tiled.frac_a[k], tiled.frac_b[k]))
            .collect();
        assert!(got.len() > 1_000, "only {} crossings", got.len());
        assert_eq!(got, expected);
    }

    #[test]
    fn nothing_where_lines_are_apart() {
        assert!(run(&[&[0.0, 0.0, 1.0, 0.0], &[0.0, 1.0, 1.0, 1.0]]).is_empty());
    }

    #[test]
    fn same_answer_whichever_way_the_lines_run() {
        let forward = run(&[&[0.1, 0.3, 7.7, 5.1], &[0.2, 4.9, 6.3, 0.7]]);
        let backward = run(&[&[6.3, 0.7, 0.2, 4.9], &[7.7, 5.1, 0.1, 0.3]]);
        assert_eq!(forward.len(), 1);
        assert_eq!((forward[0].4, forward[0].5), (backward[0].4, backward[0].5));
    }
}
