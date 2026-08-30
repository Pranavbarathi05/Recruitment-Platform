# DSC JSSSTU Recruitment Platform — Context Block

> Use this document as context for discussing database schema, auth strategy, and Supabase integration design.

---

## What This Project Is

A recruitment platform for the Developer Student Club (DSC) at JSS Science and Technology University. Candidates sign up, pick a technical domain (ML, Web Dev, UI, CyberSecurity, Backend), take a timed coding challenge in an integrated Monaco editor, and get evaluated. Leads/admins can eventually review submissions.

**Current state:** Frontend skeleton exists with working pages. Backend skeleton has routes stubbed out. Database was just removed — we're migrating to Supabase. No auth, no persistence, no evaluation logic yet.

---

## Tech Stack

| Layer | Stack |
|-------|-------|
| Frontend | React 19.2, React Router v7, Vite 7.2, Tailwind CSS v4, Monaco Editor, PropTypes (no TypeScript) |
| Backend | Python, FastAPI, Uvicorn |
| Database/Auth | **Moving to Supabase** (Postgres + Auth + RLS) |
| Eval (planned) | Docker sandbox for code execution |

---

## Backend Codebase (apps/backend/)

### main.py
```python
from fastapi import FastAPI
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from routers import submission
from routers import questions

app = FastAPI(
    title="DSC Recruitment Platform API",
    description="Backend API for code submission and evaluation",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(submission.router)
app.include_router(questions.router, tags=["Questions"])

@app.get("/")
def root():
    return {"status": "Healthy", "message": "API is working"}
```

### routers/questions.py
```python
from fastapi import APIRouter

router = APIRouter()

@router.get("/questions/domains")
def get_domains():
    # TODO: Implement with Supabase
    return []

@router.get("/questions/{domain}")
def get_questions(domain: str):
    # TODO: Implement with Supabase
    return []
```

### routers/submission.py
```python
from fastapi import APIRouter, HTTPException, status
from schemas.submission import Submission, CodeSubmissionRequest
from services.evaluator import evaluate_code

router = APIRouter(tags=["Submission"], prefix="/submission")

@router.post("/", status_code=202)
async def submit_code(submission: Submission):
    try:
        result = evaluate_code(
            attempt_id=submission.attempt_id,
            code=submission.code,
            language=submission.language,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/code", status_code=status.HTTP_202_ACCEPTED)
async def receive_code_submission(payload: CodeSubmissionRequest):
    if not payload.candidate_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="candidate_id is required"
        )
    print(f"Code received from {payload.candidate_id} for question {payload.question_id}")
    return {"message": "Submission Received"}
```

### services/evaluator.py
```python
from typing import Dict, Any

def evaluate_code(attempt_id: str, code: str, language: str) -> Dict[str, Any]:
    # TODO: Docker sandbox, test cases, actual evaluation
    return {
        "status": "received",
        "message": "Received",
        "attempt_id": attempt_id,
        "language": language,
        "code_length": len(code),
    }
```

### schemas/ (Pydantic models — define expected shapes)

**schemas/candidate.py** (defined but never used anywhere):
```python
from pydantic import BaseModel, EmailStr

class CandidateCreate(BaseModel):
    candidate_id: int
    full_name: str
    email: EmailStr
    usn: str
    semester: int
    branch: str
```

**schemas/questions.py:**
```python
from pydantic import BaseModel

class QuestionResponse(BaseModel):
    id: int
    title: str
    description: str
    base_code: str
```

**schemas/submission.py:**
```python
from pydantic import BaseModel, Field

class Submission(BaseModel):
    attempt_id: str
    code: str = Field(..., description="The users code submission")
    language: str = Field(..., description="Programming language selected by the user")

class CodeSubmissionRequest(BaseModel):
    candidate_id: str
    question_id: str
    language: str
    code_body: str
```

### services/questions_services.py (stubbed):
```python
def fetch_available_domains():
    # TODO: Implement with Supabase
    return []

def fetch_questions_by_domain(domain: str):
    # TODO: Implement with Supabase
    return []
```

### requirements-dev.txt
```
fastapi
uvicorn
python-dotenv
black
flake8
pytest
httpx
```

---

## Frontend Codebase (apps/frontend/)

### Pages

**Landing.jsx** (`/`) — Hero section with DSC branding and CTA buttons.

**Login.jsx** (`/login`) — Email/password form. On submit: calls `loginUser(email)` which stores `{username, id: "user_<timestamp>", loginTime}` in localStorage. No backend call. Redirects to `/domains`.

**Signup.jsx** (`/signup`) — Collects: fullName, email, USN, semester (1-8), branch (CSE/ECE/EEE/ME/CE/IT/BT), password. On submit: calls `onSignup` callback (not wired up), navigates to `/login`. No backend call.

**Domains.jsx** (`/domains`) — Fetches `GET http://localhost:8000/questions/domains`, renders `DomainCard` grid. Shows loading spinner, error state, or empty state.

**Dashboard.jsx** (`/dashboard`) — Placeholder. Shows hardcoded 0 applications, 0 interviews, "Active" status.

**TestEditor.jsx** (`/test/:domainId`) — The core test page.
- Checks `isUserLoggedIn()` from localStorage; redirects to `/login` if not
- If `domainId` provided: fetches domain info + questions from backend
- If no `domainId`: loads a hardcoded demo question
- Shows question title, description, Monaco editor, question navigation, submit button
- Timer component with countdown
- `submitCode()` is a `setTimeout` stub — logs to console, shows alert, does NOT POST to backend
- Test expiry tracked in localStorage via `getTestStatus()`

### Key Components

**DomainCard** — Renders domain name, question count, duration, status-aware button (Start Test / Continue Test / Login to Start / Test Expired). Uses domain-specific gradient colors from a hardcoded map.

**Timer** — Countdown timer. Persists start time in `localStorage` as `timer_{testId}_{userId}`. Warns at <5 min, auto-submits at 0. Marks test as expired in localStorage.

**CodeEditor** — Monaco Editor wrapper. Python language, vs-dark theme, 500px height.

**Navbar** — Responsive nav with dark/light theme toggle (localStorage), mobile menu.

### Frontend Auth (utils/auth.js)
```javascript
// Entirely client-side, localStorage-based
export const loginUser = (username) => {
  const user = { username, id: `user_${Date.now()}`, loginTime: Date.now() };
  localStorage.setItem('currentUser', JSON.stringify(user));
  return user;
};

export const isUserLoggedIn = () => !!localStorage.getItem('currentUser');
export const getCurrentUser = () => JSON.parse(localStorage.getItem('currentUser'));
export const logoutUser = () => localStorage.removeItem('currentUser');

export const getTestStatus = (testId) => {
  // Returns: 'login_required' | 'expired' | 'in_progress' | 'available'
  // Uses localStorage keys: timer_{testId}_{userId} and timer_{testId}_{userId}_expired
};
```

### API calls from frontend
- `http://localhost:8000/questions/domains` — hardcoded in Domains.jsx and TestEditor.jsx
- `http://localhost:8000/questions/{domainId}` — hardcoded in TestEditor.jsx
- No environment variable for API URL

---

## Planned Domains (hardcoded in frontend)
```
machineLearning, webDevelopment, userInterface, cyberSecurity, backendDevelopment
```
DomainCard.jsx has a hardcoded color map for these. Backend previously had a hardcoded config: `{"testDomain": {"name": "Programming Challenge", "duration": 1}}` — other domains defaulted to 20 min.

---

## What Was Just Removed (pre-Supabase DB)
- `database.py` — SQLAlchemy engine, SessionLocal, Base, get_db dependency
- `alembic/` + `alembic.ini` — Migration infrastructure
- `models/questions.py` — Single `Question` table (id, title, description, domain, base_code)
- `docker-compose.yml` — PostgreSQL 15 container
- `DATABASE.md` — Setup docs
- `.env.example` — DB_USER, DB_PASSWORD, DB_NAME, DB_HOST, DB_PORT
- SQLAlchemy, alembic, psycopg2-binary removed from requirements

---

## What Needs to Be Designed for Supabase

### 1. Database Schema (Postgres tables via Supabase)

Entities to consider:
- **candidates/applicants** — signup data (name, email, USN, semester, branch + Supabase Auth user)
- **domains** — test domains (name, slug, duration, question count, config)
- **questions** — per-domain questions (title, description, domain FK, base_code, test cases?)
- **test_attempts** — a candidate starting a domain test (start time, status, which domain)
- **submissions** — code submissions per question per attempt (code, language, timestamps, evaluation results)
- **evaluation_results** — scores, pass/fail, execution output
- **admin/lead roles** — who can review, who is just a candidate

### 2. Auth Strategy
- Supabase Auth for signup/login (email+password, possibly Google OAuth)
- How to link `auth.users` to a `candidates` profile table
- Row Level Security: candidates see only their own data, admins see everything
- JWT token handling: backend receives Supabase JWT, verifies it, gets user identity
- Frontend: Supabase JS client for auth, stores session in Supabase's built-in session management (replaces localStorage hack)

### 3. Backend ↔ Supabase Connection
- Backend uses `supabase-py` client or direct PostgREST
- Or: backend uses service role key for server-side operations
- How RLS policies interact with backend calls (service role bypasses RLS vs user JWT respects RLS)

### 4. Code Evaluation Flow
- Where do test cases live? (in Supabase? separate?)
- How does the evaluator sandbox work? (Docker, subprocess, cloud function?)
- How are results written back? (submission → evaluation_results)

### 5. Frontend Changes
- Replace localStorage auth with Supabase JS client
- Replace hardcoded API URLs with env var
- Protect routes properly (Dashboard, TestEditor)
- Session management across page refreshes

---

## User Flow (end to end)

1. Candidate lands on `/` (Landing page)
2. Signs up at `/signup` with: name, email, USN, semester, branch, password
3. Confirms email (Supabase built-in)
4. Logs in at `/login` with email + password
5. Sees `/domains` — picks a domain (e.g., "Web Development")
6. Enters `/test/{domainId}` — timer starts, questions load from backend
7. Writes code in Monaco editor for each question
8. Submits — code is sent to backend, evaluated against test cases
9. Sees results (pass/fail, output, score)
10. Can view history on `/dashboard`

---

## Constraints & Notes

- No TypeScript — PropTypes only
- FastAPI backend, not Node
- Python backend talks to Supabase (not direct Postgres)
- Frontend is a separate Vite dev server on port 5173
- CORS configured for localhost:5173
- The platform is for a university club — relatively small user base (< 200 candidates per recruitment cycle)
- This is a student project, not enterprise — keep it simple
