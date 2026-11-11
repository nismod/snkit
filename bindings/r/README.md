# snkit for R

The snkit kernel as an R package, with the Rust compiled in.

```r
library(snkit)

# two lines: the vertices of both, one row each, and the offset at which each line starts
coords <- rbind(c(0, 0), c(2, 2), c(0, 2), c(2, 0))
found <- snkit_call("segment_crossings", coords = coords, offsets = c(0, 2, 4))
found$xy      # a matrix with one row, 1 1: they cross at (1, 1)
found$seg_a   # 0: on the segment starting at vertex 0 ...
found$frac_a  # 0.5: ... half way along

snkit_functions()  # the names of everything that can be called
```

`snkit_call(name, ...)` takes named arguments and returns a named list. Arguments and
results have the names listed in `conformance/README.md` at the top of the repository,
where every function has small worked cases. Coordinates are matrices of two columns.

Positions count from 0, not 1: vertex 0 is the first vertex. Results are positions into the
kernel's arrays, the same in every language, so add 1 before using one to index in R.

## Installing and testing

Needs a Rust toolchain (<https://rustup.rs>). From this directory:

    R CMD INSTALL .
    SNKIT_CONFORMANCE=../../conformance/kernel Rscript tests/conformance.R

The package builds against the kernel in `../../kernel`, so it installs from a checkout of
the repository, not yet from an archive of this directory alone.
