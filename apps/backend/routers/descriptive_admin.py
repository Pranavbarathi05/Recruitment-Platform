from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from core.auth import require_admin, AuthUser
from core.supabase import supabase_client
from schemas.assessment import DescriptiveCreate, DescriptiveUpdate
import uuid
import os

router = APIRouter(prefix="/admin/descriptive-questions", tags=["Admin Descriptive"])

ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def _enrich_domain_names(questions: list) -> list:
    """Attach domain names to questions via their domain_ids array."""
    all_ids = set()
    for q in questions:
        all_ids.update(q.get("domain_ids") or [])
    if not all_ids:
        return questions

    domains_resp = (
        supabase_client.table("domains")
        .select("id, name")
        .in_("id", list(all_ids))
        .execute()
    )
    domain_map = {d["id"]: d["name"] for d in (domains_resp.data or [])}
    for q in questions:
        q["domain_names"] = [domain_map.get(did, "") for did in (q.get("domain_ids") or [])]
    return questions


@router.get("")
def list_descriptive_questions(
    admin: AuthUser = Depends(require_admin),
):
    """List all descriptive questions. Admin only."""
    try:
        response = (
            supabase_client.table("descriptive_questions")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return _enrich_domain_names(response.data or [])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{question_id}")
def get_descriptive_question(
    question_id: str,
    admin: AuthUser = Depends(require_admin),
):
    """Get a single descriptive question. Admin only."""
    try:
        resp = (
            supabase_client.table("descriptive_questions")
            .select("*")
            .eq("id", question_id)
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Descriptive question not found")
        q = resp.data[0]
        _enrich_domain_names([q])
        return q
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", status_code=201)
def create_descriptive_question(
    payload: DescriptiveCreate,
    admin: AuthUser = Depends(require_admin),
):
    """Create a descriptive question. Admin only."""
    try:
        # Validate domain_ids exist
        if payload.domain_ids:
            domains_resp = (
                supabase_client.table("domains")
                .select("id")
                .in_("id", payload.domain_ids)
                .execute()
            )
            if not domains_resp.data or len(domains_resp.data) != len(payload.domain_ids):
                raise HTTPException(status_code=400, detail="One or more domain IDs not found")

        result = supabase_client.table("descriptive_questions").insert({
            "question_text": payload.question_text,
            "image_url": payload.image_url,
            "word_limit": payload.word_limit,
            "domain_ids": payload.domain_ids,
            "is_active": payload.is_active,
        }).execute()

        return result.data[0] if result.data else {"status": "created"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{question_id}")
def update_descriptive_question(
    question_id: str,
    payload: DescriptiveUpdate,
    admin: AuthUser = Depends(require_admin),
):
    """Update a descriptive question. Admin only."""
    try:
        existing = (
            supabase_client.table("descriptive_questions")
            .select("id")
            .eq("id", question_id)
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Descriptive question not found")

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        # Validate domain_ids if provided
        if "domain_ids" in updates and updates["domain_ids"]:
            domains_resp = (
                supabase_client.table("domains")
                .select("id")
                .in_("id", updates["domain_ids"])
                .execute()
            )
            if not domains_resp.data or len(domains_resp.data) != len(updates["domain_ids"]):
                raise HTTPException(status_code=400, detail="One or more domain IDs not found")

        result = (
            supabase_client.table("descriptive_questions")
            .update(updates)
            .eq("id", question_id)
            .execute()
        )
        return result.data[0] if result.data else {"status": "updated"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{question_id}")
def delete_descriptive_question(
    question_id: str,
    admin: AuthUser = Depends(require_admin),
):
    """Delete a descriptive question. Admin only."""
    try:
        existing = (
            supabase_client.table("descriptive_questions")
            .select("id")
            .eq("id", question_id)
            .execute()
        )
        if not existing.data:
            raise HTTPException(status_code=404, detail="Descriptive question not found")

        # Check if referenced by any assessment attempt
        attempts = (
            supabase_client.table("assessment_attempts")
            .select("id")
            .contains("selected_descriptive_question_ids", [question_id])
            .limit(1)
            .execute()
        )
        if attempts.data:
            raise HTTPException(
                status_code=409,
                detail="Cannot delete: question is referenced by existing attempts. Use deactivation instead.",
            )

        supabase_client.table("descriptive_questions").delete().eq("id", question_id).execute()
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    admin: AuthUser = Depends(require_admin),
):
    """Upload an image for a descriptive question. Admin only.

    Stores to Supabase Storage bucket 'question-images' and returns the
    public URL that can be stored in the question record.
    """
    try:
        # Validate content type
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type: {file.content_type}. Allowed: PNG, JPEG, WebP, GIF",
            )

        # Read and validate size
        contents = await file.read()
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {len(contents)} bytes. Maximum: {MAX_FILE_SIZE} bytes",
            )

        # Generate unique path
        ext = file.filename.rsplit(".", 1)[-1] if "." in (file.filename or "") else "png"
        path = f"descriptive/{uuid.uuid4().hex}.{ext}"

        # Upload to Supabase Storage
        supabase_client.storage.from_("question-images").upload(
            path, contents, {"content-type": file.content_type}
        )

        # Get public URL
        public_url = supabase_client.storage.from_("question-images").get_public_url(path)

        return {"image_url": public_url, "path": path}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
