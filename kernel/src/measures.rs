//! Distances along lines, and the small edits that keep line ends on nodes.

/// For each vertex: the length of the segment starting there (0 at the last
/// vertex of a line) and the distance along its line. For each line: its length.
pub struct Measures {
    pub seglen: Vec<f64>,
    pub measure: Vec<f64>,
    pub length: Vec<f64>,
}

pub fn line_measures(coords: &[f64], offsets: &[i64]) -> Measures {
    let n = coords.len() / 2;
    let mut out = Measures {
        seglen: vec![0.0; n],
        measure: vec![0.0; n],
        length: Vec::with_capacity(offsets.len().max(1) - 1),
    };
    for line in offsets.windows(2) {
        let mut along = 0.0;
        for v in line[0] as usize..line[1] as usize {
            out.measure[v] = along;
            if v + 1 < line[1] as usize {
                out.seglen[v] = (coords[2 * v + 2] - coords[2 * v]).hypot(coords[2 * v + 3] - coords[2 * v + 1]);
                along += out.seglen[v];
            }
        }
        out.length.push(along);
    }
    out
}

/// Find the place a given distance along a line: the vertex that starts the
/// segment it is on, how far along that segment as a fraction, and its
/// coordinate. A place on a vertex is given as that vertex with fraction 0,
/// except at the very end of the line.
pub fn locate(
    coords: &[f64],
    offsets: &[i64],
    seglen: &[f64],
    measure: &[f64],
    line: &[i64],
    at: &[f64],
) -> (Vec<i64>, Vec<f64>, Vec<f64>) {
    let mut vertex = Vec::with_capacity(line.len());
    let mut frac = Vec::with_capacity(line.len());
    let mut xy = Vec::with_capacity(2 * line.len());
    for (&l, &at) in line.iter().zip(at) {
        let (first, last) = (offsets[l as usize] as usize, offsets[l as usize + 1] as usize - 1);
        let within = &measure[first..=last];
        let v = (first + within.partition_point(|&m| m <= at))
            .saturating_sub(1)
            .clamp(first, last.max(first + 1) - 1);
        let f = if seglen[v] > 0.0 {
            ((at - measure[v]) / seglen[v]).clamp(0.0, 1.0)
        } else {
            0.0
        };
        xy.extend_from_slice(&place(coords, v, f));
        vertex.push(v as i64);
        frac.push(f);
    }
    (vertex, frac, xy)
}

/// The coordinate a fraction of the way along the segment starting at a vertex.
pub fn place(coords: &[f64], vertex: usize, frac: f64) -> [f64; 2] {
    let a = [coords[2 * vertex], coords[2 * vertex + 1]];
    if frac == 0.0 {
        return a;
    }
    let b = [coords[2 * vertex + 2], coords[2 * vertex + 3]];
    if frac == 1.0 {
        return b;
    }
    [a[0] + frac * (b[0] - a[0]), a[1] + frac * (b[1] - a[1])]
}

/// Move the end vertices of each edge exactly onto its end nodes.
pub fn sync_ends(coords: &[f64], offsets: &[i64], xy: &[f64], src: &[i64], dst: &[i64]) -> Vec<f64> {
    let mut out = coords.to_vec();
    for (e, line) in offsets.windows(2).enumerate() {
        let (first, last) = (line[0] as usize, line[1] as usize - 1);
        let (s, d) = (src[e] as usize, dst[e] as usize);
        out[2 * first..2 * first + 2].copy_from_slice(&xy[2 * s..2 * s + 2]);
        out[2 * last..2 * last + 2].copy_from_slice(&xy[2 * d..2 * d + 2]);
    }
    out
}

/// Add a vertex at each edge end that is not already exactly on its end node.
pub fn extend_ends(coords: &[f64], offsets: &[i64], xy: &[f64], src: &[i64], dst: &[i64]) -> (Vec<f64>, Vec<i64>) {
    let mut out = Vec::with_capacity(coords.len() + 4 * src.len());
    let mut out_offsets = Vec::with_capacity(offsets.len());
    out_offsets.push(0);
    for (e, line) in offsets.windows(2).enumerate() {
        let (first, end) = (line[0] as usize, line[1] as usize);
        let start_node = &xy[2 * src[e] as usize..2 * src[e] as usize + 2];
        let end_node = &xy[2 * dst[e] as usize..2 * dst[e] as usize + 2];
        if coords[2 * first..2 * first + 2] != *start_node {
            out.extend_from_slice(start_node);
        }
        out.extend_from_slice(&coords[2 * first..2 * end]);
        if coords[2 * end - 2..2 * end] != *end_node {
            out.extend_from_slice(end_node);
        }
        out_offsets.push((out.len() / 2) as i64);
    }
    (out, out_offsets)
}

/// Turn component labels (each the lowest position in its component) into
/// consecutive group numbers, in order of first member, and mark each first member.
pub fn group_index(labels: &[i64]) -> (Vec<i64>, Vec<bool>) {
    let mut number = vec![0i64; labels.len()];
    let mut is_first = vec![false; labels.len()];
    let mut count = 0;
    for (i, &label) in labels.iter().enumerate() {
        if label as usize == i {
            is_first[i] = true;
            number[i] = count;
            count += 1;
        }
    }
    (labels.iter().map(|&label| number[label as usize]).collect(), is_first)
}

#[cfg(test)]
mod tests {
    use super::*;

    const COORDS: [f64; 10] = [0.0, 0.0, 3.0, 0.0, 3.0, 4.0, 10.0, 10.0, 10.0, 12.0];
    const OFFSETS: [i64; 3] = [0, 3, 5];

    #[test]
    fn measures_restart_on_each_line() {
        let m = line_measures(&COORDS, &OFFSETS);
        assert_eq!(m.seglen, vec![3.0, 4.0, 0.0, 2.0, 0.0]);
        assert_eq!(m.measure, vec![0.0, 3.0, 7.0, 0.0, 2.0]);
        assert_eq!(m.length, vec![7.0, 2.0]);
    }

    #[test]
    fn locate_finds_segment_fraction_and_coordinate() {
        let m = line_measures(&COORDS, &OFFSETS);
        let (vertex, frac, xy) = locate(
            &COORDS,
            &OFFSETS,
            &m.seglen,
            &m.measure,
            &[0, 0, 0, 0, 1, 1],
            &[0.0, 1.5, 3.0, 7.0, 1.0, 99.0],
        );
        assert_eq!(vertex, vec![0, 0, 1, 1, 3, 3]);
        assert_eq!(frac, vec![0.0, 0.5, 0.0, 1.0, 0.5, 1.0]);
        assert_eq!(xy, vec![0.0, 0.0, 1.5, 0.0, 3.0, 0.0, 3.0, 4.0, 10.0, 11.0, 10.0, 12.0]);
    }

    #[test]
    fn ends_follow_nodes() {
        let xy = [0.0, 0.5, 3.0, 4.0, 10.0, 10.0, 10.0, 13.0];
        let moved = sync_ends(&COORDS, &OFFSETS, &xy, &[0, 2], &[1, 3]);
        assert_eq!(moved, vec![0.0, 0.5, 3.0, 0.0, 3.0, 4.0, 10.0, 10.0, 10.0, 13.0]);
        let (extended, offsets) = extend_ends(&COORDS, &OFFSETS, &xy, &[0, 2], &[1, 3]);
        assert_eq!(offsets, vec![0, 4, 7]);
        assert_eq!(
            extended,
            vec![0.0, 0.5, 0.0, 0.0, 3.0, 0.0, 3.0, 4.0, 10.0, 10.0, 10.0, 12.0, 10.0, 13.0]
        );
    }

    #[test]
    fn groups_are_numbered_by_first_member() {
        let (group, is_first) = group_index(&[0, 1, 1, 0, 4]);
        assert_eq!(group, vec![0, 1, 1, 0, 2]);
        assert_eq!(is_first, vec![true, true, false, false, true]);
    }
}
