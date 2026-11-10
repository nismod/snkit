//! Dividing space into tiles by a tree of splits.
//!
//! A tiling is a binary tree. Node `k` splits on `axis[k]` (0 for x, 1 for y)
//! at `split[k]`: places below the split go to `low[k]`, the rest to
//! `high[k]`. A child of `-(t + 1)` is tile `t`. The tiles so made cover the
//! whole plane and do not overlap, so every point belongs to exactly one.
//! Splitting where the data is thick gives tiles of even weight, not even size.

/// A tiling, as arrays describing each node of the tree.
pub struct Tiling<'a> {
    pub axis: &'a [i64],
    pub split: &'a [f64],
    pub low: &'a [i64],
    pub high: &'a [i64],
}

impl Tiling<'_> {
    /// The one tile a point belongs to. Without any splits there is a single tile, 0.
    pub fn owner(&self, point: [f64; 2]) -> i64 {
        if self.axis.is_empty() {
            return 0;
        }
        let mut node = 0i64;
        loop {
            let k = node as usize;
            node = if point[self.axis[k] as usize] < self.split[k] {
                self.low[k]
            } else {
                self.high[k]
            };
            if node < 0 {
                return -(node + 1);
            }
        }
    }

    /// Every tile a box reaches into, in keeping with `owner`: a box holding a
    /// point is always given that point's tile.
    pub fn reached(&self, b: &[f64], stack: &mut Vec<i64>, mut visit: impl FnMut(i64)) {
        if self.axis.is_empty() {
            return visit(0);
        }
        stack.clear();
        stack.push(0);
        while let Some(node) = stack.pop() {
            if node < 0 {
                visit(-(node + 1));
                continue;
            }
            let k = node as usize;
            let axis = self.axis[k] as usize;
            if b[axis + 2] >= self.split[k] {
                stack.push(self.high[k]);
            }
            if b[axis] < self.split[k] {
                stack.push(self.low[k]);
            }
        }
    }
}

/// The owning tile of each point (interleaved coordinates).
pub fn owners(tiling: &Tiling, xy: &[f64]) -> Vec<i64> {
    xy.chunks_exact(2).map(|p| tiling.owner([p[0], p[1]])).collect()
}

/// For boxes given four numbers each, every (box, tile) where the box reaches
/// into the tile. A box with NaN is passed over.
pub fn reaches(tiling: &Tiling, boxes: &[f64]) -> (Vec<i64>, Vec<i64>) {
    let (mut rows, mut tiles, mut stack) = (Vec::new(), Vec::new(), Vec::new());
    for (row, b) in boxes.chunks_exact(4).enumerate() {
        if b.iter().any(|v| v.is_nan()) {
            continue;
        }
        tiling.reached(b, &mut stack, |tile| {
            rows.push(row as i64);
            tiles.push(tile);
        });
    }
    (rows, tiles)
}

#[cfg(test)]
mod tests {
    use super::*;

    // split on x at 10; below that, split on y at 5: tiles 0 (low y), 1 (high y), 2 (high x)
    const TILING: Tiling = Tiling {
        axis: &[0, 1],
        split: &[10.0, 5.0],
        low: &[1, -1],
        high: &[-3, -2],
    };

    #[test]
    fn each_point_has_one_owner() {
        assert_eq!(
            owners(&TILING, &[0.0, 0.0, 0.0, 5.0, 10.0, 0.0, 9.999, 4.999]),
            vec![0, 1, 2, 0]
        );
        let none = Tiling {
            axis: &[],
            split: &[],
            low: &[],
            high: &[],
        };
        assert_eq!(owners(&none, &[3.0, 4.0]), vec![0]);
    }

    #[test]
    fn boxes_reach_every_tile_they_touch() {
        let boxes = [
            0.0,
            0.0,
            1.0,
            1.0,
            0.0,
            4.0,
            12.0,
            6.0,
            10.0,
            0.0,
            10.0,
            0.0,
            f64::NAN,
            0.0,
            1.0,
            1.0,
        ];
        let (rows, tiles) = reaches(&TILING, &boxes);
        assert_eq!(rows, vec![0, 1, 1, 1, 2]);
        assert_eq!(tiles, vec![0, 0, 1, 2, 2]);
    }
}
