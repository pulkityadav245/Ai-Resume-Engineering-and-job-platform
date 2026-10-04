"""Scores ONE job against ONE resume. Deterministic and explainable.

score = 45% skill coverage  (required skills weigh 1.0, preferred 0.5)
      + 30% title relevance (job title vs the target role's titles)
      + 15% evidence        (matched skills actually used in projects/experience)
      + 10% level fit       (fresher vs senior titles / years of experience asked)
Gates: fresher + senior title -> score capped at 40; fresher + 3+ years asked -> capped at 55.
Weights are a starting heuristic, NOT validated -- tune on labelled data.

LIMITATION: job boards (Adzuna included) usually return only a description SNIPPET, so
skills that appear later in the full posting are invisible here. Jobs with <2 detected
skills are flagged as low-confidence.
"""
import re
from difflib import SequenceMatcher

from app.schemas.jobs import Job, JobMatch
from app.schemas.resume import ResumeData
from app.services.skill_taxonomy import get_taxonomy

W_SKILL, W_TITLE, W_EVID, W_LEVEL = 0.45, 0.30, 0.15, 0.10

SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff|architect|manager|head|director|vp)\b", re.I)
JUNIOR = re.compile(r"\b(junior|jr\.?|intern(ship)?|trainee|fresher|graduate|entry[- ]level)\b", re.I)
PREFERRED = re.compile(r"\b(preferred|plus|good to have|nice to have|bonus|desirable|advantage|optional)\b", re.I)
YEARS_REQ = re.compile(r"(\d{1,2})\s*(?:\+|\s*-\s*\d{1,2}|\s*to\s*\d{1,2})?\s*(?:years?|yrs?)\b", re.I)
_TOK = re.compile(r"[a-z0-9+#.]+")
_STOP = {"and", "of", "the", "for", "a", "an", "in", "at", "with"}
_LEVEL_WORDS = {"senior", "sr", "junior", "jr", "lead", "intern", "internship", "trainee", "graduate",
                "associate", "entry", "level", "fresher"}


def _tokens(s: str) -> set[str]:
    toks = {t.strip(".") for t in _TOK.findall(s.lower())}
    return {t for t in toks if t and t not in _STOP and t not in _LEVEL_WORDS}


def title_relevance(job_title: str, candidate_titles: list[str]) -> float:
    jt = _tokens(job_title)
    best = 0.0
    for c in candidate_titles:
        ct = _tokens(c)
        if not ct or not jt:
            continue
        containment = len(ct & jt) / len(ct)
        ratio = SequenceMatcher(None, " ".join(sorted(ct)), " ".join(sorted(jt))).ratio()
        best = max(best, containment, ratio)
    return round(best, 3)


def extract_jd_skills(job: Job) -> dict[str, str]:
    """{skill: 'required'|'preferred'} -- classification is a sentence-level heuristic."""
    tax = get_taxonomy()
    out: dict[str, str] = {}
    text = f"{job.title}. {job.description}"
    for sentence in re.split(r"(?<=[.;!?])\s+|\n|\u2022", text):
        kind = "preferred" if PREFERRED.search(sentence) else "required"
        for m in tax.find(sentence):
            if kind == "required":
                out[m.name] = "required"
            else:
                out.setdefault(m.name, "preferred")
    return out


def experience_required(job: Job) -> int | None:
    m = YEARS_REQ.search(f"{job.title}. {job.description}")
    return int(m.group(1)) if m else None


def level_fit(level: str, title: str, years: int | None) -> tuple[float, list[str]]:
    if level == "fresher":
        if SENIOR.search(title):
            return 0.0, ["senior-level role"]
        if years is not None and years >= 3:
            return 0.2, [f"asks {years}+ years of experience"]
        if years is not None and years >= 1:
            return 0.7, [f"asks {years}+ year(s) of experience"]
        return 1.0, []
    if JUNIOR.search(title) and not SENIOR.search(title):
        return 0.6, ["junior-level role"]
    return 1.0, []


def match_job(job: Job, resume: ResumeData, level: str, candidate_titles: list[str],
              via_roles: list[str]) -> JobMatch:
    have = {s.name for s in resume.skills}
    evidence = {s for it in [*resume.projects, *resume.experience] for s in it.skills_used}

    jd = extract_jd_skills(job)
    weights = {s: (1.0 if k == "required" else 0.5) for s, k in jd.items()}
    matched = [s for s in jd if s in have]
    flags: list[str] = []
    if len(jd) >= 1:
        skill_score = sum(weights[s] for s in matched) / sum(weights.values())
    else:
        skill_score = 0.4
    if len(jd) < 2:
        flags.append("few skills visible in listing (low confidence)")

    tr = title_relevance(job.title, candidate_titles)
    evid = (len([s for s in matched if s in evidence]) / len(matched)) if matched else 0.0
    years = experience_required(job)
    lf, lf_flags = level_fit(level, job.title, years)
    flags += lf_flags

    score = 100 * (W_SKILL * skill_score + W_TITLE * tr + W_EVID * evid + W_LEVEL * lf)
    # hard gates: a fresher should never see a senior / 3+ yrs job near the top just because skills overlap
    if lf == 0.0:
        score = min(score, 40.0)
    elif lf <= 0.2:
        score = min(score, 55.0)
    return JobMatch(
        job=job, score=round(score, 1), matched_skills=matched,
        missing_required=[s for s, k in jd.items() if k == "required" and s not in have],
        missing_preferred=[s for s, k in jd.items() if k == "preferred" and s not in have],
        jd_skills_found=len(jd), title_relevance=tr, level_fit=lf,
        experience_required_years=years, via_roles=via_roles, flags=flags,
    )
