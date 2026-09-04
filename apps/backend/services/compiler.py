"""
Compiler Service Integration

Communicates with the external gateway-api /api/execute endpoint.
The gateway-api then forwards to compiler-1 for isolated execution.

Architecture:
  dsc_recruit backend -> gateway-api /api/execute -> compiler-1 /execute

This service:
- Sends source code + test cases to the gateway
- Receives execution results
- Never executes code locally
- Never invokes Docker directly
- Uses httpx for async HTTP calls
"""

import os
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# Gateway API configuration
COMPILER_URL = os.getenv("COMPILER_URL", "http://localhost:8001")
COMPILER_TIMEOUT = float(os.getenv("COMPILER_TIMEOUT", "30.0"))


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
    Execute code against test cases via the compiler service.
    
    Args:
        language: Programming language (python3, cpp, java)
        source_code: The source code to execute
        test_cases: List of {input, expected_output, label?} dicts
        time_limit_seconds: Time limit per test case
        memory_limit_mb: Memory limit
        max_output_bytes: Maximum output size
        attempt_id: Assessment attempt ID (for tracking)
        problem_id: Coding problem ID (for tracking)
        session_id: Session ID (for tracking)
    
    Returns:
        CompilerResponse with execution results
    
    Raises:
        CompilerError: If the compiler service is unavailable
    """
    # Map our language names to compiler API names
    language_map = {
        "python3": "python",
        "cpp": "cpp",
        "java": "java",
    }
    compiler_language = language_map.get(language, language)
    
    # Build request payload
    payload = {
        "language": compiler_language,
        "source_code": source_code,
        "test_cases": [
            {
                "input": tc.get("input", ""),
                "expected_output": tc.get("expected_output", ""),
                "label": tc.get("label"),
            }
            for tc in test_cases
        ],
        "limits": {
            "time_limit_seconds": time_limit_seconds,
            "memory_limit_mb": memory_limit_mb,
            "max_output_bytes": max_output_bytes,
        },
    }
    
    # Add tracking context if available
    if attempt_id:
        payload["attempt_id"] = attempt_id
    if problem_id:
        payload["question_id"] = problem_id
    if session_id:
        payload["session_id"] = session_id
    
    url = f"{COMPILER_URL}/api/execute"
    
    try:
        async with httpx.AsyncClient(timeout=COMPILER_TIMEOUT) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
            return CompilerResponse(
                status=data.get("status", "internal_error"),
                language=data.get("language", compiler_language),
                execution_time_ms=data.get("execution_time_ms", 0),
                tests=data.get("tests", []),
                error=data.get("error"),
                failed_test=data.get("failed_test"),
                total_tests=data.get("total_tests", 0),
                passed_tests=data.get("passed_tests", 0),
            )
    
    except httpx.ConnectError as e:
        logger.error(f"Compiler service unavailable: {e}")
        raise CompilerError(f"Compiler service unavailable: {e}")
    
    except httpx.TimeoutException as e:
        logger.error(f"Compiler service timeout: {e}")
        raise CompilerError(f"Compiler service timeout: {e}")
    
    except httpx.HTTPStatusError as e:
        logger.error(f"Compiler service error: {e.response.status_code} - {e.response.text}")
        raise CompilerError(f"Compiler service error: {e.response.status_code}")
    
    except Exception as e:
        logger.error(f"Unexpected compiler service error: {e}")
        raise CompilerError(f"Unexpected error: {e}")


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
    Synchronous version of execute_code for use in non-async contexts.
    
    Uses httpx.Client instead of httpx.AsyncClient.
    """
    language_map = {
        "python3": "python",
        "cpp": "cpp",
        "java": "java",
    }
    compiler_language = language_map.get(language, language)
    
    payload = {
        "language": compiler_language,
        "source_code": source_code,
        "test_cases": [
            {
                "input": tc.get("input", ""),
                "expected_output": tc.get("expected_output", ""),
                "label": tc.get("label"),
            }
            for tc in test_cases
        ],
        "limits": {
            "time_limit_seconds": time_limit_seconds,
            "memory_limit_mb": memory_limit_mb,
            "max_output_bytes": max_output_bytes,
        },
    }
    
    if attempt_id:
        payload["attempt_id"] = attempt_id
    if problem_id:
        payload["question_id"] = problem_id
    if session_id:
        payload["session_id"] = session_id
    
    url = f"{COMPILER_URL}/api/execute"
    
    try:
        with httpx.Client(timeout=COMPILER_TIMEOUT) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
            return CompilerResponse(
                status=data.get("status", "internal_error"),
                language=data.get("language", compiler_language),
                execution_time_ms=data.get("execution_time_ms", 0),
                tests=data.get("tests", []),
                error=data.get("error"),
                failed_test=data.get("failed_test"),
                total_tests=data.get("total_tests", 0),
                passed_tests=data.get("passed_tests", 0),
            )
    
    except httpx.ConnectError as e:
        logger.error(f"Compiler service unavailable: {e}")
        raise CompilerError(f"Compiler service unavailable: {e}")
    
    except httpx.TimeoutException as e:
        logger.error(f"Compiler service timeout: {e}")
        raise CompilerError(f"Compiler service timeout: {e}")
    
    except httpx.HTTPStatusError as e:
        logger.error(f"Compiler service error: {e.response.status_code} - {e.response.text}")
        raise CompilerError(f"Compiler service error: {e.response.status_code}")
    
    except Exception as e:
        logger.error(f"Unexpected compiler service error: {e}")
        raise CompilerError(f"Unexpected error: {e}")
