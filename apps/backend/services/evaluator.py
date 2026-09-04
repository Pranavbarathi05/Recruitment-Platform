"""
Code Evaluator — delegates to the compiler service.

Used by the legacy /submission/ endpoint.
For the main coding assessment flow, use code_executor.py directly.
"""

import logging
from typing import Dict, Any

from services.compiler import execute_code_sync, CompilerError

logger = logging.getLogger(__name__)


def evaluate_code(attempt_id: str, code: str, language: str) -> Dict[str, Any]:
    """
    Evaluate submitted code via the compiler service.

    Args:
        attempt_id: Unique identifier for the submission attempt
        code: The code string to evaluate
        language: Programming language of the code

    Returns:
        Dictionary containing evaluation result
    """
    # Map language names for the compiler API
    language_map = {
        "python3": "python",
        "cpp": "cpp",
        "java": "java",
    }
    compiler_language = language_map.get(language, language)

    try:
        # Execute with empty stdin, no test cases (legacy endpoint)
        response = execute_code_sync(
            language=language,
            source_code=code,
            test_cases=[{"input": "", "expected_output": ""}],
            time_limit_seconds=5.0,
        )

        return {
            "status": response.status,
            "message": response.error or "Evaluation complete",
            "attempt_id": attempt_id,
            "language": language,
            "execution_time_ms": response.execution_time_ms,
            "passed": response.status == "accepted",
        }

    except CompilerError as e:
        logger.error(f"Compiler service error for attempt {attempt_id}: {e}")
        return {
            "status": "error",
            "message": f"Compiler service error: {str(e)}",
            "attempt_id": attempt_id,
            "language": language,
            "execution_time_ms": 0,
            "passed": False,
        }

    except Exception as e:
        logger.error(f"Unexpected error evaluating attempt {attempt_id}: {e}")
        return {
            "status": "error",
            "message": f"Evaluation error: {str(e)}",
            "attempt_id": attempt_id,
            "language": language,
            "execution_time_ms": 0,
            "passed": False,
        }
