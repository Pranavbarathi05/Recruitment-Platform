# CPP Run — Emscripten feasibility (read-only)

> Research note only. No repo files were modified for this answer.
> A separate research file already exists at `CPP_RUN_INITIATIVE.md`.

## What we want
Compile a **runtime-generated** C++17 source file (candidate code + our harness) to WebAssembly **inside the browser**, then execute it inside a Web Worker, using `std::vector`, `std::string`, nested vectors, and the Emscripten libc/libc++ runtime.

## The critical distinction
Emscripten gives us two different capabilities, and they are **not** the same:

1. **Execute pre-compiled Emscripten Wasm/JS in the browser.**
   This is fully supported, mature, and easy.
   - Compile offline with `emcc` → `.js` + `.wasm` (or a single `.mjs` with `MODULARIZE`/`EXPORT_ES6`).
   - Load that artifact in a worker or main thread.
   - Call exported functions, use cwrap/ccall, etc.
   - This is how the existing Pyodide runner works in principle: a big runtime is loaded once, then code runs inside it.

2. **Compile C++ to Wasm from browser-side JS at runtime.**
   This is the hard part for us, because our C++ source is not known until the candidate types it and clicks Run.

## Smallest practical setup if compilation happens server-side or at build time
If we were willing to compile **before** it reaches the browser (for example a backend Compilation service, or a pre-signed artifact), the smallest browser-side setup is:

- An Emscripten-compiled runtime/module with `MODULARIZE=1` and ideally `EXPORT_ES6=1` (or `.mjs`) so it can be `import`ed.
- The generated JS glue + Wasm binary served as static assets (or fetched once and cached).
- A worker that instantiates the module and calls the harness entry point.
- STL (`vector`, `string`, nested vectors) works normally because it is compiled into the module by Emscripten via libc++.

This is straightforward and works today.

## Why in-browser compilation is the hard blocker
To run **arbitrary candidate C++** entirely client-side the same way Pyodide runs arbitrary Python, we would need the C++ → Wasm compilation to happen in the browser.

The practical browser-side options for that are:

- **Emscripten's official toolchain is not a browser library.**
  `emcc` is a CLI that shells out to clang/LLVM, wasm-ld, Binaryen tools, etc. There is no supported “emscripten.js” that takes source strings and returns Wasm in-browser.

- **Emscripten compiled to Wasm exists, but only as a research/niche project.**
  The clearest example is **Emception** (`jprendes/emception`), which compiles clang/LLVM + Binaryen to Wasm and runs them in the browser to compile C/C++ to Wasm.
  - It demonstrates feasibility.
  - It is **not** a ready-made frontend dependency.
  - Its build is heavy (full LLVM in Wasm), and the project is not positioned as a stable npm package or Vite plugin.
  - It is effectively a compiler-in-compiler approach, not a small runtime.

- **WASI SDK alone does not solve this.**
  WASI SDK can produce standalone Wasm, but it still requires a native/wasm toolchain to do the compilation; it does not magically give you a browser-side C++ compiler with STL support.

## Assets that would still be needed
Even in the most favorable path (pre-compiled module), we would still need to ship:

- The Emscripten JS runtime/glue (or a module wrapper around it).
- The Wasm binary (or a small set of them).
- Enough of the Emscripten runtime libc/libc++ to support the C++ features we use.
- A worker loader that wires `stdout`/`stderr`, test input injection, and harness result extraction into our existing result shape.

If we go the in-browser-compiler path, the asset burden becomes much larger: effectively a compiler toolchain in Wasm.

## STL support
- For **execution of pre-compiled code**: yes, `std::vector`, `std::string`, and nested STL containers work as usual in Emscripten-compiled code.
- For **in-browser compilation**: unsupported by anything production-grade; would depend on a compiler-in-wasm approach with its own limitations.

## Web Worker compatibility
- Executing an Emscripten module in a worker is realistic, especially with `MODULARIZE`/`EXPORT_ES6` and async instantiation.
- The main caveat is async startup and the need to wait for `onRuntimeInitialized`/module promise before calling exports.
- Our current Pyodide worker pattern maps well to this.

## The big practical question for our app
The key decision is not “Emscripten or not” — it is:

**Where does C++ → Wasm compilation happen?**

- If **browser-side at Run time**: this is the blocker. No small, mature, supported solution exists for compiling arbitrary C++17 + STL in-browser with Emscripten. Emception-style approaches are research-grade and large.
- If **server-side or pre-built**: much more feasible, but then C++ Run is no longer “entirely client-side compilation,” and we are back to sending code/submissions somewhere for compilation.

## Recommended next check before proceeding
If we want client-side C++ Run to be realistic, the first experiment should be:

- Build a tiny Emscripten module from a known harness + candidate file,
- Load it in a worker with `MODULARIZE`/`EXPORT_ES6`,
- Instantiate once and call the harness entry point,
- Feed it test data from JS and read results back,
- Measure artifact size, startup time, and STL behavior.

That experiment validates the **execution** side. The **compilation** side is the real remaining question, and it is the part that does not currently have a small supported browser answer.
