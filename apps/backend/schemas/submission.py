from pydantic import BaseModel, Field


class Submission(BaseModel):
    attempt_id: str
    code: str = Field(..., description="The users code submission")
    language: str = Field(..., description="Programming language selected by the user")


class CodeSubmissionRequest(BaseModel):
    candidate_id: str
    question_id: str
    language: str
    code_body: str
