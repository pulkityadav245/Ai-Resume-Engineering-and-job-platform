"""Deterministic resume parser: text -> ResumeData. Works with no API key.
Best-effort on structure; the user reviews/edits the result in the UI."""
import re

from app.schemas.resume import (
    Bullet, Education, Experience, Personal, Project, ResumeData, Skill,
)
from app.services.skill_taxonomy import get_taxonomy

SECTION_ALIASES = {
    "education": ["education", "academic background", "academics", "qualifications"],
    "skills": ["skills", "technical skills", "key skills", "core competencies", "tech stack"],
    "projects": ["projects", "academic projects", "personal projects", "key projects"],
    "experience": ["experience", "work experience", "internships", "internship",
                   "professional experience", "employment", "work history"],
    "coursework": ["coursework", "relevant coursework", "relevant courses", "courses taken",
                   "academic coursework"],
    "certifications": ["certifications", "certificates", "licenses", "certifications and courses"],
    "achievements": ["achievements", "awards", "accomplishments", "honors",
                     "extracurricular", "leadership", "positions of responsibility"],
}
_HEADING = {a: sec for sec, al in SECTION_ALIASES.items() for a in al}
BULLET = re.compile(r"^\s*([\u2022\u25cf\u25aa\u25a0\u2023\u25e6\u25cb\u2219\u2013\u2014\-\*\u00b7o])\s+")
META = re.compile(r"^(technologies|technology|tech\s*stack|tech|stack|tools)(\s+(used|stack))?\s*[:\-\u2013]", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){9,11}\d")
URL = re.compile(r"(?:https?://)?(?:www\.)?(?:github\.com|linkedin\.com|gitlab\.com|leetcode\.com)/[\w\-./]+", re.I)
DEGREE = re.compile(
    r"\b(b\.?\s?tech|m\.?\s?tech|b\.?\s?e\b|m\.?\s?e\b|bca|mca|b\.?\s?sc|m\.?\s?sc|bachelors?|masters?|"
    r"diploma|class\s?x{1,2}i{0,2}|12th|10th|intermediate|higher secondary|senior secondary)\b", re.I)
INSTITUTE = re.compile(r"(university|institute|college|school|academy|iit|nit)", re.I)
YEARS = re.compile(r"((?:19|20)\d{2})(?:\s*(?:[-\u2013\u2014]|\bto\b)\s*((?:19|20)?\d{2}|present|current))?", re.I)
SCHOOL_ROW = re.compile(r"^\s*(xii|xi|x)\b", re.I)   # table rows like "XII  Some School  PCM  2022-23  89.8%"


def _years(m) -> str | None:
    if not m:
        return None
    end = m.group(2)
    if end and len(end) == 2:
        end = m.group(1)[:2] + end
    return m.group(1) + (f" - {end}" if end else "")


FUZZY = {
    "coursework": ["coursework"],
    "education": ["educat", "academic"],
    "skills": ["skill", "technolog", "competenc"],
    "projects": ["project"],
    "experience": ["experience", "internship", "employment"],
    "certifications": ["certif", "licen"],
    "achievements": ["achievement", "award", "accomplish", "honor", "extracurricular",
                     "leadership", "responsibilit", "activities"],
}


def _heading_of(line: str) -> str | None:
    if not line or len(line) > 40:
        return None
    key = re.sub(r"[^a-z& ]", "", line.lower()).strip()
    if key in _HEADING:
        return _HEADING[key]
    # short ALL-CAPS lines like "EDUCATIONAL QUALIFICATIONS" -> fuzzy match
    if line.upper() == line and re.search(r"[A-Z]", line) and len(line.split()) <= 5:
        for sec, words in FUZZY.items():
            if any(w in key for w in words):
                return sec
    return None


def split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for line in text.splitlines():
        sec = _heading_of(line.strip())
        if sec:
            current = sec
            sections.setdefault(current, [])
        else:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _parse_personal(header: str, full_text: str) -> Personal:
    lines = [l.strip() for l in header.splitlines() if l.strip()]
    name = lines[0] if lines and not EMAIL.search(lines[0]) and len(lines[0]) < 60 else None
    email = EMAIL.search(full_text)
    phone = PHONE.search(header or full_text)
    links = list(dict.fromkeys(m.group(0) for m in URL.finditer(full_text)))
    return Personal(name=name, email=email.group(0) if email else None,
                    phone=phone.group(0).strip() if phone else None, links=links)


HEADER_WORDS = {"course", "university", "branch", "year", "cgpa", "institute", "board",
                "college", "percentage", "degree", "school"}
INST_RE = re.compile(r"((?:[A-Z][\w&.'\-]*\s+){1,6}(?:University|Institute|College|School|Academy))")
SCORE_RE = re.compile(
    r"(?:(?:cgpa|gpa)\s*[:\-]?\s*\d{1,2}(?:\.\d{1,2})?)|(?:\d{1,2}(?:\.\d{1,2})?\s*(?:cgpa|gpa))"
    r"|(?:\d{2,3}(?:\.\d+)?\s*%)", re.I)


def _is_table_header(line: str) -> bool:
    """'Course University Branch Year CGPA/%' style header rows of education tables."""
    return len(set(re.findall(r"[a-z]+", line.lower())) & HEADER_WORDS) >= 3


def _parse_education(block: str) -> list[Education]:
    out: list[Education] = []
    lines = [l.strip() for l in block.splitlines() if l.strip() and not _is_table_header(l)]
    for i, line in enumerate(lines):
        dm = DEGREE.search(line) or SCHOOL_ROW.match(line)
        if not dm:
            continue
        window = lines[max(0, i - 1): i + 3]
        wtext = " ".join(window)
        # institute: on the same line (table row) or on a neighbouring line
        inst = None
        im = INST_RE.search(line[:dm.start()] + " " + line[dm.end():])
        if im:
            inst = im.group(1).strip()
        else:
            inst = next((w for w in window if INSTITUTE.search(w)), None)
            if inst:
                inst = re.sub(r"[\s,|-]*\(?(?:19|20)\d{2}.*$", "", inst).strip(" ,|-") or inst
        years = _years(YEARS.search(line) or YEARS.search(wtext))
        sm = SCORE_RE.search(line) or SCORE_RE.search(wtext)
        score = sm.group(0).strip() if sm else None
        # degree text = this line minus institute / years / score
        d = line
        if inst and inst in d:
            d = d.replace(inst, " ")
        d = SCORE_RE.sub(" ", YEARS.sub(" ", d))
        d = re.sub(r"\s+", " ", d)
        d = re.sub(r"(\s*[,|]\s*)+", ", ", d).strip(" ,|-\u2013:")
        out.append(Education(id=f"edu_{len(out)+1}", degree=d or line, institute=inst,
                             years=years, score=score))
    if not out and lines:   # heading found but no known degree keyword: keep the raw lines
        inst = next((l for l in lines if INSTITUTE.search(l)), None)
        out.append(Education(id="edu_1", degree=lines[0], institute=inst if inst != lines[0] else None,
                             years=_years(YEARS.search(" ".join(lines)))))
    return out


def _marker(line: str) -> str | None:
    m = BULLET.match(line)
    return m.group(1) if m else None


def _entries(block: str, prefix: str) -> list[tuple[str, list[str], str]]:
    """Split a Projects/Experience block into (title, bullets, raw_text).

    Two layouts are supported:
    A) titles are plain lines, details are bullets            ->  plain mode
    B) titles AND details are both bullets with DIFFERENT markers
       (e.g. '\u2022 Title (dates)' then '\u25e6 detail') -> the first line's marker = title marker.
    Lines without any marker that follow a bullet are wrapped continuations of it.
    """
    lines = [l.rstrip() for l in block.splitlines() if l.strip()]
    markers = {_marker(l) for l in lines if _marker(l)}
    title_marker = _marker(lines[0]) if lines and len(markers) >= 2 else None

    # each entry: [title, bullets, meta_lines, last_kind]
    entries: list[list] = []

    def new_entry(title: str):
        entries.append([title, [], [], "title"])

    for l in lines:
        m = _marker(l)
        text = BULLET.sub("", l).strip() if m else l.strip()
        if title_marker:
            if m == title_marker:
                new_entry(text)
            elif m:                                   # detail bullet
                if not entries:
                    continue
                if META.match(text):
                    entries[-1][2].append(text); entries[-1][3] = "meta"
                else:
                    entries[-1][1].append(text); entries[-1][3] = "bullet"
            elif entries:                             # wrapped continuation
                e = entries[-1]
                if e[3] == "bullet":
                    e[1][-1] += " " + text
                elif e[3] == "title":
                    e[0] += " " + text
                else:
                    e[2].append(text)
        else:
            if m:
                if not entries:
                    continue
                if META.match(text):
                    entries[-1][2].append(text); entries[-1][3] = "meta"
                else:
                    entries[-1][1].append(text); entries[-1][3] = "bullet"
            elif entries and META.match(text):
                entries[-1][2].append(text); entries[-1][3] = "meta"
            elif entries and entries[-1][3] == "bullet" and text[:1].islower():
                entries[-1][1][-1] += " " + text
            else:
                new_entry(text)
    return [(t, b, "\n".join([t, *meta, *b])) for t, b, meta, _ in entries]


def parse_resume(text: str) -> ResumeData:
    tax = get_taxonomy()
    sections = split_sections(text)
    personal = _parse_personal(sections.get("header", ""), text)

    # --- skills ---
    skills: dict[str, Skill] = {}
    skills_block = sections.get("skills", "")
    for m in tax.find(skills_block):
        skills[m.name] = Skill(name=m.name, category=m.category, source="skills_section")
    for m in tax.find(sections.get("coursework", "")):
        skills.setdefault(m.name, Skill(name=m.name, category=m.category, source="coursework"))
    for m in tax.find(text):
        skills.setdefault(m.name, Skill(name=m.name, category=m.category, source="project_text"))
    for acronym, implied in tax.find_implied(text).items():
        for name in implied:
            if name not in skills and name in tax.skills:
                skills[name] = Skill(name=name, category=tax.skills[name].get("category"),
                                     source="inferred", inferred_from=acronym)

    # --- projects ---
    projects: list[Project] = []
    for title, bullets, raw in _entries(sections.get("projects", ""), "proj"):
        pid = f"proj_{len(projects)+1}"
        projects.append(Project(
            id=pid, title=title,
            bullets=[Bullet(id=f"{pid}_b{i+1}", text=b) for i, b in enumerate(bullets)],
            skills_used=[m.name for m in tax.find(raw)],
        ))

    # --- experience ---
    experience: list[Experience] = []
    for title, bullets, raw in _entries(sections.get("experience", ""), "exp"):
        eid = f"exp_{len(experience)+1}"
        experience.append(Experience(
            id=eid, title=title,
            bullets=[Bullet(id=f"{eid}_b{i+1}", text=b) for i, b in enumerate(bullets)],
            skills_used=[m.name for m in tax.find(raw)],
        ))

    def simple_list(block: str) -> list[str]:
        return [BULLET.sub("", l).strip() for l in block.splitlines() if l.strip()]

    return ResumeData(
        personal=personal,
        education=_parse_education(sections.get("education", "")),
        skills=list(skills.values()),
        projects=projects,
        experience=experience,
        coursework=simple_list(sections.get("coursework", "")),
        certifications=simple_list(sections.get("certifications", "")),
        achievements=simple_list(sections.get("achievements", "")),
    )
