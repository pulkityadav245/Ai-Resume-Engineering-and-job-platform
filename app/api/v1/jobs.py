from fastapi import APIRouter, HTTPException

from app.db.session import session_scope
from app.schemas.jobs import JobSearchRequest, JobSearchResponse
from app.services.job_providers.base import ProviderError
from app.services.job_providers.factory import get_provider
from app.services.job_search import search_jobs
from app.services.job_store import search_jobs_db, stats

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/search", response_model=JobSearchResponse)
async def search(req: JobSearchRequest):
    """Master Resume JSON -> target roles (or the roles you pass) -> ranked open jobs.
    source=live calls the provider now; source=database searches jobs stored by `python -m app.cli ingest`."""
    if req.source == "database":
        with session_scope() as s:
            return search_jobs_db(req.resume, s, roles=req.roles, location=req.location, top_roles=req.top_roles,
                                  max_results=req.max_results, min_score=req.min_score, job_type=req.job_type)
    try:
        provider = get_provider()
    except ProviderError as e:
        raise HTTPException(503, str(e))
    return await search_jobs(req.resume, provider, roles=req.roles, location=req.location,
                             top_roles=req.top_roles, max_results=req.max_results, min_score=req.min_score,
                             job_type=req.job_type)


@router.get("/stats")
def job_stats():
    """What the jobs database holds: totals, sources, top Indian cities, most demanded skills."""
    with session_scope() as s:
        return stats(s)
