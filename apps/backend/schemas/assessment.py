from pydantic import BaseModel, Field
from typing import Optional

# Valid semesters — matches the DB constraint CHECK (semester IN (1, 3, 5, 7))
VALID_SEMESTERS = [1, 3, 5, 7]

# Semester display labels
SEMESTER_LABELS = {
    1: "1st Semester",
    3: "3rd Semester",
    5: "5th Semester",
    7: "7th Semester",
}


class DomainCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    slug: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    duration_minutes: int = Field(default=20, ge=1, le=120)
    is_active: bool = True


class DomainUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    slug: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    duration_minutes: Optional[int] = Field(None, ge=1, le=120)
    is_active: Optional[bool] = None


class MCQCreate(BaseModel):
    domain_id: str
    semester: int = Field(..., description="Semester: 1, 3, 5, or 7")
    question_text: str = Field(..., min_length=1)
    option_a: str = Field(..., min_length=1)
    option_b: str = Field(..., min_length=1)
    option_c: str = Field(..., min_length=1)
    option_d: str = Field(..., min_length=1)
    correct_option: str = Field(..., pattern=r'^[ABCD]$')
    explanation: Optional[str] = None
    is_active: bool = True

    def model_post_init(self, __context):
        if self.semester not in VALID_SEMESTERS:
            raise ValueError(f"Semester must be one of {VALID_SEMESTERS}")


class MCQUpdate(BaseModel):
    semester: Optional[int] = Field(None, description="Semester: 1, 3, 5, or 7")
    question_text: Optional[str] = Field(None, min_length=1)
    option_a: Optional[str] = Field(None, min_length=1)
    option_b: Optional[str] = Field(None, min_length=1)
    option_c: Optional[str] = Field(None, min_length=1)
    option_d: Optional[str] = Field(None, min_length=1)
    correct_option: Optional[str] = Field(None, pattern=r'^[ABCD]$')
    explanation: Optional[str] = None
    is_active: Optional[bool] = None

    def model_post_init(self, __context):
        if self.semester is not None and self.semester not in VALID_SEMESTERS:
            raise ValueError(f"Semester must be one of {VALID_SEMESTERS}")


class AssessmentStartRequest(BaseModel):
    domain_ids: list[str] = Field(..., min_length=1, max_length=2)


class AnswerSaveRequest(BaseModel):
    question_id: str
    selected_option: str = Field(..., pattern=r'^[ABCD]$')
