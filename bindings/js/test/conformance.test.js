// Run the kernel-tier conformance cases (conformance/kernel at the top of the
// repository) against the WebAssembly build: npm test

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");

const snkit = require("../pkg/node/snkit_wasm.js");

const root = path.join(__dirname, "..", "..", "..", "conformance", "kernel");
const flat = (value) => (Array.isArray(value) ? value.flat(Infinity) : [value]).map(Number);

const covered = new Set();
for (const folder of fs.readdirSync(root).sort()) {
  for (const file of fs.readdirSync(path.join(root, folder)).sort()) {
    const item = JSON.parse(fs.readFileSync(path.join(root, folder, file), "utf8"));
    covered.add(item.function);
    test(`${item.function}: ${item.title}`, () => {
      const result = snkit.call(item.function, item.input);
      assert.deepStrictEqual(Object.keys(result).sort(), Object.keys(item.expected).sort());
      for (const [name, expected] of Object.entries(item.expected)) {
        const got = flat(Array.from(result[name]));
        const want = flat(expected);
        assert.strictEqual(got.length, want.length, `length of ${name}`);
        got.forEach((value, i) => assert.ok(Math.abs(value - want[i]) <= 1e-9, `${name}[${i}]: ${value} != ${want[i]}`));
      }
    });
  }
}

test("every function has a case", () => {
  assert.deepStrictEqual([...covered].sort(), snkit.functions().sort());
});

test("typed arrays in, typed arrays out", () => {
  const coords = new Float64Array([0, 0, 2, 2, 0, 2, 2, 0]);
  const found = snkit.call("segment_crossings", { coords, offsets: new Int32Array([0, 2, 4]) });
  assert.ok(found.seg_a instanceof Int32Array && found.xy instanceof Float64Array);
  assert.deepStrictEqual(Array.from(found.xy), [1, 1]);
  const groups = snkit.call("group_index", { labels: new Int32Array([0, 1, 1]) });
  assert.ok(groups.is_first instanceof Uint8Array);
});

test("mistakes are reported as errors", () => {
  assert.throws(() => snkit.call("no_such_function", {}), /no function/);
  assert.throws(() => snkit.call("point_pairs", { tolerance: 1 }), /missing argument 'xy'/);
  assert.throws(() => snkit.call("point_pairs", { xy: "here", tolerance: 1 }), /must be/);
});
