//! A static R-tree packed along a Hilbert curve.
//!
//! Built once from all boxes, then only queried. This is the layout of
//! "flatbush": items are sorted by the Hilbert value of their box centre and
//! grouped bottom-up into nodes of `NODE_SIZE` children. It has no pointers
//! and no per-node allocation: memory is 36 bytes per item plus about 7% for
//! the upper levels, in two flat arrays.

const NODE_SIZE: usize = 16;

/// `[min_x, min_y, max_x, max_y]`
pub type Box2 = [f64; 4];

pub struct PackedRTree {
    boxes: Vec<Box2>,
    /// For an item: its position in the input. For a node: the position of its first child.
    indices: Vec<u32>,
    level_bounds: Vec<usize>,
    num_items: usize,
}

impl PackedRTree {
    pub fn new(items: &[Box2]) -> Self {
        let num_items = items.len();
        assert!(num_items < (u32::MAX as usize) / 2, "too many items for one index");
        let mut level_bounds = vec![num_items];
        let mut num_nodes = num_items;
        let mut count = num_items;
        while count > 1 || level_bounds.len() == 1 {
            count = count.div_ceil(NODE_SIZE).max(1);
            num_nodes += count;
            level_bounds.push(num_nodes);
            if count == 1 {
                break;
            }
        }

        // order items along a Hilbert curve through their centres
        let mut extent = [f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
        for b in items {
            extent = [
                extent[0].min(b[0]),
                extent[1].min(b[1]),
                extent[2].max(b[2]),
                extent[3].max(b[3]),
            ];
        }
        let scale = |low: f64, high: f64| if high > low { 65535.0 / (high - low) } else { 0.0 };
        let (scale_x, scale_y) = (scale(extent[0], extent[2]), scale(extent[1], extent[3]));
        let mut order: Vec<(u32, u32)> = items
            .iter()
            .enumerate()
            .map(|(i, b)| {
                let x = (scale_x * ((b[0] + b[2]) / 2.0 - extent[0])) as u32;
                let y = (scale_y * ((b[1] + b[3]) / 2.0 - extent[1])) as u32;
                (hilbert(x, y), i as u32)
            })
            .collect();
        order.sort_unstable();

        let mut boxes: Vec<Box2> = Vec::with_capacity(num_nodes);
        let mut indices: Vec<u32> = Vec::with_capacity(num_nodes);
        for &(_, i) in &order {
            boxes.push(items[i as usize]);
            indices.push(i);
        }
        drop(order);

        // build each level from the one below
        let mut pos = 0;
        for &end in &level_bounds[..level_bounds.len() - 1] {
            while pos < end {
                let first_child = pos;
                let mut union = boxes[pos];
                let node_end = (pos + NODE_SIZE).min(end);
                for b in &boxes[pos..node_end] {
                    union = [
                        union[0].min(b[0]),
                        union[1].min(b[1]),
                        union[2].max(b[2]),
                        union[3].max(b[3]),
                    ];
                }
                pos = node_end;
                boxes.push(union);
                indices.push(first_child as u32);
            }
        }
        PackedRTree {
            boxes,
            indices,
            level_bounds,
            num_items,
        }
    }

    /// Call `visit` with the input position of every item whose box touches `query`.
    /// `stack` is scratch space, reused between calls.
    pub fn search(&self, query: &Box2, stack: &mut Vec<usize>, mut visit: impl FnMut(u32)) {
        if self.num_items == 0 {
            return;
        }
        stack.clear();
        let mut node = self.boxes.len() - 1;
        loop {
            let level_end = self.level_bounds[self.level_bounds.partition_point(|&bound| bound <= node)];
            let end = (node + NODE_SIZE).min(level_end);
            for pos in node..end {
                let b = &self.boxes[pos];
                if query[2] < b[0] || query[3] < b[1] || query[0] > b[2] || query[1] > b[3] {
                    continue;
                }
                if node >= self.num_items {
                    stack.push(self.indices[pos] as usize);
                } else {
                    visit(self.indices[pos]);
                }
            }
            match stack.pop() {
                Some(next) => node = next,
                None => break,
            }
        }
    }
}

/// An entry in the queue of a nearest search: a distance, then boxes before
/// exact distances, then position, so that ties go to the lowest position.
#[derive(PartialEq)]
pub struct Candidate(f64, bool, u32);

impl Eq for Candidate {}

impl Ord for Candidate {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        // reversed: the heap gives the largest, and the nearest is wanted
        other
            .0
            .total_cmp(&self.0)
            .then(other.1.cmp(&self.1))
            .then(other.2.cmp(&self.2))
    }
}

impl PartialOrd for Candidate {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

pub type Queue = std::collections::BinaryHeap<Candidate>;

impl PackedRTree {
    /// Find the item nearest to a point, no further than `max_distance`.
    ///
    /// `distance` gives the true distance from the point to an item, or
    /// `None` to pass over it. Among items equally near, the one earliest in
    /// the input is returned. `queue` is scratch space, reused between calls.
    pub fn nearest(
        &self,
        point: [f64; 2],
        max_distance: f64,
        queue: &mut Queue,
        mut distance: impl FnMut(u32) -> Option<f64>,
    ) -> Option<(u32, f64)> {
        if self.num_items == 0 {
            return None;
        }
        queue.clear();
        queue.push(Candidate(0.0, false, (self.boxes.len() - 1) as u32));
        while let Some(Candidate(d, exact, pos)) = queue.pop() {
            if exact {
                return Some((pos, d));
            }
            let pos = pos as usize;
            if pos < self.num_items {
                let item = self.indices[pos];
                if let Some(d) = distance(item).filter(|&d| d <= max_distance) {
                    queue.push(Candidate(d, true, item));
                }
                continue;
            }
            let first = self.indices[pos] as usize;
            let level_end = self.level_bounds[self.level_bounds.partition_point(|&bound| bound <= first)];
            for child in first..(first + NODE_SIZE).min(level_end) {
                let b = &self.boxes[child];
                let dx = (b[0] - point[0]).max(point[0] - b[2]).max(0.0);
                let dy = (b[1] - point[1]).max(point[1] - b[3]).max(0.0);
                let d = dx.hypot(dy);
                if d <= max_distance {
                    queue.push(Candidate(d, false, child as u32));
                }
            }
        }
        None
    }
}

/// Position along a Hilbert curve of a point on a 2^16 by 2^16 grid.
fn hilbert(x: u32, y: u32) -> u32 {
    let (mut x, mut y) = (x.min(65535), y.min(65535));
    let mut d = 0u32;
    let mut s = 1u32 << 15;
    while s > 0 {
        let rx = u32::from(x & s > 0);
        let ry = u32::from(y & s > 0);
        d += s * s * ((3 * rx) ^ ry);
        if ry == 0 {
            if rx == 1 {
                x = 65535 - x;
                y = 65535 - y;
            }
            std::mem::swap(&mut x, &mut y);
        }
        s >>= 1;
    }
    d
}

#[cfg(test)]
mod tests {
    use super::*;

    fn brute(items: &[Box2], q: &Box2) -> Vec<u32> {
        (0..items.len() as u32)
            .filter(|&i| {
                let b = items[i as usize];
                !(q[2] < b[0] || q[3] < b[1] || q[0] > b[2] || q[1] > b[3])
            })
            .collect()
    }

    #[test]
    fn nearest_matches_brute_force() {
        let mut state = 7u64;
        let mut next = || {
            state = state
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        let points: Vec<[f64; 2]> = (0..3000)
            .map(|_| [(next() * 50.0).round(), (next() * 50.0).round()])
            .collect();
        let items: Vec<Box2> = points.iter().map(|p| [p[0], p[1], p[0], p[1]]).collect();
        let tree = PackedRTree::new(&items);
        let mut queue = Queue::new();
        for _ in 0..500 {
            let q = [next() * 60.0 - 5.0, next() * 60.0 - 5.0];
            let far = |i: u32| (points[i as usize][0] - q[0]).hypot(points[i as usize][1] - q[1]);
            // pass over every third item, to test that too
            let found = tree.nearest(q, f64::INFINITY, &mut queue, |i| (i % 3 != 0).then(|| far(i)));
            let expected = (0..points.len() as u32)
                .filter(|i| i % 3 != 0)
                .map(|i| (far(i), i))
                .min_by(|x, y| x.partial_cmp(y).unwrap())
                .map(|(d, i)| (i, d));
            assert_eq!(found, expected);
            assert_eq!(tree.nearest(q, -1.0, &mut queue, |i| Some(far(i))), None);
        }
    }

    #[test]
    fn search_matches_brute_force() {
        // a deterministic scatter of boxes of mixed sizes
        let mut state = 12345u64;
        let mut next = || {
            state = state
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            ((state >> 33) as f64) / ((1u64 << 31) as f64)
        };
        for &n in &[0usize, 1, 15, 16, 17, 300, 5000] {
            let items: Vec<Box2> = (0..n)
                .map(|_| {
                    let (x, y, w, h) = (next() * 100.0, next() * 100.0, next() * 3.0, next() * 30.0);
                    [x, y, x + w, y + h]
                })
                .collect();
            let tree = PackedRTree::new(&items);
            let mut stack = Vec::new();
            for q in items
                .iter()
                .take(200)
                .chain(std::iter::once(&[-1.0, -1.0, 200.0, 200.0]))
            {
                let mut found = Vec::new();
                tree.search(q, &mut stack, |i| found.push(i));
                found.sort_unstable();
                assert_eq!(found, brute(&items, q));
            }
        }
    }
}
