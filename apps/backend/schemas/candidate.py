from pydantic import BaseModel, EmailStr


class CandidateCreate(BaseModel):
    candidate_id: int
    full_name: str
    email: EmailStr
    usn: str
    semester: int
    branch: str
