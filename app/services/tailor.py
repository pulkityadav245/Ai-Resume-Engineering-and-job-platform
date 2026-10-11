"""Resume tailoring from the Master Resume only.
Default mode is EXTRACTIVE: it selects, reorders and de-emphasises existing content, never writes new text, so it
cannot fabricate by construction. Optional rewrite mode lets a model rephrase bullets, but every result goes through
factuality.enforce(): anything unsupported is reverted to the original bullet. JD skills the candidate lacks are
reported as `skill_gap` and are never added."""
import re
from datetime import date
from typing import Callable

from app.schemas.jobs import Job
from app.schemas.resume import Bullet, Experience, Project, ResumeData
from app.schemas.tailor import Coverage, TailorResponse, TraceEntry
from app.services.factuality import enforce, master_text, skill_universe
from app.services.job_matcher import extract_jd_skills
from app.services.keyword_profile import build_keyword_profile
from app.services.skill_taxonomy import get_taxonomy

Rewriter = Callable[[str, list[str], str], str]      # (bullet, allowed_skills, jd_title) -> new bullet


def _present_skills(r: ResumeData) -> set[str]:
    return ({s.name for s in r.skills} | {sk for it in [*r.projects, *r.experience] for sk in it.skills_used}
            | {m.name for m in get_taxonomy().find(master_text(r))})


def build_tailored(master: ResumeData, jd_text: str, jd_title: str | None = None, mode: str = "extractive",
                   rewriter: Rewriter | None = None, max_projects: int = 3, max_bullets: int = 3,
                   max_achievements: int = 3, today: date | None = None) -> tuple[ResumeData, dict]:
    """Build the tailored resume BEFORE enforcement. Returns (raw tailored resume, context)."""
    tax = get_taxonomy()
    jd = extract_jd_skills(Job(source="jd", external_id="jd", title=jd_title or "", description=jd_text, url="jd://local"))
    jd_w = {s: (1.0 if k == "required" else 0.5) for s, k in jd.items()}
    universe = skill_universe(master)
    matched, gap = [s for s in jd if s in universe], [s for s in jd if s not in universe]
    kvec = build_keyword_profile(master, today=today).vector()
    bskills = lambda text: {m.name for m in tax.find(text)}                      # noqa: E731
    bullet_score = lambda b: sum(jd_w.get(s, 0) for s in bskills(b.text)) + (0.3 if re.search(r"\d", b.text) else 0)  # noqa: E731

    def item_score(it) -> float:
        ss = set(it.skills_used).union(*[bskills(b.text) for b in it.bullets]) if it.bullets else set(it.skills_used)
        return sum(jd_w.get(s, 0) for s in ss)

    changes: list[str] = []

    def build_items(items, cls, limit):
        ranked = sorted(range(len(items)), key=lambda i: (-item_score(items[i]), i))
        keep = ranked if limit is None else ranked[:limit]
        out = []
        for i in keep:
            it = items[i]
            sel = sorted(range(len(it.bullets)), key=lambda j: (-bullet_score(it.bullets[j]), j))[:max_bullets]
            bullets = []
            for j in sel:
                b, text = it.bullets[j], it.bullets[j].text
                if mode == "rewrite" and rewriter:
                    allowed = [s for s in matched if s in (set(it.skills_used) | bskills(b.text))]
                    text = rewriter(b.text, allowed, jd_title or "") or b.text
                bullets.append(Bullet(id=b.id, text=text, source_id=b.id, rewritten=text.strip() != b.text.strip()))
            used = sorted(it.skills_used, key=lambda s: (-jd_w.get(s, 0), it.skills_used.index(s)))
            out.append(cls(id=it.id, title=it.title, bullets=bullets, skills_used=used))
            if len(bullets) < len(it.bullets):
                changes.append(f"'{it.title[:40]}': kept the {len(bullets)} most relevant of {len(it.bullets)} bullets")
        dropped = [items[i].title for i in ranked[len(keep):]]
        if dropped:
            changes.append("Left out less relevant: " + "; ".join(t[:40] for t in dropped))
        return out

    projects = build_items(master.projects, Project, max_projects)
    experience = build_items(master.experience, Experience, None)
    rank = lambda s: (0 if jd.get(s.name) == "required" else 1 if jd.get(s.name) == "preferred" else 2, -kvec.get(s.name, 0))  # noqa: E731
    skills = sorted(master.skills, key=rank)
    if [s.name for s in skills] != [s.name for s in master.skills]:
        changes.append("Reordered skills: JD-relevant first (" + ", ".join(s.name for s in skills if s.name in matched)[:80] + ")")
    certs = sorted(master.certifications, key=lambda c: 0 if {m.name for m in tax.find(c)} & set(jd) else 1)
    raw = ResumeData(personal=master.personal.model_copy(deep=True), education=[e.model_copy(deep=True) for e in master.education],
                     skills=[s.model_copy(deep=True) for s in skills], projects=projects, experience=experience,
                     coursework=list(master.coursework), certifications=certs,
                     achievements=master.achievements[:max_achievements])
    if not jd:
        changes.append("No recognisable skills in the job description; only ordering/selection rules were applied.")
    if gap:
        changes.append("Skill gap (NOT added to the resume): " + ", ".join(gap))
    return raw, {"jd": jd, "jd_w": jd_w, "matched": matched, "gap": gap, "changes": changes}


def tailor_resume(master: ResumeData, jd_text: str, jd_title: str | None = None, mode: str = "extractive",
                  rewriter: Rewriter | None = None, **kw) -> TailorResponse:
    raw, ctx = build_tailored(master, jd_text, jd_title, mode, rewriter, **kw)
    final, before, after = enforce(master, raw)
    jd_w = ctx["jd_w"]
    total = sum(jd_w.values())
    cov = lambda present: round(sum(w for s, w in jd_w.items() if s in present) / total, 4) if total else 0.0  # noqa: E731
    reverted = before.unsupported
    changes = ctx["changes"] + ([f"Validator reverted/removed {reverted} unsupported item(s) from the model rewrite"] if reverted else [])
    return TailorResponse(
        tailored=final,
        trace=[TraceEntry(output_id=b.id, source_id=b.source_id, rewritten=b.rewritten)
               for it in [*final.projects, *final.experience] for b in it.bullets],
        jd_skills=ctx["jd"], matched_skills=ctx["matched"], skill_gap=ctx["gap"],
        coverage=Coverage(before=cov(_present_skills(master)), after=cov(_present_skills(final)),
                          ceiling=round(sum(jd_w[s] for s in ctx["matched"]) / total, 4) if total else 0.0),
        changes=changes, factuality=after, factuality_before_enforcement=before)
