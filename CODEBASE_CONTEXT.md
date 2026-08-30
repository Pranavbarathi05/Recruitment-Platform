# DSC JSSSTU Recruitment Platform — Codebase Context

> Reference document for the `dsc-recruitment-platform` project. Created from a full codebase scan and debugging session.

---

## Overview

An end-to-end evaluation system for recruiting leads and members for the Developer Student Club (DSC) at JSS Science and Technology University. Candidates take domain-specific technical challenges (ML, Web, UI, CyberSecurity, Backend) through an integrated code editor.

**Status:** Early-stage prototype / skeleton. Many planned features are stubs or TODOs.

---

## Architecture

**Monorepo with two apps:**

```
dsc-recruitment-platform/
├── apps/
│   ├── backend/          # Python / FastAPI
│   └── frontend/         # React 19 / Vite / Tailwind v4
├── README.md
├── CONTRIBUTING.md
└── .coderabbit.yaml
```

- **82 commits**, 13 human contributors, 18 merged PRs
- Branch: `main`

---

## Backend (`apps/backend/`)

### Stack
- **Framework:** FastAPI + Uvicorn
- **ORM:** SQLAlchemy (declarative base)
- **Migrations:** Alembic
- **Database:** PostgreSQL 15 (via Docker Compose)
- **Dependencies:** `requirements-dev.txt` — fastapi, uvicorn, sqlalchemy, alembic, psycopg2-binary, python-dotenv, black, flake8, pytest, httpx

### Database Setup
- **Docker Compose** spins up Postgres 15 Alpine on `localhost:5432`
- Credentials from `.env` (defaults): `dsc_user` / `dsc_password` / `dsc_recruitment`
- Data persisted in Docker volume `postgres_data`
- `database.py` creates engine + `SessionLocal` + `Base`

### Database Status (at time of scan)
- **No tables exist yet** — Alembic migrations have NOT been run
- Need to run `alembic upgrade head` to create tables
- If migration chain is broken: `alembic stamp head && alembic upgrade head`
- **No seed data** — no questions or domains in the DB. Need to INSERT manually or write a seed script

### Models (`models/questions.py`)
```python
class Question(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    description = Column(String)
    domain = Column(String, index=True)
    base_code = Column(Text)
```
Single table. No Candidate model exists yet (only a Pydantic schema).

### Schemas (Pydantic)
| File | Models |
|------|--------|
| `schemas/submission.py` | `Submission` (attempt_id, code, language), `CodeSubmissionRequest` (candidate_id, question_id, language, code_body) |
| `schemas/questions.py` | `QuestionResponse` (id, title, description, base_code) |
| `schemas/candidate.py` | `CandidateCreate` (candidate_id, full_name, email, usn, semester, branch) — **unused** |

### Routers
| File | Endpoints |
|------|-----------|
| `routers/questions.py` | `GET /questions/domains` — returns unique domains with question count and duration |
| | `GET /questions/{domain}` — returns questions filtered by domain |
| `routers/submission.py` | `POST /submission/` — calls `evaluate_code()` (stub) |
| | `POST /submission/code` — receives code submission, does NOT evaluate (V1 stub) |

### Services
| File | Function | Status |
|------|----------|--------|
| `services/questions_services.py` | `fetch_available_domains()` — queries distinct domains from DB, maps to config | Working (needs data) |
| | `fetch_questions_by_domain()` — queries questions by domain | Working (needs data) |
| `services/evaluator.py` | `evaluate_code()` — **placeholder stub**, returns metadata only | TODO: Docker sandbox, test cases, actual evaluation |

### Key Details
- **CORS** configured for `http://localhost:5173` only
- Domain config hardcoded in `questions_services.py`: `{"testDomain": {"name": "Programming Challenge", "duration": 1}}` — other domains default to 20 min
- **No auth middleware** on backend
- **No candidate persistence** — no candidate router or service
- **Single test file** `test_main.py` — only `assert True`

---

## Frontend (`apps/frontend/`)

### Stack
- **React 19.2** + React Router v7
- **Vite 7.2** (dev server on port 5173)
- **Tailwind CSS v4** with custom theme system
- **Monaco Editor** (`@monaco-editor/react`) for code editing
- **Swiper** (in deps but not visibly used in current pages)
- **PropTypes** for type checking (no TypeScript)

### Pages
| Page | Route | Description |
|------|-------|-------------|
| `Landing.jsx` | `/` | Hero section with DSC branding and CTA buttons |
| `Login.jsx` | `/login` | Login form with image carousel — **no real auth** |
| `Signup.jsx` | `/signup` | Signup form (name, email, USN, semester, branch, password) — **no backend call** |
| `Domains.jsx` | `/domains` | Fetches domains from `GET http://localhost:8000/questions/domains` and renders DomainCards |
| `Dashboard.jsx` | `/dashboard` | Placeholder with hardcoded stats (0 applications, 0 interviews) |
| `TestEditor.jsx` | `/test-editor`, `/test/:domainId` | Code editor with timer, question navigation, submission |

### Components
| Component | Location | Description |
|-----------|----------|-------------|
| `Navbar` | `components/layout/` | Responsive nav with dark/light theme toggle (localStorage), mobile menu |
| `Hero` | `components/sections/` | Landing page hero with DSC logo and CTA buttons |
| `CodeEditor` | `components/` | Monaco Editor wrapper — Python, vs-dark theme, 500px height |
| `DomainCard` | `components/` | Domain card with gradient header, question count, duration, start/continue/expired button |
| `Timer` | `components/` | Countdown timer — persists start time in localStorage, warning at <5 min, auto-submits |

### Auth System (`utils/auth.js`)
- **Entirely client-side, localStorage-based**
- `loginUser(username)` stores `{ username, id: "user_<timestamp>", loginTime }` in localStorage
- `isUserLoggedIn()` — checks if `currentUser` key exists in localStorage
- `getCurrentUser()` — parses and returns the stored user object
- `getTestStatus(testId)` — returns `login_required` | `expired` | `in_progress` | `available`
- **No backend auth, no JWT, no tokens, no password verification**
- **No real authentication** — login just checks email/password are non-empty

### Theme System (`index.css`)
- CSS custom variables for dark/light modes (`--bg-primary`, `--text-primary`, etc.)
- Tailwind v4 `@utility` directives: `bg-theme-primary`, `text-theme-secondary`, etc.
- Dark mode default, light mode via `.light` class on `<html>`
- Smooth transitions on theme switch, custom scrollbar, float animation

### API Calls from Frontend
- `http://localhost:8000/questions/domains` — hardcoded in `Domains.jsx` and `TestEditor.jsx`
- `http://localhost:8000/questions/{domainId}` — hardcoded in `TestEditor.jsx`
- **No environment variable for API URL** — hardcoded throughout

---

## Known Issues & Gaps

### Critical
1. **No tables in database** — Alembic migrations never run. Need `alembic upgrade head`
2. **No seed data** — DB is empty, so Domains page shows nothing even if backend runs
3. **Backend not running** — frontend fetches fail with "Failed to load domains"
4. **API URL hardcoded** — `http://localhost:8000` hardcoded in frontend instead of env var

### Authentication
5. **No real auth** — login/signup are purely client-side localStorage
6. **No password hashing or verification**
7. **No backend auth endpoints** — no `/auth/login`, `/auth/register`, etc.
8. **`CandidateCreate` schema defined but never used**

### Code Evaluation
9. **`evaluate_code()` is a stub** — just returns metadata, no actual execution
10. **No Docker sandbox** for code execution
11. **No test cases** for questions

### Frontend
12. **No route protection** — pages like Dashboard are accessible without login (only TestEditor checks)
13. **TestEditor submit is a `setTimeout` stub** — doesn't actually POST to backend
14. **Timer warning interval dependency** — `Timer.jsx` has `timeRemaining` in useEffect deps which may cause extra re-renders

### Testing
15. **Only 1 test file** — `test_main.py` with `assert True`
16. **No frontend tests**

---

## Planned Features (from README)
- Domain-Aligned Tasks (ML, Web, Cloud, UI/UX, Cyber)
- Integrated Code Editor with role-specific syntax highlighting
- Automated Grading with Docker sandboxing
- Proctoring Suite (tab-switch detection, browser logging, screen recording)
- AI Evaluator (experimental) for descriptive/design questions

---

## Quick Reference Commands

```bash
# Start database
cd apps/backend
sudo docker compose up -d

# Run migrations
alembic upgrade head

# Start backend
uvicorn main:app --reload

# Start frontend (separate terminal)
cd apps/frontend
npm run dev

# Connect to DB (psql)
PGPASSWORD=dsc_password psql -h localhost -p 5432 -U dsc_user -d dsc_recruitment

# Insert sample data
INSERT INTO questions (title, description, domain, base_code) VALUES
('Two Sum', 'Return indices of two numbers that add up to target.', 'webDevelopment', '# Write your solution here'),
('Binary Search', 'Implement binary search on a sorted array.', 'backendDevelopment', '# Write your solution here');
```

---

## File Tree (source files only)

```
apps/backend/
├── main.py                    # FastAPI app, CORS, router includes
├── database.py                # SQLAlchemy engine, session, Base
├── alembic.ini                # Alembic config
├── docker-compose.yml         # Postgres 15 container
├── .env.example               # DB credentials template
├── requirements-dev.txt       # Python dependencies
├── DATABASE.md                # DB setup guide
├── test_main.py               # Placeholder test
├── alembic/
│   ├── env.py                 # Alembic env (imports Base, Question model)
│   └── versions/              # Migration files
├── api/
│   └── __init__.py            # Empty
├── core/
│   └── __init__.py            # Empty
├── models/
│   └── questions.py           # Question SQLAlchemy model
├── routers/
│   ├── questions.py           # GET /questions/domains, GET /questions/{domain}
│   └── submission.py          # POST /submission/, POST /submission/code
├── schemas/
│   ├── candidate.py           # CandidateCreate (unused)
│   ├── questions.py           # QuestionResponse
│   └── submission.py          # Submission, CodeSubmissionRequest
├── services/
│   ├── evaluator.py           # evaluate_code() stub
│   └── questions_services.py  # DB queries for domains/questions
└── utils/
    └── __init__.py            # Empty

apps/frontend/
├── package.json               # React 19, Vite 7, Tailwind 4, Monaco
├── vite.config.js
├── index.html
├── eslint.config.js
├── public/                    # Static assets (logo-hero.png, logo-nav.png)
├── src/
│   ├── main.jsx               # React root
│   ├── App.jsx                # Router setup, theme init
│   ├── App.css                # Minimal (Tailwind handles most)
│   ├── index.css              # Theme variables, Tailwind utilities, animations
│   ├── assets/images/         # team.jpg, learn.jpg, share.jpg
│   ├── utils/
│   │   └── auth.js            # localStorage-based auth helpers
│   ├── pages/
│   │   ├── index.js           # Barrel exports
│   │   ├── Landing.jsx        # Hero section
│   │   ├── Login.jsx          # Login form + carousel
│   │   ├── Signup.jsx         # Signup form + carousel
│   │   ├── Domains.jsx        # Fetches & displays domain cards
│   │   ├── Dashboard.jsx      # Placeholder dashboard
│   │   └── TestEditor.jsx     # Code editor + timer + submission
│   └── components/
│       ├── index.js           # Barrel exports
│       ├── CodeEditor.jsx     # Monaco Editor wrapper
│       ├── DomainCard.jsx     # Domain card with status-aware button
│       ├── Timer.jsx          # Countdown with localStorage persistence
│       ├── layout/
│       │   └── Navbar.jsx     # Responsive nav + theme toggle
│       └── sections/
│           └── Hero.jsx       # Landing hero section
```
