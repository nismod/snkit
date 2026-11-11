#!/bin/sh
# Build the kernel as WebAssembly, for Node (pkg/node) and for browsers (pkg/web).
# Needs: rustup target add wasm32-unknown-unknown; cargo install wasm-bindgen-cli --version 0.2.100
set -e
cd "$(dirname "$0")"
cargo build --release --target wasm32-unknown-unknown
wasm=target/wasm32-unknown-unknown/release/snkit_wasm.wasm
wasm-bindgen --target nodejs --out-dir pkg/node "$wasm"
wasm-bindgen --target web --out-dir pkg/web "$wasm"
