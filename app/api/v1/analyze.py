from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.schemas.jobs import JobSearchResponse
from app.schemas.resume import ParseResponse
from app.schemas.roles import RoleInferenceResponse
from app.services.job_providers.base import ProviderError
from app.services.job_providers.factory import get_provider
from app.services.job_search import search_jobs
from app.services.pdf_extract import ExtractionError
from app.services.resume_service import parse_upload
from app.services.role_inference import infer_roles

router = APIRouter(prefix="/analyze", tags=["analyze"])


class AnalyzeResponse(BaseModel):
    parse: ParseResponse
    roles: RoleInferenceResponse
    jobs: JobSearchResponse | None = None


@router.post("", response_model=AnalyzeResponse)
async def analyze(file: UploadFile = File(...),
                  include_jobs: bool = Query(False, description="Also search open jobs for the inferred roles"),
                  location: str | None = Query(None, description="e.g. Bengaluru, Dehradun, Remote")):
    """Upload a resume -> parsed JSON + ranked target roles (+ matching open jobs if include_jobs)."""
    data = await file.read()
    try:
        parsed = parse_upload(file.filename or "", data)
    except ExtractionError as e:
        raise HTTPException(422, str(e))
    roles = infer_roles(parsed.resume)
    jobs = None
    if include_jobs:
        try:
            jobs = await search_jobs(parsed.resume, get_provider(), location=location)
        except ProviderError as e:
            raise HTTPException(503, str(e))
    return AnalyzeResponse(parse=parsed, roles=roles, jobs=jobs)
