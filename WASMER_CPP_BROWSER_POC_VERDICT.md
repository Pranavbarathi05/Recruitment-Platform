# Wasmer Browser Clang — C++17 POC Verdict

> Read-only. No repository files modified. POC artifacts are in `/tmp/wasmer-poc` only.

## What we built
- Installed `@wasmer/sdk@0.11.0` into an isolated `/tmp/wasmer-poc` directory, outside the repository.
- Used the Node entrypoint `/tmp/wasmer-poc/node_modules/@wasmer/sdk/dist/node.js`.
- Loaded `clang/clang` from the Wasmer registry.
- Created a sandbox with a C++ source file mounted as `test.cpp`.
- Attempted to compile with `clang` to `test.wasm` using `-std=c++17`, then run with `wasmer`.

## What we verified
- The SDK module loads.
- `new Wasmer().ready()` completes.
- `wasmer.packages.load('clang/clang')` resolves.
- `wasmer.sandboxes.create(...)` creates a sandbox.
- `sandbox.command('clang', [...])` builds a command object.

## What we could NOT complete
- The clang compile command did **not** return a normal result within our timeout window.
- In every probe, the runner got past `SANDBOX_READY` and `COMMAND_BUILT` and then stalled.
- We observed the process staying alive for minutes with no new output, then timed out.

## Evidence
- `/tmp/wasmer-poc/probe.log`: reached `CORE_READY / PKG_LOADED true / SANDBOX_READY / COMMAND_BUILT`, then no further output.
- `/tmp/wasmer-poc/probe2.log`: same.
- `/tmp/wasmer-poc/mt.log`: same.
- In background runs, the node process remained alive for several minutes after `COMMAND_BUILT` and never produced compile output.

This is a **timeout/hang**, not a clean compile error we could inspect.

## Why this matters for the target program
We could not obtain:
1. A successful compile.
2. A successful execution.
3. The actual compiler command result or stdout.
4. Confirmation that C++ standard-library linking worked in this environment.

Because of that, we cannot say the target program was compiled or run.

## Most likely blocker we saw indirectly
The SDK spawns a real Node Worker for sandbox execution. The Node Worker is a separate thread with its own memory/heap. If that worker has a tight memory ceiling or hits some internal deadlock/resource limit during startup or package mount, the parent can appear alive while the actual work never completes. We saw:

- Worker-based execution path in the SDK dist files.
- The process hanging after sandbox/command construction.
- No useful stderr or compile output being captured.

That is consistent with an environment-side execution constraint rather than a clean API rejection.

## Public documentation we used
- Wasmer blog post on running clang in the browser: shows C compilation and execution primarily.
- `clang/clang` registry page: describes clang + wasm-ld, but the visible examples are C-focused.
- Wasix docs: describe `wasix-libc` for C; C++ stdlib story is not clearly established for the prebuilt browser package.

So the public material establishes “clang can run in the browser via Wasmer” for C, but does **not** document a verified C++17 + STL workflow for the exact browser package.

## Verdict
BLOCKED — requires a specific external verification.

Specifically:
- We need a real environment where the Wasmer sandbox worker can actually complete.
- We need to see whether the clang package in that environment supports C++17 + a usable C++ standard library.
- We need to confirm whether `vector<string>` and `iostream` link and run as expected.

Until that is validated end to end, this approach is:
- documented as possible for C,
- not verified for the requested C++17 STL program,
- blocked in this environment by an execution stall that prevented compilation and execution.

## What would unblock it
- Run the same POC in an environment with sufficient memory and a working Wasmer worker.
- Preferably run a minimal C++ compile first, then the target program.
- Capture the real compiler stderr/output and confirm linking against C++ standard library symbols.
- If that succeeds, then re-evaluate React/Worker integration.

## Result for your checklist
1. Compilation succeeded: **not verified**
2. Execution succeeded: **not verified**
3. stdout: **not captured**
4. Exact compiler command used: **`clang test.cpp -o test.wasm -std=c++17`** (built, not completed)
5. C++ standard-library linking worked: **not verified**
6. Blocker encountered: **sandbox compile command hung/timed out in this environment; C++ stdlib support for the browser package is not publicly confirmed**
