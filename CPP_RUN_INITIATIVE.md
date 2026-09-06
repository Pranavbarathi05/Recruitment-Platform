# CPP Run Initiative — Browser-Side C++ Execution via Emscripten

> Read-only research artifact. No repository changes beyond this file.

## Goal
Enable C++ Run (candidate feedback only) entirely in the browser, mirroring the existing Pyodide Python runner.

- **Run:** browser-side, Web Worker, WASM, public test cases only, timer enforced by worker termination.
- **Submit:** unchanged server-side path via FastAPI → Judge0.

## Why Emscripten
After comparing available approaches, the only viable option for full C++17 + STL in the browser is **Emscripten** compiling candidate code + harness to WebAssembly, then executing inside a dedicated Web Worker.

Alternatives considered and rejected:
- **WASI SDK alone:** produces standalone Wasm, but no JS glue — requires a separate browser-side WASI polyfill/runtime that is immature for STL-heavy C++17.
- **Raw clang/LLVM in browser:** no realistic option; compilers are too large, not designed for browser isolation.
- **Custom JS-based C++ interpreter:** does not exist at the maturity/standard-library level we need.

## Why it fits this project
- Same architecture pattern as the existing Pyodide runner (Web Worker, local assets, timeout via termination).
- Reuses our existing C++ harness generator (function-based LeetCode style, JSON test-data protocol) with only the execution backend swapped.
- Candidate code stays unchanged: normal C++17 with `std::vector`, `std::string`, nested vectors, etc.
- Offline-capable once the Emscripten WASM runtime bundle is served from the app (like `/pyodide/` today).

## Recommended approach
1. Pre-bundle a minimal Emscripten WASM toolchain/runtime in the app (analogous to the Pyodide copy step), served from a local path such as `/cpp-wasm/`.
2. Add a new worker (parallel to `codeRunner.worker.js`) that:
   - receives candidate source + harness source,
   - compiles them to a standalone Wasm module,
   - instantiates it in the worker,
   - injects test arguments and captures results/stdout/stderr,
   - returns the same structured result shape used by the Python runner.
3. Add a small compiler-runner abstraction in `runner.js` so the main thread can invoke the C++ worker when `isClientRunnable('cpp')` is true.
4. Extend `languages.js` to mark `cpp` as client-runnable once the toolchain is available.

## Known constraints
- This is a research note only. No implementation has been done.
- Emscripten is a real compiler toolchain, not a trivial JS library; bundling it for in-browser use is materially larger and more complex than Pyodide.
- We should validate C++17 + STL support, startup cost, and worker behavior before depending on it for assessments.
- Until implemented and tested, server-side Judge0 remains the execution path for C++ Run and Submit.

## Status
RESEARCH_ONLY
