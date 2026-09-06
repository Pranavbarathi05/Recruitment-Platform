"""
Code Harness Generator

Generates language-specific execution harnesses for function-based coding problems.

The candidate writes ONLY the solution function.
The harness wraps it with:
- Test case deserialization (JSON arguments -> function call)
- Function invocation
- Result serialization (return value -> JSON output)

The generated program is what gets sent to Judge0.
"""

import json
import logging
import re
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# Python Harness (primary)
# ============================================================

def _parse_python_param_names(parsed_signature: Optional[str]) -> list[str]:
    """
    Extract the actual parameter names from a Python function signature string.

    We keep names in their declaration order and discard type annotations,
    default values, and the special 'self'/'cls' tokens. When the signature has
    no useful parameter list we return the empty list.

    Only the parameter names themselves matter here: the caller decides whether
    the generated starter is a class method (adds `self`) or a free function.
    """
    if not parsed_signature or not parsed_signature.strip():
        return []

    open_paren = parsed_signature.find("(")
    close_paren = parsed_signature.rfind(")")
    if open_paren == -1 or close_paren == -1 or close_paren < open_paren:
        return []

    params_str = parsed_signature[open_paren + 1:close_paren].strip()
    if not params_str:
        return []

    collected: list[str] = []
    for part in params_str.split(","):
        part = part.strip()
        if not part:
            continue

        # Drop return annotation, then default value, then a single trailing
        # `: Type` annotation. This keeps `nums: List[int]` -> `nums` without
        # needing a full Python type parser.
        arrow_idx = part.find("->")
        if arrow_idx != -1:
            part = part[:arrow_idx].strip()
        eq_idx = part.find("=")
        if eq_idx != -1:
            part = part[:eq_idx].strip()
        if ":" in part:
            candidate = part.split(":")[0].strip()
            if candidate and candidate.isidentifier() and candidate not in ("self", "cls"):
                collected.append(candidate)
                continue
            # The text before the colon was not a clean name (e.g. a bare type
            # hint); fall through and recover the identifier from the remainder.
            part = part.split(":")[-1].strip()

        # Fallback: walk whitespace-separated tokens backward and keep the last
        # plain identifier that is not self/cls.
        p_tokens = part.split()
        if not p_tokens:
            continue
        for raw in reversed(p_tokens):
            if raw in ("self", "cls"):
                continue
            if raw.isidentifier():
                collected.append(raw)
                break

    return collected


def _generate_python_starter_code(
    function_name: str,
    class_name: Optional[str],
    function_signature: Optional[str] = None,
) -> str:
    """
    Generate a candidate-visible Python starter that matches the configured
    problem metadata.

    The candidate sees ONLY the function/class boilerplate, never the harness.
    """
    if not function_name:
        raise ValueError("function_name is required for Python starter code")

    param_names = [p for p in _parse_python_param_names(function_signature) if p not in ("self", "cls")]
    body_params = param_names if param_names else ["arg1", "arg2"]

    if class_name:
        if not class_name.strip():
            raise ValueError("class_name must not be blank when provided")
        return (
            f"class {class_name.strip()}:\n"
            f"    def {function_name}(self, {", ".join(body_params)}):\n"
            f"        # Write your solution here\n"
            f"        pass\n"
        )

    return (
        f"def {function_name}({", ".join(body_params)}):\n"
        f"    # Write your solution here\n"
        f"    pass\n"
    )


def generate_python_harness(
    candidate_code: str,
    function_name: str,
    class_name: Optional[str],
    test_arguments: List[List[Any]],
    test_expected: List[Any],
    function_signature: Optional[str] = None,
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
        '        results.append({"passed": _passed, "actual": _result, "expected": _tc_expected})',
        "    except Exception as e:",
        '        results.append({"passed": False, "error": str(e), "expected": _tc_expected})',
        "",
        "print(json.dumps(results, ensure_ascii=False))",
    ])

    return "\n".join(lines)


# ============================================================
# C++ Harness
# ============================================================

# Minimal JSON library for C++ harness
_CXX_JSON_LIB = r"""
#include <string>
#include <vector>
#include <map>
#include <sstream>
#include <cstdlib>
#include <algorithm>
#include <cctype>

namespace json {

enum Type { NUL, BOOL, NUM, STR, ARR, OBJ };

struct Value {
    Type type;
    bool bval;
    double nval;
    std::string sval;
    std::vector<Value> aval;
    std::vector<std::pair<std::string, Value>> oval;

    Value() : type(NUL), bval(false), nval(0) {}
    Value(bool b) : type(BOOL), bval(b), nval(0) {}
    Value(double n) : type(NUM), bval(false), nval(n) {}
    Value(int n) : type(NUM), bval(false), nval(n) {}
    Value(const std::string& s) : type(STR), bval(false), nval(0), sval(s) {}
    Value(const char* s) : type(STR), bval(false), nval(0), sval(s) {}

    Value& operator[](const std::string& key) {
        type = OBJ;
        for (auto& p : oval) if (p.first == key) return p.second;
        oval.push_back({key, Value()});
        return oval.back().second;
    }

    Value& operator[](int idx) {
        type = ARR;
        while ((int)aval.size() <= idx) aval.push_back(Value());
        return aval[idx];
    }

    bool is_null() const { return type == NUL; }
    bool is_bool() const { return type == BOOL; }
    bool is_number() const { return type == NUM; }
    bool is_string() const { return type == STR; }
    bool is_array() const { return type == ARR; }
    bool is_object() const { return type == OBJ; }

    int to_int() const { return (int)nval; }
    double to_double() const { return nval; }
    const std::string& to_string() const { return sval; }
    bool to_bool() const { return bval; }
    const std::vector<Value>& to_array() const { return aval; }
    const std::vector<std::pair<std::string, Value>>& to_object() const { return oval; }
};

static void skip_ws(const std::string& s, size_t& i) {
    while (i < s.size() && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r')) i++;
}

static Value parse_value(const std::string& s, size_t& i);

static Value parse_string(const std::string& s, size_t& i) {
    i++; // skip opening quote
    std::string result;
    while (i < s.size() && s[i] != '"') {
        if (s[i] == '\\') { i++; if (i < s.size()) result += s[i]; }
        else result += s[i];
        i++;
    }
    i++; // skip closing quote
    return Value(result);
}

static Value parse_number(const std::string& s, size_t& i) {
    size_t start = i;
    if (s[i] == '-') i++;
    while (i < s.size() && (std::isdigit(s[i]) || s[i] == '.' || s[i] == 'e' || s[i] == 'E' || s[i] == '+' || s[i] == '-')) {
        if (i > start + 1 && (s[i] == '+' || s[i] == '-') && s[i-1] != 'e' && s[i-1] != 'E') break;
        i++;
    }
    return Value(std::atof(s.substr(start, i - start).c_str()));
}

static Value parse_array(const std::string& s, size_t& i) {
    i++; // skip [
    Value arr;
    arr.type = ARR;
    skip_ws(s, i);
    if (i < s.size() && s[i] == ']') { i++; return arr; }
    while (i < s.size()) {
        skip_ws(s, i);
        arr.aval.push_back(parse_value(s, i));
        skip_ws(s, i);
        if (i < s.size() && s[i] == ',') { i++; continue; }
        if (i < s.size() && s[i] == ']') { i++; break; }
    }
    return arr;
}

static Value parse_object(const std::string& s, size_t& i) {
    i++; // skip {
    Value obj;
    obj.type = OBJ;
    skip_ws(s, i);
    if (i < s.size() && s[i] == '}') { i++; return obj; }
    while (i < s.size()) {
        skip_ws(s, i);
        Value key = parse_string(s, i);
        skip_ws(s, i);
        if (i < s.size() && s[i] == ':') i++;
        skip_ws(s, i);
        Value val = parse_value(s, i);
        obj.oval.push_back({key.sval, val});
        skip_ws(s, i);
        if (i < s.size() && s[i] == ',') { i++; continue; }
        if (i < s.size() && s[i] == '}') { i++; break; }
    }
    return obj;
}

static Value parse_value(const std::string& s, size_t& i) {
    skip_ws(s, i);
    if (i >= s.size()) return Value();
    char c = s[i];
    if (c == '"') return parse_string(s, i);
    if (c == '{') return parse_object(s, i);
    if (c == '[') return parse_array(s, i);
    if (c == 't') { i += 4; return Value(true); }
    if (c == 'f') { i += 5; return Value(false); }
    if (c == 'n') { i += 4; return Value(); }
    return parse_number(s, i);
}

static Value parse(const std::string& s) {
    size_t i = 0;
    return parse_value(s, i);
}

static std::string escape(const std::string& s) {
    std::string r;
    for (char c : s) {
        switch (c) {
            case '"': r += "\\\""; break;
            case '\\': r += "\\\\"; break;
            case '\n': r += "\\n"; break;
            case '\r': r += "\\r"; break;
            case '\t': r += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", (unsigned char)c);
                    r += buf;
                } else {
                    r += c;
                }
        }
    }
    return r;
}

static std::string stringify(const Value& v) {
    std::ostringstream oss;
    switch (v.type) {
        case NUL: oss << "null"; break;
        case BOOL: oss << (v.bval ? "true" : "false"); break;
        case NUM: {
            if (v.nval == (long long)v.nval && std::abs(v.nval) < 1e15)
                oss << (long long)v.nval;
            else {
                char buf[64];
                snprintf(buf, sizeof(buf), "%.15g", v.nval);
                oss << buf;
            }
            break;
        }
        case STR: oss << "\"" << escape(v.sval) << "\""; break;
        case ARR: {
            oss << "[";
            for (size_t i = 0; i < v.aval.size(); i++) {
                if (i > 0) oss << ",";
                oss << stringify(v.aval[i]);
            }
            oss << "]";
            break;
        }
        case OBJ: {
            oss << "{";
            for (size_t i = 0; i < v.oval.size(); i++) {
                if (i > 0) oss << ",";
                oss << "\"" << escape(v.oval[i].first) << "\":" << stringify(v.oval[i].second);
            }
            oss << "}";
            break;
        }
    }
    return oss.str();
}

} // namespace json
"""

# Template for test data embedding in C++
_CXX_TEST_DATA_TEMPLATE = """
// === Embedded Test Data ===
static const char* TEST_DATA_JSON = "{test_data_json}";
static const char* EXPECTED_DATA_JSON = "{expected_data_json}";
"""


# ============================================================
# C++ Marshal Helpers — JSON <-> Native C++ Type Conversion
# ============================================================
# These functions return C++ source code strings that are embedded
# into the generated harness program. They use the existing json::Value
# type from _CXX_JSON_LIB.


def _generate_cpp_marshal_helpers() -> str:
    """
    Generate C++ helper functions for converting between json::Value
    and standard C++ LeetCode types.

    json::Value API used (from _CXX_JSON_LIB):
      Constructors: Value(), Value(bool), Value(double), Value(int),
                    Value(string), Value(const char*)
      Accessors:    to_int(), to_double(), to_bool(), to_string(),
                    to_array(), to_object()
      Type checks:  is_null(), is_bool(), is_number(), is_string(),
                    is_array(), is_object()
      Fields:       type, bval, nval, sval, aval
    """
    return """
// === JSON <-> Native Type Marshaling Helpers ===

// --- Scalar: json::Value -> native ---

static int jsonToInt(const json::Value& v) {
    if (v.is_number()) return v.to_int();
    if (v.is_string()) return std::atoi(v.to_string().c_str());
    if (v.is_bool()) return v.to_bool() ? 1 : 0;
    return 0;
}

static long long jsonToLongLong(const json::Value& v) {
    if (v.is_number()) return (long long)v.to_double();
    if (v.is_string()) return std::atoll(v.to_string().c_str());
    if (v.is_bool()) return v.to_bool() ? 1LL : 0LL;
    return 0LL;
}

static double jsonToDouble(const json::Value& v) {
    if (v.is_number()) return v.to_double();
    if (v.is_string()) return std::atof(v.to_string().c_str());
    if (v.is_bool()) return v.to_bool() ? 1.0 : 0.0;
    return 0.0;
}

static bool jsonToBool(const json::Value& v) {
    if (v.is_bool()) return v.to_bool();
    if (v.is_number()) return v.to_int() != 0;
    if (v.is_string()) return !v.to_string().empty();
    if (v.is_null()) return false;
    return true;
}

static std::string jsonToString(const json::Value& v) {
    if (v.is_string()) return v.to_string();
    if (v.is_number()) return json::stringify(v);
    if (v.is_bool()) return v.to_bool() ? "true" : "false";
    if (v.is_null()) return "";
    return json::stringify(v);
}

// --- 1D Vector: json::Value array -> std::vector<T> ---

static std::vector<int> jsonToVectorInt(const json::Value& v) {
    std::vector<int> r;
    if (!v.is_array()) return r;
    const auto& arr = v.to_array();
    r.reserve(arr.size());
    for (size_t i = 0; i < arr.size(); i++) r.push_back(jsonToInt(arr[i]));
    return r;
}

static std::vector<long long> jsonToVectorLongLong(const json::Value& v) {
    std::vector<long long> r;
    if (!v.is_array()) return r;
    const auto& arr = v.to_array();
    r.reserve(arr.size());
    for (size_t i = 0; i < arr.size(); i++) r.push_back(jsonToLongLong(arr[i]));
    return r;
}

static std::vector<double> jsonToVectorDouble(const json::Value& v) {
    std::vector<double> r;
    if (!v.is_array()) return r;
    const auto& arr = v.to_array();
    r.reserve(arr.size());
    for (size_t i = 0; i < arr.size(); i++) r.push_back(jsonToDouble(arr[i]));
    return r;
}

static std::vector<std::string> jsonToVectorString(const json::Value& v) {
    std::vector<std::string> r;
    if (!v.is_array()) return r;
    const auto& arr = v.to_array();
    r.reserve(arr.size());
    for (size_t i = 0; i < arr.size(); i++) r.push_back(jsonToString(arr[i]));
    return r;
}

static std::vector<bool> jsonToVectorBool(const json::Value& v) {
    std::vector<bool> r;
    if (!v.is_array()) return r;
    const auto& arr = v.to_array();
    r.reserve(arr.size());
    for (size_t i = 0; i < arr.size(); i++) r.push_back(jsonToBool(arr[i]));
    return r;
}

// --- 2D Vector: json::Value nested array -> std::vector<std::vector<T>> ---

static std::vector<std::vector<int>> jsonToVectorVectorInt(const json::Value& v) {
    std::vector<std::vector<int>> r;
    if (!v.is_array()) return r;
    const auto& arr = v.to_array();
    r.reserve(arr.size());
    for (size_t i = 0; i < arr.size(); i++) r.push_back(jsonToVectorInt(arr[i]));
    return r;
}

static std::vector<std::vector<std::string>> jsonToVectorVectorString(const json::Value& v) {
    std::vector<std::vector<std::string>> r;
    if (!v.is_array()) return r;
    const auto& arr = v.to_array();
    r.reserve(arr.size());
    for (size_t i = 0; i < arr.size(); i++) r.push_back(jsonToVectorString(arr[i]));
    return r;
}

// --- Scalar: native -> json::Value ---

static json::Value intToJson(int v) { return json::Value(v); }
static json::Value longLongToJson(long long v) { return json::Value((double)v); }
static json::Value doubleToJson(double v) { return json::Value(v); }
static json::Value boolToJson(bool v) { return json::Value(v); }
static json::Value stringToJson(const std::string& v) { return json::Value(v); }

// --- 1D Vector: std::vector<T> -> json::Value ---

static json::Value vectorIntToJson(const std::vector<int>& v) {
    json::Value r; r.type = json::ARR;
    for (size_t i = 0; i < v.size(); i++) r.aval.push_back(json::Value(v[i]));
    return r;
}

static json::Value vectorLongLongToJson(const std::vector<long long>& v) {
    json::Value r; r.type = json::ARR;
    for (size_t i = 0; i < v.size(); i++) r.aval.push_back(json::Value((double)v[i]));
    return r;
}

static json::Value vectorDoubleToJson(const std::vector<double>& v) {
    json::Value r; r.type = json::ARR;
    for (size_t i = 0; i < v.size(); i++) r.aval.push_back(json::Value(v[i]));
    return r;
}

static json::Value vectorStringToJson(const std::vector<std::string>& v) {
    json::Value r; r.type = json::ARR;
    for (size_t i = 0; i < v.size(); i++) r.aval.push_back(json::Value(v[i]));
    return r;
}

static json::Value vectorBoolToJson(const std::vector<bool>& v) {
    json::Value r; r.type = json::ARR;
    for (size_t i = 0; i < v.size(); i++) r.aval.push_back(json::Value(v[i]));
    return r;
}

// --- 2D Vector: std::vector<std::vector<T>> -> json::Value ---

static json::Value vectorVectorIntToJson(const std::vector<std::vector<int>>& v) {
    json::Value r; r.type = json::ARR;
    for (size_t i = 0; i < v.size(); i++) r.aval.push_back(vectorIntToJson(v[i]));
    return r;
}

static json::Value vectorVectorStringToJson(const std::vector<std::vector<std::string>>& v) {
    json::Value r; r.type = json::ARR;
    for (size_t i = 0; i < v.size(); i++) r.aval.push_back(vectorStringToJson(v[i]));
    return r;
}
"""


# ============================================================
# C++ Signature Parsing (scalar + vector<int> support)
# ============================================================

# Normalized type -> json::Value -> native conversion helper
_CPP_JSON_TO_NATIVE = {
    "int": "jsonToInt",
    "long long": "jsonToLongLong",
    "double": "jsonToDouble",
    "bool": "jsonToBool",
    "string": "jsonToString",
    "vector<int>": "jsonToVectorInt",
    "vector<string>": "jsonToVectorString",
    "vector<double>": "jsonToVectorDouble",
    "vector<long long>": "jsonToVectorLongLong",
    "vector<bool>": "jsonToVectorBool",
    "vector<vector<int>>": "jsonToVectorVectorInt",
    "vector<vector<string>>": "jsonToVectorVectorString",
}

# Normalized type -> native -> json::Value conversion helper
_CPP_NATIVE_TO_JSON = {
    "int": "intToJson",
    "long long": "longLongToJson",
    "double": "doubleToJson",
    "bool": "boolToJson",
    "string": "stringToJson",
    "vector<int>": "vectorIntToJson",
    "vector<string>": "vectorStringToJson",
    "vector<double>": "vectorDoubleToJson",
    "vector<long long>": "vectorLongLongToJson",
    "vector<bool>": "vectorBoolToJson",
    "vector<vector<int>>": "vectorVectorIntToJson",
    "vector<vector<string>>": "vectorVectorStringToJson",
}

# Normalized type -> C++ native type spelling used in generated code
_CPP_NATIVE_TYPES = {
    "int": "int",
    "long long": "long long",
    "double": "double",
    "bool": "bool",
    "string": "std::string",
    "vector<int>": "std::vector<int>",
    "vector<string>": "std::vector<std::string>",
    "vector<double>": "std::vector<double>",
    "vector<long long>": "std::vector<long long>",
    "vector<bool>": "std::vector<bool>",
    "vector<vector<int>>": "std::vector<std::vector<int>>",
    "vector<vector<string>>": "std::vector<std::vector<std::string>>",
}


def _split_top_level(text: str, sep: str = ",") -> list:
    """Split on a separator while ignoring separators inside (), [], {}, <>."""
    parts = []
    depth = 0
    current = []
    for ch in text:
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return [p for p in parts if p]


def _normalize_cpp_type(t: str) -> str:
    """Normalize a C++ type to a canonical spelling.

    Handles std:: prefixes, const, references, pointers, and whitespace.
    e.g. 'const std::vector<int>&' -> 'vector<int>'
         'int'                     -> 'int'
    """
    t = t.replace("std::", "")
    t = t.replace("const", "")
    t = t.replace("&", "")
    t = t.replace("*", "")
    t = " ".join(t.split())
    return t.strip()


def _parse_cpp_signature(signature: Optional[str]):
    """Parse a C++ function signature into (return_type, function_name, [(param_type, param_name), ...]).

    Returns None if the signature cannot be parsed.
    Example: 'int add(int a, int b)' -> ('int', 'add', [('int', 'a'), ('int', 'b')])
    """
    if not signature:
        return None
    s = signature.strip()
    open_paren = s.find("(")
    close_paren = s.rfind(")")
    if open_paren == -1 or close_paren == -1 or close_paren < open_paren:
        return None

    prefix = s[:open_paren].strip()
    params_str = s[open_paren + 1:close_paren].strip()

    tokens = prefix.split()
    if len(tokens) < 2:
        return None
    return_type = " ".join(tokens[:-1])
    fn_name = tokens[-1].strip()

    params = []
    if params_str:
        for part in _split_top_level(params_str, ","):
            eq = part.find("=")
            if eq != -1:
                part = part[:eq].strip()  # strip default values
            ptoks = part.split()
            if len(ptoks) == 1:
                params.append((" ".join(ptoks), None))
            else:
                params.append((" ".join(ptoks[:-1]), ptoks[-1]))

    return return_type, fn_name, params


def generate_cpp_harness(
    candidate_code: str,
    function_name: str,
    class_name: Optional[str],
    test_arguments: List[List[Any]],
    test_expected: List[Any],
    function_signature: Optional[str] = None,
) -> str:
    """
    Generate a C++ program that:
    1. Includes a minimal JSON parser
    2. Embeds test data as JSON strings
    3. Defines the candidate's solution
    4. Calls the function with each test case
    5. Compares results and outputs JSON array of pass/fail
    """
    # Build test data as JSON
    test_data = json.dumps(
        [{"args": args, "expected": exp} for args, exp in zip(test_arguments, test_expected)],
        ensure_ascii=False,
    )

    # Escape for C++ string literal
    test_data_escaped = test_data.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    # Parse the function signature to determine parameter/return types.
    # When a signature IS provided it is treated as the authoritative
    # native-typed contract: if it cannot be honored by the typed marshal
    # path (unparseable, function-name mismatch, or an unsupported parameter
    # or return type) we fail loudly here instead of silently falling back to
    # passing raw json::Value values into the candidate's function.
    #
    # When NO signature is provided (legacy problems / callers), the legacy
    # raw json::Value invocation is preserved unchanged.
    parsed_sig = _parse_cpp_signature(function_signature)
    sig_params = []
    sig_return = None
    if function_signature and function_signature.strip():
        if parsed_sig is None:
            raise ValueError(
                f"Unsupported C++ function signature {function_signature!r}: "
                "could not be parsed into a return type, function name and "
                "parameter list."
            )
        sig_return, sig_fn_name, sig_params = parsed_sig
        if sig_fn_name != function_name:
            raise ValueError(
                f"Unsupported C++ function signature {function_signature!r}: "
                f"function name {sig_fn_name!r} does not match the requested "
                f"function {function_name!r}."
            )
        normalized_params = [_normalize_cpp_type(p[0]) for p in sig_params]
        normalized_return = _normalize_cpp_type(sig_return)
        for i, pt in enumerate([p[0] for p in sig_params]):
            if normalized_params[i] not in _CPP_JSON_TO_NATIVE:
                raise ValueError(
                    f"Unsupported C++ parameter type {pt!r} (normalized to "
                    f"{normalized_params[i]!r}) at parameter {i} of signature "
                    f"{function_signature!r}. Supported parameter types: "
                    f"{', '.join(sorted(_CPP_JSON_TO_NATIVE))}"
                )
        if normalized_return not in _CPP_NATIVE_TO_JSON:
            raise ValueError(
                f"Unsupported C++ return type {sig_return!r} (normalized to "
                f"{normalized_return!r}) in signature {function_signature!r}. "
                f"Supported return types: "
                f"{', '.join(sorted(_CPP_NATIVE_TO_JSON))}"
            )

    lines = [
        "#include <iostream>",
        "#include <string>",
        "#include <vector>",
        "#include <sstream>",
        "#include <cstdlib>",
        "#include <cmath>",
        "",
        "using namespace std;",
        "",
        "// === Minimal JSON Library ===",
        _CXX_JSON_LIB,
        "",
        "// === Marshal Helpers ===",
        _generate_cpp_marshal_helpers(),
        "",
        "// === Embedded Test Data ===",
        f'static const char* TEST_DATA_JSON = "{test_data_escaped}";',
        "",
        "// === Candidate Solution ===",
        candidate_code,
        "",
        "// === Test Harness ===",
        "int main() {",
        "    json::Value test_data = json::parse(TEST_DATA_JSON);",
        "    json::Value results;",
        "    results.type = json::ARR;",
        "",
        "    for (size_t i = 0; i < test_data.to_array().size(); i++) {",
        "        json::Value tc = test_data.to_array()[i];",
        "        json::Value args = tc[\"args\"];",
        "        json::Value expected = tc[\"expected\"];",
        "",
        "        try {",
    ]

    # Determine whether we can emit a typed call for every parameter.
    # A successfully parsed + validated signature always uses the typed path;
    # only a missing signature reaches the legacy raw json::Value path below.
    typed_call = parsed_sig is not None

    if typed_call:
        # Convert each JSON argument to a native typed local, call the
        # candidate function with native values, then convert the native
        # return value back to json::Value.
        for i, pt in enumerate(normalized_params):
            native_type = _CPP_NATIVE_TYPES[pt]
            conv = _CPP_JSON_TO_NATIVE[pt]
            lines.append(f"            {native_type} _arg{i} = {conv}(args.to_array()[{i}]);")

        native_return = _CPP_NATIVE_TYPES[normalized_return]
        args_call = ", ".join(f"_arg{i}" for i in range(len(sig_params)))
        if class_name:
            lines.append(f"            {class_name} _obj;")
            lines.append(f"            {native_return} _result_native = _obj.{function_name}({args_call});")
        else:
            lines.append(f"            {native_return} _result_native = {function_name}({args_call});")
        lines.append(f"            json::Value _result = {_CPP_NATIVE_TO_JSON[normalized_return]}(_result_native);")
    else:
        # Legacy path: pass raw json::Value objects straight through.
        if class_name:
            lines.append(f"            {class_name} _obj;")
            if len(test_arguments) > 0 and len(test_arguments[0]) > 0:
                args_call = ", ".join(f"args.to_array()[{i}]" for i in range(len(test_arguments[0])))
            else:
                args_call = ""
            lines.append(f"            json::Value _result = _obj.{function_name}({args_call});")
        else:
            if len(test_arguments) > 0 and len(test_arguments[0]) > 0:
                args_call = ", ".join(f"args.to_array()[{i}]" for i in range(len(test_arguments[0])))
            else:
                args_call = ""
            lines.append(f"            json::Value _result = {function_name}({args_call});")

    lines.extend([
        "            bool _passed = (json::stringify(_result) == json::stringify(expected));",
        '            json::Value _r; _r.type = json::OBJ;',
        '            _r["passed"] = json::Value(_passed);',
        '            _r["actual"] = _result;',
        '            _r["expected"] = expected;',
        "            results.aval.push_back(_r);",
        "        } catch (const std::exception& e) {",
        '            json::Value _r; _r.type = json::OBJ;',
        '            _r["passed"] = json::Value(false);',
        '            _r["error"] = json::Value(std::string(e.what()));',
        '            _r["expected"] = expected;',
        "            results.aval.push_back(_r);",
        "        }",
        "    }",
        "",
        '    std::cout << json::stringify(results) << std::endl;',
        "    return 0;",
        "}",
    ])

    return "\n".join(lines)


# ============================================================
# Java Harness
# ============================================================

# Minimal JSON library for Java harness
_JAVA_JSON_LIB = """
// === Minimal JSON Library for Java ===
class JsonValue {
    enum Type { NUL, BOOL, NUM, STR, ARR, OBJ }
    Type type = Type.NUL;
    boolean bval;
    double nval;
    String sval = "";
    java.util.List<JsonValue> aval = new java.util.ArrayList<>();
    java.util.List<String> keys = new java.util.ArrayList<>();
    java.util.List<JsonValue> oval = new java.util.ArrayList<>();

    JsonValue() {}
    JsonValue(boolean b) { type = Type.BOOL; bval = b; }
    JsonValue(double n) { type = Type.NUM; nval = n; }
    JsonValue(int n) { type = Type.NUM; nval = n; }
    JsonValue(String s) { type = Type.STR; sval = s; }

    JsonValue get(String key) {
        for (int i = 0; i < keys.size(); i++) {
            if (keys.get(i).equals(key)) return oval.get(i);
        }
        return new JsonValue();
    }

    JsonValue get(int idx) {
        if (idx < aval.size()) return aval.get(idx);
        return new JsonValue();
    }

    int toInt() { return (int) nval; }
    double toDouble() { return nval; }
    String str() { return sval; }
    boolean bool() { return bval; }

    static JsonValue parse(String s) { return Parser.parse(s); }

    static String escape(String s) {
        StringBuilder sb = new StringBuilder();
        for (char c : s.toCharArray()) {
            switch (c) {
                case '\"': sb.append("\\\\\""); break;
                case '\\\\\\\\': sb.append("\\\\\\\\\\\\\\\\\"); break;
                case '\\n': sb.append("\\\\n"); break;
                case '\\r': sb.append("\\\\r"); break;
                case '\\t': sb.append("\\\\t"); break;
                default: sb.append(c);
            }
        }
        return sb.toString();
    }

    static String stringify(JsonValue v) {
        if (v == null) return "null";
        switch (v.type) {
            case NUL: return "null";
            case BOOL: return v.bval ? "true" : "false";
            case NUM:
                if (v.nval == (long) v.nval && Math.abs(v.nval) < 1e15)
                    return Long.toString((long) v.nval);
                return Double.toString(v.nval);
            case STR: return "\\"" + escape(v.sval) + "\\"";
            case ARR:
                StringBuilder sb = new StringBuilder("[");
                for (int i = 0; i < v.aval.size(); i++) {
                    if (i > 0) sb.append(",");
                    sb.append(stringify(v.aval.get(i)));
                }
                return sb.append("]").toString();
            case OBJ:
                StringBuilder ob = new StringBuilder("{");
                for (int i = 0; i < v.keys.size(); i++) {
                    if (i > 0) ob.append(",");
                    ob.append("\\"").append(escape(v.keys.get(i))).append("\\":");
                    ob.append(stringify(v.oval.get(i)));
                }
                return ob.append("}").toString();
            default: return "null";
        }
    }

    static class Parser {
        static int pos;
        static String src;

        static JsonValue parse(String s) {
            src = s; pos = 0;
            return parseValue();
        }

        static void skipWs() {
            while (pos < src.length() && Character.isWhitespace(src.charAt(pos))) pos++;
        }

        static JsonValue parseValue() {
            skipWs();
            if (pos >= src.length()) return new JsonValue();
            char c = src.charAt(pos);
            if (c == '"') return parseString();
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == 't') { pos += 4; return new JsonValue(true); }
            if (c == 'f') { pos += 5; return new JsonValue(false); }
            if (c == 'n') { pos += 4; return new JsonValue(); }
            return parseNumber();
        }

        static JsonValue parseString() {
            pos++; // skip opening quote
            StringBuilder sb = new StringBuilder();
            while (pos < src.length() && src.charAt(pos) != '\"') {
                if (src.charAt(pos) == '\\\\') { pos++; if (pos < src.length()) sb.append(src.charAt(pos)); }
                else sb.append(src.charAt(pos));
                pos++;
            }
            pos++; // skip closing quote
            return new JsonValue(sb.toString());
        }

        static JsonValue parseNumber() {
            int start = pos;
            if (src.charAt(pos) == '-') pos++;
            while (pos < src.length() && (Character.isDigit(src.charAt(pos)) || src.charAt(pos) == '.' || src.charAt(pos) == 'e' || src.charAt(pos) == 'E' || src.charAt(pos) == '+' || src.charAt(pos) == '-')) {
                if (pos > start + 1 && (src.charAt(pos) == '+' || src.charAt(pos) == '-') && src.charAt(pos-1) != 'e' && src.charAt(pos-1) != 'E') break;
                pos++;
            }
            return new JsonValue(Double.parseDouble(src.substring(start, pos)));
        }

        static JsonValue parseArray() {
            pos++; // skip [
            JsonValue arr = new JsonValue();
            arr.type = Type.ARR;
            skipWs();
            if (pos < src.length() && src.charAt(pos) == ']') { pos++; return arr; }
            while (pos < src.length()) {
                skipWs();
                arr.aval.add(parseValue());
                skipWs();
                if (pos < src.length() && src.charAt(pos) == ',') { pos++; continue; }
                if (pos < src.length() && src.charAt(pos) == ']') { pos++; break; }
            }
            return arr;
        }

        static JsonValue parseObject() {
            pos++; // skip {
            JsonValue obj = new JsonValue();
            obj.type = Type.OBJ;
            skipWs();
            if (pos < src.length() && src.charAt(pos) == '}') { pos++; return obj; }
            while (pos < src.length()) {
                skipWs();
                JsonValue key = parseString();
                skipWs();
                if (pos < src.length() && src.charAt(pos) == ':') pos++;
                skipWs();
                JsonValue val = parseValue();
                obj.keys.add(key.sval);
                obj.oval.add(val);
                skipWs();
                if (pos < src.length() && src.charAt(pos) == ',') { pos++; continue; }
                if (pos < src.length() && src.charAt(pos) == '}') { pos++; break; }
            }
            return obj;
        }
    }
}
"""


# ============================================================
# Java Signature Parsing + Typed Marshal Support
# ============================================================

# Normalized type -> json::Value -> native conversion helper (Java)
_JAVA_JSON_TO_NATIVE = {
    "int": "jsonToInt",
    "long": "jsonToLong",
    "double": "jsonToDouble",
    "boolean": "jsonToBoolean",
    "String": "jsonToString",
    "int[]": "jsonToIntArray",
    "long[]": "jsonToLongArray",
    "double[]": "jsonToDoubleArray",
    "boolean[]": "jsonToBooleanArray",
    "String[]": "jsonToStringArray",
    "int[][]": "jsonToIntMatrix",
    "String[][]": "jsonToStringMatrix",
}

# Normalized type -> native -> json::Value conversion helper (Java)
_JAVA_NATIVE_TO_JSON = {
    "int": "intToJson",
    "long": "longToJson",
    "double": "doubleToJson",
    "boolean": "booleanToJson",
    "String": "stringToJson",
    "int[]": "intArrayToJson",
    "long[]": "longArrayToJson",
    "double[]": "doubleArrayToJson",
    "boolean[]": "booleanArrayToJson",
    "String[]": "stringArrayToJson",
    "int[][]": "intMatrixToJson",
    "String[][]": "stringMatrixToJson",
}

# Normalized type -> Java native type spelling used in generated code
_JAVA_NATIVE_TYPES = {
    "int": "int",
    "long": "long",
    "double": "double",
    "boolean": "boolean",
    "String": "String",
    "int[]": "int[]",
    "long[]": "long[]",
    "double[]": "double[]",
    "boolean[]": "boolean[]",
    "String[]": "String[]",
    "int[][]": "int[][]",
    "String[][]": "String[][]",
}

# Java method modifiers that may prefix a return type in a signature
_JAVA_MODIFIERS = {
    "public", "private", "protected", "static", "final",
    "abstract", "synchronized", "native", "strictfp", "default",
}


def _normalize_java_type(t: str) -> str:
    """Normalize a Java type spelling to a canonical form.

    Removes whitespace and optional array dimension spaces so forms like
    'int []', 'int[ ]', 'String  []' collapse to 'int[]' / 'String[]'.
    Handles the fully-qualified 'java.lang.String' spelling.
    """
    t = t.strip()
    if t.startswith("java.lang."):
        t = t[len("java.lang."):]
    # Collapse all interior whitespace so 'int []' -> 'int[]'.
    t = "".join(t.split())
    return t


def _parse_java_signature(signature: Optional[str]):
    """Parse a Java function signature into
    (return_type, function_name, [(param_type, param_name), ...], is_static).

    Returns None if the signature cannot be parsed.
    Example: 'public int[] twoSum(int[] nums, int target)' ->
        ('int[]', 'twoSum', [('int[]', 'nums'), ('int', 'target')], False)
    """
    if not signature:
        return None
    s = signature.strip()
    if s.endswith(";"):
        s = s[:-1].strip()
    open_paren = s.find("(")
    close_paren = s.rfind(")")
    if open_paren == -1 or close_paren == -1 or close_paren < open_paren:
        return None

    prefix = s[:open_paren].strip()
    params_str = s[open_paren + 1:close_paren].strip()

    tokens = prefix.split()
    if len(tokens) < 2:
        return None

    # Trailing tokens like 'throws ...' are not part of the signature head.
    is_static = "static" in tokens

    # Peel modifiers off the front; the remainder before the function name is
    # the return type. Generic / templated returns stay intact as one token
    # group (List<Integer> etc.) and will be rejected by the type maps later.
    return_tokens = []
    fn_name = None
    i = 0
    while i < len(tokens):
        if tokens[i] in _JAVA_MODIFIERS:
            i += 1
            continue
        # return-type tokens run up to (but excluding) the final token when a
        # plain (possibly array) type is present.
        remaining = tokens[i:]
        if len(remaining) >= 2:
            return_tokens = remaining[:-1]
            fn_name = remaining[-1]
            break
        fn_name = remaining[-1]
        break

    if fn_name is None or fn_name in _JAVA_MODIFIERS:
        return None
    return_type = " ".join(return_tokens) if return_tokens else "void"

    params = []
    if params_str:
        for part in _split_top_level(params_str, ","):
            part = part.strip()
            if not part:
                continue
            # Drop annotations/varargs markers minimally: keep type + optional name.
            p_tokens = part.split()
            if len(p_tokens) == 1:
                # Type only, no parameter name (legal in abstract/interface decls).
                params.append((p_tokens[0], None))
            else:
                ptype = " ".join(p_tokens[:-1])
                pname = p_tokens[-1]
                params.append((ptype, pname))

    return return_type, fn_name, params, is_static


def _generate_java_marshal_helpers() -> str:
    """Return Java static helper methods that convert between JsonValue and
    native Java types (int/long/double/boolean/String plus their arrays and
    the supported 2D forms). Inserted inside the generated Main class."""
    return """
    // === JSON <-> Native Type Marshaling Helpers ===

    // --- Scalar: JsonValue -> native ---
    static int jsonToInt(JsonValue v) {
        if (v == null || v.type == JsonValue.Type.NUL) return 0;
        if (v.type == JsonValue.Type.NUM) return v.toInt();
        if (v.type == JsonValue.Type.STR) {
            try { return Integer.parseInt(v.str().trim()); } catch (Exception e) { return 0; }
        }
        if (v.type == JsonValue.Type.BOOL) return v.bool() ? 1 : 0;
        return 0;
    }
    static long jsonToLong(JsonValue v) {
        if (v == null || v.type == JsonValue.Type.NUL) return 0L;
        if (v.type == JsonValue.Type.NUM) return (long) v.toDouble();
        if (v.type == JsonValue.Type.STR) {
            try { return Long.parseLong(v.str().trim()); } catch (Exception e) { return 0L; }
        }
        if (v.type == JsonValue.Type.BOOL) return v.bool() ? 1L : 0L;
        return 0L;
    }
    static double jsonToDouble(JsonValue v) {
        if (v == null || v.type == JsonValue.Type.NUL) return 0.0;
        if (v.type == JsonValue.Type.NUM) return v.toDouble();
        if (v.type == JsonValue.Type.STR) {
            try { return Double.parseDouble(v.str().trim()); } catch (Exception e) { return 0.0; }
        }
        if (v.type == JsonValue.Type.BOOL) return v.bool() ? 1.0 : 0.0;
        return 0.0;
    }
    static boolean jsonToBoolean(JsonValue v) {
        if (v == null || v.type == JsonValue.Type.NUL) return false;
        if (v.type == JsonValue.Type.BOOL) return v.bool();
        if (v.type == JsonValue.Type.NUM) return v.toInt() != 0;
        if (v.type == JsonValue.Type.STR) return Boolean.parseBoolean(v.str().trim());
        return false;
    }
    static String jsonToString(JsonValue v) {
        if (v == null || v.type == JsonValue.Type.NUL) return "";
        if (v.type == JsonValue.Type.STR) return v.str();
        return JsonValue.stringify(v);
    }

    // --- 1D Array: JsonValue -> native array ---
    static int[] jsonToIntArray(JsonValue v) {
        if (v == null || v.type != JsonValue.Type.ARR) return new int[0];
        int[] r = new int[v.aval.size()];
        for (int i = 0; i < v.aval.size(); i++) r[i] = jsonToInt(v.aval.get(i));
        return r;
    }
    static long[] jsonToLongArray(JsonValue v) {
        if (v == null || v.type != JsonValue.Type.ARR) return new long[0];
        long[] r = new long[v.aval.size()];
        for (int i = 0; i < v.aval.size(); i++) r[i] = jsonToLong(v.aval.get(i));
        return r;
    }
    static double[] jsonToDoubleArray(JsonValue v) {
        if (v == null || v.type != JsonValue.Type.ARR) return new double[0];
        double[] r = new double[v.aval.size()];
        for (int i = 0; i < v.aval.size(); i++) r[i] = jsonToDouble(v.aval.get(i));
        return r;
    }
    static boolean[] jsonToBooleanArray(JsonValue v) {
        if (v == null || v.type != JsonValue.Type.ARR) return new boolean[0];
        boolean[] r = new boolean[v.aval.size()];
        for (int i = 0; i < v.aval.size(); i++) r[i] = jsonToBoolean(v.aval.get(i));
        return r;
    }
    static String[] jsonToStringArray(JsonValue v) {
        if (v == null || v.type != JsonValue.Type.ARR) return new String[0];
        String[] r = new String[v.aval.size()];
        for (int i = 0; i < v.aval.size(); i++) r[i] = jsonToString(v.aval.get(i));
        return r;
    }

    // --- 2D Array: JsonValue -> native matrix ---
    static int[][] jsonToIntMatrix(JsonValue v) {
        if (v == null || v.type != JsonValue.Type.ARR) return new int[0][0];
        int[][] r = new int[v.aval.size()][];
        for (int i = 0; i < v.aval.size(); i++) r[i] = jsonToIntArray(v.aval.get(i));
        return r;
    }
    static String[][] jsonToStringMatrix(JsonValue v) {
        if (v == null || v.type != JsonValue.Type.ARR) return new String[0][0];
        String[][] r = new String[v.aval.size()][];
        for (int i = 0; i < v.aval.size(); i++) r[i] = jsonToStringArray(v.aval.get(i));
        return r;
    }

    // --- Scalar: native -> JsonValue ---
    static JsonValue intToJson(int v) { return new JsonValue(v); }
    static JsonValue longToJson(long v) { return new JsonValue((double) v); }
    static JsonValue doubleToJson(double v) { return new JsonValue(v); }
    static JsonValue booleanToJson(boolean v) { return new JsonValue(v); }
    static JsonValue stringToJson(String v) { return v == null ? new JsonValue() : new JsonValue(v); }

    // --- 1D Array: native array -> JsonValue ---
    static JsonValue intArrayToJson(int[] v) {
        JsonValue r = new JsonValue(); r.type = JsonValue.Type.ARR;
        if (v != null) for (int i = 0; i < v.length; i++) r.aval.add(new JsonValue(v[i]));
        return r;
    }
    static JsonValue longArrayToJson(long[] v) {
        JsonValue r = new JsonValue(); r.type = JsonValue.Type.ARR;
        if (v != null) for (int i = 0; i < v.length; i++) r.aval.add(new JsonValue((double) v[i]));
        return r;
    }
    static JsonValue doubleArrayToJson(double[] v) {
        JsonValue r = new JsonValue(); r.type = JsonValue.Type.ARR;
        if (v != null) for (int i = 0; i < v.length; i++) r.aval.add(new JsonValue(v[i]));
        return r;
    }
    static JsonValue booleanArrayToJson(boolean[] v) {
        JsonValue r = new JsonValue(); r.type = JsonValue.Type.ARR;
        if (v != null) for (int i = 0; i < v.length; i++) r.aval.add(new JsonValue(v[i]));
        return r;
    }
    static JsonValue stringArrayToJson(String[] v) {
        JsonValue r = new JsonValue(); r.type = JsonValue.Type.ARR;
        if (v != null) for (int i = 0; i < v.length; i++) r.aval.add(v[i] == null ? new JsonValue() : new JsonValue(v[i]));
        return r;
    }

    // --- 2D Array: native matrix -> JsonValue ---
    static JsonValue intMatrixToJson(int[][] v) {
        JsonValue r = new JsonValue(); r.type = JsonValue.Type.ARR;
        if (v != null) for (int i = 0; i < v.length; i++) r.aval.add(intArrayToJson(v[i]));
        return r;
    }
    static JsonValue stringMatrixToJson(String[][] v) {
        JsonValue r = new JsonValue(); r.type = JsonValue.Type.ARR;
        if (v != null) for (int i = 0; i < v.length; i++) r.aval.add(stringArrayToJson(v[i]));
        return r;
    }
"""


def _matching_brace(text: str, open_pos: int) -> int:
    """Return the index of the '}' matching the '{' at open_pos, or -1."""
    depth = 0
    i = open_pos
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _find_java_class_for_function(candidate_code: str, function_name: str):
    """Best-effort detection of the Java class that declares `function_name`.

    Returns the class name or None. Used only when the caller did not supply
    class_name for a typed Java signature (static-style free functions).
    The class whose body actually CONTAINS the declaration wins, so nested
    helper classes declared before the method are not mistaken for the owner.
    """
    matches = list(re.finditer(r"\b" + re.escape(function_name) + r"\s*\(", candidate_code))
    if not matches:
        return None
    decl_pos = matches[0].start()

    # Collect every class declaration with its body range [open, close].
    candidates = []
    for m in re.finditer(r"\bclass\s+([A-Za-z_$][\w$]*)", candidate_code):
        name = m.group(1)
        brace = candidate_code.find("{", m.end())
        if brace == -1:
            continue
        close = _matching_brace(candidate_code, brace)
        if close == -1:
            continue
        candidates.append((brace, close, name))

    # The innermost class whose body contains the declaration is the owner.
    best = None
    best_open = -1
    for open_pos, close_pos, name in candidates:
        if open_pos < decl_pos < close_pos and open_pos > best_open:
            best = name
            best_open = open_pos
    return best


def generate_java_harness(
    candidate_code: str,
    function_name: str,
    class_name: Optional[str],
    test_arguments: List[List[Any]],
    test_expected: List[Any],
    function_signature: Optional[str] = None,
) -> str:
    """
    Generate a Java program that:
    1. Includes a minimal JSON library
    2. Embeds test data
    3. Defines the candidate's solution
    4. Calls the function with each test case
    5. Compares results and outputs JSON array of pass/fail
    """
    # Build test data as JSON
    test_data = json.dumps(
        [{"args": args, "expected": exp} for args, exp in zip(test_arguments, test_expected)],
        ensure_ascii=False,
    )

    # Escape for Java string literal
    test_data_escaped = test_data.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    # Parse + validate the signature when provided. When a signature IS given
    # it is the authoritative native-typed contract: unsupported/unparseable/
    # mismatched signatures fail loudly instead of passing raw JsonValue into a
    # native candidate method. When NO signature is provided (legacy problems /
    # callers) the original raw JsonValue invocation is preserved unchanged.
    parsed_sig = _parse_java_signature(function_signature)
    sig_params = []
    sig_return = None
    is_static = False
    if function_signature and function_signature.strip():
        if parsed_sig is None:
            raise ValueError(
                f"Unsupported Java function signature {function_signature!r}: "
                "could not be parsed into a return type, function name and "
                "parameter list."
            )
        sig_return, sig_fn_name, sig_params, is_static = parsed_sig
        if sig_fn_name != function_name:
            raise ValueError(
                f"Unsupported Java function signature {function_signature!r}: "
                f"function name {sig_fn_name!r} does not match the requested "
                f"function {function_name!r}."
            )
        normalized_params = [_normalize_java_type(p[0]) for p in sig_params]
        normalized_return = _normalize_java_type(sig_return)
        for i, pt in enumerate([p[0] for p in sig_params]):
            if normalized_params[i] not in _JAVA_JSON_TO_NATIVE:
                raise ValueError(
                    f"Unsupported Java parameter type {pt!r} (normalized to "
                    f"{normalized_params[i]!r}) at parameter {i} of signature "
                    f"{function_signature!r}. Supported parameter types: "
                    f"{', '.join(sorted(_JAVA_JSON_TO_NATIVE))}"
                )
        if normalized_return not in _JAVA_NATIVE_TO_JSON:
            raise ValueError(
                f"Unsupported Java return type {sig_return!r} (normalized to "
                f"{normalized_return!r}) in signature {function_signature!r}. "
                f"Supported return types: "
                f"{', '.join(sorted(_JAVA_NATIVE_TO_JSON))}"
            )

    # The marshal helpers are only needed on the typed (signature-driven)
    # path; the legacy raw-JsonValue path omits them so legacy output is
    # preserved byte-for-byte. When present they are static methods inside
    # Main so the generated calls can reference them unqualified.
    emit_helpers = parsed_sig is not None

    lines = [
        "import java.util.*;",
        "",
        "// === Minimal JSON Library ===",
        _JAVA_JSON_LIB,
        "",
        "// === Candidate Solution ===",
        candidate_code,
        "",
        "// === Test Harness ===",
        "public class Main {",
    ]
    if emit_helpers:
        lines.append(_generate_java_marshal_helpers())
    lines.extend([
        f'    static String TEST_DATA_JSON = "{test_data_escaped}";',
        "",
        "    public static void main(String[] args) {",
        "        JsonValue test_data = JsonValue.parse(TEST_DATA_JSON);",
        "        JsonValue results = new JsonValue();",
        "        results.type = JsonValue.Type.ARR;",
        "",
        "        for (int i = 0; i < test_data.aval.size(); i++) {",
        "            JsonValue tc = test_data.aval.get(i);",
        '            JsonValue tcArgs = tc.get("args");',
        '            JsonValue expected = tc.get("expected");',
        "",
        "            try {",
    ])

    # Generate the function call.
    typed_call = parsed_sig is not None
    if typed_call:
        # Resolve the class the method lives on: explicit class_name wins;
        # otherwise best-effort detect it from the candidate code (used for
        # static-style free functions). Instance methods are always invoked on
        # a fresh instance, which also compiles for static candidate methods.
        invoke_class = class_name
        if not invoke_class:
            invoke_class = _find_java_class_for_function(candidate_code, function_name)
        if not invoke_class:
            raise ValueError(
                f"Cannot determine the Java class owning {function_name!r}: "
                "provide class_name or declare the method inside a class in the "
                "candidate code."
            )

        for i, pt in enumerate(normalized_params):
            native_type = _JAVA_NATIVE_TYPES[pt]
            conv = _JAVA_JSON_TO_NATIVE[pt]
            lines.append(f"                {native_type} _arg{i} = {conv}(tcArgs.get({i}));")

        native_return = _JAVA_NATIVE_TYPES[normalized_return]
        args_call = ", ".join(f"_arg{i}" for i in range(len(sig_params)))
        if invoke_class and class_name:
            # class_name supplied -> always instance call (works for instance
            # and static candidate methods).
            lines.append(f"                {class_name} _obj = new {class_name}();")
            lines.append(
                f"                {native_return} _result_native = _obj.{function_name}({args_call});"
            )
        elif is_static:
            lines.append(
                f"                {native_return} _result_native = {invoke_class}.{function_name}({args_call});"
            )
        else:
            lines.append(f"                {invoke_class} _obj = new {invoke_class}();")
            lines.append(
                f"                {native_return} _result_native = _obj.{function_name}({args_call});"
            )
        lines.append(f"                JsonValue _result = {_JAVA_NATIVE_TO_JSON[normalized_return]}(_result_native);")
    elif class_name:
        lines.append(f"                {class_name} _obj = new {class_name}();")
        if len(test_arguments) > 0 and len(test_arguments[0]) > 0:
            # For single arg, pass directly; for multiple, pass as array elements
            if len(test_arguments[0]) == 1:
                arg_call = "tcArgs"
            else:
                arg_call = ", ".join(f"tcArgs.get({i})" for i in range(len(test_arguments[0])))
        else:
            arg_call = ""
        lines.append(f"                JsonValue _result = _obj.{function_name}({arg_call});")
    else:
        if len(test_arguments) > 0 and len(test_arguments[0]) == 1:
            arg_call = "tcArgs"
        elif len(test_arguments) > 0 and len(test_arguments[0]) > 1:
            arg_call = ", ".join(f"tcArgs.get({i})" for i in range(len(test_arguments[0])))
        else:
            arg_call = ""
        lines.append(f"                JsonValue _result = {function_name}({arg_call});")

    lines.extend([
        '                boolean _passed = JsonValue.stringify(_result).equals(JsonValue.stringify(expected));',
        '                JsonValue _r = new JsonValue(); _r.type = JsonValue.Type.OBJ;',
        '                _r.keys.add("passed"); _r.oval.add(new JsonValue(_passed));',
        '                _r.keys.add("actual"); _r.oval.add(_result);',
        '                _r.keys.add("expected"); _r.oval.add(expected);',
        "                results.aval.add(_r);",
        "            } catch (Exception e) {",
        '                JsonValue _r = new JsonValue(); _r.type = JsonValue.Type.OBJ;',
        '                _r.keys.add("passed"); _r.oval.add(new JsonValue(false));',
        '                _r.keys.add("error"); _r.oval.add(new JsonValue(e.toString()));',
        '                _r.keys.add("expected"); _r.oval.add(expected);',
        "                results.aval.add(_r);",
        "            }",
        "        }",
        "",
        "        System.out.println(JsonValue.stringify(results));",
        "    }",
        "}",
    ])

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
    function_signature: Optional[str] = None,
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
            test_arguments, test_expected, function_signature,
        )
    elif language == "cpp":
        return generate_cpp_harness(
            candidate_code, function_name, class_name,
            test_arguments, test_expected, function_signature,
        )
    elif language == "java":
        return generate_java_harness(
            candidate_code, function_name, class_name,
            test_arguments, test_expected, function_signature,
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
