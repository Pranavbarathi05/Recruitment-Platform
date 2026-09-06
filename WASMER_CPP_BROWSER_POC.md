# Wasmer Browser Clang — C++17 POC Research

> Read-only. No repository changes. Temporary POC probe lives in /tmp only.

## What we are evaluating
Can the documented Wasmer browser approach compile **and** run this C++17 program?

```cpp
#include <iostream>
#include <vector>
#include <string>
using namespace std;

int main() {
    vector<string> values = {"hello", "world"};
    vector<vector<int>> matrix = {{1, 2}, {3, 4}};
    cout << values[0] << " " << values[1] << " "
         << matrix[0][0] + matrix[1][1];
    return 0;
}
```

## What we actually inspected
- Wasmer SDK npm package `@wasmer/sdk` version `0.11.0`
- Published SDK tarball, unpacked in `/tmp`
- SDK entrypoint files: `dist/index.js`, `dist/browser-worker.js`, `dist/node.js`
- SDK wasm runtime artifact: `pkg/wasmer_sdk_js_bg.wasm` (~4.4MB)
- SDK API surface: `Wasmer`, `Sandbox`, `Sandbox.command(selector, args, options)`, `Command.run(options)`, `Command.spawn(options)`, `Output`
- Wasmer registry pages for `clang/clang`
- Wasix docs for C, `wasix-libc`, `wasixcc`

## Exact API shape implied by the SDK
A browser sandbox flow would look conceptually like:

```js
import { Wasmer } from "@wasmer/sdk/browser";

const wasmer = new Wasmer();
await wasmer.ready();

const sandbox = await wasmer.sandboxes.create({
  packages: ["clang/clang"],
  files: { "example.cpp": SOURCE },
});

const compile = await sandbox.command("clang", [
  "example.cpp", "-o", "example.wasm", "-std=c++17"
]).run();

const execute = await sandbox.command("wasmer", [
  "run", "example.wasm"
]).run();
```

The SDK supports:
- mounting files into the sandbox
- selecting a command by name from a package
- running with timeout and output limits
- capturing stdout/stderr and exit status

## Critical uncertain points for this specific C++ program

### 1. Does the browser clang package provide a usable C++ compiler and linker
- The public Wasmer docs and `clang/clang` page emphasize C and WASI.
- The clang package is described as enabling “clang and its linker using only WebAssembly,” but the published examples are C-focused.
- For our program we need:
  - clang to accept C++ input
  - a working wasm-ld step
  - C++ standard library support sufficient for `vector<string>` and `vector<vector<int>>`
  - iostream support that works in the sandbox environment

None of that is verified by the public material we found. It is plausible for clang in general, but **not confirmed for the exact browser package**.

### 2. C++ standard library
- The SDK itself is a runtime, not a C++ standard library distribution.
- Wasix docs mention `wasix-libc`, which is a C library, not a full C++ stdlib.
- `wasixcc` mentions `libc++`/`libc++abi` support for WASIX, but that is about the broader WASIX project, not necessarily the prebuilt browser clang package.
- Therefore the key open question is: in the browser sandbox, does compiling this source succeed with a usable C++ library, or does it fail at link time due to missing `stdc++`/`libc++` bits?

### 3. Execution model
- The SDK can run a compiled wasm binary inside the sandbox.
- Worker-backed WASIX execution requires COOP/COEP:
  - Cross-Origin-Opener-Policy: same-origin
  - Cross-Origin-Embedder-Policy: require-corp
- The SDK also mentions WISP for outbound networking from browser sandboxes.
- For our program, networking is not required, so only the SharedArrayBuffer/COOP/COEP requirement matters.

### 4. Download size
- SDK wasm runtime artifact alone is ~4.4MB.
- The Wasmer blog post cites the clang package at ~100MB uncompressed, with a goal of ~30MB compressed.
- That is significant for a candidate-facing Run button, though not disqualifying for a prototype.

## Environment capability we checked
- Node available: yes, v24.20.0
- npm available: yes, 11.19.0
- `@wasmer/sdk` version resolved: 0.11.0
- We did NOT install the package into the repository and did NOT modify package.json.
- We did NOT run a full browser POC because:
  - the SDK is large,
  - the browser entrypoint requires COOP/COEP and a served page,
  - and the open C++ stdlib question makes a browser POC more of a verification step than a discovery step.

We did inspect the SDK package contents directly from the published tarball, which is why this report is stronger than “only docs.”

## What is documented as possible
- Running a C compiler in the browser via Wasmer SDK is documented and demoed.
- Creating a sandbox, mounting files, running commands, and capturing output is directly supported by the SDK API.
- Running a compiled wasm binary inside the same sandbox model is supported in principle.

## What is NOT verified
- Compiling this exact C++17 source with STL containers using the browser clang package.
- Linking against a usable C++ standard library inside the browser sandbox.
- That `iostream`, `vector<string>`, and nested `vector<vector<int>>` behave as expected.
- That the prebuilt `clang/clang` package exposes a C++ command path suitable for this workflow.

## The real gate
The main uncertainty is **not** the Wasmer SDK itself. The SDK is real, published, and inspectable. The uncertainty is whether the **clang package + sandbox environment** provides a practical C++17 toolchain with enough of the C++ standard library for arbitrary candidate code.

## Conclusion
GO — viable for a prototype, **if** prototype scope is explicit:

- Prototype the Wasmer SDK + browser clang flow.
- Verify that the exact C++17 STL example compiles and runs in the sandbox.
- Verify COOP/COEP behavior and acceptable download size.
- Treat C++ stdlib usability as the first major checkbox, not a foregone conclusion.

If prototyping shows the browser clang package cannot reliably compile and link STL-heavy C++17 code, then this approach should be considered blocked for our use case, even though the SDK itself is viable.
