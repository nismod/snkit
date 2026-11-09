//! Array kernel for spatial network operations.
//!
//! Everything here takes and returns flat arrays: there are no tables, no
//! attributes and no geometry objects. A network is
//!
//! - `xy`: node coordinates, interleaved `x0, y0, x1, y1, ...`
//! - `src`, `dst`: for each edge, the position of its end nodes
//! - `coords`, `offsets`: edge geometries as one interleaved coordinate array
//!   and `m + 1` offsets, so that edge `e` has vertices
//!   `offsets[e]..offsets[e + 1]` (the GeoArrow layout)
//!
//! The Python package `snkit` has a reference implementation of the same
//! functions in `snkit/_kernel.py`; the two are tested against each other.

pub mod components;
pub mod crossings;
pub mod points;
pub mod rtree;
pub mod split;

#[cfg(feature = "python")]
mod python;
