# DSC JSSSTU Recruitment Platform 🚀

An end-to-end evaluation system designed to recruit the next generation of leads and members for the Developer Student Club at JSS Science and Technology University. Unlike generic platforms, this system assesses candidates through **domain-specific** technical challenges.

## 📌 Project Overview
The platform streamlines the recruitment process by providing role-based assessments. Whether it's implementing a Scikit-learn model for an ML role or designing a responsive component for Web, this platform provides the environment to test real-world skills.

## ✨ Key Features
- **Domain-Aligned Tasks:** Specialized environments for ML, Web, Cloud, UI/UX, and Cyber roles.
- **Integrated Code Editor:** Real-time code execution with role-specific syntax highlighting.
- **Automated Grading:** Secure, sandboxed code execution using Docker.
- **Proctoring Suite:** Tab-switch detection, browser activity logging, and screen recording to ensure fairness.
- **AI Evaluator:** (Experimental) Agentic grading for descriptive and design-based questions.

## ▶️ Client-side “Run” (Web Worker + WASM)

The coding interface has two independent actions:

- **Run Code** — *feedback only*. For **Python 3**, execution happens **entirely in the candidate's browser**: the code is sent to a Web Worker that runs CPython compiled to WebAssembly (**Pyodide**). No code leaves the machine, no backend execution request is made, and an infinite loop can never freeze the page (the worker is terminated on timeout and recreated for the next run). Run executes against **public test cases only** (the same ones shown in the problem statement).
- **Submit Solution** — *authoritative*. Completely unchanged: the code is posted to the backend and evaluated server-side against **all** test cases (public + hidden). Run results are never used for scoring and never trusted as assessment data.

### Runtime assets are local (offline-safe)

Pyodide's ~14MB WASM runtime and Python standard library are copied from `node_modules/pyodide` into `public/pyodide/` by `scripts/copy-pyodide.mjs` (runs automatically via `postinstall`, `predev`, and `prebuild`). The app serves them at `/pyodide/` — **no CDN and no external compiler service** is required, so candidates on restricted networks can still Run code.

### Language support for client-side Run

| Language | Client-side Run | Notes |
|----------|-----------------|-------|
| `python3` | ✅ | Pyodide (CPython → WASM) in a module Web Worker; per-test time limit enforced by worker termination |
| `cpp` | ⚠️ Fallback | No bundled browser toolchain yet — Run uses the existing server-side run endpoint |
| `java` | ⚠️ Fallback | No practical browser JVM — Run uses the existing server-side run endpoint |

### How the client-side runner works

`src/execution/` contains the executor:

- `harness.js` — pure harness generation (mirrors the backend's Python harness: call `function_name`, compare JSON-serialized result vs expected) and structured-result normalization (`passed` / `failed` / `compile_error` / `runtime_error` / `timeout`, plus stdout, stderr, expected/actual output, per-test input and timing).
- `codeRunner.worker.js` — module Web Worker that loads Pyodide from `/pyodide/`, injects the public test cases, runs the harness, and posts structured results back.
- `runner.js` — main-thread manager: unique run IDs (stale results are ignored), a busy guard against overlapping runs, an execution timeout that **terminates** the worker and reports Time Limit Exceeded, automatic worker recreation after termination, and a separate generous timeout for first-time Pyodide initialization.

Run results render in the existing **Test Results** panel (`components/TestResultsPanel.jsx`), which was already present in the coding UI but dropped several error categories; it now shows compilation diagnostics, runtime errors/stderr, wrong-answer input/expected/got, TLE status, and program stdout.

### Testing

- Frontend: `cd apps/frontend && npm test` (harness logic, worker manager/timeouts/stale-result protection, coding UI integration, local-asset verification).
- Backend: `cd apps/backend && pytest` (run-endpoint status normalization included; the Submit flow is untouched).

## 🤝 Contributing
We welcome contributions from all DSC members! Whether you're fixing bugs, adding features, or improving documentation, your help is appreciated.

- Fork and clone the repository
- Create a feature branch for your changes
- Submit a pull request for review

Check out our [Contributing Guidelines](CONTRIBUTING.md) for detailed instructions on the workflow.
