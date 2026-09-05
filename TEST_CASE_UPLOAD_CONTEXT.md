# TEST CASE UPLOAD — COMPLETE TECHNICAL AUDIT

> **Purpose**: Full technical context for the existing "Upload Test Cases" feature, supporting the redesign of coding execution (local browser Run + server-side authoritative Submit).
>
> **Date**: 2026-09-06
>
> **Constraint**: No code was modified. This is a read-only audit.

---

## 1. EXECUTIVE SUMMARY

The DSC Recruitment Platform has a fully functional admin test-case upload system that works with the **function-based (LeetCode-style) coding model**. Test cases are managed through `AdminCoding.jsx` on the frontend and `coding_admin.py` on the backend. Uploads happen as **JSON paste into a textarea** (not file upload). Each test case has `arguments` (JSON array) and `expected_output` (any JSON), plus `is_public`, `points`, and `ordering` fields. The database stores both legacy `input`/`expected_output` text columns and new `arguments` JSONB column. The system fully supports nested arrays, objects, strings, numbers, null, and booleans. There is **no file upload** — all test cases are entered or pasted as JSON text.

---

## 2. FRONTEND UPLOAD FLOW

### File: `apps/frontend/src/pages/AdminCoding.jsx`

**Route**: Accessed via navigation from `/admin` panel → "Coding Problems" button.

**UI Layout**: Two-panel design:
- **Left panel**: Problem list (create/edit/delete/activate/deactivate)
- **Right panel**: When a problem is selected, shows test case management

### Two Ways to Add Test Cases

#### A. Individual Test Case (Manual Entry)

- **Button**: "+ Add Test Case"
- **Form fields**:
  - `Arguments (JSON array)` — textarea, required, placeholder: `[[2,7,11,15], 9]`
  - `Expected Output (JSON)` — textarea, required, placeholder: `[0,1]`
  - `is_public` — checkbox (default: unchecked = hidden)
  - `points` — number input (default: 1, min: 1)
  - `ordering` — number input (default: current count, min: 0)
- **Frontend validation**:
  - `arguments` must parse as JSON and must be an array
  - `expected_output` must parse as valid JSON (any type)
- **API call** (create):
  ```js
  POST ${apiUrl}/admin/coding/problems/${selectedProblem.id}/tests
  headers: getAuthHeaders() + credentials: 'include'
  body: JSON.stringify({ arguments, expected_output, is_public, points, ordering })
  ```
- **API call** (edit):
  ```js
  PUT ${apiUrl}/admin/coding/tests/${editingTest.id}
  headers: getAuthHeaders() + credentials: 'include'
  body: JSON.stringify({ arguments, expected_output, is_public, points, ordering })
  ```

#### B. Bulk Upload (JSON Paste)

- **Button**: "📦 Bulk Upload"
- **Input**: textarea where admin pastes a JSON array
- **Placeholder example**:
  ```json
  [{"arguments": [[2,7,11,15], 9], "expected_output": [0,1], "is_public": true, "points": 1}]
  ```
- **Frontend validation**:
  - Must be valid JSON
  - Must be an array
  - Each element must have `arguments` (array) and `expected_output` (defined)
- **API call**:
  ```js
  POST ${apiUrl}/admin/coding/problems/${selectedProblem.id}/tests/bulk
  headers: getAuthHeaders() + credentials: 'include'
  body: JSON.stringify({ test_cases: parsed })
  ```

### Test Case Display

Each test case is shown with:
- Badge: `🌐 PUBLIC` (blue) or `🔒 HIDDEN` (purple)
- Test number and points: `Test 1 (1 pts)`
- Two columns: `Arguments` and `Expected` — rendered as formatted JSON in `<pre>` blocks
- Edit button → populates the individual form
- Delete button → `confirm()` dialog, then DELETE request

### NO FILE UPLOAD

There is **no file picker, no drag-and-drop, no CSV/TXT import**. All test cases are entered as JSON text in a textarea. The only "upload" mechanism is the bulk JSON paste.

---

## 3. BACKEND UPLOAD FLOW

### File: `apps/backend/routers/coding_admin.py`

**Router prefix**: `/admin/coding`

All endpoints require `Depends(require_admin)`.

### Endpoints

| Method | Path | Purpose | Status |
|--------|------|---------|--------|
| GET | `/admin/coding/problems` | List all problems (enriched with test counts) | ✅ |
| POST | `/admin/coding/problems` | Create a new problem | ✅ |
| PUT | `/admin/coding/problems/{problem_id}` | Update a problem | ✅ |
| POST | `/admin/coding/problems/{problem_id}/activate` | Activate a problem | ✅ |
| POST | `/admin/coding/problems/{problem_id}/deactivate` | Deactivate a problem | ✅ |
| DELETE | `/admin/coding/problems/{problem_id}` | Delete problem (if no submissions) | ✅ |
| **GET** | **`/admin/coding/problems/{problem_id}/tests`** | **List all test cases (public + hidden)** | ✅ |
| **POST** | **`/admin/coding/problems/{problem_id}/tests`** | **Create single test case** | ✅ |
| **POST** | **`/admin/coding/problems/{problem_id}/tests/bulk`** | **Bulk upload test cases** | ✅ |
| **PUT** | **`/admin/coding/tests/{test_id}`** | **Update a test case** | ✅ |
| **DELETE** | **`/admin/coding/tests/{test_id}`** | **Delete a test case** | ✅ |

### Bulk Upload Logic (`bulk_upload_test_cases`)

```python
@router.post("/problems/{problem_id}/tests/bulk", status_code=201)
def bulk_upload_test_cases(problem_id, payload: CodingBulkTestUpload, admin):
```

1. Verifies problem exists
2. Iterates `payload.test_cases` (a list of `CodingTestCaseCreate`)
3. For each test case, **inserts individually** (not batched):
   ```python
   supabase_client.table("coding_test_cases").insert({
       "problem_id": problem_id,
       "arguments": tc.arguments,
       "expected_output": tc.expected_output,
       "is_public": tc.is_public,
       "points": tc.points,
       "ordering": tc.ordering if tc.ordering else idx,
       "input": tc.input,
       "expected_output": tc.expected_output,  # NOTE: duplicates with line above
   }).execute()
   ```
4. Returns `{"status": "created", "count": N, "test_cases": [...]}`

### Key Observations

- **APPEND-ONLY**: Bulk upload appends test cases. It does NOT replace existing ones.
- **NO DUPLICATE DETECTION**: There is no check for duplicate arguments/expected_output.
- **NO TRANSACTION**: Each test case is inserted individually. A failure partway through leaves partial inserts.
- **ORDERING**: If `ordering` is not provided, it defaults to the loop index.
- **LEGACY FIELD BUG**: The insert dict sets `"expected_output"` twice — once from `tc.expected_output` and again from `tc.expected_output`. This is a harmless duplicate key but indicates legacy code that hasn't been cleaned up. The `"input": tc.input` field is always `None` since `CodingTestCaseCreate.input` is optional and never set by the frontend.

### Problem Deletion Cascade

When a coding problem is deleted, test cases are explicitly deleted first:
```python
supabase_client.table("coding_test_cases").delete().eq("problem_id", problem_id).execute()
supabase_client.table("coding_drafts").delete().eq("problem_id", problem_id).execute()
supabase_client.table("coding_problems").delete().eq("id", problem_id).execute()
```
The database also has `ON DELETE CASCADE` on `problem_id` FK.

---

## 4. API CONTRACTS

### Create Single Test Case

```
POST /admin/coding/problems/{problem_id}/tests
Authorization: dsc_session cookie + X-CSRF-Token

Request Body:
{
  "arguments": [[2, 7, 11, 15], 9],     // List[Any], required, min 1 element
  "expected_output": [0, 1],              // Any JSON, required
  "is_public": false,                     // bool, default false
  "points": 1,                            // int, 1-10, default 1
  "ordering": 0,                          // int, >= 0, default 0
  "input": null                           // Optional[str], legacy, always null
}

Response 201:
{
  "id": "uuid",
  "problem_id": "uuid",
  "arguments": [...],
  "expected_output": [...],
  "is_public": false,
  "points": 1,
  "ordering": 0,
  "input": null,
  "created_at": "..."
}
```

### Bulk Upload

```
POST /admin/coding/problems/{problem_id}/tests/bulk
Authorization: dsc_session cookie + X-CSRF-Token

Request Body:
{
  "test_cases": [
    {
      "arguments": [[2,7,11,15], 9],
      "expected_output": [0,1],
      "is_public": true,
      "points": 1,
      "ordering": 0
    },
    {
      "arguments": [[3,2,4], 6],
      "expected_output": [1,2],
      "is_public": false,
      "points": 2,
      "ordering": 1
    }
  ]
}

Response 201:
{
  "status": "created",
  "count": 2,
  "test_cases": [...]
}
```

### Update Test Case

```
PUT /admin/coding/tests/{test_id}
Authorization: dsc_session cookie + X-CSRF-Token

Request Body (all fields optional):
{
  "arguments": [...],
  "expected_output": {...},
  "is_public": true,
  "points": 3,
  "ordering": 5
}

Response 200:
{ "id": "uuid", "arguments": [...], ... }
```

### Delete Test Case

```
DELETE /admin/coding/tests/{test_id}
Authorization: dsc_session cookie + X-CSRF-Token

Response 200:
{ "status": "deleted" }
```

### List Test Cases (Admin)

```
GET /admin/coding/problems/{problem_id}/tests
Authorization: dsc_session cookie + X-CSRF-Token

Response 200:
[
  { "id": "uuid", "arguments": [...], "expected_output": [...], "is_public": true, "points": 1, "ordering": 0, ... },
  ...
]
```

---

## 5. DATABASE SCHEMA

### Table: `coding_test_cases`

**Introduced**: Migration 006 (`006_coding_assessment.sql`)
**Extended**: Migration 009 (`009_function_based_coding.sql`)

| Column | Type | Source | Nullable | Default | Notes |
|--------|------|--------|----------|---------|-------|
| `id` | UUID | 006 | NOT NULL | `uuid_generate_v4()` | Primary key |
| `problem_id` | UUID | 006 | NOT NULL | — | FK → `coding_problems(id)` ON DELETE CASCADE |
| `input` | TEXT | 006 | NOT NULL | — | **LEGACY**: stdin input for old model. Always `NULL` in function-based model. |
| `expected_output` | TEXT | 006 | NOT NULL | — | **LEGACY**: stdout expected for old model. In function-based model, stores JSON via Pydantic serialization. |
| `arguments` | JSONB | 009 | NULL | `NULL` | **NEW**: Function arguments as JSONB array. Example: `[[2,7,11,15], 9]` |
| `is_public` | BOOLEAN | 006 | NOT NULL | `false` | Whether visible to candidates |
| `points` | INTEGER | 006 | NOT NULL | `1` | Points for this test case (`CHECK (points > 0)`) |
| `ordering` | INTEGER | 006 | NOT NULL | `0` | Display/sorting order |
| `created_at` | TIMESTAMPTZ | 006 | NOT NULL | `NOW()` | Creation timestamp |

**Indexes**:
- `idx_coding_test_cases_problem_id` on `(problem_id)`
- `idx_coding_test_cases_public` on `(problem_id, is_public)`

**RLS**: Enabled. Only `service_role` has access. `authenticated` and `anon` are explicitly revoked.

### Migration 009 Changes

```sql
ALTER TABLE public.coding_test_cases
    ADD COLUMN IF NOT EXISTS arguments JSONB DEFAULT NULL;
```

This added the `arguments` JSONB column but did **NOT** remove or rename the legacy `input` and `expected_output TEXT` columns. Both coexist.

### What `arguments` Stores

The `arguments` column stores a JSONB array where each element is one argument to the function. Examples:

For `twoSum(nums, target)`:
```json
[[2, 7, 11, 15], 9]
```

For `add(a, b)`:
```json
[3, 5]
```

For `flatten(nested_list)`:
```json
[[1, [2, [3]], 4]]
```

### What `expected_output` Stores

The `expected_output` column stores any JSON value:

```json
[0, 1]           // array
42                // number
"hello"           // string
true              // boolean
null              // null
{"key": "value"}  // object
```

### Important Schema Note

The `expected_output` column is defined as `TEXT NOT NULL` in the original migration (006), but the Pydantic schema and insert code treat it as `Any` JSON. The Supabase PostgREST layer handles serialization. The column name collision between `expected_output TEXT` (legacy) and `expected_output Any` (Pydantic) is resolved by PostgREST/Supabase client handling JSON serialization into the TEXT column.

---

## 6. EXACT UPLOAD FILE FORMAT

### Format: JSON Array (pasted into textarea)

There is **no file upload**. The admin pastes raw JSON into a textarea.

### Expected JSON Structure

```json
[
  {
    "arguments": [[2, 7, 11, 15], 9],
    "expected_output": [0, 1],
    "is_public": true,
    "points": 1,
    "ordering": 0
  },
  {
    "arguments": [[3, 2, 4], 6],
    "expected_output": [1, 2],
    "is_public": false,
    "points": 2,
    "ordering": 1
  }
]
```

### Field Requirements

| Field | Required | Type | Validation |
|-------|----------|------|------------|
| `arguments` | Yes | `List[Any]` (must be array) | Frontend validates `Array.isArray()`, backend validates via Pydantic |
| `expected_output` | Yes | `Any` (any JSON value) | Frontend validates JSON parse, backend via Pydantic |
| `is_public` | No | `bool` | Default: `false` |
| `points` | No | `int` | Default: `1`, range: 1-10 |
| `ordering` | No | `int` | Default: loop index, min: 0 |
| `input` | No | `str` | Legacy field, always `null`, not set by frontend |

### Single Test Case Example (Two Sum)

```json
[
  {
    "arguments": [[2, 7, 11, 15], 9],
    "expected_output": [0, 1],
    "is_public": true,
    "points": 1
  }
]
```

### Complex Nested Example

```json
[
  {
    "arguments": [[[1, 3], [2, 4]], [1, 2]],
    "expected_output": [[1, 2], [3, 4]],
    "is_public": true,
    "points": 2
  }
]
```

### Named Object Arguments (Current Limitation)

The current `arguments` field is a **positional array** — each element maps to the corresponding function parameter. It does NOT support named/keyword arguments like `{"nums": [1,2,3], "target": 5}`. This is because:

1. The Pydantic schema defines `arguments: List[Any]`
2. The harness generates positional calls: `function(args[0], args[1])`
3. The admin form placeholder shows: `[[2,7,11,15], 9]`

---

## 7. FUNCTION-BASED TEST CASE FORMAT COMPATIBILITY

### A. Can it represent `[1, 2, 3]` or `{"nums": [1,2,3], "target": 5}`?

**Positional arrays: YES.** `[[1, 2, 3], 5]` works directly.

**Named objects: NO.** The current `arguments` field is always a positional array. The harness calls `function(args[0], args[1])`. There is no mechanism for named argument passing. If you need `{"nums": [1,2,3], "target": 5}`, you would need to redesign the arguments format.

### B. Can expected outputs be structured JSON?

**YES.** `expected_output` accepts any JSON value: arrays, objects, strings, numbers, booleans, null. The harness compares `json.dumps(result) == json.dumps(expected)`.

### C. Can uploaded test cases distinguish public and hidden tests?

**YES.** The `is_public` boolean field controls visibility. The frontend shows a checkbox. The upload JSON includes `"is_public": true/false`.

### D. Can it support different argument structures for different problems?

**YES.** Each problem has its own test cases with independent `arguments` arrays. The argument count and types are per-problem.

### E. Does it support nested arrays/objects/strings/numbers/null/booleans?

**YES.** Since `arguments` is `JSONB` and `expected_output` is any JSON, full nesting is supported.

### F. Does it support multiple test cases in one upload?

**YES.** The bulk upload accepts up to 100 test cases at once via the JSON array.

---

## 8. PUBLIC VS HIDDEN TEST HANDLING

### How Visibility is Set

- **Individual**: Admin toggles the `is_public` checkbox when creating/editing a test case
- **Bulk**: Each test case in the JSON array includes `"is_public": true/false`
- **Default**: `false` (hidden)

### Where Public/Hidden is Enforced

| Endpoint | Tests Retrieved | Public/Hidden |
|----------|----------------|---------------|
| `GET /admin/coding/problems/{id}/tests` | All test cases | Admin sees ALL (public + hidden) |
| `GET /coding/attempt/{id}/problems` (candidate loads problems) | **Public only** | `WHERE is_public = true` |
| `POST /coding/attempt/{id}/run` (Run Code) | **Public only** | `WHERE is_public = true` |
| `POST /coding/attempt/{id}/submit` (Submit) | **ALL** (public + hidden) | No `is_public` filter |

### Specific Query Patterns

**Candidate loads problems** (`coding.py:100-104`):
```python
tests_resp = (
    supabase_client.table("coding_test_cases")
    .select("id, arguments, expected_output, ordering, points, input")
    .eq("problem_id", p["id"])
    .eq("is_public", True)  # ← PUBLIC ONLY
    .order("ordering")
    .execute()
)
```

**Run Code** (`coding.py:238-243`):
```python
tests_resp = (
    supabase_client.table("coding_test_cases")
    .select("id, arguments, expected_output, is_public, ordering, input")
    .eq("problem_id", payload.problem_id)
    .eq("is_public", True)  # ← PUBLIC ONLY
    .order("ordering")
    .execute()
)
```

**Submit** (`coding.py:290-294`):
```python
tests_resp = (
    supabase_client.table("coding_test_cases")
    .select("id, arguments, expected_output, is_public, points, ordering, input")
    .eq("problem_id", payload.problem_id)
    .order("ordering")
    .execute()
    # ← NO is_public filter — gets ALL tests
)
```

### Security Guarantee

- Hidden test cases are **never sent to the candidate frontend** during problem loading
- Run Code uses **only public tests**
- Submit uses **all tests** but runs server-side only
- The `is_public` field is never exposed to candidates
- The candidate-facing `GET /coding/attempt/{id}/problems` response includes `test_cases` array but only contains public tests with `id`, `arguments`, `expected_output`, `ordering`, `points`, `input` — no `is_public` field is returned

### Potential Concern for Local Execution

If test cases are embedded in the browser for local execution, **public test cases would be visible in the browser's JavaScript/memory**. However, this is by design — they are already visible in the current UI. Hidden test cases must remain server-side only.

---

## 9. CURRENT RUN FLOW

### Run Code (Candidate Feedback, Unscored)

```
Candidate clicks "Run Code" in CodingTest.jsx
    ↓
POST /coding/attempt/{attemptId}/run
  Body: { problem_id, language, source_code }
  Cookie: dsc_session
    ↓
coding.py: run_code()
  1. Verify attempt ownership + in_progress + not expired
  2. Verify problem_id belongs to attempt
  3. Fetch PUBLIC test cases from coding_test_cases
  4. Fetch problem config (time_limit_ms, memory_limit_mb, function_name, class_name)
  5. Call code_executor.run_code_public()
    ↓
code_executor.py: run_code_public()
  1. Extract arguments + expected_output from test cases
  2. Call harness.generate_harness() → complete executable source
  3. Create compiler_test_cases (empty input, expected as JSON string)
  4. Call compiler.execute_code_sync()
    ↓
harness.py: generate_harness()
  - Generates language-specific code that:
    - Embeds test data as JSON constants
    - Defines/imports candidate's solution
    - Calls function with each test case's arguments
    - Compares result to expected output
    - Prints JSON array of {passed, actual, expected}
    ↓
compiler.py: execute_code_sync()
  - Sends to Judge0 CE (self-hosted)
  - POST /submissions (base64, async)
  - Polls GET /submissions/{token}
  - Returns CompilerResponse with per-test results
    ↓
code_executor.py
  - Maps Judge0 results to per-test pass/fail
  - Returns { all_passed, results: [{id, is_public, passed, expected_output, actual_output, status}] }
    ↓
coding.py
  - Returns to candidate: { all_passed, results: [...] }
    ↓
CodingTest.jsx
  - Displays pass/fail for each public test case
  - Shows expected/actual on failure
  - Does NOT show submission scores
```

---

## 10. CURRENT SUBMIT FLOW

### Submit (Server-Side Authoritative Scoring)

```
Candidate clicks "Submit" in CodingTest.jsx
    ↓
POST /coding/attempt/{attemptId}/submit
  Body: { problem_id, language, source_code }
  Cookie: dsc_session
    ↓
coding.py: submit_coding_solution()
  1. Verify attempt ownership + in_progress + not expired
  2. Fetch ALL test cases (public + hidden) — NO is_public filter
  3. Call code_executor.evaluate_submission()
    ↓
code_executor.py: evaluate_submission()
  1. Same harness generation as Run
  2. Execute via Judge0
  3. Score: sum points for passed tests
  4. Returns { score, max_score, tests_passed, tests_total, test_results }
    ↓
coding.py
  - Determines submission status: passed/failed/error/timeout
  - Upserts coding_submissions table
  - Cleans up coding_drafts
  - Returns ONLY { status, submission_id } — NO score/max_score exposed to candidate
```

### What the Candidate Sees After Submit

The candidate gets only `status` (passed/failed/error/timeout) and `submission_id`. The actual score is stored server-side in `coding_submissions.score` and rolled up into the assessment total.

---

## 11. SQL TEST CASE HANDLING

**NOT FOUND / NOT IMPLEMENTED**

There is no support for SQL/database test cases anywhere in the codebase:

- No SQL-specific test case schema fields
- No database setup/teardown logic
- No CREATE TABLE or INSERT seed data handling
- No temporary PostgreSQL database creation
- No SQL-specific test configuration
- The harness only generates code for Python, C++, and Java
- The `VALID_CODING_LANGUAGES` list is `["python3", "cpp", "java"]` — no SQL
- A test in `test_main.py` references `language="sql"` (line 2741) but this is in an MCQ context, not coding test cases

The test-case upload system cannot represent SQL test cases.

---

## 12. SECURITY & AUTHORIZATION

### Authentication

All admin test-case endpoints use `Depends(require_admin)`:
- Verifies `dsc_session` cookie contains valid JWT
- JWT verified via Supabase JWKS
- Looks up profile in Supabase
- Checks `role == 'admin'`

### Authorization

- **Unauthenticated**: → 401
- **Authenticated candidate**: → 403 (require_admin rejects)
- **Authenticated admin**: → Allowed

### Data Protection

- Test cases stored in Supabase with RLS enabled
- Only `service_role` has access (used by FastAPI backend)
- `authenticated` and `anon` roles are explicitly revoked
- Hidden test cases are never included in candidate-facing API responses
- The `GET /admin/coding/problems/{id}/tests` endpoint includes hidden tests but requires admin auth

### CSRF Protection

- All state-changing requests require `X-CSRF-Token` header
- CSRF token stored in readable `dsc_csrf` cookie
- `getAuthHeaders()` reads the cookie and adds the header

### Mass Assignment Risks

- The Pydantic schemas explicitly define allowed fields
- `CodingTestCaseCreate` and `CodingTestCaseUpdate` use `Field()` with validation
- `problem_id` is taken from the URL path, not the request body (no path traversal risk)

### Security Concern for Local Execution

If public test cases are embedded in the browser:
- **Public test cases are already visible** in the current candidate UI
- **Hidden test cases must never reach the browser** — this is currently enforced
- The `arguments` and `expected_output` of public tests are already displayed to candidates
- No security regression from embedding public tests for local execution

---

## 13. COMPLETE FILE MAP

### Frontend

| File | Responsibility |
|------|---------------|
| `apps/frontend/src/pages/AdminCoding.jsx` | Admin coding problem + test case management UI (problem CRUD, test CRUD, bulk upload) |
| `apps/frontend/src/pages/CodingTest.jsx` | Candidate coding test page (shows problems, public test examples, Run/Submit buttons) |
| `apps/frontend/src/components/CodeEditor.jsx` | Code editor component (Monaco/CodeMirror) |

### Backend

| File | Responsibility |
|------|---------------|
| `apps/backend/routers/coding_admin.py` | Admin API: problem CRUD, test case CRUD, bulk upload |
| `apps/backend/routers/coding.py` | Candidate API: load problems, run, submit, drafts |
| `apps/backend/schemas/coding.py` | Pydantic schemas for all coding requests/responses |
| `apps/backend/services/code_executor.py` | Orchestrates harness generation + compiler execution |
| `apps/backend/services/compiler.py` | Judge0 CE client (async submissions + polling) |
| `apps/backend/services/harness.py` | Language-specific harness generators (Python, C++, Java) |
| `apps/backend/services/evaluator.py` | Additional evaluation logic (if used) |

### Schemas

| File | Key Schemas |
|------|------------|
| `apps/backend/schemas/coding.py` | `CodingTestCaseCreate`, `CodingTestCaseUpdate`, `CodingBulkTestUpload`, `CodingRunRequest`, `CodingSubmitRequest`, `CodingProblemCreate`, `CodingProblemUpdate` |

### Database Migrations

| Migration | Relevant Changes |
|-----------|-----------------|
| `006_coding_assessment.sql` | Created `coding_test_cases` table with `input TEXT`, `expected_output TEXT`, `is_public`, `points`, `ordering` |
| `009_function_based_coding.sql` | Added `arguments JSONB` column to `coding_test_cases`; added `function_name`, `class_name`, `function_signature` to `coding_problems` |

### Services

| File | Responsibility |
|------|---------------|
| `services/harness.py` | `generate_python_harness()`, `generate_cpp_harness()`, `generate_java_harness()`, `generate_harness()` |
| `services/compiler.py` | `execute_code_sync()` — Judge0 async submission + polling |
| `services/code_executor.py` | `run_code_public()` (Run), `evaluate_submission()` (Submit) |

### Tests

| File | What is Tested |
|------|---------------|
| `apps/backend/test_main.py` | Backend test suite (185 tests total). Includes `TestCompilerServiceIntegration` for Judge0 mocking. No dedicated test-case upload tests found in the new test classes. |

---

## 14. COMPATIBILITY WITH LOCAL BROWSER EXECUTION

### What Can Remain Unchanged

1. **Test case data format** — `arguments` (JSONB array) and `expected_output` (any JSON) are already machine-readable and can be embedded in the browser
2. **Public/hidden distinction** — The `is_public` field already controls what candidates see
3. **Test case ordering** — The `ordering` field is preserved
4. **Points per test** — The `points` field is preserved
5. **Admin upload flow** — The JSON paste interface works as-is
6. **Problem metadata** — `function_name`, `class_name`, `starter_code`, `supported_languages` are already sent to the candidate
7. **Run Code response shape** — `{ all_passed, results: [{id, is_public, passed, expected_output, actual_output, status}] }`
8. **Submit endpoint** — Server-side scoring uses the same test case data

### What Needs to Change for the New Architecture

#### For Local Run Code (Browser)

The candidate would need:
1. **Public test case data** — Already available via `GET /coding/attempt/{id}/problems` (the `test_cases` array in each problem)
2. **Harness generation** — Currently server-side only. Would need a browser-side equivalent (or WebAssembly-based execution)
3. **The `arguments` and `expected_output` fields** — Already included in the candidate-facing response
4. **No new API needed for Run** — Public tests are already sent with the problem data

#### For Server-Side Submit

1. **No change to test case format** — Submit already uses the same `arguments`/`expected_output` from the database
2. **No change to scoring** — `evaluate_submission()` already handles this
3. **Candidate would send source code** — Same as current `POST /coding/attempt/{id}/submit`
4. **The candidate's submitted code would be the SAME code they ran locally** — No harness needed on the server if the candidate sends their raw function implementation

### Key Insight

The existing test case format is **already fully compatible** with both local and server-side execution. The `arguments` array maps directly to function parameters, and `expected_output` is the expected return value. A browser-side execution engine would:
1. Receive the test cases (already in the problem response)
2. Deserialize the `arguments` array
3. Call the candidate's function with positional arguments
4. Compare `JSON.stringify(result)` to `JSON.stringify(expected_output)`
5. Return pass/fail

No changes to the test case upload system, database schema, or test case format are needed.

---

## 15. REQUIRED CHANGES FOR NEW ARCHITECTURE

### Minimal Changes Required

| Area | Change | Reason |
|------|--------|--------|
| **Frontend Run Code** | Replace server round-trip with browser-side evaluation | Local execution |
| **Harness (Run)** | Move to browser or use WebAssembly | The current `harness.py` generates server-executable code; browser needs equivalent |
| **Submit** | Keep server-side, but candidate sends raw function code | Authoritative scoring |
| **Test case loading** | Already works — public tests sent with problem data | No change needed |
| **Admin upload** | No change needed | Format is compatible |
| **Database** | No change needed | Schema is compatible |
| **Backend Run endpoint** | Could be deprecated or repurposed | If Run is fully client-side |
| **Backend Submit endpoint** | Keep as-is | Authoritative server-side scoring |

### Components That Would Interact With New Model

1. **`GET /coding/attempt/{id}/problems`** — Already sends public test cases to the candidate. This is the data source for local execution.
2. **`POST /coding/attempt/{id}/run`** — Currently server-side. Would be replaced by browser-side evaluation.
3. **`POST /coding/attempt/{id}/submit`** — Keep as-is. Server-side authoritative scoring.
4. **`harness.py`** — The logic for deserializing arguments, calling functions, and comparing results would be reimplemented in JavaScript for the browser.
5. **`code_executor.py: evaluate_submission()`** — Keep for server-side Submit scoring.

---

## 16. KNOWN BUGS & LIMITATIONS

### Bugs

1. **Duplicate `expected_output` key in bulk upload insert** (`coding_admin.py:280`): The insert dict sets `"expected_output"` twice. Harmless but indicates unclean code.

2. **Legacy `input` column always NULL**: The `input TEXT NOT NULL` column from migration 006 is never populated by the function-based upload. The Pydantic schema has `input: Optional[str] = None` but it's included in the insert as `tc.input` which is always `NULL`. This violates the `NOT NULL` constraint at the database level — but Supabase/PostgREST appears to handle this via the service_role bypass.

3. **No bulk transaction**: Each test case in bulk upload is inserted individually. A failure mid-upload leaves partial inserts with no rollback.

4. **No duplicate detection**: Uploading the same test case twice creates duplicates.

### Limitations

1. **No file upload**: Test cases can only be pasted as JSON text. No CSV, TXT, or file import.

2. **Positional arguments only**: The `arguments` field is always a positional array `[[arg1, arg2], ...]`. No named/keyword argument support like `{"nums": [...], "target": 5}`.

3. **Max 100 test cases per bulk upload**: `CodingBulkTestUpload` has `max_length=100`.

4. **Max 10 points per test case**: `points` field is capped at 10.

5. **No SQL test case support**: Cannot represent SQL/database test cases.

6. **No test case templates**: No pre-built templates for common patterns (e.g., two-pointer, BFS, DP).

7. **No validation of expected output correctness**: The system trusts that the admin provides correct expected outputs.

8. **No test case preview**: Admin cannot "dry run" a test case to verify it works before saving.

---

## 17. EXACT EXAMPLES FROM THE EXISTING CODE

### Example: Creating a Two Sum Problem with Test Cases

**Problem** (via POST `/admin/coding/problems`):
```json
{
  "title": "Two Sum",
  "slug": "two-sum",
  "description": "Given an array of integers nums and an integer target, return indices of the two numbers.",
  "difficulty": "easy",
  "function_name": "twoSum",
  "class_name": "Solution",
  "function_signature": "def twoSum(self, nums: List[int], target: int) -> List[int]",
  "supported_languages": ["python3", "cpp", "java"],
  "starter_code": {
    "python3": "class Solution:\n    def twoSum(self, nums, target):\n        pass\n",
    "cpp": "class Solution {\npublic:\n    vector<int> twoSum(vector<int>& nums, int target) {\n        return {};\n    }\n};\n",
    "java": "class Solution {\n    public int[] twoSum(int[] nums, int target) {\n        return new int[]{};\n    }\n}\n"
  },
  "time_limit_ms": 2000,
  "memory_limit_mb": 256,
  "points": 10
}
```

**Test Cases** (via POST `/admin/coding/problems/{id}/tests/bulk`):
```json
{
  "test_cases": [
    {
      "arguments": [[2, 7, 11, 15], 9],
      "expected_output": [0, 1],
      "is_public": true,
      "points": 1,
      "ordering": 0
    },
    {
      "arguments": [[3, 2, 4], 6],
      "expected_output": [1, 2],
      "is_public": true,
      "points": 1,
      "ordering": 1
    },
    {
      "arguments": [[3, 3], 6],
      "expected_output": [0, 1],
      "is_public": false,
      "points": 2,
      "ordering": 2
    }
  ]
}
```

### Example: What the Candidate Sees

When the candidate loads problems (`GET /coding/attempt/{id}/problems`), each problem includes:
```json
{
  "id": "uuid",
  "title": "Two Sum",
  "function_name": "twoSum",
  "class_name": "Solution",
  "starter_code": { "python3": "...", "cpp": "...", "java": "..." },
  "test_cases": [
    {
      "id": "uuid",
      "arguments": [[2, 7, 11, 15], 9],
      "expected_output": [0, 1],
      "ordering": 0,
      "points": 1
    },
    {
      "id": "uuid",
      "arguments": [[3, 2, 4], 6],
      "expected_output": [1, 2],
      "ordering": 1,
      "points": 1
    }
  ]
}
```

Note: Only public tests are included. The hidden test `[[3, 3], 6] → [0, 1]` is NOT sent.

### Example: What the Candidate Submits

```json
POST /coding/attempt/{id}/run
{
  "problem_id": "uuid",
  "language": "python3",
  "source_code": "class Solution:\n    def twoSum(self, nums, target):\n        for i in range(len(nums)):\n            for j in range(i+1, len(nums)):\n                if nums[i] + nums[j] == target:\n                    return [i, j]\n        return []\n"
}
```

### Example: Run Response

```json
{
  "all_passed": true,
  "results": [
    {
      "id": "uuid",
      "is_public": true,
      "passed": true,
      "expected_output": null,
      "actual_output": null,
      "status": "passed",
      "execution_time_ms": 12
    },
    {
      "id": "uuid",
      "is_public": true,
      "passed": true,
      "expected_output": null,
      "actual_output": null,
      "status": "passed",
      "execution_time_ms": 8
    }
  ]
}
```

On failure:
```json
{
  "all_passed": false,
  "results": [
    {
      "id": "uuid",
      "is_public": true,
      "passed": false,
      "expected_output": [0, 1],
      "actual_output": null,
      "status": "wrong_answer",
      "execution_time_ms": 15
    }
  ]
}
```

---

## FILES INSPECTED

1. `apps/frontend/src/pages/AdminCoding.jsx` — Admin test case upload UI
2. `apps/frontend/src/pages/CodingTest.jsx` — Candidate coding test page
3. `apps/backend/routers/coding_admin.py` — Admin test case API
4. `apps/backend/routers/coding.py` — Candidate coding API
5. `apps/backend/schemas/coding.py` — Pydantic schemas
6. `apps/backend/services/code_executor.py` — Execution orchestration
7. `apps/backend/services/compiler.py` — Judge0 client
8. `apps/backend/services/harness.py` — Language-specific harness generators
9. `apps/backend/migrations/006_coding_assessment.sql` — Original coding tables
10. `apps/backend/migrations/009_function_based_coding.sql` — Function-based model migration

## CONFIRMATION

**No files were modified.** Only `TEST_CASE_UPLOAD_CONTEXT.md` was created at the repository root. All other files remain unchanged.
