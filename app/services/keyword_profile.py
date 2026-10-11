"""G1: weighted keyword profile. A skill is worth more when it is proven (used in projects/jobs),
recent, or certified, and less when it is only a coursework subject or an acronym expansion."""
import re
from collections import defaultdict
from datetime import date

from app.core.scoring_config import KEYWORD_WEIGHTS
from app.schemas.keywords import KeywordProfile, KeywordWeight
from app.schemas.resume import ResumeData
from app.services.skill_taxonomy import get_taxonomy

_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*[\u2019'`]?\s*((?:19|20)?\d{2})\b", re.I)
_PRESENT = re.compile(r"\b(present|current|ongoing|till date)\b", re.I)
_SOURCE_KEY = {"skills_section": "skills_section", "coursework": "coursework",
               "project_text": "mentioned_in_text", "inferred": "inferred"}


def end_date(text: str, today: date) -> date | None:
    """End of 'Jan'26 - May'26' style ranges found in a project/job title."""
    if _PRESENT.search(text):
        return today
    found = _DATE.findall(text)
    if not found:
        return None
    mon, yr = found[-1]
    y = int(yr)
    return date(2000 + y if y < 100 else y, _MONTHS[mon[:3].lower()], 1)


def _is_recent(d: date | None, today: date, months: float) -> bool:
    return d is not None and (today.year - d.year) * 12 + (today.month - d.month) <= months


def build_keyword_profile(resume: ResumeData, today: date | None = None,
                          cfg: dict[str, float] | None = None) -> KeywordProfile:
    cfg = {**KEYWORD_WEIGHTS, **(cfg or {})}
    today = today or date.today()
    tax = get_taxonomy()
    comps: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    ev: dict[str, list[str]] = defaultdict(list)

    for s in resume.skills:
        key = _SOURCE_KEY.get(s.source, "mentioned_in_text")
        comps[s.name][key] = cfg[key]
        ev[s.name].append(key.replace("_", " ") + (f" ({s.inferred_from})" if s.inferred_from else ""))

    for kind, items, wkey in (("project", resume.projects, "project_evidence"),
                              ("experience", resume.experience, "experience_evidence")):
        for it in items:
            recent = _is_recent(end_date(it.title, today), today, cfg["recent_months"])
            for sk in dict.fromkeys(it.skills_used):
                if comps[sk][wkey] < cfg["max_evidence_items"] * cfg[wkey]:
                    comps[sk][wkey] += cfg[wkey]
                ev[sk].append(f"{kind}: {it.title}")
                if recent:
                    comps[sk]["recent_bonus"] = cfg["recent_bonus"]

    for cert in resume.certifications:
        for m in tax.find(cert):
            comps[m.name]["certification"] += cfg["certification"]
            ev[m.name].append(f"certification: {cert}")

    rows = sorted(((sk, dict(c), sum(c.values())) for sk, c in comps.items()), key=lambda x: -x[2])
    top = rows[0][2] if rows else 1.0
    return KeywordProfile(
        skills=[KeywordWeight(skill=sk, weight=round(w, 3), normalized=round(w / top, 3), components=c,
                              evidence=list(dict.fromkeys(ev[sk]))) for sk, c, w in rows],
        total_weight=round(sum(r[2] for r in rows), 3), weights_config=cfg)
