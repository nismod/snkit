# snkit for JavaScript

The snkit kernel compiled to WebAssembly (about 350 KB), for Node and for browsers.

```js
const snkit = require("snkit");

// two lines, as coordinates x0, y0, x1, y1, ... and the offset at which each line starts
const coords = new Float64Array([0, 0, 2, 2, 0, 2, 2, 0]);
const offsets = new Int32Array([0, 2, 4]);

const found = snkit.call("segment_crossings", { coords, offsets });
found.xy;      // Float64Array [1, 1]: they cross at (1, 1)
found.seg_a;   // Int32Array [0]: on the segment starting at vertex 0 ...
found.frac_a;  // Float64Array [0.5]: ... half way along

snkit.functions();  // the names of everything that can be called
```

`call(name, args)` takes an object of named arguments and returns an object of named
results. Arguments and results have the names listed in `conformance/README.md` at the top
of the repository, where every function has small worked cases.

- Positions and counts are `Int32Array`; distances and fractions are `Float64Array`;
  coordinates are a `Float64Array` of x and y in turn; true-or-false results are
  `Uint8Array`. Plain arrays of numbers are accepted as arguments too, with coordinates as
  pairs if you like.
- A mistake in the arguments throws an `Error` saying which argument.
- Everything runs on one thread, and positions are limited to 2^31.

## Building and testing

    rustup target add wasm32-unknown-unknown
    cargo install wasm-bindgen-cli --version 0.2.100
    npm run build     # writes pkg/node and pkg/web
    npm test          # runs the conformance cases in Node

In a browser, load `pkg/web/snkit_wasm.js` as a module and await its default export before
calling `call`.
