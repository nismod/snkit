//! Pairs of points within a distance of each other.

/// Find all pairs of points no further apart than `tolerance`.
///
/// `xy` is interleaved. Each pair is returned once, lower position first,
/// sorted. Points are sorted into a grid of cells as wide as the tolerance, so
/// a point's partners are in its own cell or one of the eight around it.
/// Memory: 20 bytes per point, plus the pairs found.
pub fn point_pairs(xy: &[f64], tolerance: f64) -> (Vec<i64>, Vec<i64>) {
    let n = xy.len() / 2;
    assert!(n <= u32::MAX as usize, "more than 2^32 points");
    let mut first = Vec::new();
    let mut second = Vec::new();
    if n < 2 {
        return (first, second);
    }
    let cell = if tolerance > 0.0 {
        tolerance
    } else {
        // only coincident points match: any cell size is correct, so pick one
        // that puts about one point in each cell
        let (mut low, mut high) = ([f64::INFINITY; 2], [f64::NEG_INFINITY; 2]);
        for p in xy.chunks_exact(2) {
            low = [low[0].min(p[0]), low[1].min(p[1])];
            high = [high[0].max(p[0]), high[1].max(p[1])];
        }
        let side = ((high[0] - low[0]).max(high[1] - low[1]) / (n as f64).sqrt()).max(f64::MIN_POSITIVE);
        if side.is_finite() {
            side
        } else {
            1.0
        }
    };
    let cell_of = |i: usize| ((xy[2 * i] / cell).floor() as i64, (xy[2 * i + 1] / cell).floor() as i64);
    let mut sorted: Vec<((i64, i64), u32)> = (0..n).map(|i| (cell_of(i), i as u32)).collect();
    sorted.sort_unstable();

    let limit = tolerance * tolerance;
    for &((cx, cy), i) in &sorted {
        let (x, y) = (xy[2 * i as usize], xy[2 * i as usize + 1]);
        for dx in -1..=1 {
            // the three cells above one another are adjacent in sorted order
            let from = sorted.partition_point(|&(c, _)| c < (cx + dx, cy - 1));
            for &((ox, oy), j) in &sorted[from..] {
                if ox != cx + dx || oy > cy + 1 {
                    break;
                }
                if j <= i {
                    continue;
                }
                let (ddx, ddy) = (xy[2 * j as usize] - x, xy[2 * j as usize + 1] - y);
                if ddx * ddx + ddy * ddy <= limit {
                    first.push(i as i64);
                    second.push(j as i64);
                }
            }
        }
    }
    let mut order: Vec<usize> = (0..first.len()).collect();
    order.sort_unstable_by_key(|&k| (first[k], second[k]));
    (
        order.iter().map(|&k| first[k]).collect(),
        order.iter().map(|&k| second[k]).collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_near_and_coincident_points() {
        let xy = [0.0, 0.0, 0.05, 0.0, 5.0, 5.0, 0.0, 0.0, -0.05, -0.05];
        assert_eq!(point_pairs(&xy, 0.0), (vec![0], vec![3]));
        assert_eq!(point_pairs(&xy, 0.06), (vec![0, 0, 1], vec![1, 3, 3]));
        assert_eq!(point_pairs(&xy, 0.08), (vec![0, 0, 0, 1, 3], vec![1, 3, 4, 3, 4]));
    }
}
