"""Persistent job store: upsert on ingest, search from the database (no live API call per user request)."""
import json
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.data.india import normalize_city
from app.db.models import JobRow
from app.schemas.jobs import Job, JobMatch, JobSearchResponse, RoleQuery
from app.schemas.resume import ResumeData
from app.services.job_matcher import _tokens, extract_jd_skills, match_job, passes_job_type
from app.services.job_search import _plan_queries, dedup_key

GENERIC = {"developer", "engineer", "software", "programmer"}
CANDIDATE_LIMIT = 500


def _key(job: Job) -> str:
    return "|".join(dedup_key(job))


def upsert_jobs(s: Session, jobs: list[Job]) -> Counter:
    """inserted / updated (same source+id seen again) / duplicates (same job from another source)."""
    st: Counter = Counter()
    now = datetime.now(timezone.utc)
    for job in jobs:
        row = s.scalar(select(JobRow).where(JobRow.source == job.source, JobRow.external_id == job.external_id))
        if row:
            row.last_seen, row.is_active = now, True
            st["updated"] += 1
            continue
        key = _key(job)
        if s.scalar(select(JobRow.id).where(JobRow.dedup_key == key)):
            st["duplicates"] += 1
            continue
        s.add(JobRow(
            source=job.source, external_id=job.external_id, dedup_key=key, title=job.title, company=job.company,
            location=job.location, city=normalize_city(job.location), description=job.description, url=job.url,
            posted_at=job.posted_at, salary_min=job.salary_min, salary_max=job.salary_max,
            salary_predicted=job.salary_predicted, contract_type=job.contract_type,
            skills_json=json.dumps(extract_jd_skills(job)), first_seen=now, last_seen=now))
        s.flush()
        st["inserted"] += 1
    s.commit()
    return st


def _to_job(r: JobRow) -> Job:
    return Job(source=r.source, external_id=r.external_id, title=r.title, company=r.company, location=r.location,
               description=r.description, url=r.url, posted_at=r.posted_at, salary_min=r.salary_min,
               salary_max=r.salary_max, salary_predicted=r.salary_predicted, contract_type=r.contract_type)


def _candidates(s: Session, titles: list[str], location: str | None) -> list[JobRow]:
    token_sets = []
    for t in titles:
        toks = _tokens(t)
        toks = (toks - GENERIC) or toks
        if toks:
            token_sets.append(sorted(toks))
    if not token_sets:
        return []
    stmt = select(JobRow).where(JobRow.is_active.is_(True),
                                or_(*[and_(*[JobRow.title.ilike(f"%{t}%") for t in toks]) for toks in token_sets]))
    if location:
        city = normalize_city(location)
        stmt = stmt.where(JobRow.city == city) if city else stmt.where(JobRow.location.ilike(f"%{location.strip()}%"))
    return list(s.scalars(stmt.order_by(JobRow.last_seen.desc()).limit(CANDIDATE_LIMIT)))


def search_jobs_db(resume: ResumeData, s: Session, roles: list[str] | None = None, location: str | None = None,
                   top_roles: int = 3, max_results: int = 30, min_score: float = 25.0,
                   job_type: str = "any") -> JobSearchResponse:
    level, plan = _plan_queries(resume, roles, top_roles)
    warnings: list[str] = []
    total = s.scalar(select(func.count(JobRow.id))) or 0
    if total == 0:
        warnings.append("The jobs database is empty. Fill it first: python -m app.cli ingest --provider adzuna")
    if not plan:
        warnings.append("No target roles could be inferred from this resume.")
        return JobSearchResponse(provider="database", level=level, roles_used=[], total_fetched=0,
                                 after_dedup=0, jobs=[], warnings=warnings)
    merged: dict[int, tuple[JobRow, list[str]]] = {}
    fetched: dict[str, int] = {}
    for role, _score, _q, cands in plan:
        rows = _candidates(s, cands, location)
        fetched[role] = len(rows)
        for r in rows:
            merged.setdefault(r.id, (r, []))[1].append(role)
    cmap = {role: c for role, _s, _q, c in plan}
    matches: list[JobMatch] = [match_job(_to_job(r), resume, level, [t for x in via for t in cmap[x]], via)
                               for r, via in merged.values() if passes_job_type(_to_job(r), job_type)]
    matches.sort(key=lambda m: m.score, reverse=True)
    return JobSearchResponse(
        provider="database", level=level,
        roles_used=[RoleQuery(role=r, role_score=sc, queries=c[:3], fetched=fetched[r]) for r, sc, _q, c in plan],
        total_fetched=sum(fetched.values()), after_dedup=len(merged),
        jobs=[m for m in matches if m.score >= min_score][:max_results], warnings=warnings)


def stats(s: Session) -> dict:
    def grouped(col, n=10):
        return [{"name": k, "jobs": v} for k, v in s.execute(
            select(col, func.count(JobRow.id)).where(col.is_not(None)).group_by(col)
            .order_by(func.count(JobRow.id).desc()).limit(n))]
    skills: Counter = Counter()
    for (blob,) in s.execute(select(JobRow.skills_json).limit(20000)):   # sample cap for the MVP
        skills.update(json.loads(blob or "{}").keys())
    return {"total_jobs": s.scalar(select(func.count(JobRow.id))) or 0, "by_source": grouped(JobRow.source),
            "top_cities": grouped(JobRow.city), "top_skills": [{"name": k, "jobs": v} for k, v in skills.most_common(15)],
            "last_seen": (lambda d: d.isoformat() if d else None)(s.scalar(select(func.max(JobRow.last_seen))))}
