from pydantic import BaseModel, Field

from app.schemas.resume import ResumeData


class Job(BaseModel):
    source: str
    external_id: str
    title: str
    company: str | None = None
    location: str | None = None
    description: str = ""                 # NOTE: job boards often return only a snippet
    url: str                              # always link users to this (provider ToS)
    posted_at: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_predicted: bool | None = None  # True = provider's estimate, not stated by employer
    contract_type: str | None = None


class JobMatch(BaseModel):
    job: Job
    score: float                          # 0-100 heuristic fit, see job_matcher.py
    matched_skills: list[str]
    missing_required: list[str]
    missing_preferred: list[str]
    jd_skills_found: int
    title_relevance: float                # 0-1
    level_fit: float                      # 0-1
    experience_required_years: int | None = None
    via_roles: list[str]
    flags: list[str] = Field(default_factory=list)


class JobSearchRequest(BaseModel):
    resume: ResumeData
    roles: list[str] | None = None        # None -> auto-infer from resume
    location: str | None = None
    top_roles: int = Field(3, ge=1, le=5)
    max_results: int = Field(30, ge=1, le=100)
    min_score: float = Field(25.0, ge=0, le=100)


class RoleQuery(BaseModel):
    role: str
    role_score: float | None = None
    queries: list[str]
    fetched: int = 0


class JobSearchResponse(BaseModel):
    provider: str
    level: str
    roles_used: list[RoleQuery]
    total_fetched: int
    after_dedup: int
    jobs: list[JobMatch]
    warnings: list[str] = Field(default_factory=list)
