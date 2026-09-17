"""
Tests for the Compiler-1 / Compiler-2 / Compiler-3 pool in services/compiler.py.

Offline: the Judge0 HTTP calls are mocked with httpx.MockTransport, so no live
compiler is needed. These tests pin the behaviour the multi-machine deployment
relies on:

  * one compiler node configured  -> behaves exactly as before (no pool);
  * several nodes configured      -> submissions are distributed round-robin;
  * a submission is always polled on the node that accepted it;
  * an unreachable or queue-full node is skipped, so one dead execution machine
    cannot fail a candidate's submission while another is healthy;
  * every node down               -> CompilerError (never a silent success).
"""
from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import services.compiler as compiler  # noqa: E402

NODE_1 = "http://compiler-1:2358"
NODE_2 = "http://compiler-2:2358"
NODE_3 = "http://compiler-3:2358"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


@pytest.fixture(autouse=True)
def _reset_cursor():
    """Start every test from a known round-robin position."""
    compiler._pool_cursor = 0
    yield
    compiler._pool_cursor = 0


def _install_async_mock(monkeypatch: pytest.MonkeyPatch, handler: Callable) -> None:
    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(compiler.httpx, "AsyncClient", factory)


def _final_submission(stdout: str = "[]") -> dict[str, Any]:
    """A finished Judge0 submission (status 3 = Accepted) with base64 fields."""
    return {
        "stdout": _b64(stdout),
        "stderr": _b64(""),
        "compile_output": _b64(""),
        "status_id": 3,
        "time": "0.010",
        "memory": 1000,
    }


def _submit():
    return asyncio.run(
        compiler._submit_to_judge0(
            source_code="print(1)", language="python3", time_limit_seconds=2.0
        )
    )


# ── Pool resolution ──────────────────────────────────────────────────────────

def test_default_pool_is_the_single_legacy_url() -> None:
    """With no COMPILER_n_URL set, the pool is the legacy single endpoint."""
    assert compiler.COMPILER_POOL == [compiler.JUDGE0_BASE_URL.rstrip("/")]
    assert compiler.compiler_pool_urls() == [compiler.JUDGE0_BASE_URL.rstrip("/")]


def test_round_robin_helper_cycles_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compiler, "COMPILER_POOL", [NODE_1, NODE_2, NODE_3])
    picked = [compiler._next_compiler_node() for _ in range(7)]
    assert picked == [NODE_1, NODE_2, NODE_3, NODE_1, NODE_2, NODE_3, NODE_1]


def test_failover_order_puts_the_chosen_node_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(compiler, "COMPILER_POOL", [NODE_1, NODE_2, NODE_3])
    assert compiler._failover_order(NODE_2) == [NODE_2, NODE_1, NODE_3]


# ── Distribution across the pool ─────────────────────────────────────────────

def test_submissions_are_distributed_round_robin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_hosts: list[str] = []
    poll_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            post_hosts.append(request.url.host)
            return httpx.Response(201, json={"token": f"tok-{len(post_hosts)}"})
        poll_hosts.append(request.url.host)
        return httpx.Response(200, json=_final_submission())

    _install_async_mock(monkeypatch, handler)
    monkeypatch.setattr(compiler, "COMPILER_POOL", [NODE_1, NODE_2, NODE_3])

    for _ in range(6):
        _submit()

    assert post_hosts == [
        "compiler-1", "compiler-2", "compiler-3",
        "compiler-1", "compiler-2", "compiler-3",
    ]
    # Each submission is polled on the node that accepted it.
    assert poll_hosts == post_hosts


def test_single_node_pool_sends_everything_to_that_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            post_hosts.append(request.url.host)
            return httpx.Response(201, json={"token": "t"})
        return httpx.Response(200, json=_final_submission())

    _install_async_mock(monkeypatch, handler)
    monkeypatch.setattr(compiler, "COMPILER_POOL", [NODE_1])

    for _ in range(3):
        _submit()
    assert post_hosts == ["compiler-1"] * 3


# ── Failover ─────────────────────────────────────────────────────────────────

def test_dead_node_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    post_hosts: list[str] = []
    poll_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if request.method == "POST":
            if host == "compiler-1":
                raise httpx.ConnectError("connection refused", request=request)
            post_hosts.append(host)
            return httpx.Response(201, json={"token": "tok-2"})
        poll_hosts.append(host)
        return httpx.Response(200, json=_final_submission())

    _install_async_mock(monkeypatch, handler)
    monkeypatch.setattr(compiler, "COMPILER_POOL", [NODE_1, NODE_2])

    result = _submit()

    assert result["status_id"] == 3
    assert post_hosts == ["compiler-2"]
    assert poll_hosts == ["compiler-2"]


def test_queue_full_node_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    post_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            if request.url.host == "compiler-1":
                return httpx.Response(503, json={"error": "queue is full"})
            post_hosts.append(request.url.host)
            return httpx.Response(201, json={"token": "tok-2"})
        return httpx.Response(200, json=_final_submission())

    _install_async_mock(monkeypatch, handler)
    monkeypatch.setattr(compiler, "COMPILER_POOL", [NODE_1, NODE_2])

    result = _submit()
    assert result["status_id"] == 3
    assert post_hosts == ["compiler-2"]


def test_all_nodes_down_raises_compiler_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _install_async_mock(monkeypatch, handler)
    monkeypatch.setattr(compiler, "COMPILER_POOL", [NODE_1, NODE_2, NODE_3])

    with pytest.raises(compiler.CompilerError) as excinfo:
        _submit()
    assert "unavailable" in str(excinfo.value).lower()


def test_non_503_http_error_is_not_masked_by_failover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real rejection (e.g. 422 validation) must surface, not be hidden."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "bad request"})

    _install_async_mock(monkeypatch, handler)
    monkeypatch.setattr(compiler, "COMPILER_POOL", [NODE_1, NODE_2])

    with pytest.raises(compiler.CompilerError) as excinfo:
        _submit()
    assert "422" in str(excinfo.value)
