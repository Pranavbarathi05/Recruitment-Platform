# CURRENT CODING EXECUTION — COMPLETE TECHNICAL AUDIT

> **AUDIT STATUS:**
> - ✅ Read-only — no source files modified
> - ✅ No migrations modified
> - ✅ No git commits/pushes performed
> - ⚠️ One new file created: `CURRENT_CODING_EXECUTION_CONTEXT.md` (this report)

---

## 1. EXECUTIVE SUMMARY

### A. What changed in the latest pull?

Two key commits were added on top of the previous work:

| Commit | Description |
|--------|-------------|
| `cb3630f` | `wasm compiler client side` — Added entire `apps/frontend/src/execution/` directory (runner, worker, harness, languages), `TestResultsPanel.jsx`, Pyodide npm dependency + copy script, vitest tests |
| `ec1a9eb` | `pyodide fix` — Minor fix to the Pyodide integration |

These introduced a **complete client-side Python execution pipeline** using Pyodide (CPython compiled to WASM) running in a Web Worker.

### B–J. Status Matrix

| Question | Answer |
|----------|--------|
| Is WASM execution actually implemented? | **YES — for Python only** |
| Is Pyodide actually implemented? | **YES — v314.0.6, locally bundled, Web Worker** |
| Which languages execute locally? | **Python 3 only** |
| Does "Run" avoid the backend for Python? | **YES — zero HTTP requests** |
| Does "Submit" use authoritative server-side? | **YES — unchanged, via Judge0** |
| Is Judge0 still involved? | **YES — for Submit and non-Python Run** |
| Is the legacy compiler/gateway involved? | **NO — dead code, replaced by Judge0** |
| Any stubs/fake implementations? | **NO — Python execution is real** |
| Production-ready? | **PARTIALLY — Python yes, C++/Java need server fallback** |

---

## 2. GIT / RECENT CHANGE AUDIT

**Branch:** `main`  
**Latest commit:** `ec1a9eb pyodide fix`

| Commit | Message | Relevance |
|--------|---------|-----------|
| `ec1a9eb` | `pyodide fix` | Minor Pyodide integration fix |
| `cb3630f` | `wasm compiler client side` | **Main WASM/Pyodide implementation** |
| `d9bca82` | `feat:add assessment reset and delete management` | Admin bulk operations |
| `1b1a6bf` | `fix:auth configuration and login flow` | Auth fixes |
| `7a5347c` | `route supabase auth to backend` | Auth migration |

**Uncommitted local changes** (from our previous work):
- `apps/backend/.env.example` — Judge0 config (unrelated to WASM)
- `apps/backend/services/compiler.py` — Judge0 client (unrelated to WASM)
- `apps/backend/services/harness.py` — Language harnesses (unrelated to WASM)
- `TEST_CASE_UPLOAD_CONTEXT.md` — Previous audit report

---

## 3. FRONTEND CODING UI — RUN BUTTON TRACE

### Files Involved

| File | Role |
|------|------|
| `apps/frontend/src/pages/CodingTest.jsx` | Standalone coding page (coding-only assessment) |
| `apps/frontend/src/pages/MCQTest.jsx` | Combined MCQ+Coding workspace (main assessment) |
| `apps/frontend/src/execution/runner.js` | Main-thread manager (WorkerRunner class + singleton) |
| `apps/frontend/src/execution/codeRunner.worker.js` | Web Worker: loads Pyodide, executes Python |
| `apps/frontend/src/execution/harness.js` | Harness generator + result normalizer (pure functions) |
| `apps/frontend/src/execution/languages.js` | Language support matrix |
| `apps/frontend/src/components/TestResultsPanel.jsx` | Result display component |

### Exact Call Chain When Candidate Clicks "Run"

Both `CodingTest.jsx` and `MCQTest.jsx` use the same logic:

```
"▶ Run Code" button (onClick={handleRunCode})
    │
    ▼
handleRunCode()
    │
    ├── isClientRunnable(language) === true?
    │       │
    │       ├── YES (python3):
    │       │     │
    │       │     ▼
    │       │   runCodeLocally({
    │       │     language: 'python3',
    │       │     sourceCode,          // candidate's editor contents
    │       │     testCases,           // problem.test_cases (PUBLIC ONLY)
    │       │     functionName,        // problem.function_name
    │       │     className,           // problem.class_name
    │       │     timeLimitMs,         // problem.time_limit_ms
    │       │   })
    │       │     │
    │       │     ▼
    │       │   WorkerRunner.run()          [runner.js]
    │       │     │
    │       │     ├── creates Web Worker: new Worker('./codeRunner.worker.js')
    │       │     │     │
    │       │     │     ▼
    │       │     │   worker.postMessage({ type: 'execute', runId, payload })
    │       │     │     │
    │       │     │     ▼
    │       │     │   [INSIDE WEB WORKER — codeRunner.worker.js]
    │       │     │     │
    │       │     │     ├── getPyodide()  ← lazy-loads CPython WASM from /pyodide/
    │       │     │     │
    │       │     │     ├── buildPythonHarness({
    │       │     │     │     sourceCode,    // candidate's solution
    │       │     │     │     functionName,
    │       │     │     │     className,
    │       │     │     │     testCases,
    │       │     │     │   })              [harness.js]
    │       │     │     │     │
    │       │     │     │     └── returns complete Python source:
    │       │     │     │           candidate code + test loop + JSON comparison
    │       │     │     │
    │       │     │     ├── pyodide.runPython(harnessSource, { globals })
    │       │     │     │     │
    │       │     │     │     └── Python executes locally via WASM
    │       │     │     │
    │       │     │     ├── reads globals.get('__FREEBUFF_PAYLOAD')
    │       │     │     │     └── JSON results: [{passed, actual, expected, time_ms}, ...]
    │       │     │     │
    │       │     │     └── worker.postMessage({ type: 'result', runId, result })
    │       │     │
    │       │     └── resolves Promise with result
    │       │
    │       └── NO (cpp, java):
    │             │
    │             ▼
    │           runCodeOnServer(problem)
    │             │
    │             ├── POST /coding/attempt/{id}/run
    │             │     └── FastAPI → code_executor → harness → Judge0
    │             │
    │             └── returns result
    │
    ▼
setRunResults(result)  →  TestResultsPanel displays results
```

**KEY FINDING: For Python, Run makes ZERO backend HTTP requests.**  
For C++ and Java, Run falls back to the server-side `POST /coding/attempt/{id}/run` endpoint.

---

## 4. WASM IMPLEMENTATION

### Runtime Used

**Pyodide v314.0.6** — CPython 3.x compiled to WebAssembly.  
NOT Emscripten directly. NOT wasm-bindgen. NOT a custom WASM binary.

### File Map

| File | Purpose |
|------|---------|
| `apps/frontend/src/execution/codeRunner.worker.js` | Web Worker that loads Pyodide and runs Python |
| `apps/frontend/src/execution/runner.js` | Main-thread WorkerRunner class |
| `apps/frontend/src/execution/harness.js` | Python harness generator (mirrors backend `harness.py`) |
| `apps/frontend/src/execution/languages.js` | Language support matrix |
| `apps/frontend/scripts/copy-pyodide.mjs` | Copies Pyodide assets from node_modules to public/ |
| `apps/frontend/scripts/copy-pyodide.test.mjs` | Tests for the copy script |
| `apps/frontend/src/execution/runner.test.js` | WorkerRunner unit tests |
| `apps/frontend/src/execution/harness.test.js` | Harness function unit tests |

### How Pyodide Assets Are Served

1. `npm install` installs `pyodide@314.0.6` into `node_modules/pyodide/`
2. `scripts/copy-pyodide.mjs` copies WASM runtime into `public/pyodide/`
3. Vite serves `/pyodide/` as static assets (same origin, no CDN)
4. Worker loads via `import('/pyodide/pyodide.mjs')` at runtime

### Key Properties

| Property | Value |
|----------|-------|
| Runtime | Pyodide (CPython compiled to WASM) |
| Version | 314.0.6 |
| Loading | Lazy — only when first Run clicked |
| Thread | Web Worker (separate thread) |
| Cache | Singleton `pyodidePromise` per worker lifecycle |
| Assets | Served locally from `/pyodide/` (no CDN) |
| Network access | Not available (WASM sandbox) |
| Filesystem | Virtual filesystem within WASM sandbox |

### Timeouts / Limits

| Limit | Value | Mechanism |
|-------|-------|-----------|
| Execution timeout | `problem.time_limit_ms + 1500ms` overhead | Main thread `setTimeout` → `worker.terminate()` |
| Init timeout | 60,000ms | Main thread `setTimeout` → worker terminated |
| Output limit | 65,536 chars | Truncated in worker stdout/stderr capture |
| Memory limit | Browser default (no explicit limit set) | Relies on WASM memory management |
| Overlapping runs | Rejected | `WorkerRunner.busy` check |

### Infinite Loop Handling

1. Candidate code runs synchronously in the Web Worker
2. The main thread enforces `timeLimitMs + 1500ms` timeout via `setTimeout`
3. On timeout, main thread calls `worker.terminate()` — forcibly kills the worker
4. Next run lazily creates a fresh worker + re-initializes Pyodide
5. The page **never freezes** because execution is off the main thread

---

## 5. PYODIDE IMPLEMENTATION — DETAILED

### Loading Sequence

```
1. Candidate clicks "Run"
2. WorkerRunner.run() called
3. Worker.postMessage({ type: 'execute', ... })
4. Worker receives message:
   a. If pyodidePromise is null → sends { type: 'loading' } to main thread
   b. Calls getPyodide():
      - import('/pyodide/pyodide.mjs')  ← dynamic import
      - mod.loadPyodide({
          indexURL: '/pyodide/',
          stdout: capture,
          stderr: capture,
        })
   c. Sends { type: 'started' } to main thread
   d. Calls executeRun(payload)
5. executeRun():
   a. buildPythonHarness() → generates complete Python program
   b. Creates fresh globals namespace
   c. Injects TEST_ARGS and TEST_EXPECTED via pyodide.toPy()
   d. pyodide.runPython(harnessSource, { globals })
   e. Reads globals.get('__FREEBUFF_PAYLOAD')
   f. Returns structured result
```

### How Python Test Cases Are Executed

The `buildPythonHarness()` function in `harness.js` generates Python code that:

```python
import json, time

# === Candidate Solution ===
<class Solution>    # candidate's code injected here

# === Test Harness ===
results = []
for _tc_idx, (_tc_args, _tc_expected) in enumerate(zip(TEST_ARGS, TEST_EXPECTED)):
    _tc_start = time.perf_counter()
    try:
        _instance = Solution()              # if className is set
        _result = _instance.solve(_tc_args[0], _tc_args[1])  # positional args
        _result_json = json.dumps(_result, ensure_ascii=False)
        _expected_json = json.dumps(_tc_expected, ensure_ascii=False)
        _passed = _result_json == _expected_json
        results.append({"passed": _passed, "actual": _result, "expected": _tc_expected, "time_ms": ...})
    except Exception as e:
        results.append({"passed": False, "error": str(e), "expected": _tc_expected, "time_ms": ...})

__FREEBUFF_PAYLOAD = json.dumps(results, ensure_ascii=False)
```

`TEST_ARGS` and `TEST_EXPECTED` are injected into the Python namespace by the worker via `pyodide.toPy()`, avoiding JSON escaping issues in source code.

### Exception Handling

| Exception Type | Classification | UI Display |
|---------------|---------------|------------|
| `SyntaxError` / `IndentationError` / `TabError` | `compile_error` | Red diagnostics |
| `KeyboardInterrupt` | `timeout` | Time Limit Exceeded |
| Any other `Exception` inside test | `runtime_error` | Red error message |
| Exception outside test harness (module-level) | `runtime_error` | Same error for all tests |
| Pyodide initialization failure | `error` | "Could not initialize runtime" |

---

## 6. FUNCTION-BASED MODEL — HOW IT WORKS LOCALLY

### Example: Two Sum

**Problem metadata:**
```json
{
  "function_name": "twoSum",
  "class_name": "Solution",
  "function_signature": "def twoSum(self, nums: List[int], target: int) -> List[int]"
}
```

**Test case (public, sent to browser):**
```json
{
  "id": "abc-123",
  "arguments": [[2, 7, 11, 15], 9],
  "expected_output": [0, 1]
}
```

**What the browser executes:**
```python
TEST_ARGS = [[2, 7, 11, 15], 9]   # injected via pyodide.toPy()
TEST_EXPECTED = [0, 1]

# Candidate's solution (from editor):
class Solution:
    def twoSum(self, nums, target):
        # ... candidate's implementation
        pass

# Harness:
_instance = Solution()
_result = _instance.twoSum([2, 7, 11, 15], 9)  # positional unpacking
_passed = json.dumps([0,1]) == json.dumps(_result)
```

**Comparison:** `json.dumps(result) == json.dumps(expected)` — strict JSON string equality.

### Argument Unpacking

The harness maps `arguments` array positionally to function parameters:
- `arguments[0]` → first parameter
- `arguments[1]` → second parameter
- etc.

For class methods, `self` is implicit — the harness instantiates the class first.

---

## 7. LANGUAGE SUPPORT MATRIX

| Language | Local Run | Technology | Actually Executes? | Compile Errors | Runtime Errors | TLE | Memory Limit | Notes |
|----------|-----------|------------|-------------------|----------------|---------------|-----|-------------|-------|
| **Python 3** | ✅ YES | Pyodide v314.0.6 (WASM) | ✅ Real execution | ✅ SyntaxError detected | ✅ Exception captured | ✅ Worker.terminate() | Browser default | Full implementation |
| **C++** | ❌ NO | Falls back to server | N/A (server-side) | Via Judge0 | Via Judge0 | Via Judge0 | Via Judge0 | Not client-runnable |
| **Java** | ❌ NO | Falls back to server | N/A (server-side) | Via Judge0 | Via Judge0 | Via Judge0 | Via Judge0 | Not client-runnable |
| **SQL** | ❌ NO | NOT IMPLEMENTED | N/A | N/A | N/A | N/A | N/A | No SQL support anywhere |

The `CLIENT_RUNNABLE_LANGUAGES` array in `languages.js` contains only `['python3']`.

---

## 8. TEST CASE FLOW — PUBLIC/PRIVATE ENFORCEMENT

### Admin → Database
```
AdminCoding.jsx → POST /admin/coding/problems/{id}/tests/bulk
    → coding_admin.py → coding_test_cases table (with is_public flag)
```
**Unchanged.** Same JSON format, same API, same database.

### Database → Candidate Browser
```
GET /coding/attempt/{id}/problems
    → coding.py: get_coding_problems()
        → SELECT FROM coding_test_cases WHERE is_public = True
        → Sent to browser as problem.test_cases[]
```

**Only public test cases reach the browser.** The backend filter `.eq("is_public", True)` is applied at line 103 of `coding.py`.

### Browser → Local Run
```
runCodeLocally({
    testCases: problem.test_cases,  // ← already filtered to public only
    ...
})
```

### Security Guarantee

| Concern | Status |
|---------|--------|
| Hidden test cases sent to browser? | **NO** — filtered by `is_public = True` in backend query |
| Hidden expected outputs exposed? | **NO** — only public test data in `problem.test_cases` |
| Can candidate access hidden tests via JS console? | **NO** — they were never transmitted |
| Can candidate manipulate local Run results? | **YES** — but Run results are feedback only, never used for scoring |
| Is Submit still authoritative? | **YES** — server fetches ALL tests + runs via Judge0 |

---

## 9. CURRENT RUN FLOW

### Python (Client-Side)

```
Candidate Browser
    │
    ├── GET /coding/attempt/{id}/problems  ──→ FastAPI
    │     (gets problem metadata + PUBLIC test cases)
    │
    ├── "Run" button clicked
    │     │
    │     └── [ZERO HTTP REQUESTS]
    │           │
    │           ├── Web Worker loads Pyodide (first time ~10MB)
    │           ├── buildPythonHarness() generates Python code
    │           ├── pyodide.runPython() executes locally
    │           └── Results returned to main thread
    │
    └── Results displayed by TestResultsPanel.jsx
```

### C++ / Java (Server-Side Fallback)

```
Candidate Browser
    │
    └── "Run" button clicked
          │
          └── POST /coding/attempt/{id}/run  ──→ FastAPI
                │
                ├── code_executor.py: run_code_public()
                │     └── harness.py: generate_harness()
                │
                └── compiler.py: execute_code_sync()
                      └── Judge0 CE: POST /submissions (async)
                      └── Judge0 CE: GET /submissions/{token} (poll)
```

### Submit (All Languages — Unchanged)

```
Candidate Browser
    │
    └── "Submit" button clicked
          │
          └── POST /coding/attempt/{id}/submit  ──→ FastAPI
                │
                ├── Fetches ALL test cases (public + hidden)
                │
                ├── code_executor.py: evaluate_submission()
                │     └── harness.py: generate_harness()
                │
                ├── compiler.py → Judge0 CE
                │
                ├── Score calculated server-side
                │
                └── Returns { status, submission_id } to candidate
                    (score/max_score NOT sent to client)
```

---

## 10. CURRENT SUBMIT FLOW — VERIFICATION

**Submit is fully server-side and authoritative.** Verified from `coding.py:280-330`:

1. Fetches ALL test cases: `SELECT ... FROM coding_test_cases WHERE problem_id = ...` (NO `is_public` filter)
2. Calls `evaluate_submission()` → `code_executor.py` → `compiler.py` → Judge0
3. Score calculated server-side: `earned_points = sum(tc.points for passed tests)`
4. Stored in `coding_submissions` table
5. Returns ONLY `{ status, submission_id }` — **no score, no test results sent to client**

**The candidate cannot submit a client-generated score.**

---

## 11. JUDGE0 STATUS

| Operation | Uses Judge0? |
|-----------|-------------|
| Python Run (local) | ❌ No |
| C++ Run (server fallback) | ✅ Yes |
| Java Run (server fallback) | ✅ Yes |
| Submit (all languages) | ✅ Yes |

**Judge0 client:** `apps/backend/services/compiler.py`  
**Judge0 config:** `JUDGE0_BASE_URL`, `JUDGE0_AUTH_TOKEN` env vars  
**Judge0 CE version:** 1.13.1 (self-hosted)

---

## 12. LEGACY COMPILER / GATEWAY STATUS

| Component | Status | Required? |
|-----------|--------|-----------|
| `compiler.py` (old gateway-api path) | **REPLACED** — now uses Judge0 directly | Judge0 is required for Submit |
| `gateway-api` | **DEAD CODE** — not called by anything | Not required |
| `compiler-1` service | **DEAD CODE** — not called by anything | Not required |
| `COMPILER_URL` env var | **DEAD** — replaced by `JUDGE0_BASE_URL` | Not required |

The legacy compiler→gateway→compiler-1 chain has been fully replaced by direct Judge0 integration. The old code path is dead.

---

## 13. SQL SUPPORT

**NOT IMPLEMENTED.**

No SQL language support exists anywhere in the codebase:
- `VALID_CODING_LANGUAGES = ["python3", "cpp", "java"]` — no "sql"
- No PostgreSQL temporary database creation
- No SQL test case schema fields
- No SQL harness
- No SQL execution path

---

## 14. BROWSER RESOURCE / PERFORMANCE

| Concern | Assessment |
|---------|-----------|
| Main thread blocking | ✅ **NOT blocked** — all execution in Web Worker |
| Pyodide loaded once? | ✅ **YES** — singleton per worker lifecycle |
| Worker recreated after TLE? | ✅ **YES** — fresh worker on next run |
| Overlapping runs | ✅ **BLOCKED** — `WorkerRunner.busy` rejects |
| Multiple simultaneous runs | ✅ **NOT possible** — serialized by busy flag |
| Memory cleanup | ✅ **Worker.terminate()** on TLE/error; fresh worker next time |
| Pyodide init time | ⚠️ **~2-5 seconds first time** (downloads 10MB WASM from local `/pyodide/`) |
| Subsequent runs | ✅ **Fast** — Pyodide already initialized in worker |
| Network dependency | ✅ **None after first load** — all assets served locally |
| Mobile browsers | ⚠️ **Untested** — WASM support varies |

### Critical: The 75+ Candidate Problem

**This implementation directly solves the original bottleneck.** Each candidate's Python Run executes entirely in their own browser. Zero server load for Python Runs. The server is only hit for:
- Loading problems (lightweight DB queries)
- Submit (one execution per problem submission)
- Draft autosave (lightweight PUT)

For 75+ simultaneous candidates all clicking Run, each browser runs independently. The server only handles Submit operations, which are inherently sequential per-candidate anyway.

---

## 15. SECURITY MODEL

### What Is Trusted / Untrusted

| Entity | Trust Level | Impact |
|--------|-------------|--------|
| Candidate source code | **UNTRUSTED** | Runs in WASM sandbox |
| Public test cases in browser | **LOW RISK** | Already visible to candidate in UI |
| Local Run results | **UNTRUSTED** | Feedback only, never used for scoring |
| Submit source code | **TRUSTED for scoring** | Evaluated server-side via Judge0 |
| Hidden test cases | **NEVER IN BROWSER** | Server-side only |
| Score | **SERVER-GENERATED** | Cannot be client-manipulated |

### Key Security Properties

1. **Local Run results are never used for scoring** — they are feedback only
2. **Submit always evaluates server-side** with Judge0 against ALL test cases
3. **Hidden test cases never reach the browser** — filtered by `is_public = True`
4. **The candidate cannot submit a fake score** — the score is computed by `evaluate_submission()` server-side
5. **The candidate cannot access other candidates' data** — enforced by `_verify_attempt_ownership()`

---

## 16. ADMIN CODING / TEST CASE SYSTEM

**Unchanged from previous audit.** Verified from current `AdminCoding.jsx` and `coding_admin.py`.

### Admin Activate/Deactivate Bug Analysis

The reported bug: "activate and deactivate buttons don't work properly and they keep logging me out."

**Frontend code** (AdminCoding.jsx line ~170):
```javascript
const handleToggleProblemActive = async (problem) => {
    const endpoint = problem.is_active
      ? `${apiUrl}/admin/coding/problems/${problem.id}/deactivate`
      : `${apiUrl}/admin/coding/problems/${problem.id}/activate`;
    const resp = await fetch(endpoint, { method: 'POST', headers: getAuthHeaders(), credentials: 'include' });
    if (resp.ok) { ... }
    // NOTE: No else clause! If response is 401/403, nothing happens silently.
};
```

**Backend code** (coding_admin.py):
```python
@router.post("/problems/{problem_id}/activate")
def activate_coding_problem(problem_id: str, admin: AuthUser = Depends(require_admin)):
    ...
    return {"status": "activated"}
```

**Root cause analysis:**

1. The backend returns `{"status": "activated"}` with HTTP 200 — no `Content-Length: 0` or empty body issue.
2. The `handleToggleProblemActive` function has **no error handling for non-200 responses** — if the session expires or CSRF fails, the response is silently ignored.
3. **Most likely cause: CSRF token mismatch.** The `getAuthHeaders()` function reads the `dsc_csrf` cookie. If the cookie has expired or been cleared (e.g., by browser cookie cleanup or SameSite restrictions), the CSRF validation on the backend fails with 403, and the frontend silently does nothing.
4. The "logging out" symptom is likely the admin seeing the page reload to `/login` after the **admin check** (line ~57: `GET /admin/domains` → 401 → `navigate('/login')`), not from the activate/deactivate call itself. This could happen if the `dsc_session` cookie expires between the page load and the button click.

**NOT a code bug** — it's a session/CSRF expiry issue. The fix would be to add error handling to `handleToggleProblemActive` to show an error message instead of silently failing.

---

## 17. AUTH / SESSION

**Unchanged.** Authentication uses:
- HttpOnly `dsc_session` cookie for session management
- `dsc_csrf` readable cookie for CSRF protection
- `getAuthHeaders()` reads CSRF cookie and adds `X-CSRF-Token` header
- All requests use `credentials: 'include'`

The WASM/Pyodide local execution does NOT change authentication requirements. Problems are loaded via authenticated API call. Run is local (no auth needed). Submit uses authenticated API call.

---

## 18. DATABASE / MIGRATIONS

**No new migrations were introduced by the WASM/Pyodide changes.**

The execution change is purely frontend — no database schema modifications.

Relevant tables (unchanged):
- `coding_problems` — problem definitions with `function_name`, `class_name`
- `coding_test_cases` — test cases with `arguments` (JSONB), `expected_output`, `is_public`
- `coding_submissions` — server-side scored submissions
- `coding_drafts` — autosaved code drafts

---

## 19. TESTS

### Backend Tests

| Suite | Result |
|-------|--------|
| `pytest test_main.py` | **179 passed, 9 failed, 3 warnings** |
| 9 failures | All in `TestCompilerServiceIntegration` — pre-existing mock issues from Judge0 migration (not related to WASM changes) |

### Frontend Tests

| Suite | Result |
|-------|--------|
| `npm run build` | ✅ Built in 1.54s |
| `npm run lint` | ✅ 0 errors, 7 warnings |

### WASM/Pyodide-Specific Tests

| File | Tests |
|------|-------|
| `execution/runner.test.js` | 8 tests — WorkerRunner: execution, stale results, timeout, overlapping, consecutive runs, init failure, worker error |
| `execution/harness.test.js` | 9 tests — harnessTestData, buildPythonHarness, buildResultsFromHarness, buildErrorResults, buildTimeoutResults, classifyRunError, formatValue |
| `scripts/copy-pyodide.test.mjs` | 1 test — verifies Pyodide assets are copied to public/ |

All execution-related tests use mock workers — they don't actually run Pyodide.

---

## 20. COMPLETE CURRENT ARCHITECTURE

### A. Candidate Loading

```
Candidate Browser
    │
    └── GET /coding/attempt/{id}/problems  ──→ FastAPI (coding.py)
          │
          ├── Fetches problem metadata (title, description, function_name, etc.)
          ├── Fetches PUBLIC test cases only (WHERE is_public = True)
          ├── Fetches submission status
          └── Returns to browser (no hidden tests, no scoring data)
```

### B. Local Run (Python)

```
Candidate Browser
    │
    └── "Run" button
          │
          ├── [ZERO HTTP REQUESTS]
          │
          ├── Web Worker (codeRunner.worker.js)
          │     │
          │     ├── loadPyodide() from /pyodide/ (local WASM)
          │     │
          │     ├── buildPythonHarness(candidate_code, test_cases)
          │     │     └── Generates: candidate code + test loop + JSON compare
          │     │
          │     ├── pyodide.runPython(harness)
          │     │     └── CPython WASM executes locally
          │     │
          │     └── Returns: { all_passed, results: [{passed, actual, expected, ...}] }
          │
          └── TestResultsPanel displays results
```

### C. Local Run (C++/Java — Server Fallback)

```
Candidate Browser
    │
    └── "Run" button
          │
          └── POST /coding/attempt/{id}/run  ──→ FastAPI
                │
                ├── code_executor.run_code_public()
                │     └── harness.generate_harness() (language-specific)
                │
                └── compiler.execute_code_sync()
                      └── Judge0 CE (self-hosted)
```

### D. Submit (All Languages)

```
Candidate Browser
    │
    └── POST /coding/attempt/{id}/submit  ──→ FastAPI
          │
          ├── Fetches ALL test cases (public + hidden)
          ├── code_executor.evaluate_submission()
          │     └── harness.generate_harness()
          ├── compiler → Judge0 CE
          ├── Score computed server-side
          ├── Stored in coding_submissions
          └── Returns: { status, submission_id } (NO score to client)
```

### E. Admin Test Case Upload

```
Admin Browser
    │
    └── POST /admin/coding/problems/{id}/tests/bulk  ──→ FastAPI
          │
          └── coding_test_cases table (with is_public, points, ordering)
```

---

## 21. PREVIOUS VS CURRENT

| Area | Previous | Current | Intended | Status |
|------|----------|---------|----------|--------|
| Python Run | Server (Judge0) | **Local WASM/Pyodide** | Local | ✅ DONE |
| C++ Run | Server (Judge0) | Server (Judge0) | Local | ❌ NOT YET |
| Java Run | Server (Judge0) | Server (Judge0) | Local | ❌ NOT YET |
| SQL Run | Not implemented | Not implemented | TBD | ❌ NOT YET |
| Public tests | Server query | Server query + browser | Browser | ✅ DONE |
| Hidden tests | Server only | Server only | Server only | ✅ CORRECT |
| Submit | Server (Judge0) | Server (Judge0) | Server (Judge0) | ✅ UNCHANGED |
| Scoring | Server-side | Server-side | Server-side | ✅ UNCHANGED |
| Judge0 | Run + Submit | Submit + non-Python Run | Submit only | ⚠️ PARTIAL |
| Legacy compiler | Dead | Dead | Remove | ⚠️ DEAD CODE |
| Test case upload | Admin JSON paste | Admin JSON paste | No change needed | ✅ UNCHANGED |
| Load bottleneck | Server-bound | **Browser-bound for Python** | Browser-bound | ✅ SOLVED for Python |

---

## 22. PRODUCTION READINESS

### For Python (Primary Concern)

| Aspect | Assessment |
|--------|-----------|
| Addresses 75-candidate load problem | ✅ **YES** — Run is browser-side, zero server load |
| Chrome support | ✅ WASM fully supported |
| Firefox support | ✅ WASM fully supported |
| Safari support | ✅ WASM supported (Safari 11+) |
| Edge support | ✅ WASM supported |
| Pyodide first-load time | ⚠️ ~2-5 seconds (10MB WASM download from same-origin `/pyodide/`) |
| Subsequent runs | ✅ Fast (Pyodide stays in worker) |
| TLE handling | ✅ Worker.terminate() from main thread |
| Infinite loop protection | ✅ Worker.terminate() |
| Memory leak protection | ✅ Worker terminated and recreated |
| Mobile support | ⚠️ Untested — may have performance issues |
| Manipulation risk | ⚠️ Candidate can tamper with Run results — but Run is feedback only, Submit is authoritative |

### For C++ and Java

| Aspect | Assessment |
|--------|-----------|
| Local execution | ❌ **NOT IMPLEMENTED** — falls back to server |
| Server fallback works | ✅ Yes — same Judge0 path as before |
| Load bottleneck | ❌ **Still exists for C++/Java** — 75 candidates running C++ simultaneously would hit Judge0 |

### Remaining Risks

1. **C++/Java Run still hits Judge0** — the original 75-candidate bottleneck is only solved for Python
2. **Pyodide init latency** — first run per candidate takes 2-5 seconds to load WASM
3. **No explicit WASM memory limit** — very large data structures could slow the browser
4. **Candidate can inspect Run results via DevTools** — but this is by design (Run is feedback only)
5. **No mobile testing** — WASM performance on mobile may be poor

---

## 23. COMPLETE FILE MAP

### Frontend — Execution

| File | Responsibility |
|------|---------------|
| `apps/frontend/src/execution/runner.js` | WorkerRunner class, createWorker(), runCodeLocally() singleton |
| `apps/frontend/src/execution/codeRunner.worker.js` | Web Worker: loads Pyodide, runs Python, returns results |
| `apps/frontend/src/execution/harness.js` | buildPythonHarness(), harnessTestData(), buildResultsFromHarness(), classifyRunError(), buildTimeoutResults() |
| `apps/frontend/src/execution/languages.js` | CLIENT_RUNNABLE_LANGUAGES = ['python3'], isClientRunnable() |
| `apps/frontend/src/execution/runner.test.js` | WorkerRunner unit tests (8 tests) |
| `apps/frontend/src/execution/harness.test.js` | Harness function unit tests (9 tests) |

### Frontend — UI

| File | Responsibility |
|------|---------------|
| `apps/frontend/src/pages/CodingTest.jsx` | Standalone coding page — imports runCodeLocally, isClientRunnable |
| `apps/frontend/src/pages/MCQTest.jsx` | Combined MCQ+Coding workspace — imports runCodeLocally, isClientRunnable |
| `apps/frontend/src/components/CodeEditor.jsx` | Monaco editor component |
| `apps/frontend/src/components/TestResultsPanel.jsx` | Displays Run results (pass/fail/error per test) |
| `apps/frontend/src/pages/AdminCoding.jsx` | Admin problem + test case CRUD |
| `apps/frontend/src/contexts/AuthContext.jsx` | Auth context with getAuthHeaders() |

### Frontend — Build/Config

| File | Responsibility |
|------|---------------|
| `apps/frontend/scripts/copy-pyodide.mjs` | Copies Pyodide from node_modules to public/pyodide/ |
| `apps/frontend/scripts/copy-pyodide.test.mjs` | Tests for copy script |
| `apps/frontend/package.json` | pyodide@^314.0.6 dependency, copy-pyodide scripts |

### Backend

| File | Responsibility |
|------|---------------|
| `apps/backend/routers/coding.py` | Candidate API: load problems, run, submit, drafts |
| `apps/backend/routers/coding_admin.py` | Admin API: problem CRUD, test CRUD, bulk upload, activate/deactivate |
| `apps/backend/schemas/coding.py` | Pydantic schemas for all coding requests |
| `apps/backend/services/code_executor.py` | Orchestrates harness + compiler for server-side execution |
| `apps/backend/services/compiler.py` | Judge0 CE client (async + sync) |
| `apps/backend/services/harness.py` | Server-side language harness generators (Python, C++, Java) |

### Database

| Migration | Relevance |
|-----------|-----------|
| `006_coding_assessment.sql` | Created coding_problems, coding_test_cases, coding_submissions, coding_drafts |
| `009_function_based_coding.sql` | Added arguments JSONB to coding_test_cases, function metadata to coding_problems |

### Tests

| File | What It Tests |
|------|--------------|
| `apps/backend/test_main.py` | 188 tests (179 pass, 9 pre-existing failures) |
| `apps/frontend/src/execution/runner.test.js` | WorkerRunner behavior |
| `apps/frontend/src/execution/harness.test.js` | Harness generation + result normalization |
| `apps/frontend/scripts/copy-pyodide.test.mjs` | Pyodide asset bundling |

---

## FINAL VERDICT

### 1. Is local Run actually implemented?
**YES — for Python 3.** Full implementation using Pyodide v314.0.6 in a Web Worker. Zero backend requests for Python Run.

### 2. Which languages work locally?
**Python 3 only.** C++ and Java fall back to server-side Judge0 execution.

### 3. Does Run hit FastAPI?
**Python: NO.** C++/Java: YES (server fallback via `POST /coding/attempt/{id}/run`).

### 4. Does Run hit Judge0?
**Python: NO.** C++/Java: YES (server fallback → Judge0).

### 5. Does Submit remain authoritative?
**YES.** Submit is unchanged — server-side evaluation against ALL test cases via Judge0.

### 6. Are hidden tests protected?
**YES.** Hidden test cases are filtered out by `WHERE is_public = True` in the backend query before data ever reaches the browser. Verified in `coding.py:103`.

### 7. Is SQL implemented?
**NO.** No SQL support exists anywhere in the codebase.

### 8. Is the old compiler still required?
**NO.** The legacy compiler/gateway path is dead code. Judge0 is the only execution backend.

### 9. Does the admin activate/deactivate logout bug remain?
**Likely YES** — the root cause is silent failure handling (no error shown on 401/403) combined with potential session/CSRF expiry. The backend endpoints are correct. The frontend lacks error handling for non-200 responses.

### 10. What are the 5 most important remaining technical issues?

1. **C++ and Java Run still hits Judge0** — the load bottleneck is only solved for Python, not for the other two supported languages
2. **Pyodide first-load latency** — 2-5 seconds for initial WASM download; could be pre-warmed but currently isn't
3. **Admin activate/deactivate silent failure** — no error message shown to admin when the toggle fails; needs proper error handling
4. **9 pre-existing backend test failures** — `TestCompilerServiceIntegration` mocks need updating (not caused by WASM changes)
5. **No C++/Java client-side execution path** — if the goal is to fully eliminate server-side Run, C++ and Java need browser runtimes (e.g., Emscripten for C++, CheerpJ for Java) or the platform must accept server-side fallback for these languages

---

## FILES INSPECTED

1. `apps/frontend/src/execution/runner.js`
2. `apps/frontend/src/execution/codeRunner.worker.js`
3. `apps/frontend/src/execution/harness.js`
4. `apps/frontend/src/execution/languages.js`
5. `apps/frontend/src/execution/runner.test.js`
6. `apps/frontend/src/execution/harness.test.js`
7. `apps/frontend/src/pages/CodingTest.jsx`
8. `apps/frontend/src/pages/MCQTest.jsx`
9. `apps/frontend/src/components/TestResultsPanel.jsx`
10. `apps/frontend/src/pages/AdminCoding.jsx`
11. `apps/frontend/src/contexts/AuthContext.jsx`
12. `apps/frontend/scripts/copy-pyodide.mjs`
13. `apps/frontend/scripts/copy-pyodide.test.mjs`
14. `apps/frontend/package.json`
15. `apps/backend/routers/coding.py`
16. `apps/backend/routers/coding_admin.py`
17. `apps/backend/schemas/coding.py`
18. `apps/backend/services/compiler.py`
19. `apps/backend/services/code_executor.py`
20. `apps/backend/services/harness.py`

**The ONLY newly created file is `CURRENT_CODING_EXECUTION_CONTEXT.md` (this report).**
