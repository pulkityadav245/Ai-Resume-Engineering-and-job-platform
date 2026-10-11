"""Defect-injection evaluation of the ATS-readiness checker (synthetic, reproducible).
Question answered: when we break one thing in a clean resume, does the matching check fire and does the score drop?
This validates that the checklist is internally consistent. It does NOT show agreement with any real ATS."""
import re

from app.services.ats import ats_check
from app.services.rule_parser import parse_resume

GOOD = """Asha Rao
Bengaluru, India | asha.rao@example.com | +91 90000 00001
github.com/asharao | linkedin.com/in/asharao

EDUCATION
B.Tech Sample Institute of Technology Computer Science 2022 - 2026 8.1 CGPA

TECHNICAL SKILLS
Languages: Python, JavaScript, SQL, Java
Web: React, Node.js, Express, MongoDB, HTML, CSS
Tools: Git, GitHub, Docker

PROJECTS
\u2022 TaskBoard (Jan 2026 - Apr 2026)
\u25e6 Built a Kanban task manager with React and Node.js that serves 40 test users.
\u25e6 Designed REST APIs with Express and MongoDB, secured with JWT authentication.
\u25e6 Containerised the application with Docker and documented the setup in the README.
\u25e6 Technologies Used: React, Node.js, Express, MongoDB, Docker
\u2022 Churn Predictor (Jul 2025 - Oct 2025)
\u25e6 Trained a scikit-learn model on 12000 customer records and reached 88% accuracy.
\u25e6 Cleaned and analysed the data with Pandas and NumPy before training the model.
\u25e6 Technologies Used: Python, Pandas, NumPy

CERTIFICATIONS
\u2022 Machine Learning Basics - Coursera

ACHIEVEMENTS
\u2022 Solved 150+ LeetCode problems
"""
State = tuple  # (text, pages, warnings, layout)


def _sub(pattern, repl, flags=0):
    return lambda st: (re.sub(pattern, repl, st[0], flags=flags), *st[1:])


def _drop_section(name):
    return lambda st: (re.sub(rf"\n{name}\n.*?(?=\n[A-Z][A-Z ]+\n|\Z)", "\n", st[0], flags=re.S), *st[1:])


DEFECTS: dict[str, tuple[callable, str]] = {          # defect -> (injector, check expected to drop below 'pass')
    "no_email": (_sub(r"asha\.rao@example\.com", ""), "email"),
    "no_phone": (_sub(r"\+91 90000 00001", ""), "phone"),
    "no_skills_section": (_drop_section("TECHNICAL SKILLS"), "core_sections"),
    "no_projects_section": (_drop_section("PROJECTS"), "core_sections"),
    "no_bullets": (_sub(r"^[\u2022\u25e6] ", "", re.M), "bullet_usage"),
    "emojis": (_sub(r"Built a", "\U0001F680 Built a"), "special_chars"),
    "first_person": (_sub(r"^\u25e6 (Built|Designed|Containerised|Trained|Cleaned)", "\u25e6 I \\1", re.M), "first_person"),
    "no_numbers": (_sub(r"\d{2,}%?\+? ?(test users|customer records)?", "many ", re.M), "quantified"),
    "mixed_date_formats": (lambda st: (st[0].replace("Jan 2026 - Apr 2026", "01/2026 - 04/2026").replace("Jul 2025 - Oct 2025", "Jul'25 - Oct'25"), *st[1:]), "date_consistency"),
    "too_long": (lambda st: (st[0], 3, *st[2:]), "length"),
    "scanned_pages": (lambda st: (st[0], st[1], ["Page 1 has no extractable text"], st[3]), "text_extractable"),
    "two_columns": (lambda st: (*st[:3], {"columns_suspected": True, "gap_line_ratio": 0.6, "images": 0}), "single_column"),
    "photo_image": (lambda st: (*st[:3], {"columns_suspected": False, "gap_line_ratio": 0.0, "images": 2}), "images"),
    "few_skills": (_sub(r"^(Languages|Web|Tools):.*$", "", re.M), "skills_breadth"),
}


def _score(state: State, jd: str | None = None):
    text, pages, warnings, layout = state
    return ats_check(text, parse_resume(text), pages=pages, warnings=warnings, jd_text=jd, layout=layout)


def run_ats_eval() -> dict:
    clean = _score((GOOD, 1, [], {}))
    rows = {}
    for name, (inject, check_id) in DEFECTS.items():
        rep = _score(inject((GOOD, 1, [], {})))
        chk = next(c for c in rep.checks if c.id == check_id)
        rows[name] = {"expected_check": check_id, "check_status": chk.status, "fired": chk.status != "pass",
                      "score": rep.score_exact, "delta": round(clean.score_exact - rep.score_exact, 2)}
    jd = "Required: React, Node.js, MongoDB and Kubernetes. Nice to have: Docker, AWS."
    with_jd = _score((GOOD, 1, [], {}), jd)
    return {"clean_score": clean.score_exact, "clean_failing_checks": [c.id for c in clean.checks if c.status == "fail"],
            "defects": rows, "detection_rate": round(sum(r["fired"] for r in rows.values()) / len(rows), 3),
            "all_scores_drop": all(r["delta"] > 0 for r in rows.values()), "with_jd_score": with_jd.score,
            "with_jd_fix": next((c.detail for c in with_jd.checks if c.id == "jd_coverage"), None)}


def render_markdown(res: dict) -> str:
    L = ["# ATS-readiness checker: defect-injection evaluation", "",
         "> SYNTHETIC clean resume with one defect injected at a time. Shows internal consistency of the checklist; "
         "it does NOT measure agreement with any real company ATS.", "",
         f"Clean resume score: **{res['clean_score']}**. Detection rate: **{res['detection_rate']:.3f}**. "
         f"Score drops for every defect: **{res['all_scores_drop']}**.", "",
         "| Injected defect | Check expected to fire | Status | Score | Drop |", "|---|---|---|---|---|"]
    L += [f"| {k} | {v['expected_check']} | {v['check_status']} | {v['score']} | {v['delta']} |" for k, v in res["defects"].items()]
    L += ["", f"With a job description (Required: React, Node.js, MongoDB, Kubernetes): score {res['with_jd_score']}; {res['with_jd_fix']}."]
    return "\n".join(L)
