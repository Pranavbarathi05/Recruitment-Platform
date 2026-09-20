"""
Compiler Service Integration — Judge0 CE 1.13.1

Communicates with self-hosted Judge0 for isolated execution of untrusted candidate code.

Architecture:
  dsc_recruit backend -> Judge0 CE /submissions

SECURITY ARCHITECTURE:
  - No local code execution
  - All execution happens in the isolated Judge0 sandbox
  - Judge0 is never exposed to the browser

Judge0 API:
  - POST /submissions (async, base64 encoded)
  - GET /submissions/{token}?base64_encoded=true
  - Poll until status_id > 2 (finished)

Language IDs (Judge0 CE 1.13.1):
  - 71: Python 3 (CPython 3.8.1)
  - 54: C++ (GCC 9.2.0)
  - 62: Java (OpenJDK 13.0.1)
  - 50: C (GCC 9.2.0)
"""

import os
import json
import time
import base64
import logging
import threading
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# Judge0 configuration
JUDGE0_BASE_URL = os.getenv("JUDGE0_BASE_URL", "http://localhost:2358")

# ── Compiler node pool (Compiler-1 / Compiler-2 / Compiler-3) ────────────────
# Endpoints are configured with COMPILER_1_URL / COMPILER_2_URL / COMPILER_3_URL.
# Any subset may be set; the order given is the round-robin order. When none of
# them is set the legacy single JUDGE0_BASE_URL is used and behaviour is
# unchanged (one compiler node).
#
# Requests are distributed round-robin. A node that cannot be reached, or whose
# queue is full, is skipped and the next node is tried, so one dead execution
# machine does not fail a candidate's submission while another is healthy. The
# node that accepted a submission is the one polled for its result, because a
# Judge0 token exists only on the node that queued it.
COMPILER_POOL = [
    url.strip().rstrip("/")
    for url in (
        os.getenv("COMPILER_1_URL", ""),
        os.getenv("COMPILER_2_URL", ""),
        os.getenv("COMPILER_3_URL", ""),
    )
    if url.strip()
] or [JUDGE0_BASE_URL.rstrip("/")]

_POOL_QUERY = "base64_encoded=true&fields=stdout,stderr,compile_output,status,time,memory,status_id"
_pool_lock = threading.Lock()
_pool_cursor = 0


def compiler_pool_urls() -> list:
    """Every configured compiler node, in round-robin order."""
    return list(COMPILER_POOL)


def _next_compiler_node() -> str:
    """Pick the next compiler node with a deterministic, thread-safe cursor."""
    global _pool_cursor
    with _pool_lock:
        node = COMPILER_POOL[_pool_cursor % len(COMPILER_POOL)]
        _pool_cursor += 1
    return node


def _failover_order(start_node: str) -> list:
    """[start_node, ...every other node] — the order to try when a node is down."""
    return [start_node] + [u for u in COMPILER_POOL if u != start_node]


def _submission_url(node: str) -> str:
    return f"{node}/submissions?{_POOL_QUERY}"


def _poll_url(node: str, token: str) -> str:
    return f"{node}/submissions/{token}?{_POOL_QUERY}"
JUDGE0_AUTH_TOKEN = os.getenv("JUDGE0_AUTH_TOKEN", "")
# Judge0 API auth header name. Must match AUTHN_HEADER in judge0.conf
# (default for this deployment: X-Judge0-Token — same as gateway-api).
JUDGE0_AUTH_HEADER = os.getenv("JUDGE0_AUTH_HEADER", "X-Judge0-Token")
# Per-submission max file size (KB). Must not exceed MAX_MAX_FILE_SIZE in
# judge0.conf (4096 in this deployment); larger values are rejected with 422.
JUDGE0_MAX_FILE_SIZE_KB = int(os.getenv("JUDGE0_MAX_FILE_SIZE_KB", "4096"))
# Do NOT send `enable_per_process_and_thread_time_limit/memory_limit: false`
# explicitly: this Judge0 build returns Internal Error (status 13) when those
# flags are explicitly false (verified empirically); omitting them uses the
# server defaults and executes correctly.
# JVM address-space floor (KB): Java (OpenJDK 13) cannot even start under
# lower rlimit-AS caps (heap + 1 GB compressed-class space pre-reserved at
# startup; javac also needs the full reservation), so Java submissions always
# request at least this much address space. Must stay <= MAX_MEMORY_LIMIT in
# judge0.conf (8388608). Empirically verified: 2 GB/4 GB fail, 8 GB works.
JUDGE0_JAVA_MEMORY_LIMIT_KB = int(
    os.getenv("JUDGE0_JAVA_MEMORY_LIMIT_KB", str(8 * 1024 * 1024))
)
JUDGE0_POLL_INTERVAL = float(os.getenv("JUDGE0_POLL_INTERVAL", "0.5"))
JUDGE0_MAX_POLL_TIME = float(os.getenv("JUDGE0_MAX_POLL_TIME", "30.0"))

# Language ID mapping for Judge0 CE
JUDGE0_LANGUAGE_IDS = {
    "python3": 71,   # Python 3.8.1
    "cpp": 54,       # C++ (GCC 9.2.0)
    "java": 62,      # Java (OpenJDK 13.0.1)
    "c": 50,         # C (GCC 9.2.0)
}

# Judge0 status IDs
# 1 = In Queue, 2 = Processing, 3+ = Finished
# 3=Accepted, 4=Wrong Answer, 5=TLE, 6=Compilation Error,
# 7-12=Runtime Error variants, 13=Internal Error, 14=Exec Format Error
JUDGE0_STATUS_FINISHED_THRESHOLD = 3

# Judge0 status ID -> our status
JUDGE0_STATUS_MAP = {
    3: "accepted",
    4: "wrong_answer",
    5: "time_limit_exceeded",
    6: "compilation_error",
    7: "runtime_error",   # SIGSEGV
    8: "runtime_error",   # SIGXFSZ
    9: "runtime_error",   # SIGFPE
    10: "runtime_error",  # SIGABRT
    11: "runtime_error",  # NZEC
    12: "runtime_error",  # Other
    13: "internal_error",
    14: "runtime_error",  # Exec Format Error
}


class CompilerError(Exception):
    """Raised when the compiler service is unavailable or returns an error."""
    pass


class CompilerResponse:
    """Response from the compiler service."""

    def __init__(
        self,
        status: str,
        language: str,
        execution_time_ms: int,
        tests: list[dict],
        error: Optional[str] = None,
        failed_test: Optional[int] = None,
        total_tests: int = 0,
        passed_tests: int = 0,
    ):
        self.status = status
        self.language = language
        self.execution_time_ms = execution_time_ms
        self.tests = tests
        self.error = error
        self.failed_test = failed_test
        self.total_tests = total_tests
        self.passed_tests = passed_tests

    def to_dict(self):
        return {
            "status": self.status,
            "language": self.language,
            "execution_time_ms": self.execution_time_ms,
            "tests": self.tests,
            "error": self.error,
            "failed_test": self.failed_test,
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
        }


def _b64encode(text: str) -> str:
    """Base64 encode a string for Judge0 API."""
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


def _b64decode(text: str) -> str:
    """Base64 decode a Judge0 response string."""
    if not text:
        return ""
    try:
        return base64.b64decode(text.encode("utf-8")).decode("utf-8")
    except Exception:
        return text


def _get_auth_headers() -> dict:
    """Get Judge0 authentication headers (header name configurable via JUDGE0_AUTH_HEADER)."""
    if JUDGE0_AUTH_TOKEN:
        return {JUDGE0_AUTH_HEADER: JUDGE0_AUTH_TOKEN}
    return {}


def _get_judge0_status(status_id: int) -> str:
    """Map Judge0 status ID to our status string."""
    return JUDGE0_STATUS_MAP.get(status_id, "internal_error")


def _parse_harness_output(stdout: str, num_tests: int) -> list:
    """
    Parse JSON output from the language harness.
    The harness prints a JSON array of test results.
    """
    try:
        results = json.loads(stdout.strip())
        if isinstance(results, list):
            return results
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: treat entire output as error
    return [{"passed": False, "error": "Could not parse harness output", "stdout": stdout}]


async def _submit_to_judge0(
    source_code: str,
    language: str,
    stdin: str = "",
    expected_output: str = "",
    time_limit_seconds: float = 2.0,
    memory_limit_kb: int = 262144,
) -> dict:
    """
    Submit code to Judge0 asynchronously and poll for result.

    Args:
        source_code: Complete source code to execute
        language: Programming language key (python3, cpp, java)
        stdin: Standard input (not used for harness-based execution)
        expected_output: Expected stdout for comparison (not used for harness)
        time_limit_seconds: CPU time limit in seconds
        memory_limit_kb: Memory limit in kilobytes

    Returns:
        Dict with stdout, stderr, compile_output, status_id, time, memory
    """
    language_id = JUDGE0_LANGUAGE_IDS.get(language)
    if language_id is None:
        raise CompilerError(f"Unsupported language for Judge0: {language}")

    # Build submission payload
    payload = {
        "language_id": language_id,
        "source_code": _b64encode(source_code),
        "stdin": _b64encode(stdin) if stdin else "",
        "cpu_time_limit": time_limit_seconds,
        "cpu_extra_time": 0.5,
        "wall_time_limit": time_limit_seconds + 5,
        "memory_limit": memory_limit_kb,
        "stack_limit": 131072,
        "max_processes_and_or_threads": 60,
        "max_file_size": JUDGE0_MAX_FILE_SIZE_KB,
        "redirect_stderr_to_stdout": False,
        "enable_network": False,
        "number_of_runs": 1,
    }

    headers = _get_auth_headers()

    # Submit asynchronously, choosing a compiler node round-robin and failing
    # over to the other nodes if this one is unreachable or its queue is full.
    node = ""
    token = None
    last_error = None
    for candidate in _failover_order(_next_compiler_node()):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    _submission_url(candidate), json=payload, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
                token = data.get("token")
                if not token:
                    raise CompilerError("Judge0 did not return a submission token")
            node = candidate
            logger.info("Judge0 submission queued on compiler node %s", candidate)
            break
        except httpx.ConnectError as e:
            last_error = CompilerError(f"Judge0 unavailable at {candidate}: {e}")
            logger.warning("Compiler node %s unreachable, trying next", candidate)
        except httpx.TimeoutException as e:
            last_error = CompilerError(f"Judge0 submission timeout at {candidate}: {e}")
            logger.warning("Compiler node %s timed out, trying next", candidate)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                last_error = CompilerError(
                    f"Judge0 HTTP error: {e.response.status_code}"
                )
                logger.warning("Compiler node %s queue full, trying next", candidate)
                continue
            raise CompilerError(f"Judge0 HTTP error: {e.response.status_code}")
        except CompilerError:
            raise
        except Exception as e:
            raise CompilerError(f"Judge0 submission error: {e}")
    if not node or not token:
        raise last_error or CompilerError(
            "Judge0 unavailable: no compiler node reachable"
        )

    # Poll for result on the node that accepted the submission.
    poll_url = _poll_url(node, token)
    start_time = time.monotonic()

    while True:
        elapsed = time.monotonic() - start_time
        if elapsed >= JUDGE0_MAX_POLL_TIME:
            raise CompilerError(
                f"Judge0 polling timed out after {JUDGE0_MAX_POLL_TIME}s"
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(poll_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning(f"Judge0 poll error: {e}")
            time.sleep(JUDGE0_POLL_INTERVAL)
            continue

        status_id = data.get("status_id", 0)
        if status_id >= JUDGE0_STATUS_FINISHED_THRESHOLD:
            # Decode base64 outputs
            return {
                "stdout": _b64decode(data.get("stdout", "")),
                "stderr": _b64decode(data.get("stderr", "")),
                "compile_output": _b64decode(data.get("compile_output", "")),
                "status_id": status_id,
                "time": data.get("time"),
                "memory": data.get("memory"),
            }

        time.sleep(JUDGE0_POLL_INTERVAL)


async def execute_code(
    language: str,
    source_code: str,
    test_cases: list[dict],
    time_limit_seconds: float = 2.0,
    memory_limit_mb: int = 256,
    max_output_bytes: int = 65536,
    attempt_id: Optional[str] = None,
    problem_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> CompilerResponse:
    """
    Execute code against test cases via Judge0.

    The source_code is already a complete harnessed program (generated by harness.py).
    Judge0 compiles/runs it once, and the harness itself handles test execution.
    We parse the harness JSON output to get per-test results.

    Args:
        language: Programming language (python3, cpp, java)
        source_code: Complete harnessed source code
        test_cases: List of {input, expected_output} dicts (metadata for result mapping)
        time_limit_seconds: Time limit per execution
        memory_limit_mb: Memory limit in MB
        max_output_bytes: Maximum output size (not used with Judge0)
        attempt_id: Assessment attempt ID (for logging)
        problem_id: Coding problem ID (for logging)
        session_id: Session ID (for logging)

    Returns:
        CompilerResponse with execution results

    Raises:
        CompilerError: If Judge0 is unavailable
    """
    memory_limit_kb = memory_limit_mb * 1024
    if language == "java":
        memory_limit_kb = max(memory_limit_kb, JUDGE0_JAVA_MEMORY_LIMIT_KB)

    try:
        result = await _submit_to_judge0(
            source_code=source_code,
            language=language,
            time_limit_seconds=time_limit_seconds,
            memory_limit_kb=memory_limit_kb,
        )
    except CompilerError:
        raise
    except Exception as e:
        logger.error(f"Unexpected Judge0 error: {e}")
        raise CompilerError(f"Unexpected Judge0 error: {e}")

    status_id = result["status_id"]
    judge0_status = _get_judge0_status(status_id)
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    compile_output = result.get("compile_output", "")

    # Parse execution time
    try:
        exec_time = float(result.get("time", 0) or 0)
        exec_time_ms = int(exec_time * 1000)
    except (ValueError, TypeError):
        exec_time_ms = 0

    # Parse memory usage
    try:
        memory_kb = float(result.get("memory", 0) or 0)
    except (ValueError, TypeError):
        memory_kb = 0

    # Truncate output if needed
    if len(stdout) > max_output_bytes:
        stdout = stdout[:max_output_bytes] + "\n[output truncated]"

    # If compilation error, return early
    if judge0_status == "compilation_error":
        return CompilerResponse(
            status="compilation_error",
            language=language,
            execution_time_ms=exec_time_ms,
            tests=[],
            error=compile_output or stderr or "Compilation failed",
            total_tests=len(test_cases),
            passed_tests=0,
        )

    # If runtime error before any output, return early
    if judge0_status in ("runtime_error", "internal_error") and not stdout.strip():
        return CompilerResponse(
            status=judge0_status,
            language=language,
            execution_time_ms=exec_time_ms,
            tests=[{"passed": False, "error": stderr or "Runtime error"} for _ in test_cases],
            error=stderr or "Runtime error",
            total_tests=len(test_cases),
            passed_tests=0,
        )

    # If TLE, return early
    if judge0_status == "time_limit_exceeded":
        return CompilerResponse(
            status="time_limit_exceeded",
            language=language,
            execution_time_ms=exec_time_ms,
            tests=[{"passed": False, "error": "Time limit exceeded"} for _ in test_cases],
            error="Time limit exceeded",
            total_tests=len(test_cases),
            passed_tests=0,
        )

    # Parse harness output (JSON array of test results)
    harness_results = _parse_harness_output(stdout, len(test_cases))

    # Build per-test results
    tests = []
    passed_count = 0
    failed_test_idx = None

    for idx in range(len(test_cases)):
        if idx < len(harness_results):
            hr = harness_results[idx]
            passed = hr.get("passed", False)
            if passed:
                passed_count += 1
            elif failed_test_idx is None:
                failed_test_idx = idx

            # If code ran (judge0_status=accepted) but test failed, it's wrong_answer
            per_test_status = "accepted" if passed else (
                "wrong_answer" if judge0_status == "accepted" else judge0_status
            )
            tests.append({
                "passed": passed,
                "actual_output": hr.get("actual"),
                "expected_output": test_cases[idx].get("expected_output"),
                "error": hr.get("error"),
                "status": per_test_status,
                "execution_time_ms": exec_time_ms // max(len(test_cases), 1),
            })
        else:
            # Harness produced fewer results than expected
            tests.append({
                "passed": False,
                "error": "Missing test result from harness",
                "status": "internal_error",
                "execution_time_ms": 0,
            })

    # Overall status
    if passed_count == len(test_cases):
        overall_status = "accepted"
    elif failed_test_idx is not None:
        overall_status = tests[failed_test_idx]["status"]
    else:
        overall_status = judge0_status

    return CompilerResponse(
        status=overall_status,
        language=language,
        execution_time_ms=exec_time_ms,
        tests=tests,
        error=stderr if judge0_status in ("runtime_error", "internal_error") else None,
        failed_test=failed_test_idx,
        total_tests=len(test_cases),
        passed_tests=passed_count,
    )


def execute_code_sync(
    language: str,
    source_code: str,
    test_cases: list[dict],
    time_limit_seconds: float = 2.0,
    memory_limit_mb: int = 256,
    max_output_bytes: int = 65536,
    attempt_id: Optional[str] = None,
    problem_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> CompilerResponse:
    """
    Synchronous wrapper around async execute_code.
    Uses httpx.Client for direct HTTP calls to Judge0.
    """
    language_id = JUDGE0_LANGUAGE_IDS.get(language)
    if language_id is None:
        raise CompilerError(f"Unsupported language for Judge0: {language}")

    memory_limit_kb = memory_limit_mb * 1024
    if language == "java":
        # The JVM pre-reserves heap + compressed-class space at startup and
        # cannot start under a smaller address-space rlimit; actual RSS stays
        # far below this. CPU time limits still bound candidate runtime.
        memory_limit_kb = max(memory_limit_kb, JUDGE0_JAVA_MEMORY_LIMIT_KB)

    # Submit synchronously
    payload = {
        "language_id": language_id,
        "source_code": _b64encode(source_code),
        "cpu_time_limit": time_limit_seconds,
        "cpu_extra_time": 0.5,
        "wall_time_limit": time_limit_seconds + 5,
        "memory_limit": memory_limit_kb,
        "stack_limit": 131072,
        "max_processes_and_or_threads": 60,
        "max_file_size": JUDGE0_MAX_FILE_SIZE_KB,
        "redirect_stderr_to_stdout": False,
        "enable_network": False,
        "number_of_runs": 1,
    }

    headers = _get_auth_headers()

    # Submit synchronously, choosing a compiler node round-robin and failing
    # over to the other nodes if this one is unreachable or its queue is full.
    node = ""
    token = None
    last_error = None
    for candidate in _failover_order(_next_compiler_node()):
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    _submission_url(candidate), json=payload, headers=headers
                )
                resp.raise_for_status()
                data = resp.json()
                token = data.get("token")
                if not token:
                    raise CompilerError("Judge0 did not return a submission token")
            node = candidate
            logger.info("Judge0 submission queued on compiler node %s", candidate)
            break
        except httpx.ConnectError as e:
            last_error = CompilerError(f"Judge0 unavailable at {candidate}: {e}")
            logger.warning("Compiler node %s unreachable, trying next", candidate)
        except httpx.TimeoutException as e:
            last_error = CompilerError(f"Judge0 submission timeout at {candidate}: {e}")
            logger.warning("Compiler node %s timed out, trying next", candidate)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 503:
                last_error = CompilerError(
                    f"Judge0 HTTP error: {e.response.status_code}"
                )
                logger.warning("Compiler node %s queue full, trying next", candidate)
                continue
            raise CompilerError(f"Judge0 HTTP error: {e.response.status_code}")
        except CompilerError:
            raise
        except Exception as e:
            raise CompilerError(f"Judge0 submission error: {e}")
    if not node or not token:
        raise last_error or CompilerError(
            "Judge0 unavailable: no compiler node reachable"
        )

    # Poll synchronously on the node that accepted the submission.
    poll_url = _poll_url(node, token)
    start_time = time.monotonic()

    while True:
        elapsed = time.monotonic() - start_time
        if elapsed >= JUDGE0_MAX_POLL_TIME:
            raise CompilerError(
                f"Judge0 polling timed out after {JUDGE0_MAX_POLL_TIME}s"
            )

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(poll_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning(f"Judge0 poll error: {e}")
            time.sleep(JUDGE0_POLL_INTERVAL)
            continue

        status_id = data.get("status_id", 0)
        if status_id >= JUDGE0_STATUS_FINISHED_THRESHOLD:
            stdout = _b64decode(data.get("stdout", ""))
            stderr = _b64decode(data.get("stderr", ""))
            compile_output = _b64decode(data.get("compile_output", ""))

            try:
                exec_time = float(data.get("time", 0) or 0)
                exec_time_ms = int(exec_time * 1000)
            except (ValueError, TypeError):
                exec_time_ms = 0

            judge0_status = _get_judge0_status(status_id)

            # If compilation error
            if judge0_status == "compilation_error":
                return CompilerResponse(
                    status="compilation_error",
                    language=language,
                    execution_time_ms=exec_time_ms,
                    tests=[],
                    error=compile_output or stderr or "Compilation failed",
                    total_tests=len(test_cases),
                    passed_tests=0,
                )

            # Parse harness output
            harness_results = _parse_harness_output(stdout, len(test_cases))

            tests = []
            passed_count = 0
            failed_test_idx = None

            for idx in range(len(test_cases)):
                if idx < len(harness_results):
                    hr = harness_results[idx]
                    passed = hr.get("passed", False)
                    if passed:
                        passed_count += 1
                    elif failed_test_idx is None:
                        failed_test_idx = idx

                    per_test_status = "accepted" if passed else (
                        "wrong_answer" if judge0_status == "accepted" else judge0_status
                    )
                    tests.append({
                        "passed": passed,
                        "actual_output": hr.get("actual"),
                        "expected_output": test_cases[idx].get("expected_output"),
                        "error": hr.get("error"),
                        "status": per_test_status,
                        "execution_time_ms": exec_time_ms // max(len(test_cases), 1),
                    })
                else:
                    tests.append({
                        "passed": False,
                        "error": "Missing test result from harness",
                        "status": "internal_error",
                        "execution_time_ms": 0,
                    })

            if passed_count == len(test_cases):
                overall_status = "accepted"
            elif failed_test_idx is not None:
                overall_status = tests[failed_test_idx]["status"]
            else:
                overall_status = judge0_status

            return CompilerResponse(
                status=overall_status,
                language=language,
                execution_time_ms=exec_time_ms,
                tests=tests,
                error=stderr if judge0_status in ("runtime_error", "internal_error") else None,
                failed_test=failed_test_idx,
                total_tests=len(test_cases),
                passed_tests=passed_count,
            )

        time.sleep(JUDGE0_POLL_INTERVAL)
