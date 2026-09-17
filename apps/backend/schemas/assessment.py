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


# ---------------------------------------------------------------------------
# Assessment configuration
# ---------------------------------------------------------------------------

class AssessmentConfigUpdate(BaseModel):
    """Schema for admin updating assessment configuration.

    Only the settings that still drive the runtime are exposed here:

      * ``duration_minutes``    — the base attempt duration the planner adds
                                  enabled hands-on time to
      * ``coding_problem_count`` — the GLOBAL DSA/coding pool size (coding is
                                  domain-independent)
      * ``name`` / ``is_active`` — config row management

    The pre-modular knobs are deliberately NOT accepted any more. None of them
    is read when a new attempt is planned:

      total_questions            -> assessment_program.mcq_total splits the
                                    technical MCQ total across selected domains
      max_domains                -> assessment_program.max_domains
      descriptive_question_count -> organizational only, now
                                    assessment_module_config.descriptive_count
      hands_on_question_count    -> assessment_module_config (hands_on_count /
                                    hands_on_additional_minutes)

    The columns still exist in the database for historical compatibility; the
    admin API simply no longer offers them.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    coding_problem_count: Optional[int] = Field(None, ge=0)
    duration_minutes: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Descriptive questions
# ---------------------------------------------------------------------------

class DescriptiveCreate(BaseModel):
    question_text: str = Field(..., min_length=1)
    image_url: Optional[str] = None
    word_limit: Optional[int] = Field(None, gt=0)
    domain_ids: list[str] = Field(default_factory=list)
    is_active: bool = True


class DescriptiveUpdate(BaseModel):
    question_text: Optional[str] = Field(None, min_length=1)
    image_url: Optional[str] = None
    word_limit: Optional[int] = Field(None, gt=0)
    domain_ids: Optional[list[str]] = None
    is_active: Optional[bool] = None


class DescriptiveAnswerSaveRequest(BaseModel):
    question_id: str
    answer_text: str = Field(default="")


# ---------------------------------------------------------------------------
# Hands-On challenges (SQL injection micro-CTF)
# ---------------------------------------------------------------------------

# Fixed challenge-type registry — mirrors the DB CHECK constraint in
# migration 012. There is deliberately no arbitrary-execution type.
HANDS_ON_CHALLENGE_TYPES = ["sql_injection_employee_portal"]
HANDS_ON_DIFFICULTIES = ["easy", "medium", "hard"]


class HandsOnCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    domain_ids: list[str] = Field(default_factory=list)
    challenge_type: str = Field(default="sql_injection_employee_portal")
    difficulty: str = Field(default="medium")
    points: int = Field(default=100, ge=0, le=1000)
    challenge_url: str = Field(..., min_length=1)
    expected_flag: str = Field(..., min_length=1, max_length=500)
    is_active: bool = True

    def model_post_init(self, __context):
        if self.challenge_type not in HANDS_ON_CHALLENGE_TYPES:
            raise ValueError(f"challenge_type must be one of {HANDS_ON_CHALLENGE_TYPES}")
        if self.difficulty not in HANDS_ON_DIFFICULTIES:
            raise ValueError(f"difficulty must be one of {HANDS_ON_DIFFICULTIES}")


class HandsOnUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, min_length=1)
    domain_ids: Optional[list[str]] = None
    challenge_type: Optional[str] = None
    difficulty: Optional[str] = None
    points: Optional[int] = Field(None, ge=0, le=1000)
    challenge_url: Optional[str] = Field(None, min_length=1)
    expected_flag: Optional[str] = Field(None, min_length=1, max_length=500)
    is_active: Optional[bool] = None

    def model_post_init(self, __context):
        if self.challenge_type is not None and self.challenge_type not in HANDS_ON_CHALLENGE_TYPES:
            raise ValueError(f"challenge_type must be one of {HANDS_ON_CHALLENGE_TYPES}")
        if self.difficulty is not None and self.difficulty not in HANDS_ON_DIFFICULTIES:
            raise ValueError(f"difficulty must be one of {HANDS_ON_DIFFICULTIES}")


class HandsOnSubmitRequest(BaseModel):
    """Candidate submission for a Hands-On challenge.

    submitted_input (the SQL payload) is stored verbatim as evidence and is
    never parsed, executed or verified. submitted_flag is the only field
    checked server-side.
    """
    question_id: str
    submitted_input: str = Field(default="", max_length=20_000)
    submitted_flag: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# Admin remark (private note on an assessment submission)
# ---------------------------------------------------------------------------

class AdminRemarkUpdate(BaseModel):
    """Private admin remark on an assessment attempt.

    Nullable — an empty string is normalized to None by the router so the
    remark can be cleared through the same PUT endpoint.
    """
    admin_remark: Optional[str] = Field(None, max_length=10_000)


# NOTE: ``AssessmentConfigUpdateHandsOn`` used to subclass
# ``AssessmentConfigUpdate`` to add ``hands_on_question_count``. That knob is
# retired (hands-on quantity and additional minutes now live in
# ``assessment_module_config``, per domain and tier), so the subclass had no
# fields left and was deleted. The endpoint uses ``AssessmentConfigUpdate``.


# ---------------------------------------------------------------------------
# Assessment module configuration (domain x tier module counts)
# ---------------------------------------------------------------------------

VALID_APPLIES_TO = ["junior", "senior", "organizational"]

# Which applies_to values are allowed for each assessment_scope.
SCOPE_ALLOWED_APPLIES_TO = {
    "technical": ["junior", "senior"],
    "organizational": ["organizational"],
}

# Maps tier/applies_to to the semester used for MCQ pool validation.
APPLIES_TO_VALIDATION_SEMESTER = {
    "junior": 3,
    "senior": 5,
    "organizational": 1,
}


class ModuleConfigUpdate(BaseModel):
    """Create or update a module configuration for a domain + tier.

    Upsert semantics: if a row already exists for (domain_id, applies_to),
    it is updated. Otherwise a new row is created.
    """
    applies_to: str = Field(..., description="junior | senior | organizational")
    mcq_count: int = Field(..., ge=0)
    descriptive_count: int = Field(..., ge=0)
    hands_on_enabled: bool = False
    hands_on_count: int = Field(..., ge=0)
    hands_on_additional_minutes: int = Field(0, ge=0)
    notes: Optional[str] = Field(None, max_length=2000)

    def model_post_init(self, __context):
        if self.applies_to not in VALID_APPLIES_TO:
            raise ValueError(f"applies_to must be one of {VALID_APPLIES_TO}")
        if not self.hands_on_enabled:
            if self.hands_on_count != 0:
                raise ValueError(
                    "hands_on_count must be 0 when hands_on_enabled is false"
                )
            if self.hands_on_additional_minutes != 0:
                raise ValueError(
                    "hands_on_additional_minutes must be 0 when "
                    "hands_on_enabled is false"
                )
