# Bindings to the snkit kernel from other languages

The kernel (`../kernel`) is plain Rust that works on flat arrays, so it can be used from
any language that can call Rust. Each binding here is thin: the kernel has one entry point,
`dispatch::call`, that takes the name of a function and a table of named arrays and gives
back named arrays, and a binding only has to pass arrays across.

| Directory | Language | How it is built | Tested by |
| --- | --- | --- | --- |
| `js` | JavaScript, in Node and browsers | WebAssembly, with wasm-bindgen | `npm test` |
| `r` | R | A package with the Rust compiled in, with extendr | `tests/conformance.R` |

Both run the same cases as the kernel's own tests and the Python package:
`../conformance/kernel`, 45 small cases as JSON covering every function.

**What these are, and are not.** They give each language the kernel: where lines cross,
cutting edges, matching points to lines, connected components, simplifying, and so on, on
arrays of coordinates. They do not yet give the operations of the Python package
(`split_edges_at_crossings`, `merge_nodes` and the rest), which combine kernel functions
with rules about ids, attributes and tolerances that are written in Python. Moving that
layer into Rust, behind the same kind of entry point, is what would make a full front end
in each language a matter of tables in and tables out; `../conformance/operations` holds
the 139 cases such a front end would have to pass.

Positions count from 0 in every language, R included: these are bindings to the kernel,
and its results are positions into its arrays.
