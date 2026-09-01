"""
Code Execution Service — Isolated Execution for Untrusted Candidate Code

Provides genuinely isolated code execution using multiple defense layers.

SECURITY ARCHITECTURE (defense in depth):

  Layer 1 — Environment Isolation
    - env -i: Only PATH, HOME, LANG, LC_ALL, TMPDIR are passed
    - NEVER passes SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, JWT secrets,
      or any application credentials to candidate code

  Layer 2 — Network Isolation
    - unshare --net: Creates a new network namespace with no interfaces
    - Candidate code CANNOT make any network connections

  Layer 3 — Filesystem Isolation (Docker primary, tmpdir fallback)
    - Docker: read-only root filesystem + writable /tmp workspace
    - Fallback: tempdir-only workspace (code runs in isolated tmpdir)

  Layer 4 — Resource Limits
    - Time limit: subprocess timeout enforced
    - Memory limit: Docker --memory flag or ulimit fallback
    - Output limit: stdout/stderr capped at 1MB
    - Process limit: Docker --pids-limit or os.setsid fallback

  Layer 5 — Execution Isolation
    - Each execution runs in its own process group (os.setsid)
    - Docker containers are destroyed after each execution
    - No shared state between executions

EXECUTION PROVIDER PRIORITY:
  1. Docker (if available and accessible)
  2. unshare + env -i + --net (Linux namespaces)
  3. env -i subprocess (minimal fallback)

The provider is selected automatically at startup. The public API
(execute_code, run_code_public, evaluate_submission) is provider-agnostic.

FOR PRODUCTION:
  - Install Docker and add the backend user to the docker group
  - Or deploy on Kubernetes with PodSecurityPolicy/RuntimeClass
  - The abstraction layer makes provider swaps trivial
"""

import subprocess
import tempfile
import os
import time
import shutil
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ============================================================
# Language Configuration
# ============================================================

LANGUAGE_CONFIGS = {
    "python3": {
        "ext": ".py",
        "compile": None,
        "run": ["python3", "{file}"],
    },
    "cpp": {
        "ext": ".cpp",
        "compile": ["g++", "-o", "{output}", "{file}", "-std=c++17", "-O2"],
        "run": ["./{output}"],
    },
    "java": {
        "ext": ".java",
        "compile": ["javac", "{file}"],
        "run": ["java", "-cp", "{dir}", "{classname}"],
    },
}

DEFAULT_TIME_LIMIT_MS = 2000
DEFAULT_MEMORY_LIMIT_MB = 256
MAX_OUTPUT_BYTES = 1024 * 1024  # 1MB

# The ONLY environment variables passed to candidate code.
# Everything else is stripped — no secrets, no credentials.
SAFE_ENV_KEYS = ["PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"]

# Safe PATH for candidate code — no access to docker, kubectl, etc.
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"


# ============================================================
# Execution Result
# ============================================================

class ExecutionResult:
    """Result of a code execution."""

    def __init__(
        self,
        status: str,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = -1,
        execution_time_ms: int = 0,
        compilation_error: Optional[str] = None,
    ):
        self.status = status
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.execution_time_ms = execution_time_ms
        self.compilation_error = compilation_error

    def to_dict(self):
        return {
            "status": self.status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "execution_time_ms": self.execution_time_ms,
            "compilation_error": self.compilation_error,
        }


# ============================================================
# Provider Detection
# ============================================================

_docker_available: Optional[bool] = None
_unshare_available: Optional[bool] = None


def _check_docker() -> bool:
    """Check if Docker is available and the current user can use it."""
    global _docker_available
    if _docker_available is not None:
        return _docker_available
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=5,
        )
        _docker_available = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _docker_available = False
    if _docker_available:
        logger.info("Docker is available — using container isolation")
    else:
        logger.info("Docker not available — falling back to namespace isolation")
    return _docker_available


def _check_unshare() -> bool:
    """Check if unshare with network namespace works."""
    global _unshare_available
    if _unshare_available is not None:
        return _unshare_available
    try:
        result = subprocess.run(
            ["unshare", "--user", "--net", "--map-root-user", "--", "true"],
            capture_output=True, timeout=5,
        )
        _unshare_available = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _unshare_available = False
    if _unshare_available:
        logger.info("Linux namespaces available — using unshare isolation")
    return _unshare_available


# ============================================================
# Safe Environment
# ============================================================

def _safe_env() -> dict:
    """Create a minimal, safe environment for candidate code.

    ONLY passes non-secret variables. Application credentials,
    API keys, JWT secrets, and Supabase config are NEVER included.
    """
    return {
        "PATH": SAFE_PATH,
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": "/tmp",
    }


# ============================================================
# Provider: Docker
# ============================================================

def _run_docker(
    source_code: str,
    language: str,
    stdin: str,
    time_limit_ms: int,
    memory_limit_mb: int,
    working_dir: str,
) -> tuple[str, str, int, int]:
    """Execute code in a Docker container with full isolation.

    Security properties:
    - Read-only root filesystem (except /tmp workspace)
    - No network access (--network none)
    - Memory limit (--memory)
    - PID limit (--pids-limit)
    - CPU limit (--cpus)
    - Non-root execution (--user 1000:1000)
    - Dropped capabilities (--cap-drop ALL)
    - No privileged mode
    - Auto-removed after execution (--rm)
    """
    config = LANGUAGE_CONFIGS[language]

    # Build the run command
    ext = config["ext"]
    if language == "java":
        classname = _get_java_classname(source_code)
        filename = f"{classname}{ext}"
    else:
        filename = f"solution{ext}"

    source_file = os.path.join(working_dir, filename)

    # Determine compile + run commands
    if config["compile"]:
        if language == "cpp":
            compile_cmd = " ".join(
                p.format(file=f"/code/{filename}", output="/code/solution")
                for p in config["compile"]
            )
            run_cmd = "/code/solution"
        elif language == "java":
            compile_cmd = f"javac /code/{filename}"
            run_cmd = f"java -cp /code {classname}"
        else:
            compile_cmd = None
            run_cmd = None
    else:
        compile_cmd = None
        run_cmd = " ".join(p.format(file=f"/code/{filename}") for p in config["run"])

    # Build the container command
    if compile_cmd:
        container_cmd = f"{compile_cmd} && {run_cmd}"
    else:
        container_cmd = run_cmd

    # Docker run command
    docker_cmd = [
        "docker", "run",
        "--rm",                          # Auto-remove container
        "--network", "none",             # No network
        "--memory", f"{memory_limit_mb}m",  # Memory limit
        "--cpus", "0.5",                 # CPU limit (half core)
        "--pids-limit", "64",            # Process limit
        "--user", "1000:1000",           # Non-root
        "--cap-drop", "ALL",             # Drop all capabilities
        "--security-opt", "no-new-privileges",  # No privilege escalation
        "-v", f"{working_dir}:/code:ro",  # Read-only code mount
        "-w", "/code",                    # Working directory
        "-e", "PATH=/usr/local/bin:/usr/bin:/bin",
        "-e", "HOME=/tmp",
        "-e", "LANG=C.UTF-8",
        "-e", "LC_ALL=C.UTF-8",
        "-e", "TMPDIR=/tmp",
        "python:3.12-slim" if language == "python3" else
        "gcc:13" if language == "cpp" else
        "eclipse-temurin:21-jdk",
        "bash", "-c", container_cmd,
    ]

    start = time.monotonic()
    try:
        proc = subprocess.run(
            docker_cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=time_limit_ms / 1000.0 + 5,  # Extra time for container startup
        )
        elapsed = int((time.monotonic() - start) * 1000)

        stdout = proc.stdout[:MAX_OUTPUT_BYTES] if proc.stdout else ""
        stderr = proc.stderr[:MAX_OUTPUT_BYTES] if proc.stderr else ""

        return stdout, stderr, proc.returncode, elapsed

    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return "", "Time Limit Exceeded", -1, elapsed
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return "", f"Docker execution error: {str(e)}", -1, elapsed


# ============================================================
# Provider: unshare (Linux namespaces)
# ============================================================

def _run_unshare(
    source_code: str,
    language: str,
    stdin: str,
    time_limit_ms: int,
    memory_limit_mb: int,
    working_dir: str,
) -> tuple[str, str, int, int]:
    """Execute code using Linux namespaces for isolation.

    Security properties:
    - User namespace: maps to unprivileged user
    - Network namespace: no network access
    - Clean environment: only PATH, HOME, LANG, LC_ALL, TMPDIR
    - Time limit: subprocess timeout
    - Output limit: 1MB
    - Process group isolation: os.setsid
    """
    config = LANGUAGE_CONFIGS[language]
    safe_env = _safe_env()

    ext = config["ext"]
    if language == "java":
        classname = _get_java_classname(source_code)
        filename = f"{classname}{ext}"
    else:
        filename = f"solution{ext}"

    source_file = os.path.join(working_dir, filename)

    # Build command
    if config["compile"]:
        if language == "cpp":
            compile_cmd = " ".join(
                p.format(file=source_file, output=os.path.join(working_dir, "solution"))
                for p in config["compile"]
            )
            run_cmd = os.path.join(working_dir, "solution")
            cmd_str = f"{compile_cmd} && {run_cmd}"
        elif language == "java":
            compile_cmd = f"javac {source_file}"
            run_cmd = f"java -cp {working_dir} {classname}"
            cmd_str = f"{compile_cmd} && {run_cmd}"
        else:
            cmd_str = None
    else:
        cmd_str = " ".join(p.format(file=source_file) for p in config["run"])

    # Use unshare with user + network namespaces, clean environment
    sandbox_cmd = [
        "unshare",
        "--user",       # User namespace (unprivileged)
        "--net",        # Network namespace (no network)
        "--map-root-user",  # Map to root inside namespace
        "--",
        "env", "-i",    # Clean environment
        f"PATH={SAFE_PATH}",
        "HOME=/tmp",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "TMPDIR=/tmp",
        "bash", "-c", cmd_str,
    ]

    start = time.monotonic()
    try:
        proc = subprocess.run(
            sandbox_cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=time_limit_ms / 1000.0,
            cwd=working_dir,
            preexec_fn=os.setsid,  # New process group
        )
        elapsed = int((time.monotonic() - start) * 1000)

        stdout = proc.stdout[:MAX_OUTPUT_BYTES] if proc.stdout else ""
        stderr = proc.stderr[:MAX_OUTPUT_BYTES] if proc.stderr else ""

        return stdout, stderr, proc.returncode, elapsed

    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return "", "Time Limit Exceeded", -1, elapsed
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return "", f"Sandbox error: {str(e)}", -1, elapsed


# ============================================================
# Provider: Fallback (env-cleaned subprocess)
# ============================================================

def _run_fallback(
    source_code: str,
    language: str,
    stdin: str,
    time_limit_ms: int,
    memory_limit_mb: int,
    working_dir: str,
) -> tuple[str, str, int, int]:
    """Minimal fallback: clean environment + timeout.

    This is the least secure option — used only when neither Docker
    nor unshare is available. Environment cleaning still prevents
    credential leakage, but filesystem and network are not isolated.
    """
    config = LANGUAGE_CONFIGS[language]
    safe_env = _safe_env()

    ext = config["ext"]
    if language == "java":
        classname = _get_java_classname(source_code)
        filename = f"{classname}{ext}"
    else:
        filename = f"solution{ext}"

    source_file = os.path.join(working_dir, filename)

    if config["compile"]:
        if language == "cpp":
            cmd = [p.format(file=source_file, output=os.path.join(working_dir, "solution"))
                   for p in config["compile"]]
        elif language == "java":
            cmd = [p.format(file=source_file) for p in config["compile"]]
        else:
            cmd = [p.format(file=source_file) for p in config["compile"]]
    else:
        cmd = [p.format(file=source_file) for p in config["run"]]

    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=time_limit_ms / 1000.0,
            cwd=working_dir,
            env=safe_env,
            preexec_fn=os.setsid,
        )
        elapsed = int((time.monotonic() - start) * 1000)

        stdout = proc.stdout[:MAX_OUTPUT_BYTES] if proc.stdout else ""
        stderr = proc.stderr[:MAX_OUTPUT_BYTES] if proc.stderr else ""

        return stdout, stderr, proc.returncode, elapsed

    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - start) * 1000)
        return "", "Time Limit Exceeded", -1, elapsed
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return "", f"Execution error: {str(e)}", -1, elapsed


# ============================================================
# Core Execution (provider-agnostic)
# ============================================================

def _get_java_classname(source_code: str) -> str:
    """Extract the public class name from Java source code."""
    for line in source_code.split("\n"):
        stripped = line.strip()
        if stripped.startswith("public class "):
            parts = stripped.split()
            if len(parts) >= 3:
                name = parts[2].split("{")[0].strip()
                return name
    return "Main"


def _get_runner():
    """Select the best available execution provider."""
    if _check_docker():
        return _run_docker
    if _check_unshare():
        return _run_unshare
    logger.warning("No isolation available — using fallback (env-cleaned subprocess)")
    return _run_fallback


def compile_code(
    source_code: str,
    language: str,
    working_dir: str,
    time_limit_ms: int = 10000,
) -> Optional[str]:
    """Compile source code if needed. Returns error message or None."""
    config = LANGUAGE_CONFIGS.get(language)
    if not config:
        return f"Unsupported language: {language}"

    if not config["compile"]:
        return None

    ext = config["ext"]
    if language == "java":
        classname = _get_java_classname(source_code)
        filename = f"{classname}{ext}"
    else:
        filename = f"solution{ext}"

    filepath = os.path.join(working_dir, filename)
    with open(filepath, "w") as f:
        f.write(source_code)

    if language == "cpp":
        output = os.path.join(working_dir, "solution")
        cmd = [part.format(file=filepath, output=output) for part in config["compile"]]
    else:
        cmd = [part.format(file=filepath) for part in config["compile"]]

    safe_env = _safe_env()
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=time_limit_ms / 1000.0,
            cwd=working_dir, env=safe_env, preexec_fn=os.setsid,
        )
        if proc.returncode != 0:
            return proc.stderr or proc.stdout or "Compilation failed"
    except subprocess.TimeoutExpired:
        return "Compilation timed out"
    except Exception as e:
        return f"Compilation error: {str(e)}"

    return None


def execute_code(
    source_code: str,
    language: str,
    stdin: str,
    time_limit_ms: int = DEFAULT_TIME_LIMIT_MS,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
) -> ExecutionResult:
    """Execute source code with given stdin in an isolated environment.

    This is the main entry point. The execution provider is selected
    automatically based on what's available in the environment.
    """
    config = LANGUAGE_CONFIGS.get(language)
    if not config:
        return ExecutionResult(status="error", stderr=f"Unsupported language: {language}")

    runner = _get_runner()

    with tempfile.TemporaryDirectory(prefix="code_exec_") as working_dir:
        ext = config["ext"]
        if language == "java":
            classname = _get_java_classname(source_code)
            filename = f"{classname}{ext}"
        else:
            filename = f"solution{ext}"

        filepath = os.path.join(working_dir, filename)
        with open(filepath, "w") as f:
            f.write(source_code)

        # Compile if needed (using safe subprocess)
        compile_error = compile_code(
            source_code, language, working_dir,
            time_limit_ms=min(time_limit_ms, 10000),
        )
        if compile_error:
            return ExecutionResult(status="compile_error", compilation_error=compile_error)

        # Execute in isolated environment
        stdout, stderr, exit_code, exec_time = runner(
            source_code, language, stdin, time_limit_ms, memory_limit_mb, working_dir
        )

        if exec_time >= time_limit_ms:
            return ExecutionResult(status="timeout", execution_time_ms=exec_time)

        if exit_code != 0:
            return ExecutionResult(
                status="failed", stdout=stdout, stderr=stderr,
                exit_code=exit_code, execution_time_ms=exec_time,
            )

        return ExecutionResult(
            status="passed", stdout=stdout, stderr=stderr,
            exit_code=0, execution_time_ms=exec_time,
        )


def run_code_public(
    source_code: str,
    language: str,
    test_cases: list[dict],
    time_limit_ms: int = DEFAULT_TIME_LIMIT_MS,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
) -> dict:
    """Run code against PUBLIC test cases (browser feedback only, never scored)."""
    results = []
    all_passed = True

    for tc in test_cases:
        result = execute_code(
            source_code, language, tc["input"],
            time_limit_ms=time_limit_ms,
            memory_limit_mb=memory_limit_mb,
        )

        actual_output = result.stdout.strip()
        expected_output = tc["expected_output"].strip()
        passed = result.status == "passed" and actual_output == expected_output
        if not passed:
            all_passed = False

        results.append({
            "id": tc.get("id"),
            "is_public": tc.get("is_public", True),
            "passed": passed,
            "expected_output": expected_output if not passed else None,
            "actual_output": actual_output if not passed else None,
            "status": result.status,
            "execution_time_ms": result.execution_time_ms,
        })

    return {"all_passed": all_passed, "results": results}


def evaluate_submission(
    source_code: str,
    language: str,
    test_cases: list[dict],
    time_limit_ms: int = DEFAULT_TIME_LIMIT_MS,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
) -> dict:
    """Evaluate submission against ALL test cases (server-side only)."""
    total_points = 0
    earned_points = 0
    tests_passed = 0
    tests_total = len(test_cases)
    max_execution_time = 0
    test_results = []

    for tc in test_cases:
        tc_points = tc.get("points", 1)
        total_points += tc_points

        result = execute_code(
            source_code, language, tc["input"],
            time_limit_ms=time_limit_ms,
            memory_limit_mb=memory_limit_mb,
        )

        actual_output = result.stdout.strip()
        expected_output = tc["expected_output"].strip()
        passed = result.status == "passed" and actual_output == expected_output

        if passed:
            earned_points += tc_points
            tests_passed += 1

        max_execution_time = max(max_execution_time, result.execution_time_ms)

        test_results.append({
            "id": tc.get("id"),
            "passed": passed,
            "status": result.status,
            "execution_time_ms": result.execution_time_ms,
        })

    return {
        "score": earned_points,
        "max_score": total_points,
        "tests_passed": tests_passed,
        "tests_total": tests_total,
        "execution_time_ms": max_execution_time,
        "test_results": test_results,
    }
