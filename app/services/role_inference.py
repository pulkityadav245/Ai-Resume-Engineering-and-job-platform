"""Role inference: explainable, deterministic. No LLM involved.

score = 45% core-skill coverage
      + 35% project/experience evidence (core skills actually USED in a project/job)
      + 10% optional-skill coverage
      + 10% education fit
These weights are a starting heuristic, NOT validated -- tune them on labelled resumes.
"""
import json
from functools import lru_cache
from pathlib import Path

from app.schemas.resume import ResumeData
from app.schemas.roles import RoleInferenceResponse, RoleMatch
from app.services.skill_taxonomy import get_taxonomy

ROLES = Path(__file__).resolve().parents[1] / "data" / "roles.json"
W_CORE, W_EVID, W_OPT, W_EDU = 0.45, 0.35, 0.10, 0.10


@lru_cache(maxsize=1)
def _roles() -> list[dict]:
    return json.loads(ROLES.read_text(encoding="utf-8"))["roles"]


def get_role_profiles() -> list[dict]:
    return _roles()


def infer_level(resume: ResumeData) -> str:
    real_jobs = [e for e in resume.experience if "intern" not in e.title.lower()
                 and "trainee" not in e.title.lower()]
    return "experienced" if real_jobs else "fresher"


def _evidence_map(resume: ResumeData) -> dict[str, list[str]]:
    ev: dict[str, list[str]] = {}
    for item in [*resume.projects, *resume.experience]:
        for s in item.skills_used:
            ev.setdefault(s, []).append(item.title)
    return ev


def infer_roles(resume: ResumeData, top_n: int = 5, min_score: float = 15.0) -> RoleInferenceResponse:
    tax = get_taxonomy()
    have = {s.name for s in resume.skills}
    evidence = _evidence_map(resume)
    edu_text = " ".join(f"{e.degree} {e.institute or ''}" for e in resume.education).lower()
    level = infer_level(resume)

    results: list[RoleMatch] = []
    for role in _roles():
        core = [c for c in role["core"] if c in tax.skills]
        opt = [o for o in role.get("optional", []) if o in tax.skills]
        matched_core = [c for c in core if c in have]
        missing_core = [c for c in core if c not in have]
        matched_opt = [o for o in opt if o in have]
        evidenced = [c for c in matched_core if c in evidence]

        core_cov = len(matched_core) / len(core) if core else 0
        evid_cov = len(evidenced) / len(core) if core else 0
        opt_cov = len(matched_opt) / len(opt) if opt else 0
        edu_fit = 1.0 if any(k in edu_text for k in role.get("edu_keywords", [])) else 0.3 if edu_text else 0.0

        score = 100 * (W_CORE * core_cov + W_EVID * evid_cov + W_OPT * opt_cov + W_EDU * edu_fit)
        if score < min_score or not matched_core:
            continue

        titles = list(role["query_titles"])
        if level == "fresher":
            titles = role.get("fresher_titles", []) + titles
        parts = [f"{len(matched_core)}/{len(core)} core skills matched"]
        if evidenced:
            parts.append(f"used in projects/experience: {', '.join(evidenced)}")
        unproven = [c for c in matched_core if c not in evidence]
        if unproven:
            parts.append(f"listed but no project evidence: {', '.join(unproven)}")
        if missing_core:
            parts.append(f"missing: {', '.join(missing_core)}")
        results.append(RoleMatch(
            role=role["name"], score=round(score, 1), matched_core=matched_core,
            missing_core=missing_core, matched_optional=matched_opt,
            evidence={c: evidence[c] for c in evidenced}, query_titles=titles,
            explanation="; ".join(parts),
        ))
    results.sort(key=lambda r: r.score, reverse=True)
    return RoleInferenceResponse(level=level, roles=results[:top_n])
