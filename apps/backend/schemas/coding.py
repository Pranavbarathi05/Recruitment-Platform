from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any, List
import json


# ============================================================
# Supported languages
# ============================================================

VALID_CODING_LANGUAGES = ["python3", "cpp", "java"]
VALID_DIFFICULTIES = ["easy", "medium", "hard"]


# ============================================================
# Coding Problem Schemas
# ============================================================

class CodingProblemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    slug: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1)
    difficulty: str = Field(default="medium")
    constraints: Optional[str] = None
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    explanation: Optional[str] = None
    starter_code: Optional[dict] = None
    supported_languages: list[str] = Field(default=["python3", "cpp", "java"])
    time_limit_ms: int = Field(default=2000, gt=0, le=30000)
    memory_limit_mb: int = Field(default=256, gt=0, le=1024)
    points: int = Field(default=10, gt=0, le=100)
    is_active: bool = True
    # Function-based model fields
    function_name: str = Field(default="solve", min_length=1, max_length=200)
    class_name: Optional[str] = Field(default=None, max_length=200)
    function_signature: Optional[str] = None

    def model_post_init(self, __context):
        if self.difficulty not in VALID_DIFFICULTIES:
            raise ValueError(f"difficulty must be one of {VALID_DIFFICULTIES}")
        for lang in self.supported_languages:
            if lang not in VALID_CODING_LANGUAGES:
                raise ValueError(
                    f"Unsupported language '{lang}'. Must be one of {VALID_CODING_LANGUAGES}"
                )


class CodingProblemUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    description: Optional[str] = Field(None, min_length=1)
    difficulty: Optional[str] = None
    constraints: Optional[str] = None
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    explanation: Optional[str] = None
    starter_code: Optional[dict] = None
    supported_languages: Optional[list[str]] = None
    time_limit_ms: Optional[int] = Field(None, gt=0, le=30000)
    memory_limit_mb: Optional[int] = Field(None, gt=0, le=1024)
    points: Optional[int] = Field(None, gt=0, le=100)
    is_active: Optional[bool] = None
    # Function-based model fields
    function_name: Optional[str] = Field(None, min_length=1, max_length=200)
    class_name: Optional[str] = Field(default=None, max_length=200)
    function_signature: Optional[str] = None

    def model_post_init(self, __context):
        if self.difficulty is not None and self.difficulty not in VALID_DIFFICULTIES:
            raise ValueError(f"difficulty must be one of {VALID_DIFFICULTIES}")
        if self.supported_languages is not None:
            for lang in self.supported_languages:
                if lang not in VALID_CODING_LANGUAGES:
                    raise ValueError(
                        f"Unsupported language '{lang}'. Must be one of {VALID_CODING_LANGUAGES}"
                    )


# ============================================================
# Test Case Schemas
# ============================================================

class CodingTestCaseCreate(BaseModel):
    # Function-based model: arguments is a JSONB array
    arguments: List[Any] = Field(..., min_length=1, description="Function arguments as a JSON array")
    expected_output: Any = Field(..., description="Expected return value as JSON")
    is_public: bool = False
    points: int = Field(default=1, gt=0, le=10)
    ordering: int = Field(default=0, ge=0)
    # Legacy fields (optional for backward compatibility)
    input: Optional[str] = None
    legacy_expected_output: Optional[str] = None

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, v):
        if not isinstance(v, list):
            raise ValueError("arguments must be a JSON array")
        return v


class CodingTestCaseUpdate(BaseModel):
    arguments: Optional[List[Any]] = Field(None, description="Function arguments as a JSON array")
    expected_output: Optional[Any] = Field(None, description="Expected return value as JSON")
    is_public: Optional[bool] = None
    points: Optional[int] = Field(None, gt=0, le=10)
    ordering: Optional[int] = Field(None, ge=0)
    input: Optional[str] = None
    legacy_expected_output: Optional[str] = None


class CodingBulkTestUpload(BaseModel):
    """Bulk upload multiple test cases at once."""
    test_cases: List[CodingTestCaseCreate] = Field(..., min_length=1, max_length=100)


# ============================================================
# Submission Schemas
# ============================================================

class CodingSubmitRequest(BaseModel):
    problem_id: str
    language: str = Field(..., min_length=1)
    source_code: str = Field(..., min_length=1)

    def model_post_init(self, __context):
        if self.language not in VALID_CODING_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{self.language}'. Must be one of {VALID_CODING_LANGUAGES}"
            )


class CodingDraftSaveRequest(BaseModel):
    problem_id: str
    language: str = Field(..., min_length=1)
    source_code: str

    def model_post_init(self, __context):
        if self.language not in VALID_CODING_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{self.language}'. Must be one of {VALID_CODING_LANGUAGES}"
            )


class CodingRunRequest(BaseModel):
    problem_id: str
    language: str = Field(..., min_length=1)
    source_code: str = Field(..., min_length=1)

    def model_post_init(self, __context):
        if self.language not in VALID_CODING_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{self.language}'. Must be one of {VALID_CODING_LANGUAGES}"
            )
