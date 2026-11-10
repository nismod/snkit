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
//! The Python package `snkit` is a front end to this crate: it turns tables
//! into these arrays, calls the kernel, and moves attributes by the positions
//! the kernel returns.

pub mod components;
pub mod crossings;
pub mod measures;
pub mod nearest;
pub mod points;
pub mod rtree;
pub mod split;

#[cfg(feature = "python")]
mod python;
