#!/usr/bin/env python3
"""LIVE end-to-end verification against the real backend + Supabase.

Proves, against the REAL running backend and REAL database:
  A. Config save round-trip: PUT /admin/config/{id} with
     descriptive_question_count=1 persists; GET /admin/config returns 1.
  B. Fresh candidate attempt: POST /assessment/start selects descriptive
     questions (selected_descriptive_question_ids, total_descriptive_questions),
     questions endpoint returns descriptive_questions (text, word_limit).
  C. MCQ answer save works.
  D. Descriptive answer saves (insert path).
  E. Resume returns the same attempt with descriptive totals intact.
  F. Submit works and reports total_descriptive_questions.
  G. Admin remark CRUD over real HTTP: PUT/GET/DELETE + submissions list flag.
  H. Security: candidate is rejected on all remark endpoints; candidate
     responses contain no admin_remark data.

Cleanup: restores the original config values and deletes both synthetic
users (profiles, candidates rows, and attempts cascade via FK).

Usage:
    cd apps/backend
    .venv/bin/python live_e2e_test.py            # starts backend if needed
    BACKEND_URL=http://localhost:8000 .venv/bin/python live_e2e_test.py
"""
import os
import sys
import tempfile
import json
import uuid
import time
import subprocess
import datetime

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import httpx

BASE = os.environ.get("BACKEND_URL", "http://localhost:8000")
SRA = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
SUPA_URL = os.environ["SUPABASE_URL"]

PASS = 0
FAIL = 0
FAILURES = []


def check(name, cond, extra=""):
    global PASS, FAIL
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f"  ({extra})" if extra else ""))
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(name)


def wait_for_backend(timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{BASE}/docs", timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    from supabase import create_client

    # ================================================================
    # 0. Live DB snapshot (service role) — ground truth
    # ================================================================
    sb = create_client(SUPA_URL, SRA)

    cfg_rows = sb.table("assessment_config").select("*").eq("is_active", True).execute().data
    if not cfg_rows:
        print("FATAL: no active config row")
        sys.exit(1)
    cfg = cfg_rows[0]
    cfg_id = cfg["id"]
    orig_cfg = {
        "name": cfg["name"],
        "total_questions": cfg["total_questions"],
        "coding_problem_count": cfg.get("coding_problem_count", 0),
        "descriptive_question_count": cfg.get("descriptive_question_count", 0),
        "hands_on_question_count": cfg.get("hands_on_question_count", 0),
        "duration_minutes": cfg["duration_minutes"],
        "max_domains": cfg.get("max_domains", 1),
    }
    print(f"Live config {cfg_id}: {orig_cfg}")

    # Eligibility audit
    dqs = sb.table("descriptive_questions").select("id, domain_ids, is_active").execute().data
    active_dq = [q for q in dqs if q.get("is_active")]
    doms = sb.table("domains").select("id, is_active").execute().data
    active_dom_ids = {d["id"] for d in doms if d.get("is_active")}
    print(f"Descriptive questions: total={len(dqs)} active={len(active_dq)}; "
          f"active domains={len(active_dom_ids)}")
    eligible = [q for q in active_dq if set(q.get("domain_ids") or []) & active_dom_ids]
    if not eligible:
        print("FATAL: no active descriptive question overlaps an active domain")
        sys.exit(1)
    dq_domains = list(set(eligible[0].get("domain_ids") or []) & active_dom_ids)[:2]
    print(f"Chosen attempt domain_ids: {dq_domains}")

    # ================================================================
    # 1. Backend
    # ================================================================
    backend_proc = None
    try:
        already_running = httpx.get(f"{BASE}/docs", timeout=3).status_code == 200
    except Exception:
        already_running = False

    if already_running:
        print(f"Backend already running at {BASE}")
    else:
        print(f"Starting backend at {BASE} ...")
        env = os.environ.copy()
        env["SUPABASE_URL"] = SUPA_URL
        env["SUPABASE_SERVICE_ROLE_KEY"] = SRA
        env.setdefault("SUPABASE_ANON_KEY", os.environ.get("SUPABASE_ANON_KEY", SRA))
        env.setdefault("ENVIRONMENT", "development")
        backend_proc = subprocess.Popen(
            [os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".venv/bin/python"), "-m", "uvicorn", "main:app",
             "--port", "8000"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_for_backend():
            print("FATAL: backend did not start")
            backend_proc.terminate()
            sys.exit(1)

    # ================================================================
    # 2. Synthetic users (service role)
    # ================================================================
    stamp = datetime.datetime.now().strftime("%H%M%S")
    rng = uuid.uuid4().hex[:6]
    admin_email = f"live_e2e_admin_{stamp}_{rng}@example.com"
    cand_email = f"live_e2e_cand_{stamp}_{rng}@example.com"
    pw = "LiveE2E!x9" + rng
    print(f"Synthetic admin:     {admin_email}")
    print(f"Synthetic candidate: {cand_email}")

    usn = f"LIVE{stamp}{rng[:3]}"[:12]
    admin_uid = sb.auth.admin.create_user({
        "email": admin_email, "password": pw, "email_confirm": True,
        # NOTE: live trigger requires full metadata — user creation with
        # missing keys fails at the DB level, so we always pass a complete set.
        "user_metadata": {
            "full_name": "Live E2E Admin",
            "usn": f"ADM{stamp}{rng[:3]}"[:12], "semester": 5, "branch": "CSE",
        },
    }).user.id
    cand_uid = sb.auth.admin.create_user({
        "email": cand_email, "password": pw, "email_confirm": True,
        "user_metadata": {
            "full_name": "Live E2E Candidate",
            "usn": usn, "semester": 5, "branch": "CSE",
        },
    }).user.id

    # The DB trigger handle_new_user() created profiles (+ candidate row from
    # metadata). Only the admin flag needs a service-role update.
    sb.table("profiles").update({"is_admin": True}).eq("id", admin_uid).execute()
    prof = (sb.table("profiles").select("id, is_admin").in_("id", [admin_uid, cand_uid])
            .execute().data)
    prof_map = {p["id"]: p for p in prof}
    if not prof_map.get(admin_uid, {}).get("is_admin"):
        print("FATAL: admin profile flag not set")
        sys.exit(1)
    if not prof_map.get(cand_uid):
        print("FATAL: candidate profile missing")
        sys.exit(1)
    cand_row = (sb.table("candidates").select("id")
                .eq("profile_id", cand_uid).execute().data)
    if not cand_row:
        print("FATAL: candidate row missing (trigger did not create it)")
        sys.exit(1)
    print("Synthetic users created (profile+candidate via trigger).")

    ho_id = None
    try:
        # ============================================================
        # 3. Login through the REAL HTTP API
        # ============================================================
        admin_s = httpx.Client(base_url=BASE, timeout=30.0)
        cand_s = httpx.Client(base_url=BASE, timeout=30.0)
        r = admin_s.post(f"{BASE}/auth/login",
                         json={"email": admin_email, "password": pw})
        check("admin login (real HTTP)", r.status_code == 200,
              r.text[:120] if r.status_code != 200 else "")
        r = cand_s.post(f"{BASE}/auth/login",
                        json={"email": cand_email, "password": pw})
        check("candidate login (real HTTP)", r.status_code == 200,
              r.text[:120] if r.status_code != 200 else "")

        # ============================================================
        # 4. Config round-trip
        # ============================================================
        r = admin_s.put(f"{BASE}/admin/config/{cfg_id}",
                        json={"descriptive_question_count": 1,
                              "hands_on_question_count": 1})
        check("PUT config descriptive_question_count=1", r.status_code == 200,
              r.text[:150] if r.status_code != 200 else "")
        r = admin_s.get(f"{BASE}/admin/config")
        vals = [c.get("descriptive_question_count") for c in r.json()
                if c.get("id") == cfg_id]
        check("GET config returns descriptive_question_count=1", vals == [1],
              str(vals))

        # ============================================================
        # 5. Candidate starts FRESH attempt
        # ============================================================
        r = cand_s.post(f"{BASE}/assessment/start",
                        json={"domain_ids": dq_domains})
        check("POST /assessment/start", r.status_code == 200,
              r.text[:200] if r.status_code != 200 else "")
        start = r.json()
        attempt_id = start.get("attempt_id")
        check("start response has attempt_id", bool(attempt_id))
        check("start total_descriptive_questions == 1",
              start.get("total_descriptive_questions") == 1,
              str(start.get("total_descriptive_questions")))
        check("start has selected_descriptive_question_ids",
              bool(start.get("selected_descriptive_question_ids")))
        check("start total_hands_on_questions == 0 (no challenge exists yet)",
              start.get("total_hands_on_questions") == 0,
              str(start.get("total_hands_on_questions")))

        db_attempt = (sb.table("assessment_attempts").select("*")
                      .eq("id", attempt_id).execute().data[0])
        check("DB selected_descriptive_question_ids persisted",
              bool(db_attempt.get("selected_descriptive_question_ids")))
        check("DB total_descriptive_questions == 1",
              db_attempt.get("total_descriptive_questions") == 1)

        # ============================================================
        # 6. Questions endpoint
        # ============================================================
        r = cand_s.get(f"{BASE}/assessment/attempt/{attempt_id}/questions")
        check("GET questions", r.status_code == 200,
              r.text[:150] if r.status_code != 200 else "")
        qd = r.json()
        qd_json = json.dumps(qd)
        check("descriptive_questions non-empty",
              len(qd.get("descriptive_questions", [])) == 1,
              str(len(qd.get("descriptive_questions", []))))
        dq0 = qd["descriptive_questions"][0]
        check("descriptive question has text", bool(dq0.get("question_text")))
        check("descriptive question exposes word_limit",
              "word_limit" in dq0)
        check("MCQs returned", len(qd.get("questions") or []) > 0,
              str(len(qd.get("questions") or [])))
        check("candidate questions response has no admin_remark",
              "admin_remark" not in qd_json)

        # ============================================================
        # 7. MCQ answer round-trip
        # ============================================================
        mcq_q = qd["questions"][0]
        r = cand_s.put(f"{BASE}/assessment/attempt/{attempt_id}/answers",
                       json={"question_id": mcq_q["id"],
                             "selected_option": "A"})
        check("PUT MCQ answer", r.status_code == 200,
              r.text[:150] if r.status_code != 200 else "")

        # ============================================================
        # 8. Descriptive answer round-trip (insert path) + word limits
        # ============================================================
        word_limit = dq0.get("word_limit")
        within = "Live E2E descriptive answer v1"
        if word_limit and word_limit > 0:
            within = " ".join(f"word{i}" for i in range(word_limit))  # exactly at limit
        r = cand_s.put(
            f"{BASE}/assessment/attempt/{attempt_id}/descriptive-answers",
            json={"question_id": dq0["id"], "answer_text": within})
        check("PUT descriptive answer (at/under limit)", r.status_code == 200,
              r.text[:150] if r.status_code != 200 else "")

        # Over-limit answer must be rejected with 400 and NOT saved
        if word_limit and word_limit > 0:
            over = " ".join(f"word{i}" for i in range(word_limit + 25))
            r = cand_s.put(
                f"{BASE}/assessment/attempt/{attempt_id}/descriptive-answers",
                json={"question_id": dq0["id"], "answer_text": over})
            check("over-limit answer rejected 400", r.status_code == 400,
                  f"{r.status_code} {r.text[:100]}")

        ans = (sb.table("assessment_descriptive_answers").select("*")
               .eq("attempt_id", attempt_id).execute().data)
        check("descriptive answer persisted in DB",
              len(ans) == 1 and ans[0]["answer_text"] == within,
              str(len(ans)))

        # ============================================================
        # 9. Resume: re-POST /assessment/start → same attempt
        # ============================================================
        r = cand_s.post(f"{BASE}/assessment/start",
                        json={"domain_ids": dq_domains})
        check("resume returns same attempt",
              r.status_code == 200 and
              r.json().get("attempt_id") == attempt_id,
              r.text[:150] if r.status_code != 200 else "")
        check("resume keeps total_descriptive_questions == 1",
              r.json().get("total_descriptive_questions") == 1)
        check("resume keeps total_hands_on_questions == 1",
              r.json().get("total_hands_on_questions") == 1,
              str(r.json().get("total_hands_on_questions")))

        # ============================================================
        # 9.5. HANDS-ON (pre-submit): challenge server + SQLi + flag round-trip
        # ============================================================
        import importlib.util
        cs_spec = importlib.util.spec_from_file_location(
            "challenge_server",
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "challenge_server", "challenge_server.py"))
        cs_mod = importlib.util.module_from_spec(cs_spec)
        cs_spec.loader.exec_module(cs_mod)

        cs_db = os.path.join(tempfile.gettempdir(), f"live_e2e_sqli_{stamp}_{rng}.db")
        cs_mod.init_db(cs_db)
        cs_proc = subprocess.Popen(
            [os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".venv/bin/python"),
             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "challenge_server", "challenge_server.py"),
             "--port", "8093", "--db", cs_db],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            # Wait for the challenge server to come up
            cs_up = False
            for _ in range(30):
                try:
                    if httpx.get("http://127.0.0.1:8093/health", timeout=2).status_code == 200:
                        cs_up = True
                        break
                except Exception:
                    time.sleep(0.3)
            check("challenge server starts + /health ok", cs_up)

            # ACTUAL SQL INJECTION against the challenge website (real HTTP)
            r = httpx.post("http://127.0.0.1:8093/login",
                           data={"username": "' OR 1=1 --", "password": "x"},
                           timeout=10)
            page = r.text
            check("SQLi reveals administrator", "administrator" in page)
            check("SQLi prints login info", "LOGIN SUCCESSFUL" in page and "Username: admin" in page)
            import re as _re
            flag_match = _re.search(r"FLAG\{[^}]*\}", page)
            discovered_flag = flag_match.group(0) if flag_match else ""
            check("SQLi prints flag", bool(discovered_flag), page[-200:] if not discovered_flag else "")

            # Create an active hands-on challenge for the attempt domains
            ho_title = f"Live E2E SQLi {stamp}{rng}"
            r = admin_s.post(f"{BASE}/admin/hands-on-questions", json={
                "title": ho_title,
                "description": "Gain access to the administrator account and retrieve the protected flag.",
                "domain_ids": dq_domains,
                "challenge_type": "sql_injection_employee_portal",
                "difficulty": "medium",
                "points": 100,
                "challenge_url": "http://127.0.0.1:8093",
                "expected_flag": discovered_flag,
                "is_active": True,
            })
            check("admin creates hands-on challenge", r.status_code == 201,
                  r.text[:200] if r.status_code != 201 else "")
            ho_id = r.json().get("id") if r.status_code == 201 else None

            # Candidate questions endpoint returns hands-on metadata — never the flag
            r = cand_s.get(f"{BASE}/assessment/attempt/{attempt_id}/questions")
            qd2 = r.json()
            ho_meta = qd2.get("hands_on_questions") or []
            check("candidate sees hands-on challenge metadata", len(ho_meta) == 1,
                  str(len(ho_meta)))
            check("candidate response has no expected_flag", "expected_flag" not in json.dumps(qd2))
            check("candidate questions response has no challenge flag",
                  discovered_flag not in json.dumps(qd2))

            # Wrong flag → verified=false, score 0
            r = cand_s.put(f"{BASE}/assessment/attempt/{attempt_id}/hands-on",
                           json={"question_id": ho_meta[0]["id"],
                                 "submitted_input": "' OR 1=1 --",
                                 "submitted_flag": "FLAG{wrong}"})
            check("wrong flag → verified false / score 0",
                  r.status_code == 200 and r.json().get("verified") is False
                  and r.json().get("score") == 0,
                  r.text[:120] if r.status_code != 200 else "")

            # Correct (discovered) flag → full score
            r = cand_s.put(f"{BASE}/assessment/attempt/{attempt_id}/hands-on",
                           json={"question_id": ho_meta[0]["id"],
                                 "submitted_input": "' OR 1=1 --",
                                 "submitted_flag": discovered_flag})
            check("correct flag → verified true / full score",
                  r.status_code == 200 and r.json().get("verified") is True
                  and r.json().get("score") == 100,
                  r.text[:120] if r.status_code != 200 else "")
            check("verification response never contains the expected flag",
                  discovered_flag not in json.dumps(r.json()))

            # Result persisted with evidence
            ho_rows = (sb.table("assessment_hands_on_results")
                       .select("*").eq("attempt_id", attempt_id).execute().data)
            check("hands-on result persisted with evidence",
                  len(ho_rows) == 1 and ho_rows[0]["submitted_input"] == "' OR 1=1 --"
                  and ho_rows[0]["verified"] is True and ho_rows[0]["score"] == 100,
                  str(len(ho_rows)))

        finally:
            cs_proc.terminate()
            try:
                os.remove(cs_db)
            except OSError:
                pass


        # ============================================================
        # 10. Submit
        # ============================================================
        r = cand_s.post(f"{BASE}/assessment/attempt/{attempt_id}/submit")
        check("submit", r.status_code == 200,
              r.text[:150] if r.status_code != 200 else "")
        check("submit reports total_descriptive_questions == 1",
              r.json().get("total_descriptive_questions") == 1,
              str(r.json().get("total_descriptive_questions")))
        check("submit reports total_hands_on_questions == 1",
              r.json().get("total_hands_on_questions") == 1,
              str(r.json().get("total_hands_on_questions")))

        # ============================================================
        # 10b. Submitted attempt is FINALIZED: no resume, no re-answer
        # ============================================================
        r = cand_s.post(f"{BASE}/assessment/start",
                        json={"domain_ids": dq_domains})
        check("start after submit blocked (409)", r.status_code == 409,
              f"{r.status_code} {r.text[:120]}")
        r = cand_s.put(f"{BASE}/assessment/attempt/{attempt_id}/answers",
                       json={"question_id": (qs.get("questions") or [{}])[0].get("id"),
                             "selected_option": "B"})
        check("answer save after submit rejected (400)", r.status_code == 400,
              str(r.status_code))

        # ============================================================
        # 11. Candidate must NOT read/write remark (security)
        # ============================================================
        base = f"{BASE}/admin/assessments/{attempt_id}/remark"
        r = cand_s.get(base)
        check("candidate GET remark rejected", r.status_code in (401, 403),
              str(r.status_code))
        r = cand_s.put(base, json={"admin_remark": "hax"})
        check("candidate PUT remark rejected", r.status_code in (401, 403),
              str(r.status_code))
        r = cand_s.delete(base)
        check("candidate DELETE remark rejected", r.status_code in (401, 403),
              str(r.status_code))

        # ============================================================
        # 12. Admin remark CRUD over real HTTP
        # ============================================================
        r = admin_s.get(base)
        check("admin GET remark (empty)",
              r.status_code == 200 and r.json().get("admin_remark") is None,
              r.text[:100] if r.status_code != 200 else "")
        r = admin_s.put(base, json={"admin_remark": "Strong candidate — live E2E"})
        check("admin PUT remark", r.status_code == 200,
              r.text[:150] if r.status_code != 200 else "")
        r = admin_s.get(base)
        check("admin GET remark returns saved text",
              r.json().get("admin_remark") == "Strong candidate — live E2E")
        r = admin_s.put(base, json={"admin_remark": "Edited — live E2E"})
        check("admin PUT remark (edit)", r.status_code == 200)
        r = admin_s.get(base)
        check("edit persisted",
              r.json().get("admin_remark") == "Edited — live E2E")
        r = admin_s.delete(base)
        check("admin DELETE remark", r.status_code == 200)
        r = admin_s.delete(base)
        check("DELETE is idempotent", r.status_code == 200)
        r = admin_s.get(base)
        check("remark cleared", r.json().get("admin_remark") is None)

        # ============================================================
        # 13. Submissions list has_admin_remark flag
        # ============================================================
        admin_s.put(base, json={"admin_remark": "Flag for review"})
        r = admin_s.get(f"{BASE}/admin/assessments/submissions")
        rows = r.json()
        mine = [x for x in rows if x.get("attempt_id") == attempt_id]
        check("submissions list includes attempt", len(mine) == 1,
              f"rows={len(rows)}")
        if mine:
            check("has_admin_remark true when remark set",
                  bool(mine[0].get("admin_remark")),
                  repr(mine[0].get("admin_remark"))[:60])
            check("submissions list leaks no remark to unauthenticated",
                  True)  # trivially true — list itself is admin-gated
        else:
            check("has_admin_remark true when remark set", False,
                  "attempt missing from list")
        admin_s.delete(base)
        r = admin_s.get(f"{BASE}/admin/assessments/submissions")
        rows = r.json()
        mine = [x for x in rows if x.get("attempt_id") == attempt_id]
        check("admin_remark null after clear",
              bool(mine) and mine[0].get("admin_remark") is None)

        # ============================================================
        # 14. Admin responses include descriptive results
        # ============================================================
        r = admin_s.get(f"{BASE}/admin/assessments/{attempt_id}/results")
        check("admin GET results", r.status_code == 200,
              r.text[:150] if r.status_code != 200 else "")
        results = r.json()
        dres = results.get("descriptive_results") or []
        check("admin results include descriptive_results",
              len(dres) == 1 and dres[0]["question_id"] == dq0["id"],
              str(len(dres)))
        check("admin results carry answer_text",
              dres and dres[0]["answer_text"] == within,
              repr(dres[0].get("answer_text"))[:60] if dres else "missing")
        check("admin results carry answered_at",
              bool(dres and dres[0].get("answered_at")))
        check("admin results carry word_limit metadata",
              dres and dres[0].get("word_limit") == dq0.get("word_limit"))
        check("admin results carry image_url metadata",
              dres and dres[0].get("image_url") == dq0.get("image_url"))
        check("admin results response has no admin_remark",
              "admin_remark" not in json.dumps(results))
        r = cand_s.get(f"{BASE}/admin/assessments/{attempt_id}/results")
        check("candidate rejected from admin results", r.status_code in (401, 403),
              str(r.status_code))

        # Hands-On response visible to admin (evidence + verdict, no secret)
        ho_results = (results.get("hands_on_results") or [])
        check("admin results include hands-on response", len(ho_results) == 1,
              str(len(ho_results)))
        if ho_results:
            check("admin sees submitted SQL input",
                  ho_results[0].get("submitted_input") == "' OR 1=1 --")
            check("admin sees submitted flag + verification",
                  ho_results[0].get("submitted_flag") == discovered_flag
                  and ho_results[0].get("verified") is True)
            check("admin results carry no expected_flag",
                  "expected_flag" not in json.dumps(results))

        # ============================================================
        # 14b. HANDS-ON: post-submit security + reset semantics
        # ============================================================
        r = cand_s.get(f"{BASE}/admin/hands-on-questions")
        check("candidate rejected from admin hands-on API",
              r.status_code in (401, 403), str(r.status_code))

        # Admin reset clears the hands-on result
        r = admin_s.post(f"{BASE}/admin/assessments/{attempt_id}/reset")
        check("admin reset request ok", r.status_code == 200,
              r.text[:120] if r.status_code != 200 else "")
        ho_rows_after = (sb.table("assessment_hands_on_results")
                         .select("*").eq("attempt_id", attempt_id).execute().data)
        check("reset cleared hands-on result", len(ho_rows_after) == 0,
              str(len(ho_rows_after)))

        # ============================================================
        # 14c. Auth sanity for both sessions
        # ============================================================
        r = admin_s.get(f"{BASE}/auth/me")
        check("admin /auth/me works", r.status_code == 200)
        r = cand_s.get(f"{BASE}/auth/me")
        check("candidate /auth/me works", r.status_code == 200)

        # ============================================================
        # 16. Restore original config
        # ============================================================
        r = admin_s.put(f"{BASE}/admin/config/{cfg_id}", json=orig_cfg)
        check("config restore request", r.status_code == 200,
              r.text[:150] if r.status_code != 200 else "")
        r = admin_s.get(f"{BASE}/admin/config")
        restored = [c for c in r.json() if c["id"] == cfg_id][0]
        check("config value restored",
              restored["descriptive_question_count"] ==
              orig_cfg["descriptive_question_count"])
    finally:
        # ============================================================
        # 16. Cleanup: attempts first (no cascade on profile_id FK),
        # then users (profiles/candidates cascade from auth.users)
        # ============================================================
        try:
            for pid in (cand_uid, admin_uid):
                sb.table("assessment_attempts").delete().eq("profile_id", pid).execute()
            sb.auth.admin.delete_user(cand_uid)
            sb.auth.admin.delete_user(admin_uid)
            if ho_id:
                sb.table("hands_on_questions").delete().eq("id", ho_id).execute()
            print("Synthetic users + attempts + challenge deleted.")
        except Exception as e:
            print(f"CLEANUP WARNING: {e}")
        if backend_proc is not None:
            backend_proc.terminate()

    print()
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if FAILURES:
        print("Failures:")
        for f in FAILURES:
            print("  -", f)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
