# snkit-kernel

The array kernel of [snkit](https://github.com/nismod/snkit), in Rust.

`snkit` finds what to change in a network by matching geometry, then applies exact edits
to topology. The part that does the heavy lifting sees only flat arrays - coordinates,
offsets, positions - and no tables, attributes or geometry objects. This crate is that
part. `snkit/_kernel.py` is the reference implementation of the same functions in NumPy,
and the two are tested against each other.

| Function | Does |
| --- | --- |
| `components` | Labels connected components (union-find). |
| `split` | Cuts edges at places along them, in one pass. |
| `segment_crossings` | Finds where line segments meet, tile by tile and in parallel, deciding with exact predicates. |
| `point_pairs` | Finds points within a distance of each other. |

It has its own spatial index (a static R-tree packed along a Hilbert curve, in `rtree.rs`)
and depends only on `rayon` and `robust`.

## Use from Python

Build and install the Python package, which needs a Rust toolchain and
[maturin](https://www.maturin.rs):

    pip install maturin
    cd kernel
    maturin build --release
    pip install target/wheels/snkit_kernel-*.whl

`snkit` then uses it without being asked. To check, or to choose:

    python -c "import snkit._kernel; print(snkit._kernel.BACKEND)"
    SNKIT_KERNEL=python python ...    # use the NumPy kernel regardless
    SNKIT_KERNEL=native python ...    # fail if the compiled kernel is missing

## Use from Rust

The crate builds without Python by default:

    cargo test --release

```rust
use snkit_kernel::crossings::segment_crossings;

// two lines, as interleaved coordinates and offsets
let coords = [0.0, 0.0, 2.0, 2.0, 0.0, 2.0, 2.0, 0.0];
let found = segment_crossings(&coords, &[0, 2, 4], false);
assert_eq!(found.xy, vec![1.0, 1.0]);
```

## Continuous integration

`kernel-workflow.yml` in this directory is a GitHub Actions workflow that tests the crate,
builds it for Python and runs the whole `snkit` test suite on it. To turn it on, move it to
`.github/workflows/kernel.yml`.

## Memory

Functions state their working memory in their documentation. In outline, for the whole
input: `components` 4 bytes per node; `split` writes its output once; `segment_crossings`
8 bytes per segment plus a small index per tile per thread; `point_pairs` 20 bytes per
point. See section 8 of `docs/source/design.md` for measurements and the plan for
networks too large for memory.
