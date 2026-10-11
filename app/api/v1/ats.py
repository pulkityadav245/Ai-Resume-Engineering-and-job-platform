from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.schemas.ats import ATSReport
from app.services.ats import ats_check
from app.services.pdf_extract import ExtractionError, extract_text
from app.services.resume_service import parse_upload

router = APIRouter(prefix="/ats", tags=["ats"])
MAX_BYTES = 5 * 1024 * 1024


def _run(filename: str, data: bytes, jd_text: str | None) -> ATSReport:
    ex = extract_text(filename, data)
    parsed = parse_upload(filename, data, use_llm=False)      # deterministic parse: the checker must be reproducible
    return ats_check(ex.text, parsed.resume, pages=ex.pages, warnings=ex.warnings, jd_text=jd_text, layout=ex.layout)


@router.post("/check", response_model=ATSReport)
async def check(file: UploadFile = File(...), jd_text: str | None = Form(None)):
    """Upload a resume (optionally with a job description) -> ATS-readiness score with per-check fixes."""
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 5 MB)")
    try:
        return await run_in_threadpool(_run, file.filename or "", data, jd_text)
    except ExtractionError as e:
        raise HTTPException(422, str(e))
