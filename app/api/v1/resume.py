from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas.resume import ParseResponse
from app.services.pdf_extract import ExtractionError
from app.services.resume_service import parse_upload

router = APIRouter(prefix="/resume", tags=["resume"])
MAX_BYTES = 5 * 1024 * 1024


@router.post("/parse", response_model=ParseResponse)
async def parse_resume_file(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 5 MB)")
    try:
        return parse_upload(file.filename or "", data)
    except ExtractionError as e:
        raise HTTPException(422, str(e))


@router.post("/debug")
async def debug_extraction(file: UploadFile = File(...)):
    """Dev helper: shows the raw extracted text, detected sections and hyperlinks,
    so you can see WHY a parse went wrong."""
    from app.services.pdf_extract import extract_text
    from app.services.rule_parser import split_sections
    data = await file.read()
    try:
        ex = extract_text(file.filename or "", data)
    except ExtractionError as e:
        raise HTTPException(422, str(e))
    secs = split_sections(ex.text)
    return {"links": ex.links, "warnings": ex.warnings,
            "sections_found": {k: v[:200] for k, v in secs.items()}, "text": ex.text}
