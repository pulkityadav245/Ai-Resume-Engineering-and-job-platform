"""Resume -> target roles -> provider queries -> dedup -> match & rank."""
import asyncio
import re

from app.schemas.jobs import Job, JobMatch, JobSearchResponse, RoleQuery
from app.schemas.resume import ResumeData
from app.services.job_matcher import match_job
from app.services.job_providers.base import JobProvider, ProviderError
from app.services.role_inference import get_role_profiles, infer_roles

QUERIES_PER_ROLE = 2
PER_PAGE = 20


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def dedup_key(j: Job) -> tuple[str, str, str]:
    return _norm(j.company), _norm(j.title), _norm((j.location or "").split(",")[0])


def _plan_queries(resume: ResumeData, roles: list[str] | None, top_roles: int):
    """-> (level, [(role_name, role_score|None, queries[], candidate_titles[])])"""
    inferred = infer_roles(resume, top_n=max(top_roles, 5))
    level = inferred.level
    by_inferred = {r.role.lower(): r for r in inferred.roles}
    profiles = {p["name"].lower(): p for p in get_role_profiles()}
    plan = []

    if roles:
        names = roles
    else:
        names = [r.role for r in inferred.roles[:top_roles]]

    for name in names:
        key = name.lower().strip()
        if key in profiles:
            p = profiles[key]
            titles = (p.get("fresher_titles", []) if level == "fresher" else []) + p["query_titles"]
            score = by_inferred[key].score if key in by_inferred else None
            plan.append((p["name"], score, titles[:QUERIES_PER_ROLE], titles + [p["name"]]))
        else:                                   # user typed a custom title -> use it verbatim
            plan.append((name.strip(), None, [name.strip()], [name.strip()]))
    return level, plan


async def search_jobs(resume: ResumeData, provider: JobProvider, roles: list[str] | None = None,
                      location: str | None = None, top_roles: int = 3, max_results: int = 30,
                      min_score: float = 25.0) -> JobSearchResponse:
    level, plan = _plan_queries(resume, roles, top_roles)
    warnings: list[str] = []
    if not plan:
        return JobSearchResponse(provider=provider.name, level=level, roles_used=[], total_fetched=0,
                                 after_dedup=0, jobs=[], warnings=[
                                     "No target roles could be inferred from this resume. "
                                     "Add skills/projects or pass roles explicitly."])
    if provider.name == "mock":
        warnings.append("DEMO MODE: these are fictional sample jobs, not real openings. "
                        "Set ADZUNA_APP_ID and ADZUNA_APP_KEY for live results.")

    # one task per (role, query title); failures are collected, not fatal
    tasks, meta = [], []
    for role, _score, queries, _cands in plan:
        for q in queries:
            tasks.append(provider.search(q, location, 1, PER_PAGE))
            meta.append((role, q))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    fetched_per_role: dict[str, int] = {r[0]: 0 for r in plan}
    merged: dict[tuple, tuple[Job, list[str]]] = {}
    total = 0
    failed = 0
    for (role, q), res in zip(meta, results):
        if isinstance(res, Exception):
            failed += 1
            msg = str(res) if isinstance(res, ProviderError) else f"unexpected error ({type(res).__name__})"
            warnings.append(f"Search for '{q}' failed: {msg}")
            continue
        fetched_per_role[role] += len(res)
        total += len(res)
        for job in res:
            k = dedup_key(job)
            if k in merged:
                if role not in merged[k][1]:
                    merged[k][1].append(role)
            else:
                merged[k] = (job, [role])
    if failed == len(tasks):
        warnings.append("All provider searches failed; no jobs returned.")

    cands = {role: c for role, _s, _q, c in plan}
    matches: list[JobMatch] = []
    for job, via in merged.values():
        titles = [t for r in via for t in cands[r]]
        matches.append(match_job(job, resume, level, titles, via))
    matches.sort(key=lambda m: m.score, reverse=True)
    kept = [m for m in matches if m.score >= min_score][:max_results]

    roles_used = [RoleQuery(role=r, role_score=s, queries=q, fetched=fetched_per_role[r])
                  for r, s, q, _c in plan]
    return JobSearchResponse(provider=provider.name, level=level, roles_used=roles_used,
                             total_fetched=total, after_dedup=len(merged), jobs=kept, warnings=warnings)
