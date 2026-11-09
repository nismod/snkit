//! Cutting edges at places along them.

/// Result of [`split`]: the new edges, and which edge each was cut from.
pub struct Split {
    pub coords: Vec<f64>,
    pub offsets: Vec<i64>,
    pub src: Vec<i64>,
    pub dst: Vec<i64>,
    pub parent: Vec<i64>,
}

/// Cut edges, inserting the coordinate of a node at each cut.
///
/// Cuts must be sorted by edge and then by position along the edge.
/// `cut_seg` is the vertex position at the start of the segment to cut.
///
/// Pieces of an edge are in order along it and take its place in the edge
/// order. A cut that lands on an existing vertex would leave a repeated
/// coordinate; it is dropped, without reducing a piece below two vertices.
///
/// One pass over the input; the output is written once and is the size of
/// the input plus two vertices per cut.
#[allow(clippy::too_many_arguments)]
pub fn split(
    coords: &[f64],
    offsets: &[i64],
    src: &[i64],
    dst: &[i64],
    cut_edge: &[i64],
    cut_seg: &[i64],
    cut_xy: &[f64],
    cut_node: &[i64],
) -> Split {
    let m = src.len();
    let k = cut_edge.len();
    let mut out = Split {
        coords: Vec::with_capacity(coords.len() + 4 * k),
        offsets: Vec::with_capacity(m + k + 1),
        src: Vec::with_capacity(m + k),
        dst: Vec::with_capacity(m + k),
        parent: Vec::with_capacity(m + k),
    };
    out.offsets.push(0);
    let mut cut = 0;
    for e in 0..m {
        let (first, last) = (offsets[e] as usize, offsets[e + 1] as usize);
        if cut == k || cut_edge[cut] as usize != e {
            out.coords.extend_from_slice(&coords[2 * first..2 * last]);
            out.offsets.push((out.coords.len() / 2) as i64);
            out.src.push(src[e]);
            out.dst.push(dst[e]);
            out.parent.push(e as i64);
            continue;
        }
        let mut piece_start = out.coords.len();
        let mut piece_src = src[e];
        for v in first..last {
            push_vertex(&mut out.coords, piece_start, coords[2 * v], coords[2 * v + 1]);
            while cut < k && cut_edge[cut] as usize == e && cut_seg[cut] as usize == v {
                let (x, y) = (cut_xy[2 * cut], cut_xy[2 * cut + 1]);
                push_vertex(&mut out.coords, piece_start, x, y);
                close_piece(&mut out, piece_start, piece_src, cut_node[cut], e);
                piece_start = out.coords.len();
                piece_src = cut_node[cut];
                out.coords.extend_from_slice(&[x, y]);
                cut += 1;
            }
        }
        close_piece(&mut out, piece_start, piece_src, dst[e], e);
    }
    out
}

/// Add a vertex to the piece being built, unless it repeats the one before.
fn push_vertex(coords: &mut Vec<f64>, piece_start: usize, x: f64, y: f64) {
    let n = coords.len();
    if n > piece_start && coords[n - 2] == x && coords[n - 1] == y {
        return;
    }
    coords.extend_from_slice(&[x, y]);
}

fn close_piece(out: &mut Split, piece_start: usize, src: i64, dst: i64, parent: usize) {
    if out.coords.len() - piece_start < 4 {
        // every piece has at least two vertices, even if they coincide
        let n = out.coords.len();
        let (x, y) = (out.coords[n - 2], out.coords[n - 1]);
        out.coords.extend_from_slice(&[x, y]);
    }
    out.offsets.push((out.coords.len() / 2) as i64);
    out.src.push(src);
    out.dst.push(dst);
    out.parent.push(parent as i64);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cuts_one_edge_twice_and_leaves_the_other() {
        // edge 0: (0,0)-(4,0), nodes 0 and 1; edge 1: (4,0)-(4,4), nodes 1 and 2
        let coords = [0.0, 0.0, 4.0, 0.0, 4.0, 0.0, 4.0, 4.0];
        let result = split(
            &coords,
            &[0, 2, 4],
            &[0, 1],
            &[1, 2],
            &[0, 0],
            &[0, 0],
            &[1.0, 0.0, 3.0, 0.5],
            &[7, 8],
        );
        assert_eq!(result.offsets, vec![0, 2, 4, 6, 8]);
        assert_eq!(
            result.coords,
            vec![0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 3.0, 0.5, 3.0, 0.5, 4.0, 0.0, 4.0, 0.0, 4.0, 4.0]
        );
        assert_eq!(result.src, vec![0, 7, 8, 1]);
        assert_eq!(result.dst, vec![7, 8, 1, 2]);
        assert_eq!(result.parent, vec![0, 0, 0, 1]);
    }

    #[test]
    fn cut_on_a_vertex_does_not_repeat_it() {
        let coords = [0.0, 0.0, 1.0, 0.0, 2.0, 0.0];
        let result = split(&coords, &[0, 3], &[0], &[1], &[0], &[1], &[1.0, 0.0], &[5]);
        assert_eq!(result.offsets, vec![0, 2, 4]);
        assert_eq!(result.coords, vec![0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 2.0, 0.0]);
    }
}
