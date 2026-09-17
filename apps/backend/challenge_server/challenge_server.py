#!/usr/bin/env python3
"""
SQL Injection micro-CTF challenge server — "Employee Portal"
============================================================

A deliberately VULNERABLE, standalone, shared challenge server for the
Hands-On assessment section. Built entirely on the Python standard library
(http.server + sqlite3) with ZERO third-party dependencies so it can run in
the smallest possible container.

ISOLATION (by design):
  - No Supabase/platform credentials, no environment secrets, no outbound
    network calls, no file access beyond its own SQLite file.
  - The SQLite database contains ONLY synthetic challenge data.
  - The vulnerable SQL query operates exclusively on that SQLite file.
  - One shared server instance serves all candidates (no per-candidate
    containers). Candidates never see each other's data because nothing
    candidate-specific is stored here at all.

THE VULNERABILITY (intentional — do not "fix"):
  The login handler interpolates user input directly into a SQL query:

      SELECT username, role, flag FROM users
      WHERE username = '<u>' AND password = '<p>'

  A successful injection prints the admin login information and the flag.
  The intended solution is standard SQL-injection reasoning; the payload is
  intentionally NOT documented in the rendered page.

Usage:
    python3 challenge_server.py [--port 8080] [--db /path/to/challenge.db]

The database file is (re)seeded with synthetic data on startup only if it
does not exist, so a restart preserves any (synthetic) mutations.
"""

import argparse
import html
import json
import os
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

# ---------------------------------------------------------------------------
# Challenge configuration
# ---------------------------------------------------------------------------

# Static flag for the first implementation. Per-attempt flags are a possible
# future extension (the platform already stores the expected flag per
# question, so rotating flags would only change the seeding step here).
DEFAULT_FLAG = "FLAG{sql1_1nj3ct10n_p0rt4l}"

DB_PATH_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "challenge.db")

PAGE_STYLE = """
    <style>
      body { font-family: Georgia, 'Times New Roman', serif; background: #1a2332;
             color: #e8e8e8; display: flex; justify-content: center; padding-top: 8vh; }
      .portal { background: #243447; border: 1px solid #3c5a78; border-radius: 10px;
                padding: 2rem 3rem; width: 420px; box-shadow: 0 8px 30px rgba(0,0,0,.5); }
      h1 { margin-top: 0; font-size: 1.4rem; letter-spacing: .5px; color: #7fb3ff; }
      label { display: block; margin: .8rem 0 .2rem; font-size: .85rem; color: #9fb6cc; }
      input { width: 100%; box-sizing: border-box; padding: .5rem; border-radius: 5px;
              border: 1px solid #3c5a78; background: #16202e; color: #e8e8e8; }
      button { margin-top: 1.2rem; width: 100%; padding: .6rem; border: 0; border-radius: 5px;
               background: #2f6fdb; color: white; font-weight: bold; cursor: pointer; }
      button:hover { background: #255cb8; }
      .success { background: #142c1b; border: 2px solid #2f9e4f; border-radius: 8px;
                 padding: 1rem 1.4rem; margin-top: 1rem; font-family: monospace; white-space: pre-wrap; }
      .error { background: #331414; border: 1px solid #a33; border-radius: 6px;
               padding: .7rem 1rem; margin-top: 1rem; color: #ffb3b3; }
      .flag { color: #ffd479; font-weight: bold; }
    </style>
"""


def init_db(db_path: str) -> None:
    """Create + seed the challenge database with synthetic data only."""
    if os.path.exists(db_path):
        return  # preserve state across restarts

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                flag TEXT
            );

            -- Synthetic challenge data only. The admin row carries the flag;
            -- regular employees carry none.
            INSERT INTO users (username, password, role, flag) VALUES
              ('admin',    'Sup3rS3cret!', 'administrator', '{flag}'),
              ('hr_maria', 'password123',  'employee',      NULL),
              ('dev_raj',  'qwerty456',    'employee',      NULL),
              ('guest',    'guest',        'guest',         NULL);
            """.replace("{flag}", DEFAULT_FLAG)
        )
        conn.commit()
    finally:
        conn.close()


def vulnerable_login(db_path: str, username: str, password: str):
    """Deliberately vulnerable login. Returns the first matching user row.

    The f-string below interpolates raw user input into the SQL text. This is
    THE vulnerability — by design. It must never be copied into real code.
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        query = (
            "SELECT username, role, flag FROM users "
            f"WHERE username = '{username}' AND password = '{password}'"
        )
        cur.execute(query)
        return cur.fetchone()
    finally:
        conn.close()


def render_login_page(message: str = "", success: dict = None, error: str = "") -> str:
    """Render the Employee Portal login page (and result banners)."""
    result_html = ""
    if success:
        result_html = (
            '<div class="success">'
            "--------------------------------<br>"
            "LOGIN SUCCESSFUL<br><br>"
            f"Username: {html.escape(success['username'])}<br>"
            f"Role: {html.escape(success['role'])}<br><br>"
            "Password: ********<br><br>"
            "Protected Flag:<br>"
            f'<span class="flag">{html.escape(success["flag"])}</span><br>'
            "--------------------------------"
            "</div>"
        )
    elif error:
        result_html = f'<div class="error">Login failed: {html.escape(error)}</div>'
    elif message:
        result_html = f'<div class="error">{html.escape(message)}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Employee Portal</title>
  {PAGE_STYLE}
</head>
<body>
  <div class="portal">
    <h1>Employee Portal</h1>
    <form method="POST" action="login">
      <label for="username">Username</label>
      <input id="username" name="username" autocomplete="off" required>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="off" required>
      <button type="submit">Login</button>
    </form>
    {result_html}
  </div>
</body>
</html>"""


class ChallengeHandler(BaseHTTPRequestHandler):
    server_version = "EmployeePortal/1.0"
    db_path = DB_PATH_DEFAULT

    # ------------------------------------------------------------------
    def _send_html(self, body: str, status: int = 200) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        # NOTE: deliberately NO X-Frame-Options / CSP frame-ancestors header.
        # The assessment UI embeds this page in an <iframe> from a different
        # origin (the platform and the challenge always differ in port at
        # minimum), so X-Frame-Options: SAMEORIGIN makes the browser refuse to
        # render the frame entirely. Same-origin framing restrictions only
        # matter when the page must not be framed elsewhere; this challenge is
        # DESIGNED to be framed by the platform. No CORS headers are needed —
        # CORS governs script reads across origins, not iframe rendering.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        if self.path in ("/", "/login", "/index.html"):
            self._send_html(render_login_page())
        elif self.path == "/health":
            body = json.dumps({"status": "ok"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send_html(
                render_login_page(message="Page not found."), status=404
            )

    # ------------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802 (stdlib naming)
        if self.path != "/login":
            self._send_html(render_login_page(message="Page not found."), status=404)
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length > 8192:  # keep request bodies tiny
            self._send_html(render_login_page(message="Request too large."), status=413)
            return

        form = parse_qs(
            self.rfile.read(length).decode("utf-8", errors="replace"),
            keep_blank_values=True,
        )
        username = (form.get("username") or [""])[0]
        password = (form.get("password") or [""])[0]

        try:
            row = vulnerable_login(self.db_path, username, password)
        except sqlite3.Error as exc:
            # A broken query leaks a generic error — realistic but harmless:
            # it exposes only the challenge's own SQLite state.
            self._send_html(
                render_login_page(error=f"query error ({exc.__class__.__name__})"),
                status=200,
            )
            return

        if row:
            self._send_html(
                render_login_page(success={
                    "username": row[0],
                    "role": row[1],
                    "flag": row[2] or "",
                })
            )
        else:
            self._send_html(render_login_page(error="invalid credentials"))

    # ------------------------------------------------------------------
    def log_message(self, fmt, *args):  # quiet default logging
        if os.environ.get("CHALLENGE_VERBOSE"):
            super().log_message(fmt, *args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Employee Portal SQLi challenge server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CHALLENGE_PORT", "8080")))
    # Default bind 0.0.0.0: candidate browsers reach the challenge over the
    # LAN, so loopback-only listening breaks every machine but the server's
    # own. Override with --host 127.0.0.1 or CHALLENGE_HOST for local testing.
    parser.add_argument("--host", default=os.environ.get("CHALLENGE_HOST", "0.0.0.0"))
    parser.add_argument("--db", default=os.environ.get("CHALLENGE_DB", DB_PATH_DEFAULT))
    args = parser.parse_args()

    init_db(args.db)
    ChallengeHandler.db_path = args.db

    server = ThreadingHTTPServer((args.host, args.port), ChallengeHandler)
    print(f"Employee Portal challenge server listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
