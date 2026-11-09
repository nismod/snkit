//! Connected components by union-find.

/// Label connected components of `n` items linked by pairs `(a, b)`.
///
/// Each item is labelled with the lowest position in its component.
/// Memory: 4 bytes per item while working, 8 per item returned.
pub fn components(n: usize, a: &[i64], b: &[i64]) -> Vec<i64> {
    assert!(n <= u32::MAX as usize, "more than 2^32 items");
    assert_eq!(a.len(), b.len());
    let mut parent: Vec<u32> = (0..n as u32).collect();

    fn find(parent: &mut [u32], mut i: u32) -> u32 {
        while parent[i as usize] != i {
            // path halving
            let grandparent = parent[parent[i as usize] as usize];
            parent[i as usize] = grandparent;
            i = grandparent;
        }
        i
    }

    for (&x, &y) in a.iter().zip(b) {
        let root_x = find(&mut parent, x as u32);
        let root_y = find(&mut parent, y as u32);
        // the lower position becomes the root, so a root is the lowest in its set
        if root_x < root_y {
            parent[root_y as usize] = root_x;
        } else if root_y < root_x {
            parent[root_x as usize] = root_y;
        }
    }
    (0..n as u32).map(|i| find(&mut parent, i) as i64).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn labels_are_lowest_member() {
        let labels = components(6, &[4, 1, 5], &[1, 2, 3]);
        assert_eq!(labels, vec![0, 1, 1, 3, 1, 3]);
    }

    #[test]
    fn nothing_linked() {
        assert_eq!(components(3, &[], &[]), vec![0, 1, 2]);
        assert_eq!(components(0, &[], &[]), Vec::<i64>::new());
    }
}
