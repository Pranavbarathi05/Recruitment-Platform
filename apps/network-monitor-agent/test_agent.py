"""Tests for the DEV-only client network-integrity helper.

The ping binary is always mocked: these tests never send real ICMP traffic.
"""

import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPConnection

import pytest

import agent
from agent import NetworkProbe, build_server


class FakePing:
    """Records invocations and returns a scripted result."""

    def __init__(self, returncode=0, stdout="", stderr="", delay=0.0, raises=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.delay = delay
        self.raises = raises
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.delay:
            time.sleep(self.delay)
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


REPLY_OK = (
    "PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n"
    "64 bytes from 8.8.8.8: icmp_seq=1 ttl=115 time=12.4 ms\n"
    "\n--- 8.8.8.8 ping statistics ---\n"
    "1 packets transmitted, 1 received, 0% packet loss, time 0ms\n"
    "rtt min/avg/max/mdev = 12.401/12.401/12.401/0.000 ms\n"
)

REPLY_TIMEOUT = (
    "PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n"
    "\n--- 8.8.8.8 ping statistics ---\n"
    "1 packets transmitted, 0 received, 100% packet loss, time 0ms\n"
)


# ---------------------------------------------------------------------------
# Probe behaviour
# ---------------------------------------------------------------------------


def test_successful_ping_is_reachable():
    fake = FakePing(returncode=0, stdout=REPLY_OK)
    probe = NetworkProbe(runner=fake)

    result = probe.check()

    assert result["reachable"] is True
    assert result["target"] == "8.8.8.8"
    assert result["packetLoss"] == 0.0
    assert result["rttMs"] == pytest.approx(12.401)
    assert result["cached"] is False
    assert result["error"] is None
    assert isinstance(result["durationMs"], int)


def test_timeout_is_not_reachable():
    fake = FakePing(returncode=1, stdout=REPLY_TIMEOUT)
    probe = NetworkProbe(runner=fake)

    result = probe.check()

    assert result["reachable"] is False
    assert result["packetLoss"] == 100.0


def test_packet_loss_without_output_is_not_reachable():
    fake = FakePing(returncode=1, stdout="", stderr="")
    probe = NetworkProbe(runner=fake)

    result = probe.check()

    assert result["reachable"] is False
    assert result["packetLoss"] is None
    assert result["error"] is None


def test_probe_invokes_the_fixed_target_with_argv_only():
    fake = FakePing(returncode=0, stdout=REPLY_OK)
    probe = NetworkProbe(runner=fake)

    probe.check()

    assert len(fake.calls) == 1
    argv = fake.calls[0]
    assert argv[0] == "ping"
    assert argv[-1] == "8.8.8.8"
    assert agent.PING_TARGET == "8.8.8.8"


def test_missing_ping_binary_is_reported_not_raised():
    fake = FakePing(raises=FileNotFoundError("ping"))
    probe = NetworkProbe(runner=fake)

    result = probe.check()

    assert result["reachable"] is False
    assert result["error"] == "ping binary not available"


def test_subprocess_timeout_is_reported_not_raised():
    fake = FakePing(raises=subprocess.TimeoutExpired(cmd="ping", timeout=3))
    probe = NetworkProbe(runner=fake)

    result = probe.check()

    assert result["reachable"] is False
    assert result["error"] == "ping timed out"


def test_unexpected_failure_is_reported_not_raised():
    fake = FakePing(raises=RuntimeError("boom"))
    probe = NetworkProbe(runner=fake)

    result = probe.check()

    assert result["reachable"] is False
    assert "unexpected probe failure" in result["error"]


def test_results_are_reused_within_the_min_interval():
    fake = FakePing(returncode=0, stdout=REPLY_OK)
    probe = NetworkProbe(runner=fake, min_interval_seconds=60)

    first = probe.check()
    second = probe.check()

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["reachable"] is True
    assert len(fake.calls) == 1, "a second poll must not spawn a second ping"


def test_probe_runs_again_after_the_min_interval_elapses():
    fake = FakePing(returncode=0, stdout=REPLY_OK)
    probe = NetworkProbe(runner=fake, min_interval_seconds=0)

    probe.check()
    probe.check()

    assert len(fake.calls) == 2


def test_overlapping_requests_share_a_single_ping():
    fake = FakePing(returncode=0, stdout=REPLY_OK, delay=0.2)
    probe = NetworkProbe(runner=fake, min_interval_seconds=60)
    results = []

    threads = [threading.Thread(target=lambda: results.append(probe.check())) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(fake.calls) == 1, "concurrent polls must not overlap pings"
    assert len(results) == 4
    assert all(r["reachable"] is True for r in results)


def test_cached_result_is_none_before_any_probe():
    assert NetworkProbe(runner=FakePing()).cached_result() is None


# ---------------------------------------------------------------------------
# Server: binding, routes, CORS, parameter handling
# ---------------------------------------------------------------------------


@pytest.fixture
def server():
    probe = NetworkProbe(runner=FakePing(returncode=0, stdout=REPLY_OK), min_interval_seconds=60)
    srv = build_server(port=0, allowed_origins=("http://localhost:5173",), probe=probe)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def _get(server, path, origin=None, method="GET"):
    scheme_host, port = "127.0.0.1", server.server_address[1]
    conn = HTTPConnection(scheme_host, port, timeout=10)
    headers = {"Origin": origin} if origin else {}
    conn.request(method, path, headers=headers)
    response = conn.getresponse()
    body = response.read().decode("utf-8")
    conn.close()
    return response, body


def test_server_binds_loopback_only(server):
    assert server.server_address[0] == "127.0.0.1"


def test_loopback_is_the_only_bindable_host():
    with pytest.raises(ValueError):
        build_server(host="0.0.0.0", port=0)


def test_network_check_returns_structured_json(server):
    response, body = _get(server, "/network-check")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["target"] == "8.8.8.8"
    assert payload["reachable"] is True
    assert set(payload) >= {"target", "reachable", "packetLoss", "checkedAt", "durationMs"}


def test_query_parameters_cannot_redirect_the_probe(server):
    """No parameter may change the target: the endpoint takes none."""
    response, body = _get(server, "/network-check?target=1.1.1.1&host=example.com&cmd=rm+-rf+/")

    assert response.status == 200
    assert json.loads(body)["target"] == "8.8.8.8"


def test_unknown_paths_are_not_found(server):
    for path in ("/", "/ping", "/network-check/extra", "/shell?cmd=ls"):
        response, _ = _get(server, path)
        assert response.status == 404, path


def test_write_methods_are_rejected(server):
    response, _ = _get(server, "/network-check", method="POST")
    assert response.status == 405


def test_allowed_origin_gets_cors_header(server):
    response, _ = _get(server, "/network-check", origin="http://localhost:5173")

    assert response.getheader("Access-Control-Allow-Origin") == "http://localhost:5173"
    assert response.getheader("Cache-Control") == "no-store"


def test_unlisted_origin_gets_no_cors_header(server):
    response, _ = _get(server, "/network-check", origin="https://evil.example")

    assert response.getheader("Access-Control-Allow-Origin") is None


def test_preflight_is_answered_for_network_check(server):
    response, _ = _get(server, "/network-check", origin="http://localhost:5173", method="OPTIONS")

    assert response.status == 204
    assert response.getheader("Access-Control-Allow-Origin") == "http://localhost:5173"
    assert "GET" in response.getheader("Access-Control-Allow-Methods")


def test_server_survives_a_probe_error(server):
    """A broken ping binary must still produce a valid JSON verdict."""
    server.RequestHandlerClass.probe = NetworkProbe(runner=FakePing(raises=FileNotFoundError()))

    response, body = _get(server, "/network-check")

    assert response.status == 200
    payload = json.loads(body)
    assert payload["reachable"] is False
    assert payload["error"] == "ping binary not available"


def test_once_mode_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(agent.NetworkProbe, "check", lambda self: {"target": "8.8.8.8", "reachable": True})

    assert agent.main(["--once"]) == 0
    assert json.loads(capsys.readouterr().out)["reachable"] is True


def test_unused_import_guard():
    """urllib.error is imported for completeness of the stdlib HTTP surface."""
    assert urllib.error is not None
