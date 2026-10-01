import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.resume import ResumeData, Skill
from app.services.grounding import ground_resume
from app.services.pdf_extract import ScannedPDFError, extract_pdf, extract_text, ExtractionError
from app.services.role_inference import infer_roles
from app.services.rule_parser import parse_resume, split_sections
from app.services.skill_taxonomy import get_taxonomy
from tests.sample_resume import SAMPLE_RESUME

client = TestClient(app)


def make_pdf(text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in text.splitlines():
        c.drawString(40, y, line)
        y -= 14
        if y < 40:
            c.showPage(); y = 800
    c.save()
    return buf.getvalue()


# ---------- taxonomy ----------
def test_taxonomy_boundaries():
    tax = get_taxonomy()
    names = {m.name for m in tax.find("Expert in JavaScript and Node.js, plus C++ and ReactJS")}
    assert {"JavaScript", "Node.js", "C++", "React"} <= names
    assert "Java" not in names          # must not match inside JavaScript
    assert "C" not in names             # 'C' must not match inside C++


def test_taxonomy_canonical_aliases():
    tax = get_taxonomy()
    assert tax.canonical("ReactJS") == "React"
    assert tax.canonical("postgres") == "PostgreSQL"
    assert tax.canonical("totally unknown tool") is None


# ---------- sections / parser ----------
def test_sections_split():
    s = split_sections(SAMPLE_RESUME)
    assert {"education", "skills", "projects", "experience", "certifications", "achievements"} <= set(s)


def test_rule_parser_structure():
    r = parse_resume(SAMPLE_RESUME)
    assert r.personal.name == "Aarav Sharma"
    assert r.personal.email == "aarav.sharma@example.com"
    assert any("github.com/aaravsharma" in l for l in r.personal.links)
    assert len(r.education) >= 1 and "B.Tech" in r.education[0].degree
    assert len(r.projects) == 2
    assert r.projects[0].title.startswith("TaskBoard")
    assert len(r.projects[0].bullets) == 3
    assert {"React", "Node.js", "MongoDB", "Docker", "JWT"} <= set(r.projects[0].skills_used)
    assert len(r.experience) == 1 and "Jest" in r.experience[0].skills_used
    names = {s.name for s in r.skills}
    assert {"Python", "Java", "C++", "React", "Git", "Docker", "Machine Learning"} - names == {"Machine Learning"}


def test_ids_unique():
    r = parse_resume(SAMPLE_RESUME)
    ids = [b.id for p in r.projects for b in p.bullets] + [p.id for p in r.projects]
    assert len(ids) == len(set(ids))


# ---------- grounding ----------
def test_grounding_removes_invented_skill_and_flags_fake_numbers():
    r = parse_resume(SAMPLE_RESUME)
    r.skills.append(Skill(name="Kubernetes", source="skills_section"))     # LLM hallucination
    r.projects[0].skills_used.append("Kafka")                              # hallucination
    r.projects[0].bullets[0].text = "Built a task manager serving 5000+ users"  # invented number
    r, issues = ground_resume(r, SAMPLE_RESUME)
    removed = {i.value for i in issues if i.action == "removed"}
    assert {"Kubernetes", "Kafka"} <= removed
    assert "Kubernetes" not in {s.name for s in r.skills}
    assert any(i.action == "flagged" and "5000" in i.reason for i in issues)


def test_grounding_keeps_clean_parse_clean():
    r = parse_resume(SAMPLE_RESUME)
    _, issues = ground_resume(r, SAMPLE_RESUME)
    assert issues == [], issues


def test_mern_inference_flagged_not_stated():
    text = SAMPLE_RESUME.replace("Web: React, Node.js, Express, MongoDB, HTML, CSS\n", "Web: MERN stack, HTML, CSS\n")
    text = text.replace("Tech Stack: MongoDB, Express, React, Node.js, Docker", "Tech Stack: Docker")
    text = text.replace("React and Node.js", "MERN").replace("React and CSS", "CSS").replace("Express and MongoDB", "MERN")
    r = parse_resume(text)
    inferred = {s.name: s for s in r.skills if s.source == "inferred"}
    assert "MongoDB" in inferred and inferred["MongoDB"].inferred_from == "MERN"


# ---------- extraction ----------
def test_pdf_roundtrip():
    out = extract_pdf(make_pdf(SAMPLE_RESUME))
    assert "TaskBoard" in out.text and out.pages == 1


def test_scanned_pdf_rejected():
    with pytest.raises(ScannedPDFError):
        extract_pdf(make_pdf("hi"))


def test_unsupported_type():
    with pytest.raises(ExtractionError):
        extract_text("resume.txt", b"x")


def test_docx_extract():
    import docx
    d = docx.Document()
    for line in SAMPLE_RESUME.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO(); d.save(buf)
    assert "TaskBoard" in extract_text("cv.docx", buf.getvalue()).text


# ---------- role inference ----------
def test_roles_for_mern_fresher():
    r = parse_resume(SAMPLE_RESUME)
    res = infer_roles(r)
    assert res.level == "fresher"
    top3 = [x.role for x in res.roles[:3]]
    assert "Full Stack Developer" in top3, top3
    fs = next(x for x in res.roles if x.role == "Full Stack Developer")
    assert "React" in fs.evidence and fs.query_titles[0].startswith(("Junior", "Graduate"))
    assert "Java Developer" not in top3 or res.roles[0].score >= next(x for x in res.roles if x.role == "Java Developer").score


def test_roles_empty_resume():
    res = infer_roles(ResumeData())
    assert res.roles == []


# ---------- API ----------
def test_api_parse_and_infer_end_to_end():
    pdf = make_pdf(SAMPLE_RESUME)
    resp = client.post("/api/v1/resume/parse", files={"file": ("cv.pdf", pdf, "application/pdf")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parser"] == "rule_based" and body["grounding_issues"] == []
    roles = client.post("/api/v1/roles/infer", json=body["resume"])
    assert roles.status_code == 200
    assert roles.json()["roles"][0]["score"] > 30


def test_api_rejects_bad_file():
    resp = client.post("/api/v1/resume/parse", files={"file": ("cv.txt", b"hello", "text/plain")})
    assert resp.status_code == 422


# ---------- regression: false-positive skills ----------
def test_nodejs_does_not_imply_javascript_or_verbs_match():
    tax = get_taxonomy()
    names = {m.name for m in tax.find("Built APIs with Node.js. Express interest in the rest of the team. linked list node.")}
    assert "JavaScript" not in names          # 'js' inside 'Node.js' must not match
    assert "REST API" not in names            # plain word 'rest' must not match
    assert "Express.js" not in {m.name for m in tax.find("I express my thanks")}
    assert "Express.js" in {m.name for m in tax.find("Web: React, Node.js, Express, MongoDB")}


def test_institute_has_no_trailing_years():
    r = parse_resume(SAMPLE_RESUME)
    assert r.education[0].institute == "Example Institute of Technology, Dehradun"
    assert r.education[0].years == "2022 - 2026"


# ---------- regression: layout seen in a real student resume ----------
NESTED = """Riya Verma
riya@example.com | 9000000000

ACADEMIC QUALIFICATIONS
Bachelor of Technology in Computer Science, Sample University, Dehradun
2022 - 2026   CGPA: 8.1

TECHNICAL SKILLS
Languages: Python, Java
Web: React, Node.js, MongoDB

PROJECTS
\u2022 Peer Learning Platform (Jan'25 \u2013 Mar'25)
\u25e6 Developed a peer-to-peer learning platform that allows users to register, showcase skills, and
send or accept learning requests.
\u25e6 Implemented user registration, login authentication, profile management and skill matching.
\u25e6 Technologies Used: MongoDB, Express.js, Node.js, JavaScript.
\u2022 Memory Manager Simulator (Jul'25 \u2013 Nov'25)
\u25e6 Developed a Virtual Memory simulator supporting FIFO, LRU and
Optimal algorithms.
\u25e6 Technologies Used: Python, FastAPI, Streamlit.

CERTIFICATIONS
\u2022 Java Fundamentals \u2013 BoardInfinity
"""


def test_nested_bullet_layout_titles_vs_details():
    r = parse_resume(NESTED)
    assert [p.title for p in r.projects] == [
        "Peer Learning Platform (Jan'25 \u2013 Mar'25)", "Memory Manager Simulator (Jul'25 \u2013 Nov'25)"]
    p1, p2 = r.projects
    assert len(p1.bullets) == 2            # 'Technologies Used' is metadata, not a bullet
    assert p1.bullets[0].text.endswith("learning requests.")      # wrapped line joined
    assert p2.bullets[0].text.endswith("Optimal algorithms.")
    assert {"MongoDB", "Express.js", "Node.js", "JavaScript"} <= set(p1.skills_used)
    assert {"Python", "FastAPI", "Streamlit"} <= set(p2.skills_used)


def test_caps_heading_education_detected():
    r = parse_resume(NESTED)
    assert len(r.education) == 1
    assert "Bachelor of Technology" in r.education[0].degree
    assert r.education[0].years == "2022 - 2026"


def test_pdf_hyperlinks_extracted():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in SAMPLE_RESUME.splitlines():
        c.drawString(40, y, line); y -= 14
    c.drawString(40, 60, "GitHub")
    c.linkURL("https://github.com/someone", (40, 55, 90, 75))
    c.save()
    ex = extract_pdf(buf.getvalue())
    assert "https://github.com/someone" in ex.links


def test_debug_endpoint():
    resp = client.post("/api/v1/resume/debug", files={"file": ("cv.pdf", make_pdf(SAMPLE_RESUME), "application/pdf")})
    assert resp.status_code == 200
    assert "education" in resp.json()["sections_found"]


# ---------- regression 3: education table + coursework section (real resume layout) ----------
TABLE_RESUME = """Riya Verma
riya@example.com

EDUCATION
Course University Branch Year CGPA/%
B.Tech Sample Era Hill University Computer Science and Engineering 2023-Present 8.64 CGPA

TECHNICAL SKILLS
Languages: Python, Java

RELEVANT COURSEWORK
Data Structures And Algorithms
Object Oriented Programming (Java)
Operating System, DBMS, Computer Networks

CERTIFICATIONS
\u2022 Linux And SQL \u2013 Google
"""


def test_education_table_row_and_header_skipped():
    r = parse_resume(TABLE_RESUME)
    assert len(r.education) == 1
    e = r.education[0]
    assert e.degree == "B.Tech Computer Science and Engineering"
    assert e.institute == "Sample Era Hill University"
    assert e.years == "2023 - Present"
    assert e.score and "8.64" in e.score


def test_coursework_separate_from_certifications():
    r = parse_resume(TABLE_RESUME)
    assert r.certifications == ["Linux And SQL \u2013 Google"]
    assert "Data Structures And Algorithms" in r.coursework
    src = {s.name: s.source for s in r.skills}
    assert src["Data Structures and Algorithms"] == "coursework"
    assert src["Python"] == "skills_section"


def test_analyze_endpoint_one_call():
    resp = client.post("/api/v1/analyze", files={"file": ("cv.pdf", make_pdf(SAMPLE_RESUME), "application/pdf")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["parse"]["resume"]["projects"] and body["roles"]["roles"][0]["role"]
