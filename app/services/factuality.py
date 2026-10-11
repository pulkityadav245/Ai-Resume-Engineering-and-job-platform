"""Hallucination control for tailored resumes. A tailored resume is compared claim-by-claim with the
Master Resume; anything not supported is reported, and `enforce` repairs the output so the final resume
always passes (by falling back to the original bullet text). Scope: this guarantees NO NEW skills, numbers,
dates, organisations, titles or inflated qualifiers. It does not prove that a rewritten sentence keeps its exact
meaning; that needs human review or an NLI model."""
import re
from collections import Counter

from app.schemas.resume import Bullet, ResumeData
from app.schemas.tailor import FactualityReport, Violation
from app.services.skill_taxonomy import get_taxonomy

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z\-']*")
_TECH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]*[a-z][A-Z][A-Za-z]*|[A-Z]{2,}[a-z]*|[A-Za-z]+\.js|[A-Za-z]+\+\+|[A-Za-z]+#)")
INFLATE = {"led", "lead", "leading", "managed", "spearheaded", "architected", "founded", "owned", "directed",
           "headed", "pioneered", "oversaw", "mentored", "principal", "head"}
SCALE = {"millions", "thousands", "enterprise", "enterprise-grade", "large-scale", "production-grade", "globally",
         "worldwide", "company-wide", "mission-critical", "high-traffic", "scalable"}


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9+#]+", "", s.lower())


def _nums(s: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(s)}


def master_text(r: ResumeData) -> str:
    parts = [r.personal.name or "", r.personal.email or "", r.personal.phone or "", *r.personal.links]
    for e in r.education:
        parts += [e.degree, e.institute or "", e.years or "", e.score or ""]
    parts += [s.name for s in r.skills]
    for it in [*r.projects, *r.experience]:
        parts += [it.title, *it.skills_used, *[b.text for b in it.bullets]]
    parts += [*r.coursework, *r.certifications, *r.achievements]
    return "\n".join(p for p in parts if p)


def skill_universe(r: ResumeData) -> set[str]:
    """Every skill the candidate legitimately has: listed, used in a project/job, or named anywhere in the text."""
    u = {s.name for s in r.skills} | {sk for it in [*r.projects, *r.experience] for sk in it.skills_used}
    return u | {m.name for m in get_taxonomy().find(master_text(r))}


def _source_bullets(r: ResumeData) -> dict[str, str]:
    return {b.id: b.text for it in [*r.projects, *r.experience] for b in it.bullets}


def validate(master: ResumeData, tailored: ResumeData) -> FactualityReport:
    tax, mtext = get_taxonomy(), master_text(master)
    msq, universe, src_b = _squash(mtext), skill_universe(master), _source_bullets(master)
    m_years = set(_YEAR.findall(mtext))
    V: list[Violation] = []
    checked = n_bul = n_traced = n_ident = 0

    def add(t, sev, value, where, reason):
        V.append(Violation(type=t, severity=sev, value=str(value)[:80], where=where, reason=reason))

    def entity(val: str, where: str, label: str):
        nonlocal checked
        if val:
            checked += 1
            if _squash(val) not in msq:
                add("entity", "error", val, where, f"{label} not found in the Master Resume")

    entity(tailored.personal.name or "", "personal.name", "name")
    entity(tailored.personal.email or "", "personal.email", "email")
    entity(tailored.personal.phone or "", "personal.phone", "phone")
    for e in tailored.education:
        for label, val in (("degree", e.degree), ("institute", e.institute or ""), ("years", e.years or ""), ("score", e.score or "")):
            entity(val, f"education.{e.id}.{label}", label)
    for coll, items in (("coursework", tailored.coursework), ("certifications", tailored.certifications), ("achievements", tailored.achievements)):
        for i, x in enumerate(items):
            entity(x, f"{coll}.{i}", coll[:-1])
    for s in tailored.skills:
        checked += 1
        if s.name not in universe:
            add("skill", "error", s.name, "skills", "skill is not in the Master Resume")

    for kind, items in (("projects", tailored.projects), ("experience", tailored.experience)):
        for it in items:
            where = f"{kind}.{it.id}"
            entity(it.title, f"{where}.title", "title")
            for yr in set(_YEAR.findall(it.title)):
                checked += 1
                if yr not in m_years:
                    add("date", "error", yr, f"{where}.title", "year not in the Master Resume")
            for sk in it.skills_used:
                checked += 1
                if sk not in universe:
                    add("skill", "error", sk, f"{where}.skills_used", "skill is not in the Master Resume")
            for b in it.bullets:
                bw, n_bul = f"{where}.{b.id}", n_bul + 1
                src = src_b.get(b.source_id or b.id)
                checked += 1
                if src is None:
                    add("untraceable", "error", b.text, bw, "bullet has no source bullet in the Master Resume")
                    continue
                n_traced += 1
                if b.text.strip() == src.strip():
                    n_ident += 1
                    if b.rewritten:
                        add("untraceable", "warning", b.text, bw, "flagged rewritten but identical to source")
                    continue
                if not b.rewritten:
                    add("untraceable", "error", b.text, bw, "marked as copied but the text differs from its source")
                for sk in {m.name for m in tax.find(b.text)}:
                    checked += 1
                    if sk not in universe:
                        add("skill", "error", sk, bw, "rewrite introduces a skill that is not in the Master Resume")
                src_nums = _nums(src)
                for n in _nums(b.text):
                    checked += 1
                    if n not in src_nums:
                        add("number", "error", n, bw, "rewrite introduces a number that is not in the source bullet")
                src_words = {w.lower() for w in _WORD.findall(src)}
                for w in {w.lower() for w in _WORD.findall(b.text)}:
                    if (w in INFLATE or w in SCALE) and w not in src_words:
                        checked += 1
                        add("inflated_qualifier", "error", w, bw, "rewrite inflates the claim (leadership/scale wording)")
                for tok in set(_TECH.findall(b.text)):
                    if tok.lower() not in src.lower() and tok not in universe:
                        checked += 1
                        add("unseen_token", "warning", tok, bw, "technical-looking term not present in the source bullet")

    errors = [v for v in V if v.severity == "error"]
    return FactualityReport(
        claims_checked=checked, unsupported=len(errors), warnings=len(V) - len(errors),
        unsupported_claim_rate=round(len(errors) / checked, 4) if checked else 0.0,
        by_type=dict(Counter(v.type for v in errors)),
        traceability_coverage=round(n_traced / n_bul, 4) if n_bul else 1.0,
        extractive_ratio=round(n_ident / n_bul, 4) if n_bul else 1.0, violations=V, passed=not errors)


def _restore_bullets(master: ResumeData, fixed: ResumeData, bad: set[str]) -> None:
    src_b = _source_bullets(master)
    for kind, items in (("projects", fixed.projects), ("experience", fixed.experience)):
        for it in items:
            new = []
            for b in it.bullets:
                src = src_b.get(b.source_id or b.id)
                if src is None:
                    continue                                    # untraceable -> dropped
                if f"{kind}.{it.id}.{b.id}" in bad:             # bad rewrite -> original text
                    b = Bullet(id=b.id, text=src, source_id=b.source_id or b.id, rewritten=False)
                new.append(b)
            it.bullets = new


def enforce(master: ResumeData, tailored: ResumeData) -> tuple[ResumeData, FactualityReport, FactualityReport]:
    """Return (final resume, report before, report after). The final resume is repaired until it passes."""
    before = validate(master, tailored)
    if before.passed:
        return tailored, before, before
    fixed, universe = tailored.model_copy(deep=True), skill_universe(master)
    bad = {v.where for v in before.violations if v.severity == "error"}
    fixed.skills = [s for s in fixed.skills if s.name in universe]
    for it in [*fixed.projects, *fixed.experience]:
        it.skills_used = [s for s in it.skills_used if s in universe]
    _restore_bullets(master, fixed, bad)
    for kind, items, orig in (("projects", fixed.projects, master.projects), ("experience", fixed.experience, master.experience)):
        by_id = {o.id: o for o in orig}
        for it in items:
            if f"{kind}.{it.id}.title" in bad or any(w.startswith(f"{kind}.{it.id}.title") for w in bad):
                it.title = by_id[it.id].title if it.id in by_id else it.title
    outside = {w.split(".")[0] for w in bad}                     # sections with unsupported plain facts
    if "personal" in outside:
        fixed.personal = master.personal.model_copy(deep=True)
    if "education" in outside:
        fixed.education = [e.model_copy(deep=True) for e in master.education]
    for sec in ("coursework", "certifications", "achievements"):
        if sec in outside:
            setattr(fixed, sec, [x for x in getattr(fixed, sec) if _squash(x) in _squash(master_text(master))])
    after = validate(master, fixed)
    if not after.passed:                                          # last resort: drop whatever still fails
        bad2 = {v.where for v in after.violations if v.severity == "error"}
        for items in (fixed.projects, fixed.experience):
            items[:] = [it for it in items if not any(w.startswith(f"{'projects' if items is fixed.projects else 'experience'}.{it.id}") and w.count(".") <= 2 for w in bad2)]
        after = validate(master, fixed)
    return fixed, before, after
