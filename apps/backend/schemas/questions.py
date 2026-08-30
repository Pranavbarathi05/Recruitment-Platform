from pydantic import BaseModel


class QuestionResponse(BaseModel):
    id: int
    title: str
    description: str
    base_code: str
