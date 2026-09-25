#!/usr/bin/env python3
"""DEV-only client network-integrity helper.

WHY THIS EXISTS
---------------
A browser JavaScript application cannot send ICMP echo requests. The assessment
integrity policy needs to know whether the CANDIDATE MACHINE can reach a fixed
target over ICMP, so this tiny local helper performs the actual `ping` and
answers over loopback HTTP:

    assessment page (browser)
        -> GET http://127.0.0.1:<port>/network-check   (loopback HTTP)
    this helper
        -> ICMP echo request to 8.8.8.8                (system ping binary)

DESIGN CONSTRAINTS (deliberate, see the assessment feature spec)
---------------------------------------------------------------
* Binds LOOPBACK ONLY (127.0.0.1). It is never reachable from the network.
* The target is HARDCODED. The endpoint accepts no parameters, so a caller can
  never make it probe an arbitrary host (no ping-based port scanning / no
  "run command" API).
* One operation only: GET /network-check. Everything else is 404/405.
* Only structured JSON is returned. No shell is involved; the ping binary is
  invoked with a fixed argv (no shell=True, no interpolation).
* Pings are short-lived with a bounded timeout, child processes are reaped, and
  concurrent/overlapping requests share one in-flight probe.
* CORS is restricted to an explicit origin allowlist (never "*").

This helper is intentionally NOT part of the deployed stack (no Docker, no
gateway/Traefik changes): it is a DEV/client-side component only.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

# --------------------------------------------------------------------------
# Policy constants — the ONLY target this helper will ever probe.
# --------------------------------------------------------------------------
PING_TARGET = "8.8.8.8"

# Default loopback port for the helper.
DEFAULT_PORT = 8765

# Bounded ICMP wait. The child process is killed if it overruns.
PING_TIMEOUT_SECONDS = 3.0

# Results are reused for this long so a burst of client polls cannot turn into a
# burst of ICMP traffic (one probe per window, at most).
MIN_PROBE_INTERVAL_SECONDS = 5.0

# Loopback-only origins the DEV frontend is served from.
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

_PACKET_LOSS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:packet\s+)?loss", re.I)
_RTT_RE = re.compile(r"=\s*[\d.]+/([\d.]+)/", re.I)


def _ping_command(target: str) -> list[str]:
    """Build the platform's single-packet ping argv. Never shell-interpolated."""

    system = platform.system().lower()
    if system == "windows":
        return ["ping", "-n", "1", "-w", str(int(PING_TIMEOUT_SECONDS * 1000)), target]
    if system == "darwin":
        # BSD/macOS: -W is milliseconds.
        return ["ping", "-c", "1", "-W", str(int(PING_TIMEOUT_SECONDS * 1000)), target]
    # Linux and other POSIX: -W is seconds.
    return ["ping", "-c", "1", "-W", str(max(1, int(PING_TIMEOUT_SECONDS))), target]


def _parse_packet_loss(stdout: str):
    match = _PACKET_LOSS_RE.search(stdout or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:  # pragma: no cover - regex already guarantees a number
        return None


def _parse_rtt_ms(stdout: str):
    match = _RTT_RE.search(stdout or "")
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:  # pragma: no cover
        return None


class NetworkProbe:
    """Performs the ICMP check with overlap protection and result reuse.

    Exactly one probe runs at a time: concurrent callers block on a lock and
    then receive the cached result instead of starting their own ping.
    """

    def __init__(
        self,
        target: str = PING_TARGET,
        timeout_seconds: float = PING_TIMEOUT_SECONDS,
        min_interval_seconds: float = MIN_PROBE_INTERVAL_SECONDS,
        runner=None,
    ):
        self.target = target
        self.timeout_seconds = timeout_seconds
        self.min_interval_seconds = min_interval_seconds
        self._runner = runner or self._run_ping
        self._lock = threading.Lock()
        self._last_result = None
        self._last_checked_monotonic = None

    # -- low level ---------------------------------------------------------
    def _run_ping(self, argv: list[str]) -> subprocess.CompletedProcess:
        kwargs = {}
        if platform.system().lower() == "windows":  # pragma: no cover - windows
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=self.timeout_seconds,
            **kwargs,
        )

    # -- public API --------------------------------------------------------
    def cached_result(self):
        with self._lock:
            if self._last_result is None or self._last_checked_monotonic is None:
                return None
            if time.monotonic() - self._last_checked_monotonic < self.min_interval_seconds:
                return dict(self._last_result, cached=True)
        return None

    def check(self) -> dict:
        """Return the connectivity verdict. Never raises."""
        cached = self.cached_result()
        if cached is not None:
            return cached

        with self._lock:
            # Another request may have completed the probe while we waited.
            if self._last_checked_monotonic is not None:
                if time.monotonic() - self._last_checked_monotonic < self.min_interval_seconds:
                    return dict(self._last_result, cached=True)

            started = time.monotonic()
            result = {
                "target": self.target,
                "reachable": False,
                "packetLoss": None,
                "rttMs": None,
                "checkedAt": datetime.now(timezone.utc).isoformat(),
                "durationMs": 0,
                "cached": False,
                "error": None,
            }
            try:
                argv = _ping_command(self.target)
                completed = self._runner(argv)
                stdout = completed.stdout or ""
                stderr = completed.stderr or ""
                result["packetLoss"] = _parse_packet_loss(stdout)
                result["rttMs"] = _parse_rtt_ms(stdout)
                if completed.returncode == 0:
                    result["reachable"] = True
                else:
                    # Timeout / packet loss / unreachable — an ordinary "no
                    # connectivity" verdict, never an infrastructure error.
                    detail = (stderr or stdout or "").strip().splitlines()
                    result["error"] = detail[0][:200] if detail else None
            except subprocess.TimeoutExpired:
                result["error"] = "ping timed out"
            except FileNotFoundError:
                result["error"] = "ping binary not available"
            except OSError as exc:
                result["error"] = f"ping failed: {exc}"
            except Exception as exc:  # pragma: no cover - defensive
                result["error"] = f"unexpected probe failure: {exc}"

            result["durationMs"] = int((time.monotonic() - started) * 1000)
            self._last_result = dict(result)
            self._last_checked_monotonic = time.monotonic()
            return result


class _Handler(BaseHTTPRequestHandler):
    server_version = "NetworkMonitorAgent/1.0"
    protocol_version = "HTTP/1.1"

    # Injected by the server factory.
    probe: NetworkProbe = None
    allowed_origins: tuple = ()

    # -- helpers -----------------------------------------------------------
    def _cors_origin(self):
        origin = self.headers.get("Origin")
        if origin and origin in self.allowed_origins:
            return origin
        return None

    def _send_json(self, status: int, payload: dict, with_cors: bool = True):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # A localhost JSON endpoint must never be cached by intermediaries.
        self.send_header("Cache-Control", "no-store")
        origin = self._cors_origin()
        if with_cors and origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    # -- routes ------------------------------------------------------------
    def do_OPTIONS(self):  # noqa: N802 - http.server API
        path = urlsplit(self.path).path
        if path != "/network-check":
            self._send_json(404, {"detail": "Not found"}, with_cors=False)
            return
        self.send_response(204)
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):  # noqa: N802 - http.server API
        path = urlsplit(self.path).path
        if path != "/network-check":
            # Only the one narrowly required operation is exposed. Note that
            # query parameters are ignored entirely: the target is fixed, so
            # /network-check?target=... can never redirect the probe.
            self._send_json(404, {"detail": "Not found"}, with_cors=False)
            return
        self._send_json(200, self.probe.check())

    def do_POST(self):  # noqa: N802 - http.server API
        self._send_json(405, {"detail": "Method not allowed"}, with_cors=False)

    do_PUT = do_DELETE = do_PATCH = do_HEAD = do_POST

    def log_message(self, fmt, *args):  # keep the DEV console readable
        if os.environ.get("NETWORK_MONITOR_VERBOSE") == "1":
            sys.stderr.write("[network-monitor] " + (fmt % args) + "\n")


def build_server(
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    allowed_origins=DEFAULT_ALLOWED_ORIGINS,
    probe: NetworkProbe = None,
) -> ThreadingHTTPServer:
    """Create the loopback-only server. The host is not caller-configurable to
    anything other than loopback by design."""
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("the network-monitor helper may only bind loopback")

    handler = type(
        "BoundHandler",
        (_Handler,),
        {"probe": probe or NetworkProbe(), "allowed_origins": tuple(allowed_origins)},
    )
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="DEV-only ICMP network-integrity helper")
    parser.add_argument("--port", type=int, default=int(os.environ.get("NETWORK_MONITOR_PORT", DEFAULT_PORT)))
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=None,
        help="Frontend origin allowed by CORS (repeatable). Defaults to the DEV Vite origins.",
    )
    parser.add_argument("--once", action="store_true", help="Run a single check, print JSON, exit")
    args = parser.parse_args(argv)

    probe = NetworkProbe()
    if args.once:
        print(json.dumps(probe.check(), indent=2))
        return 0

    origins = tuple(args.allow_origin) if args.allow_origin else DEFAULT_ALLOWED_ORIGINS
    server = build_server(port=args.port, allowed_origins=origins, probe=probe)
    host, port = server.server_address[0], server.server_address[1]
    print(f"network-monitor helper listening on http://{host}:{port}/network-check")
    print(f"  target: {PING_TARGET} (fixed)  |  allowed origins: {', '.join(origins)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
