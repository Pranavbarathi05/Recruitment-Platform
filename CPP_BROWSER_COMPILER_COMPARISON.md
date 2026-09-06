# CPP Browser Compiler Comparison — Source → Compile → Run in Browser

> Research only. No repository changes.

## Goal
Arbitrary candidate C++17 source arrives at runtime and must be compiled to Wasm in the browser, then executed in a Web Worker with STL (`vector`, `string`, nested vectors).

## Candidates compared

### 1. Emscripten (direct in-browser compilation)
- **Status:** No supported in-browser C++ compiler library from Emscripten.
- **Model:** `emcc` is a CLI toolchain; there is no small browser package that takes source strings and returns Wasm.
- **In-browser LLVM:** demonstrated only by research projects (for example Emception), not a maintained npm package.
- **Verdict:** Discarded per task constraints, and it was already the weakest path for arbitrary at-runtime compilation.

### 2. Clang compiled to Wasm and run via Wasmer JS SDK
- **Status:** Real, documented, actively maintained route for running clang in the browser.
- **NPM:** `@wasmer/sdk`, with browser entrypoint `@wasmer/sdk/browser`.
- **Mechanism:** load clang WASIX package from the Wasmer registry, mount a virtual filesystem with the candidate source, run clang to produce a Wasm binary, then run that binary in the same SDK.
- **Example flow from docs:**
  - write source to a sandbox filesystem,
  - `clang /project/example.c -o /project/example.wasm`,
  - run the resulting wasm.
- **Browser requirements:**
  - Cross-Origin-Opener-Policy: same-origin
  - Cross-Origin-Embedder-Policy: require-corp
  - because worker-backed WASIX execution needs SharedArrayBuffer.
- **Size:** clang package is large; docs mention ~100MB uncompressed, aiming for ~30MB compressed. This is the biggest practical drawback.
- **C++ support:**
  - clang/clang is a C/C++ compiler frontend.
  - Wasmer/WASIX is positioned as a broad POSIX-ish runtime, not only WASI.
  - C support is clearly demonstrated; C++ support is stated as part of clang, but STL-heavy C++17 in browser-Wasm still needs separate confirmation for libc++/libstdc++ availability, exceptions, RTTI, and linking behavior in the WASIX-in-browser context.
- **Worker compatibility:** possible in theory, but the COOP/COEP requirement and SharedArrayBuffer dependency complicate simple React/Vite pages and likely require server/response header changes, not just frontend code.
- **React/Vite fit:** the SDK is usable from JS and has browser examples, so integration is plausible. The heavyweight download and COOP/COEP requirements are the main product/UX friction, not the JS API.
- **Maturity/maintenance:** Wasmer SDK is recent and actively published; clang-in-browser demo is from late 2024. More live than Emception-style compiler-in-wasm experiments, but still a heavyweight sandbox-runtime approach rather than a thin compile-and-run library.
- **Licensing:** clang/LLVM is Apache 2.0 with LLVM exceptions; Wasmer SDK is separate and should be checked for its own license terms before production use.

### 3. WASI SDK + generic WASI runtime in browser
- **Status:** exists, but not a turnkey “paste C++ source, get Wasm in browser” solution.
- **Model:** WASI SDK produces WASI Wasm; you still need a Wasm runtime that can compile arbitrary source in-browser, or a separate toolchain-in-wasm.
- **Verdict:** does not remove the core problem; it shifts the missing piece to “a browser-runnable C++ compiler runtime.”

## Strongest candidate
**Wasmer JS SDK + browser-runnable clang package.**

It is the only option here that is:
- a published npm package,
- documented for browser use,
- shown compiling C/C++ from JS,
- not just a research demo of LLVM/Emscripten compiled to Wasm.

## Recommendation
If you want the most realistic existing project for **source → compile → run in browser**, use **Wasmer JS SDK** with a browser-capable clang package.

But add an explicit caveat: this is closest to a real path, not a confirmed turnkey C++17+STL solution. Before depending on it for an assessment platform, you would still need to verify:

1. C++17 plus STL (`vector`, `string`, nested vectors) compile and run in the browser clang/WASIX environment.
2. Exceptions and other C++ features you rely on are supported.
3. The large package download is acceptable for the candidate UX.
4. COOP/COEP and SharedArrayBuffer requirements can be satisfied in your deployment without breaking the rest of the app.
5. Execution sandboxing, time limits, and per-run isolation are achievable inside the Wasmer browser runtime.

## Conclusion
No small, mature, maintained npm package currently gives arbitrary C++17 + STL compilation and execution in-browser with the same simplicity as Pyodide gives Python. The most plausible existing route today is **Wasmer SDK + browser clang**, and even that is a heavyweight sandbox runtime with open C++/STL verification questions.

If “arbitrary C++ compiled entirely in the browser” is a hard requirement, the realistic answer is currently:

- best available lead: Wasmer JS SDK + browser clang
- not yet: a compact, mature, drop-in C++17 browser compiler with STL at Pyodide-like simplicity
