"""
Code Execution Service — Compiler Service Integration with Harness Generation

Communicates with the external compiler service (gateway-api -> compiler-1)
for isolated execution of untrusted candidate code.

Architecture:
  dsc_recruit backend -> gateway-api /api/execute -> compiler-1 /execute

SECURITY ARCHITECTURE:
  - No local code execution
  - No Docker subprocess invocation
  - No filesystem access for candidate code
  - All execution happens in the isolated compiler service
  - Gateway-api provides additional tracking/quotas

The public API (execute_code, run_code_public, evaluate_submission)
generates language-specific harnesses for function-based problems.
"""

import json
import logging
from typing import Optional, List, Any

logger = logging.getLogger(__name__)

from services.compiler import (
    execute_code_sync,
    CompilerResponse,
    CompilerError,
)
from services.harness import generate_harness

LANGUAGE_CONFIGS = {
    "python3": {"compiler_lang": "python"},
    "cpp": {"compiler_lang": "cpp"},
    "java": {"compiler_lang": "java"},
}

DEFAULT_TIME_LIMIT_MS = 2000
DEFAULT_MEMORY_LIMIT_MB = 256
MAX_OUTPUT_BYTES = 65536

# Compiler status -> status vocabulary used by the candidate-facing result UI.
# The UI renders `compile_error`, `runtime_error`, `timeout`, `failed`, `passed`.
RUN_STATUS_MAP = {
    "accepted": "passed",
    "wrong_answer": "failed",
    "time_limit_exceeded": "timeout",
    "runtime_error": "runtime_error",
    "compilation_error": "compile_error",
    "invalid_language": "error",
    "internal_error": "error",
    "capacity_exceeded": "error",
}


# ============================================================
# Execution Result (backward compatibility)
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
# Function-based execution (new model)
# ============================================================

def _parse_harness_results(output: str, num_tests: int) -> list:
    """Parse JSON output from the Python harness."""
    import json
    try:
        results = json.loads(output.strip())
        if isinstance(results, list):
            return results
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: treat entire output as a single test result
    return [{"passed": False, "error": "Could not parse harness output"}]


def run_code_public(
    source_code: str,
    language: str,
    test_cases: List[dict],
    time_limit_ms: int = DEFAULT_TIME_LIMIT_MS,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
    attempt_id: Optional[str] = None,
    problem_id: Optional[str] = None,
    function_name: str = "solve",
    class_name: Optional[str] = None,
    function_signature: Optional[str] = None,
) -> dict:
    """
    Run code against PUBLIC test cases (browser feedback only, never scored).

    Generates a harness, executes via compiler service, returns structured results.
    """
    if not test_cases:
        return {"all_passed": True, "results": [], "message": "No public test cases"}

    # Extract arguments and expected outputs from test cases
    test_arguments = [tc.get("arguments", [tc.get("input", "")]) for tc in test_cases]
    test_expected = [tc.get("expected_output", "") for tc in test_cases]

    try:
        # Generate the complete executable program with harness
        full_source = generate_harness(
            candidate_code=source_code,
            language=language,
            function_name=function_name,
            class_name=class_name,
            function_signature=function_signature,
            test_arguments=test_arguments,
            test_expected=test_expected,
        )

        # For the compiler, we send the full program as source_code
        # and individual test cases for output comparison
        compiler_test_cases = [
            {
                "input": "",  # No stdin needed — harness embeds test data
                "expected_output": json.dumps(expected, ensure_ascii=False),
            }
            for expected in test_expected
        ]

        response = execute_code_sync(
            language=language,
            source_code=full_source,
            test_cases=compiler_test_cases,
            time_limit_seconds=time_limit_ms / 1000.0,
            memory_limit_mb=memory_limit_mb,
            max_output_bytes=MAX_OUTPUT_BYTES,
            attempt_id=attempt_id,
            problem_id=problem_id,
        )

        compiler_tests = response.tests or []
        compilation_error = (
            response.error if response.status == "compilation_error" else None
        )

        results = []
        all_passed = True

        for idx, tc in enumerate(test_cases):
            passed = False
            status = RUN_STATUS_MAP.get(response.status, "error")
            actual_output = None
            stderr = None
            execution_time_ms = response.execution_time_ms

            if idx < len(compiler_tests):
                test = compiler_tests[idx]
                passed = bool(test.get("passed", False))
                actual_output = test.get("actual_output")
                stderr = test.get("stderr") or test.get("error")
                execution_time_ms = test.get(
                    "execution_time_ms", execution_time_ms
                )
                if not passed:
                    status = RUN_STATUS_MAP.get(
                        test.get("status") or response.status, status
                    )

            if not passed:
                all_passed = False
                # Surface compiler diagnostics so the UI can show them. The
                # compiler service reports compilation failures with an empty
                # tests list and the diagnostics in `error`.
                if status == "compile_error" and not stderr and compilation_error:
                    stderr = compilation_error

            # For public tests, show expected/actual/input on failure.
            # `input`/`arguments` are public test-case fields already sent to
            # the candidate in the problems payload.
            results.append({
                "id": tc.get("id"),
                "is_public": True,
                "passed": passed,
                "expected_output": tc.get("expected_output") if not passed else None,
                # actual_output is public-test data (the candidate's own
                # return value for a public case), so it is shown for both
                # passing and failing tests.
                "actual_output": actual_output,
                "input": tc.get("input"),
                "arguments": tc.get("arguments"),
                "stderr": stderr if not passed else None,
                "status": "passed" if passed else status,
                "execution_time_ms": execution_time_ms,
            })

        payload = {"all_passed": all_passed, "results": results}
        if compilation_error:
            payload["compilation_error"] = compilation_error
        return payload

    except CompilerError as e:
        logger.error(f"Compiler service error during run: {e}")
        return {
            "all_passed": False,
            "results": [],
            "error": f"Compiler service unavailable: {str(e)}",
        }
    except Exception as e:
        logger.error(f"Unexpected error during run: {e}")
        return {
            "all_passed": False,
            "results": [],
            "error": f"Execution error: {str(e)}",
        }


def evaluate_submission(
    source_code: str,
    language: str,
    test_cases: List[dict],
    time_limit_ms: int = DEFAULT_TIME_LIMIT_MS,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
    attempt_id: Optional[str] = None,
    problem_id: Optional[str] = None,
    function_name: str = "solve",
    class_name: Optional[str] = None,
    function_signature: Optional[str] = None,
) -> dict:
    """
    Evaluate submission against ALL test cases (server-side only).

    Generates harness, executes via compiler, scores based on test results.
    """
    import json as json_mod

    total_points = 0
    earned_points = 0
    tests_passed = 0
    tests_total = len(test_cases)
    max_execution_time = 0
    test_results = []

    try:
        # Extract arguments and expected outputs
        test_arguments = [tc.get("arguments", [tc.get("input", "")]) for tc in test_cases]
        test_expected = [tc.get("expected_output", "") for tc in test_cases]

        # Generate the complete executable program
        full_source = generate_harness(
            candidate_code=source_code,
            language=language,
            function_name=function_name,
            class_name=class_name,
            function_signature=function_signature,
            test_arguments=test_arguments,
            test_expected=test_expected,
        )

        compiler_test_cases = [
            {
                "input": "",
                "expected_output": json_mod.dumps(expected, ensure_ascii=False),
            }
            for expected in test_expected
        ]

        response = execute_code_sync(
            language=language,
            source_code=full_source,
            test_cases=compiler_test_cases,
            time_limit_seconds=time_limit_ms / 1000.0,
            memory_limit_mb=memory_limit_mb,
            max_output_bytes=MAX_OUTPUT_BYTES,
            attempt_id=attempt_id,
            problem_id=problem_id,
        )

        for idx, tc in enumerate(test_cases):
            tc_points = tc.get("points", 1)
            total_points += tc_points

            test_result = response.tests[idx] if idx < len(response.tests) else {}
            passed = test_result.get("passed", False)

            if passed:
                earned_points += tc_points
                tests_passed += 1

            exec_time = test_result.get("execution_time_ms", 0)
            max_execution_time = max(max_execution_time, exec_time)

            compiler_status = test_result.get("status", response.status)
            status_map = {
                "accepted": "passed",
                "wrong_answer": "failed",
                "time_limit_exceeded": "timeout",
                "runtime_error": "failed",
                "compilation_error": "compile_error",
                "invalid_language": "error",
                "internal_error": "error",
                "capacity_exceeded": "error",
            }
            status = status_map.get(compiler_status, "error")

            test_results.append({
                "id": tc.get("id"),
                "passed": passed,
                "status": status,
                "execution_time_ms": exec_time,
            })

        return {
            "score": earned_points,
            "max_score": total_points,
            "tests_passed": tests_passed,
            "tests_total": tests_total,
            "execution_time_ms": max_execution_time,
            "test_results": test_results,
        }

    except CompilerError as e:
        logger.error(f"Compiler service error during submission: {e}")
        return {
            "score": 0,
            "max_score": sum(tc.get("points", 1) for tc in test_cases),
            "tests_passed": 0,
            "tests_total": tests_total,
            "execution_time_ms": 0,
            "test_results": [
                {"id": tc.get("id"), "passed": False, "status": "error", "execution_time_ms": 0}
                for tc in test_cases
            ],
        }
    except Exception as e:
        logger.error(f"Unexpected error during submission: {e}")
        return {
            "score": 0,
            "max_score": sum(tc.get("points", 1) for tc in test_cases),
            "tests_passed": 0,
            "tests_total": tests_total,
            "execution_time_ms": 0,
            "test_results": [
                {"id": tc.get("id"), "passed": False, "status": "error", "execution_time_ms": 0}
                for tc in test_cases
            ],
        }


# ============================================================
# Legacy stdin/stdout execution (backward compatibility)
# ============================================================

def execute_code(
    source_code: str,
    language: str,
    stdin: str,
    time_limit_ms: int = DEFAULT_TIME_LIMIT_MS,
    memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
) -> ExecutionResult:
    """
    Execute source code with given stdin via the compiler service.
    Legacy function for backward compatibility.
    """
    config = LANGUAGE_CONFIGS.get(language)
    if not config:
        return ExecutionResult(status="error", stderr=f"Unsupported language: {language}")

    try:
        test_cases = [{"input": stdin, "expected_output": ""}]

        response = execute_code_sync(
            language=language,
            source_code=source_code,
            test_cases=test_cases,
            time_limit_seconds=time_limit_ms / 1000.0,
            memory_limit_mb=memory_limit_mb,
            max_output_bytes=MAX_OUTPUT_BYTES,
        )

        status_map = {
            "accepted": "passed",
            "wrong_answer": "failed",
            "time_limit_exceeded": "timeout",
            "runtime_error": "failed",
            "compilation_error": "compile_error",
            "invalid_language": "error",
            "internal_error": "error",
            "capacity_exceeded": "error",
        }

        status = status_map.get(response.status, "error")

        stdout = ""
        stderr = ""
        if response.tests:
            test = response.tests[0]
            stdout = test.get("stdout", "") or test.get("actual_output", "")
            stderr = test.get("stderr", "") or test.get("error", "")

        return ExecutionResult(
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=0 if status == "passed" else 1,
            execution_time_ms=response.execution_time_ms,
            compilation_error=response.error if status == "compile_error" else None,
        )

    except CompilerError as e:
        logger.error(f"Compiler service error: {e}")
        return ExecutionResult(status="error", stderr=f"Compiler service error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return ExecutionResult(status="error", stderr=f"Execution error: {str(e)}")
