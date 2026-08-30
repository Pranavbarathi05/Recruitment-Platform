from fastapi import APIRouter, HTTPException, status, Depends
from schemas.submission import Submission, CodeSubmissionRequest
from services.evaluator import evaluate_code
from core.auth import get_current_user, AuthUser

router = APIRouter(tags=["Submission"], prefix="/submission")


@router.post("/", status_code=202)
async def submit_code(
    submission: Submission,
    current_user: AuthUser = Depends(get_current_user),
):
    """
    Receive code submission — requires authentication.
    The authenticated user identity comes from the JWT, not the request body.
    """
    try:
        result = evaluate_code(
            attempt_id=submission.attempt_id,
            code=submission.code,
            language=submission.language,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/code", status_code=status.HTTP_202_ACCEPTED)
async def receive_code_submission(
    payload: CodeSubmissionRequest,
    current_user: AuthUser = Depends(get_current_user),
):
    """
    V1 endpoint:
    - Receives code submission
    - Does NOT evaluate code
    - Uses authenticated user identity from JWT (not candidate_id from body)
    """
    print(
        f"Code received from {current_user.id} "
        f"for question {payload.question_id}"
    )

    return {"message": "Submission Received"}
