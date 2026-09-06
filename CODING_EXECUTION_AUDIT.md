# Coding Problem Execution Flow — READ-ONLY Audit

Auditor: automated assistant
Scope: current DEV repository state only
Restrictions: no source files modified, no migrations modified, no git commits/pushes.
Repo status at audit time: `git diff --name-only` was empty; `git status --short` shows only untracked scratch notes/docs in the working tree (no tracked files changed). Existing committed files are unchanged.

---

## 1. Current architecture

The platform has three distinct execution paths right now:

1. **Candidate Python Run (client-side)** — `CodingTest.jsx` detects `language === 'python3'` via `runner.isClientRunnable(...)`, then calls `runner.runCodeLocally(...)`. That runs inside a Web Worker (`codeRunner.worker.js`) with Pyodide. No backend Run endpoint is involved for python3.
2. **Candidate C++/Java Run (server-side fallback)** — same UI, same `handleRunCode`, but `isClientRunnable(language)` is false, so it POSTs `/coding/attempt/{id}/run`.
3. **Candidate Submit (always server-side)** — `POST /coding/attempt/{id}/submit`.

That split means Python Run today is **not** hitting the backend Run endpoint; C++ and Java Run still do.

Submission is always server-side and authoritative. The frontend does not trust local Run results for scoring.

---

## 2. Exact files/functions involved

### Admin configuration
- Admin UI: `apps/frontend/src/pages/AdminCoding.jsx`
  - default starter code, function metadata, per-language starter code, test case form, bulk JSON upload, edit/delete
- Admin router: `apps/backend/routers/coding_admin.py`
  - `list_coding_problems`, `create_coding_problem`, `update_coding_problem`, `activate/deactivate/delete`, `list_test_cases`, `create_test_case`, `bulk_upload_test_cases`, `update_test_case`, `delete_test_case`

### Candidate problem loading
- Candidate router: `apps/backend/routers/coding.py`
  - `GET /coding/attempt/{id}/problems` → fetches problems + **public-only** test cases + drafts + submission status
  - `PUT /coding/attempt/{id}/draft`, `GET /coding/attempt/{id}/draft/{problem_id}`
- Candidate frontend: `apps/frontend/src/pages/CodingTest.jsx`
  - loads `problem.starter_code[defaultLang] || getDefaultStarter(lang)` when no draft exists

### Run flow
- Frontend: `apps/frontend/src/pages/CodingTest.jsx` → `handleRunCode` → `isClientRunnable(language)` branch selection
  - python3: `runner.runCodeLocally(...)` in `apps/frontend/src/execution/runner.js`
  - cpp/java: `POST /coding/attempt/{id}/run` → `run_code()` in `apps/backend/routers/coding.py`
- Backend Run (cpp/java): `run_code_public()` in `apps/backend/services/code_executor.py`
  - fetches `function_name, class_name, function_signature` from `coding_problems`
  - extracts test args and expected outputs from DB test cases
  - calls `generate_harness(...)` in `apps/backend/services/harness.py`
  - submits generated program to Judge0 via `execute_code_sync()` in `apps/backend/services/compiler.py`
- Client-side Python Run: `apps/frontend/src/execution/runner.js` → worker `apps/frontend/src/execution/codeRunner.worker.js`
  - harness built in `apps/frontend/src/execution/harness.js` → `buildPythonHarness(...)`
  - harness mirrors backend Python harness logic but is pure client-side JS + Pyodide

### Submit flow
- Frontend: `handleSubmitSolution` → `POST /coding/attempt/{id}/submit` → `submit_coding_solution()` in `apps/backend/routers/coding.py`
- Backend: `evaluate_submission()` in `apps/backend/services/code_executor.py`
  - same `generate_harness()` + `execute_code_sync()` path
  - uses **all** test cases (no public filter in the router)
  - computes `score`, `tests_passed`, `tests_total` server-side
  - upserts `coding_submissions` and returns only `{ status, submission_id }`

### Harness generation
- `apps/backend/services/harness.py`
  - `generate_python_harness(...)`
  - `generate_cpp_harness(...)`
  - `generate_java_harness(...)`
  - dispatcher: `generate_harness(language=...)`

### Test results rendering
- Frontend: `apps/frontend/src/components/TestResultsPanel.jsx`

---

## 3. Where hardcoded test cases exist

There is **no hardcoded problem-definition test-case table** in the current committed backend or frontend. The only "hardcoded" defaults are:

1. **Fallback starter-code strings** in `CodingTest.jsx`:
   - `getDefaultStarter('python3')` returns:
     ```
     # Write your solution here

     def solve():
         pass
     ```
   - `getDefaultStarter('cpp')` returns an `int main()` skeleton.
   - `getDefaultStarter('java')` returns a `public class Main { public static void main... }` skeleton.

2. **Default admin problem starter code** in `AdminCoding.jsx`:
   - `DEFAULT_STARTER_CODE.python3`:
     ```
     class Solution:
         def solve(self, nums, target):
             # Write your solution here
             pass
     ```
   - `DEFAULT_STARTER_CODE.cpp` and `.java` similarly provide a `Solution` class skeleton with `solve(...)`.

3. **Mock/fixture test-case data** in `apps/backend/test_main.py`:
   - `_make_test_case(...)` uses `expected_output: "0 1"`.
   - some tests use `input: "2", expected_output: "4"`.
   - This is **test fixture data**, not runtime problem data. It does not populate the DB for real candidates.

Important nuance: the current committed repo does **not** ship with any persisted sample coding problem in migrations. There is no SQL seed creating coding problems in `006_coding_assessment.sql` or `009_function_based_coding.sql`. So any real candidate assessment depends on admin-created problems and test cases.

So the real "hidden hardcoded test case" risk today is **not a DB seed**, it is the mismatch between:
- what admins store (`coding_test_cases.arguments`) and
- what the frontend displays / the harness executes.

---

## 4. How starter_code currently reaches the editor

Candidate flow:

1. `GET /coding/attempt/{id}/problems`
   - backend SELECTs `starter_code` from `coding_problems`.
   - returns `problems[]` with `starter_code` dict like `{"python3": "...", "cpp": "...", "java": "..."}`.

2. `CodingTest.jsx`
   - on problem change: if `problem.draft` exists → uses `problem.draft.source_code`.
   - else → reads `problem.starter_code[defaultLang]`.
   - fallback: if empty → `getDefaultStarter(defaultLang)`.

So if a real problem's `starter_code[lang]` is `null` or missing, the editor shows the generic fallback, which for python3 is:
```
# Write your solution here

def solve():
    pass
```

That fallback is **not** derived from the problem's configured function name, class name, or signature.

---

## 5. Why `solve is not defined` can occur

The most likely production scenario is:

1. Admin creates a function-based python3 problem.
2. `function_name` is `solve` (or something else).
3. `class_name` may be blank or `Solution`.
4. `starter_code` is missing/empty for python3.
5. Candidate loads the problem → editor gets the generic fallback:
   ```
   def solve():
       pass
   ```
   or possibly **empty string** if the fallback logic or load path returns empty.

Then the backend run path for cpp/java (and the python path conceptually) expects candidate code to define a callable named `function_name`. If the editor contains:

- empty code, or
- a function with a different name, or
- top-level script code without defining that name,

then harness generation emits Python that calls `solve(...)` or `_instance.solve(...)` and the executed program either:

- raises `NameError: name 'solve' is not defined`, or
- calls the wrong function, or
- returns nothing/incorrect results.

This is consistent with symptom **A** in the prompt.

A secondary route: if `function_name` on the problem is different from the fallback function name (`solve`), the candidate may be editing a function named `solve` while the harness calls the configured name. That mismatch also produces `NameError` or wrong answers.

---

## 6. Where expected-vs-actual validation currently happens

For **server-side Run/Submit**, validation is in two places:

- `apps/backend/services/harness.py` — per-test harness generates a program that compares `json::stringify(_result) == json::stringify(expected)` (C++), or `_result_json == _expected_json` (Python), or `JsonValue.stringify(...).equals(...)` (Java). That produces per-test pass/fail inside the executed program.
- `apps/backend/services/compiler.py` — `execute_code_sync()` parses the harness JSON output (`_parse_harness_output(stdout, num_tests)`) and maps each harness result into `CompilerResponse.tests[]`.

Then:

- `run_code_public()` builds candidate-facing results including `expected_output`/`actual_output`/`input` on failure.
- `evaluate_submission()` calculates score from `test_cases[] points` + per-test `passed`.

For **client-side Python Run**, the analogous validation is in `apps/frontend/src/execution/harness.js`:

- `buildPythonHarness(...)` builds a Python harness that compares `json.dumps(_result) == json.dumps(_tc_expected)`.
- `buildResultsFromHarness(...)` normalizes the worker's parsed harness JSON to the UI result shape.

So for Python, expected-vs-actual is handled **entirely in the browser**.

---

## 7. Any mismatch between admin test-case data and execution

There are several concrete mismatches in the current code:

### 7.1 Arguments vs input field usage
- Admin schema: `coding_test_cases.arguments` is the canonical JSON array for function-based problems.
- Backend test-case fetch (candidate router) SELECTs `arguments`, `input`, `expected_output`, etc.
- `code_executor.py` uses:
  ```python
  test_arguments = [tc.get("arguments", [tc.get("input", "")]) for tc in test_cases]
  test_expected = [tc.get("expected_output", "") for tc in test_cases]
  ```
  This gracefully falls back to `input` if `arguments` is missing.

- The frontend display path in `CodingTest.jsx` sometimes renders the old `tc.input` style:
  - Examples block uses `tc.input` and `tc.expected_output`.
  - `harness.js` for Python Run uses `tc.arguments ?? tc.input ?? ''`.

So there is a dual-format surface: the newer `arguments` JSON array and the older `input` string. That dual-format is fine for backward compatibility, but it can cause confusion and inconsistency if admin data is incomplete.

### 7.2 Empty/mismatched starter code vs function metadata
- A problem can have `function_name`, `class_name`, `function_signature`, `supported_languages` set, while `starter_code[lang]` is missing.
- The frontend falls back to a generic skeleton, which may not match `function_name`/`class_name`.
- The harness generator uses the **backend function metadata**, not the editor content, so execution may call a function the candidate did not write.

### 7.3 Function signature is available but only typed paths use it
- `function_signature` is fetched from DB for python3, cpp, and java.
- `generate_python_harness(...)` receives it but **does not currently use it** to drive native type marshaling or call patterns.
- `generate_cpp_harness(...)` and `generate_java_harness(...)` have typed signature paths that can strongly type calls, but python uses the older generic argument-index approach.

So for python, the backend does not currently use `function_signature` to generate a typed call; it indexes `_tc_args[i]`.

### 7.4 Public vs hidden
- Candidate problem loading and Run use **only public** test cases.
- Submit uses **all** test cases.
- That part is correct.

### 7.5 Python Run does not go through the DB test-case fetch endpoint for execution params
- Client-side python Run receives `problem.test_cases` (already public-only from `GET /problems`).
- That is correct for Run. Hidden tests are not shipped.

### 7.6 Legacy cpp/java harness path still exists when no signature
- If `function_signature` is blank/None, C++ and Java fall back to the raw `json::Value`/`JsonValue` invocation.
- That legacy path likely does **not** support modern LeetCode-style native signatures correctly; it passes JSON objects into the candidate function.
- The typed path fixes that, but it only activates when signature is provided.

---

## 8. Any hardcoded test cases in frontend/backend/harness code

Strictly speaking, in the current committed code:

- No hardcoded **problem** test cases.
- No hardcoded **problem** source code templates used for execution outside admin UI defaults.

The closest things to "hardcoded problems" are:

1. Admin UI `DEFAULT_STARTER_CODE` defaults (frontend only, per-language skeletons).
2. Candidate UI `getDefaultStarter(...)` fallback strings.
3. Test fixtures in `test_main.py`.

There is **no** runtime fallback test-case list hardcoded in `run_code_public` or `evaluate_submission`. If the DB returns no test cases:
- Run returns `{"all_passed": True, "results": [], "message": "No public test cases"}`.
- Submit raises `400 "No test cases configured"`.

---

## 9. Exact recommended changes, ordered by priority

### Priority 1 — Make starter_code authoritative and consistent with function metadata

This is the most likely fix for symptom **A** and for editor/execution mismatch.

1. **Admin side:**
   - When an admin creates/updates a function-based python3 problem, the admin UI should prefill/derive `starter_code.python3` from `function_name` + `class_name` + `function_signature` + `supported_languages`, so the stored starter code matches the intended function shape.
   - Keep per-language starter code editable, but ensure the default is generated from the metadata, not an arbitrary static string.

2. **Candidate side:**
   - Candidate editor must load the **stored starter code**; never fall back to a generic skeleton that ignores `function_name`/`class_name`.
   - If `starter_code[lang]` is missing for the active language, that should be treated as a configuration problem, not silently replaced with a generic `def solve(): pass`.

3. **Backend side:**
   - `GET /coding/attempt/{id}/problems` already returns `starter_code`. The frontend should use it and surface a clear problem if it is empty.

This directly addresses:
- `solve is not defined` when starter code is empty or uses wrong name.
- mismatched boilerplate when admin wants `class Solution` but editor loads a bare function.

### Priority 2 — Align starter code with harness expectations

The harness generators assume:

- Python: candidate defines `function_name` (and optionally `class_name` with that method).
- C++/Java: candidate defines `function_name` (optionally inside `class_name`).

So the starter code should contain exactly that. In other words:

- For python3 with `class_name=Solution`, starter code should be something like:
  ```python
  class Solution:
      def solve(self, nums, target):
          # Write your solution here
          pass
  ```
- For python3 with no class, starter code should be:
  ```python
  def solve(nums, target):
      # Write your solution here
      pass
  ```

The current AdminCoding default `class Solution ... def solve(...)` is a reasonable template, but downstream candidate loading must preserve it.

### Priority 3 — Fix python Run so public DB test cases drive validation, not hardcoded/fallback expectations

If there are production symptoms where validation/results are incorrect after manual code entry, the likely causes are:

- Candidate wrote the function but the harness call signature is wrong (wrong arg count, wrong class instantiation).
- Harness uses `_tc_args[i]` indexing, which is fragile if `test_arguments` shape disagrees with the actual function params.
- Test expected outputs stored in DB do not match the intended problem (data issue, not code issue).

For python, the backend already uses DB test cases; the client-side Python Run also uses `problem.test_cases`. So the fix is likely:

- ensure public test cases are correctly authored in DB (`arguments` JSON array + `expected_output`),
- ensure starter code defines the function the harness calls,
- ensure `function_name` and `class_name` match the starter code.

### Priority 4 — Make the legacy cpp/java path safe or remove reliance on it

Today, if `function_signature` is blank, cpp/java fall back to passing raw JSON into the candidate function. That is likely part of why cpp/java can fail even when candidate code looks correct.

If the goal is production correctness:

- Admin UI should require or strongly encourage `function_signature` for cpp and java.
- Backend should either:
  - require `function_signature` for typed execution, or
  - derive a usable signature from `starter_code` + `function_name` + `class_name` for the typed path when possible.

This is not a frontend issue; it is a harness/backend issue.

### Priority 5 — Keep hidden-test protection and scoring server-side exactly as is

Current behavior is already correct:

- hidden tests are not sent to candidate.
- scoring only happens server-side on Submit.
- submission response does not expose score.
- Run is non-authoritative.

No architectural change is needed here.

---

## 10. Risks/regressions to watch for

1. **Changing default starter code may break existing problems** if problems currently depend on the old fallback shape. Any change should be additive or default-generation based, not a silent rewrite of stored data.
2. **Python client-side Run currently bypasses the backend Run endpoint**, so any comparison between Python Run and Submit may differ because they use different harnesses:
   - client-side harness in `harness.js`
   - server-side harness in `harness.py`
   - these are intentionally similar but are not the same code. Drift can cause different pass/fail results.
3. **C++/Java typed signature path is great where it works, but only works when signature is provided.** If admins do not provide it, execution reverts to the legacy raw-JSON path.
4. **Arguments vs input dual format** may cause inconsistent displays or harness input if test cases were created in mixed formats.
5. **Empty/missing starter_code for a language** can produce a candidate editor that looks valid but does not define the required function.

---

## 11. What is NOT changed in this audit

- No files were modified.
- No migrations touched.
- No auth changed.
- No Judge0 config changed.
- No frontend Run-vs-submit architecture changed.
- No database schema proposed.
- No new test code proposed.

---

## 12. Summary verdict on the requested production symptoms

- **Symptom A — `name 'solve' is not defined`:** most likely caused by empty/mismatched starter code + harness calling a function the editor did not define.
- **Symptom B — manual code works but validation/results are wrong:** likely caused by mismatch between authored DB test cases (arguments/expected_output) and the harness call shape, or by stale/incorrect public test-case data.
- **Symptom C — system appears to have existing/hardcoded test cases:** not true in the current committed code as a DB problem seed. The appearance is probably caused by the generic fallback skeleton + test-fixture-style mental model, or by cached/incorrect admin-authored test data.
- **Symptom D — boilerplate should exist behind the scenes and be correctly provided as starter code:** yes; that is exactly the current intended design, but the current fallback logic weakens it when stored starter code is missing.

If you want, the next step is a second, smaller audit focused only on the python starter-code → editor → harness call chain, with exact recommended small changes and the exact risky regressions for each.
