from fastapi import APIRouter, HTTPException

from app.schemas.jobs import JobSearchRequest, JobSearchResponse
from app.services.job_providers.base import ProviderError
from app.services.job_providers.factory import get_provider
from app.services.job_search import search_jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/search", response_model=JobSearchResponse)
async def search(req: JobSearchRequest):
    """Master Resume JSON -> target roles (or the roles you pass) -> ranked open jobs."""
    try:
        provider = get_provider()
    except ProviderError as e:
        raise HTTPException(503, str(e))
    return await search_jobs(req.resume, provider, roles=req.roles, location=req.location,
                             top_roles=req.top_roles, max_results=req.max_results,
                             min_score=req.min_score)
