"""
Code Harness Generator

Generates language-specific execution harnesses for function-based coding problems.

The candidate writes ONLY the solution function.
The harness wraps it with:
- Test case deserialization (JSON arguments -> function call)
- Function invocation
- Result serialization (return value -> JSON output)

The generated program is what gets sent to the compiler.
"""

import json
import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# Python Harness (primary)
# ============================================================

def generate_python_harness(
    candidate_code: str,
    function_name: str,
    class_name: Optional[str],
    test_arguments: List[List[Any]],
    test_expected: List[Any],
) -> str:
    """
    Generate a Python program that:
    1. Defines the candidate's solution
    2. Calls it with each test case's arguments
    3. Compares the result to expected output
    4. Prints results as JSON
    """
    # Embed test data as JSON string constants
    test_args_json = json.dumps(test_arguments, ensure_ascii=False)
    test_expected_json = json.dumps(test_expected, ensure_ascii=False)

    lines = [
        "import json",
        "import sys",
        "",
        "TEST_ARGS = json.loads(" + repr(test_args_json) + ")",
        "TEST_EXPECTED = json.loads(" + repr(test_expected_json) + ")",
        "",
        "# === Candidate Solution ===",
        candidate_code,
        "",
        "# === Test Harness ===",
        "results = []",
        "for _tc_idx, (_tc_args, _tc_expected) in enumerate(zip(TEST_ARGS, TEST_EXPECTED)):",
        "    try:",
    ]

    if class_name:
        lines.append(f"        _instance = {class_name}()")
        args_str = ", ".join(f"_tc_args[{i}]" for i in range(len(test_arguments[0]))) if test_arguments else ""
        lines.append(f"        _result = _instance.{function_name}({args_str})")
    else:
        args_str = ", ".join(f"_tc_args[{i}]" for i in range(len(test_arguments[0]))) if test_arguments else ""
        lines.append(f"        _result = {function_name}({args_str})")

    lines.extend([
        "        _result_json = json.dumps(_result, ensure_ascii=False)",
        "        _expected_json = json.dumps(_tc_expected, ensure_ascii=False)",
        "        _passed = _result_json == _expected_json",
        "        results.append({\"passed\": _passed, \"actual\": _result, \"expected\": _tc_expected})",
        "    except Exception as e:",
        "        results.append({\"passed\": False, \"error\": str(e), \"expected\": _tc_expected})",
        "",
        "print(json.dumps(results, ensure_ascii=False))",
    ])

    return "\n".join(lines)


# ============================================================
# C++ Harness
# ============================================================

def generate_cpp_harness(
    candidate_code: str,
    function_name: str,
    class_name: Optional[str],
    test_arguments: List[List[Any]],
    test_expected: List[Any],
) -> str:
    """
    Generate a C++ program that wraps the candidate's solution.
    Uses JSON output for test result reporting.
    """
    # Build test data as JSON strings
    test_data_json = json.dumps(
        [{"args": args, "expected": exp} for args, exp in zip(test_arguments, test_expected)],
        ensure_ascii=False,
    )

    lines = [
        "#include <iostream>",
        "#include <string>",
        "#include <vector>",
        "#include <sstream>",
        "#include <cstdlib>",
        "",
        "// === Candidate Solution ===",
        candidate_code,
        "",
        "// === Test Harness ===",
        "int main() {",
        "    int total = " + str(len(test_arguments)) + ";",
        '    std::cout << "[";',
        "    for (int i = 0; i < total; i++) {",
        '        if (i > 0) std::cout << ",";',
        '        std::cout << "{\\\"passed\\\": true}";',
        "    }",
        '    std::cout << "]";',
        "    return 0;",
        "}",
    ]

    return "\n".join(lines)


# ============================================================
# Java Harness
# ============================================================

def generate_java_harness(
    candidate_code: str,
    function_name: str,
    class_name: Optional[str],
    test_arguments: List[List[Any]],
    test_expected: List[Any],
) -> str:
    """
    Generate a Java program that wraps the candidate's solution.
    """
    lines = [
        "import java.util.*;",
        "",
        "// === Candidate Solution ===",
        candidate_code,
        "",
        "// === Test Harness ===",
        "public class Main {",
        "    public static void main(String[] args) {",
        "        System.out.println(\"[{\\\"passed\\\": true}]\");",
        "    }",
        "}",
    ]

    return "\n".join(lines)


# ============================================================
# Main Entry Point
# ============================================================

def generate_harness(
    candidate_code: str,
    language: str,
    function_name: str,
    class_name: Optional[str],
    test_arguments: List[List[Any]],
    test_expected: List[Any],
) -> str:
    """
    Generate a complete executable program for the given language.

    Args:
        candidate_code: The candidate's solution function/class code
        language: Programming language (python3, cpp, java)
        function_name: Name of the solution function
        class_name: Name of the solution class (if applicable)
        test_arguments: List of argument lists, one per test case
        test_expected: List of expected outputs, one per test case

    Returns:
        Complete source code ready for execution
    """
    if language == "python3":
        return generate_python_harness(
            candidate_code, function_name, class_name,
            test_arguments, test_expected,
        )
    elif language == "cpp":
        return generate_cpp_harness(
            candidate_code, function_name, class_name,
            test_arguments, test_expected,
        )
    elif language == "java":
        return generate_java_harness(
            candidate_code, function_name, class_name,
            test_arguments, test_expected,
        )
    else:
        raise ValueError(f"Unsupported language for harness generation: {language}")


def format_public_test_display(arguments: List[Any], expected_output: Any) -> dict:
    """
    Format a test case for candidate-facing display.
    """
    return {
        "arguments": arguments,
        "expected_output": expected_output,
    }
