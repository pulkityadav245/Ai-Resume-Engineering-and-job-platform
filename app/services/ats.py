"""ATS-readiness checker: a transparent, weighted checklist (not any real ATS's algorithm).
Every check returns a 0-1 score, a plain-English detail and a concrete fix. Weights live in CHECKS below."""
import re

from app.schemas.ats import ATSCheck, ATSReport
from app.schemas.resume import ResumeData
from app.services.job_matcher import extract_jd_skills
from app.schemas.jobs import Job
from app.services.keyword_profile import _DATE
from app.services.rule_parser import BULLET, split_sections
from app.services.skill_taxonomy import get_taxonomy

ACTION_VERBS = {"developed", "built", "implemented", "designed", "created", "optimized", "optimised", "improved", "led",
                "managed", "automated", "integrated", "deployed", "engineered", "analyzed", "analysed", "reduced",
                "increased", "launched", "migrated", "tested", "refactored", "configured", "collaborated", "wrote",
                "architected", "delivered", "maintained", "established", "enabled", "supported", "trained", "evaluated",
                "visualized", "simulated", "organized", "organised", "presented", "contributed", "achieved", "solved"}
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2705]")
_FIRST_PERSON = re.compile(r"\b(i|my|me|myself)\b", re.I)
_ID_PATTERNS = {"mon-yy": re.compile(r"\b[A-Za-z]{3,9}\s*[\u2019']?\s*\d{2}\b"), "mon-yyyy": re.compile(r"\b[A-Za-z]{3,9}\.?\s+\d{4}\b"),
                "mm/yyyy": re.compile(r"\b\d{1,2}/\d{4}\b"), "yyyy-yy": re.compile(r"\b(?:19|20)\d{2}\s*[-\u2013]\s*\d{2}\b"),
                "yyyy-yyyy": re.compile(r"\b(?:19|20)\d{2}\s*[-\u2013]\s*(?:(?:19|20)\d{2}|present|current)\b", re.I)}


def _status(score: float) -> str:
    return "pass" if score >= 0.8 else "warn" if score >= 0.5 else "fail"


def _bullets(resume: ResumeData) -> list[str]:
    return [b.text for it in [*resume.projects, *resume.experience] for b in it.bullets]


def ats_check(text: str, resume: ResumeData, pages: int = 1, warnings: list[str] | None = None,
              jd_text: str | None = None, layout: dict | None = None) -> ATSReport:
    warnings, layout = warnings or [], layout or {}
    secs = split_sections(text)
    bullets, p = _bullets(resume), resume.personal
    nb = len(bullets) or 1
    checks: list[ATSCheck] = []

    def add(cid, cat, name, weight, score, detail, fix=None):
        score = max(0.0, min(1.0, score))
        checks.append(ATSCheck(id=cid, category=cat, name=name, weight=weight, score=round(score, 3),
                               status=_status(score), detail=detail, fix=None if score >= 0.8 else fix))

    # ---- parseability
    empty = sum("no extractable text" in w for w in warnings)
    add("text_extractable", "Parseability", "Text can be extracted", 10, 1 - empty / max(pages, 1),
        f"{empty} of {pages} page(s) have no readable text" if empty else "All pages have readable text",
        "Export the resume as a text-based PDF (not a scan or image).")
    tbl = any("table" in w.lower() for w in warnings)
    add("no_tables", "Parseability", "No tables or multi-column traps", 5, 0.4 if tbl else 1.0,
        "Tables detected; many ATS read them out of order" if tbl else "No table problems detected",
        "Replace tables with simple headings and bullet lists in a single column.")
    cols = bool(layout.get("columns_suspected"))
    add("single_column", "Parseability", "Single-column reading order", 6, 0.3 if cols else 1.0,
        f"{round(layout.get('gap_line_ratio', 0) * 100)}% of lines look split into columns" if cols else "No multi-column layout detected",
        "Use a single-column layout; columns and sidebars are often read in the wrong order.")
    imgs = int(layout.get("images", 0))
    add("images", "Parseability", "No important text inside images", 3, 1.0 if not imgs else 0.7,
        f"{imgs} embedded image(s); text inside images cannot be read" if imgs else "No embedded images",
        "Remove photos/logos or make sure no contact detail or skill exists only inside an image.")
    # ---- contact
    add("email", "Contact", "Email present", 4, 1.0 if p.email else 0.0, p.email or "No email found", "Add a professional email address at the top.")
    add("phone", "Contact", "Phone present", 3, 1.0 if p.phone else 0.0, p.phone or "No phone found", "Add a phone number at the top.")
    links = " ".join(p.links).lower()
    lk = (("linkedin" in links) + ("github" in links))
    add("links", "Contact", "LinkedIn / GitHub link", 3, [0.3, 0.7, 1.0][lk], f"{lk} of 2 profile links found",
        "Add working LinkedIn and GitHub links (as real hyperlinks).")
    # ---- sections
    core = [bool(resume.education or secs.get("education")), bool(secs.get("skills")), bool(resume.projects or resume.experience)]
    add("core_sections", "Sections", "Education, Skills, Projects/Experience", 12, sum(core) / 3,
        f"{sum(core)} of 3 core sections found", "Add the missing section with a standard heading (Education, Skills, Projects or Experience).")
    heads = len([k for k in secs if k != "header" and secs[k]])
    add("standard_headings", "Sections", "Standard section headings recognised", 4, heads / 4, f"{heads} recognised headings",
        "Use standard headings such as Education, Skills, Projects, Experience, Certifications.")
    add("optional_sections", "Sections", "Certifications / Achievements", 4, 0.5 * bool(resume.certifications) + 0.5 * bool(resume.achievements),
        f"certifications: {len(resume.certifications)}, achievements: {len(resume.achievements)}", "Add certifications and achievements if you have them.")
    # ---- format
    fresher = not resume.experience
    ok_pages = 1.0 if pages <= (1 if fresher else 2) else 0.8 if pages == 2 else 0.4
    add("length", "Format", "Sensible length", 6, ok_pages, f"{pages} page(s)", "Keep freshers to 1 page and experienced candidates to at most 2 pages.")
    date_text = (secs.get("projects", "") + "\n" + secs.get("experience", "")).strip() or text   # education year ranges are a normal different style
    fmts = [k for k, rx in _ID_PATTERNS.items() if rx.search(date_text)]
    add("date_consistency", "Format", "Consistent date format", 4, {0: 0.7, 1: 1.0, 2: 0.6}.get(len(fmts), 0.4),
        f"date styles used: {', '.join(fmts) or 'none'}", "Use one date style everywhere, for example 'Jan 2026 - May 2026'.")
    add("bullet_usage", "Format", "Bullet points used", 4, min(len(bullets) / 4, 1.0), f"{len(bullets)} bullets in projects/experience", "Describe projects and jobs in short bullet points.")
    emoji = len(_EMOJI.findall(text))
    add("special_chars", "Format", "No emojis or decorative symbols", 3, 1.0 if not emoji else 0.4, f"{emoji} emoji/symbol character(s)", "Remove emojis and decorative symbols.")
    # ---- content
    starts = sum(1 for b in bullets if (re.findall(r"[A-Za-z]+", b) or [""])[0].lower() in ACTION_VERBS)
    add("action_verbs", "Content", "Bullets start with action verbs", 6, (starts / nb) / 0.6, f"{starts} of {len(bullets)} bullets", "Start bullets with verbs such as Built, Implemented, Designed, Optimized.")
    quant = sum(1 for b in bullets if re.search(r"\d", b))
    add("quantified", "Content", "Bullets with numbers or measurable results", 6, (quant / nb) / 0.3, f"{quant} of {len(bullets)} bullets contain a number",
        "Add real measurable results only where they are true (users, speed-up, accuracy).")
    good = sum(1 for b in bullets if 8 <= len(b.split()) <= 35)
    add("bullet_length", "Content", "Bullet length 8-35 words", 4, good / nb, f"{good} of {len(bullets)} bullets", "Keep bullets between one and two lines.")
    fp = sum(bool(_FIRST_PERSON.search(b)) for b in bullets)
    add("first_person", "Content", "No first-person pronouns", 3, 1.0 if not fp else 0.5, f"{fp} bullet(s) use I/my/me", "Remove 'I', 'my', 'me' from bullets.")
    # ---- keywords
    listed = [s for s in resume.skills if s.source == "skills_section"]     # skills an ATS reads from the skills section
    n_sk = len(listed)
    add("skills_breadth", "Keywords", "Enough skills listed", 6, n_sk / 10, f"{n_sk} skills", "List at least 10 relevant technical skills you actually have.")
    ev = {s for it in [*resume.projects, *resume.experience] for s in it.skills_used}
    backed = sum(1 for s in listed if s.name in ev)
    add("skills_evidence", "Keywords", "Skills are backed by projects/experience", 6, (backed / max(n_sk, 1)) / 0.5, f"{backed} of {n_sk} skills used in a project or job",
        "Mention each key skill in at least one project or experience bullet.")
    jd_used = bool(jd_text and jd_text.strip())
    if jd_used:
        jd = extract_jd_skills(Job(source="jd", external_id="jd", title="", description=jd_text, url="jd://local"))
        w = {s: (1.0 if k == "required" else 0.5) for s, k in jd.items()}
        have = {s.name for s in resume.skills} | ev | {m.name for m in get_taxonomy().find(text)}
        cov = sum(x for s, x in w.items() if s in have) / sum(w.values()) if w else 0.0
        miss = [s for s in w if s not in have]
        add("jd_coverage", "Keywords", "Job description keyword coverage", 14, cov, f"{round(cov * 100)}% of JD skills present" + (f"; missing: {', '.join(miss[:8])}" if miss else ""),
            "Add the missing skills ONLY if you really have them; otherwise treat them as skill gaps.")

    total_w = sum(c.weight for c in checks)
    exact = 100 * sum(c.weight * c.score for c in checks) / total_w
    score = round(exact)
    cats: dict[str, list[ATSCheck]] = {}
    for c in checks:
        cats.setdefault(c.category, []).append(c)
    fixes = [c.fix for c in sorted(checks, key=lambda c: -c.weight * (1 - c.score)) if c.fix][:5]
    label = "Strong" if score >= 80 else "Fair" if score >= 60 else "Needs work"
    return ATSReport(score=score, score_exact=round(exact, 2), label=label, jd_used=jd_used, checks=checks, top_fixes=fixes,
                     categories={k: round(100 * sum(c.weight * c.score for c in v) / sum(c.weight for c in v), 1) for k, v in cats.items()})
