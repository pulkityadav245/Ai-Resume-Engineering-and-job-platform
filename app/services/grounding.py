"""Grounding check: every fact in the parsed resume must be traceable to the source text.
Anything the parser (especially an LLM) produced that is NOT in the text is removed/flagged.
The same idea is reused later to validate tailored resumes."""
import re

from app.schemas.resume import GroundingIssue, ResumeData
from app.services.skill_taxonomy import get_taxonomy, normalize

_NUM = re.compile(r"\d[\d,.]*%?")


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9+#]+", "", s.lower())


def _in_text(value: str, squashed_text: str) -> bool:
    v = _squash(value)
    return bool(v) and v in squashed_text


def ground_resume(resume: ResumeData, source_text: str) -> tuple[ResumeData, list[GroundingIssue]]:
    tax = get_taxonomy()
    squashed = _squash(source_text)
    issues: list[GroundingIssue] = []

    # skills: must be mentioned (any alias) in the text, unless explicitly inferred via MERN-like acronym
    kept_skills = []
    for s in resume.skills:
        if s.source == "inferred":
            if s.inferred_from and re.search(re.escape(s.inferred_from), source_text, re.I):
                kept_skills.append(s)
                continue
        elif tax.mentions(source_text, s.name) or _in_text(s.name, squashed):
            kept_skills.append(s)
            continue
        issues.append(GroundingIssue(field="skills", value=s.name, action="removed",
                                     reason="Not found in resume text"))
    resume.skills = kept_skills
    valid_names = {s.name for s in kept_skills}

    # skills_used on projects / experience must be real and in the resume
    for coll, label in ((resume.projects, "projects"), (resume.experience, "experience")):
        for item in coll:
            ok = []
            for name in item.skills_used:
                if name in valid_names or tax.mentions(source_text, name) or _in_text(name, squashed):
                    ok.append(name)
                else:
                    issues.append(GroundingIssue(field=f"{label}.{item.id}.skills_used", value=name,
                                                 action="removed", reason="Not found in resume text"))
            item.skills_used = ok

    # titles / institutes / degrees must exist in the text
    for p in resume.projects:
        if not _in_text(p.title, squashed):
            issues.append(GroundingIssue(field=f"projects.{p.id}.title", value=p.title,
                                         action="flagged", reason="Title not found verbatim in text"))
    for e in resume.education:
        if e.institute and not _in_text(e.institute, squashed):
            issues.append(GroundingIssue(field=f"education.{e.id}.institute", value=e.institute,
                                         action="removed", reason="Not found in resume text"))
            e.institute = None

    # bullets: every number in a bullet must appear in the source (catches invented metrics)
    for coll, label in ((resume.projects, "projects"), (resume.experience, "experience")):
        for item in coll:
            for b in item.bullets:
                if not _in_text(b.text, squashed):
                    bad = [n for n in _NUM.findall(b.text) if n.strip(".,") not in source_text]
                    if bad:
                        issues.append(GroundingIssue(field=f"{label}.{item.id}.bullets.{b.id}",
                                                     value=b.text, action="flagged",
                                                     reason=f"Numbers not in source: {bad}"))
    return resume, issues
