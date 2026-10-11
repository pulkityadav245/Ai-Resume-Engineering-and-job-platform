"""Evaluation harness for tailoring. Produces hallucination metrics for the paper.
IMPORTANT: the default 'model' is a SIMULATED rewriter that injects fabrications at a fixed rate. It measures the
VALIDATOR (what it catches and what it lets through), not any real LLM. Real LLM numbers: run with --llm and a key."""
import random
import statistics
import zlib
from typing import Callable

from app.schemas.resume import Bullet, ResumeData, Skill
from app.services.factuality import skill_universe, validate
from app.services.rule_parser import parse_resume
from app.services.tailor import _present_skills, build_tailored
from app.services.tailor_llm import LLMRewriter, llm_available
from app.services.job_matcher import extract_jd_skills
from app.schemas.jobs import Job

SYNTH_RESUMES = {
    "mern_fresher": """Asha Rao\nasha@example.com | 9000000001\nEDUCATION\nB.Tech Sample Institute of Technology Computer Science 2022-Present 8.1 CGPA\nTECHNICAL SKILLS\nLanguages: JavaScript, Python\nWeb: React, Node.js, MongoDB, HTML, CSS\nTools: Git, GitHub\nPROJECTS\n\u2022 TaskBoard (Jan'26 \u2013 Apr'26)\n\u25e6 Built a Kanban task manager with React and Node.js used by 40 test users.\n\u25e6 Designed REST APIs with Express and MongoDB secured with JWT authentication.\n\u25e6 Technologies Used: React, Node.js, Express, MongoDB\n\u2022 Portfolio Site (Aug'25 \u2013 Sep'25)\n\u25e6 Created a responsive portfolio using HTML, CSS and JavaScript.\nACHIEVEMENTS\n\u2022 Solved 150+ LeetCode problems\n""",
    "python_fresher": """Ravi Menon\nravi@example.com | 9000000002\nEDUCATION\nB.Tech Sample University Information Technology 2021-2025 8.4 CGPA\nTECHNICAL SKILLS\nLanguages: Python, SQL, C++\nData: Pandas, NumPy, scikit-learn\nTools: Git, Linux\nPROJECTS\n\u2022 Churn Predictor (Jul'25 \u2013 Oct'25)\n\u25e6 Trained a scikit-learn model on 12000 customer records and reached 88% accuracy.\n\u25e6 Cleaned and analysed data with Pandas and NumPy.\n\u25e6 Technologies Used: Python, Pandas, scikit-learn\n\u2022 Sales Dashboard (Jan'25 \u2013 Mar'25)\n\u25e6 Built a Streamlit dashboard over a MySQL database.\nCERTIFICATIONS\n\u2022 Machine Learning Basics \u2013 Coursera\n""",
    "java_fresher": """Neha Iyer\nneha@example.com | 9000000003\nEDUCATION\nB.E Sample College of Engineering Computer Engineering 2021-2025 7.9 CGPA\nTECHNICAL SKILLS\nLanguages: Java, SQL, C\nBackend: Spring Boot, MySQL\nTools: Git, Docker\nPROJECTS\n\u2022 Library Manager (Aug'25 \u2013 Nov'25)\n\u25e6 Developed a Spring Boot application with MySQL for 300 members.\n\u25e6 Implemented role based login and REST API endpoints.\n\u25e6 Technologies Used: Java, Spring Boot, MySQL\n\u2022 Chat Server (Feb'25 \u2013 Apr'25)\n\u25e6 Wrote a multi-client chat server in Java using sockets.\n""",
}
SYNTH_JDS = {
    "fullstack": ("Full Stack Developer", "Required: React, Node.js, MongoDB and Kubernetes. Experience with AWS and GraphQL. Nice to have: Docker, TypeScript."),
    "data": ("Data Analyst", "Required: Python, SQL, Pandas and Kafka. Experience with Redis. Nice to have: Streamlit, Machine Learning, AWS."),
    "backend": ("Java Backend Developer", "Required: Java, Spring Boot, MySQL and Kubernetes. Experience with microservices and Kafka. Nice to have: Docker, Redis."),
}
TRAPS = ["Kubernetes", "Kafka", "GraphQL", "Redis", "AWS", "TypeScript"]


class SimulatedModel:
    """Deterministic stand-in for an LLM that fabricates with probability p per bullet."""
    EDITS = [lambda t: t.rstrip(".") + " using Kubernetes and Kafka.", lambda t: t.rstrip(".") + ", improving performance by 87%.",
             lambda t: "Led " + t[0].lower() + t[1:], lambda t: t.rstrip(".") + " for enterprise clients.",
             lambda t: t.rstrip(".") + " with Docker and Redis."]

    def __init__(self, p: float, seed: int):
        self.p, self.rng = p, random.Random(seed)

    def __call__(self, bullet: str, allowed: list[str], title: str) -> str:
        return self.rng.choice(self.EDITS)(bullet) if self.rng.random() < self.p else bullet


def _bullet_errors(report) -> int:
    return len({v.where for v in report.violations if v.severity == "error" and v.where.count(".") == 2})


def _trap_hit(resume: ResumeData, master: ResumeData, gap: list[str]) -> bool:
    return bool(set(gap) & _present_skills(resume) - skill_universe(master))


def _pairs():
    for rk, text in SYNTH_RESUMES.items():
        for jk, (title, jd) in SYNTH_JDS.items():
            yield rk, jk, parse_resume(text), title, jd


def _row(samples: list[dict]) -> dict:
    m = lambda k: round(statistics.mean(s[k] for s in samples), 4)  # noqa: E731
    return {"n": len(samples), "unsupported_claim_rate": m("ucr"), "fabricated_bullet_rate": m("fab"),
            "trap_capture_rate": m("trap"), "extractive_ratio": m("ext"), "jd_coverage": m("cov"),
            "outputs_passing_validator": m("pass")}


def run_tailoring_eval(seeds: int = 10, p: float = 0.5, use_llm: bool = False) -> dict:
    rows: dict[str, list[dict]] = {"A": [], "B": [], "C": []}
    for rk, jk, master, title, jd_text in _pairs():
        jd = extract_jd_skills(Job(source="jd", external_id="jd", title=title, description=jd_text, url="jd://local"))
        wts = {s: (1.0 if k == "required" else 0.5) for s, k in jd.items()}
        cov = lambda r: sum(w for s, w in wts.items() if s in _present_skills(r)) / sum(wts.values())  # noqa: E731
        sample = lambda raw, rep, gap: {"ucr": rep.unsupported_claim_rate, "fab": _bullet_errors(rep) / max(sum(len(i.bullets) for i in [*raw.projects, *raw.experience]), 1),  # noqa: E731
                                        "trap": float(_trap_hit(raw, master, gap)), "ext": rep.extractive_ratio, "cov": cov(raw), "pass": float(rep.passed)}
        from app.services.factuality import enforce
        raw, ctx = build_tailored(master, jd_text, title)                                     # A: extractive
        final, _b, after = enforce(master, raw)
        rows["A"].append(sample(final, after, ctx["gap"]))
        for sd in range(1 if use_llm else seeds):
            model: Callable = LLMRewriter() if use_llm else SimulatedModel(p, seed=zlib.crc32(f"{rk}|{jk}|{sd}".encode()))
            raw, ctx = build_tailored(master, jd_text, title, "rewrite", model)
            final, before, after = enforce(master, raw)
            rows["B"].append(sample(raw, before, ctx["gap"]))                                # B: model, no validator
            rows["C"].append(sample(final, after, ctx["gap"]))                               # C: model + validator
    label = "Real LLM" if use_llm else f"Simulated model (fabrication prob. {p})"
    return {"conditions": {f"A. Extractive selection (no model)": _row(rows["A"]),
                           f"B. {label}, no validator": _row(rows["B"]),
                           f"C. {label} + validator (ours)": _row(rows["C"])},
            "detection": detection_test(), "simulated": not use_llm, "seeds": 1 if use_llm else seeds}


def _inject(kind: str, raw: ResumeData, master: ResumeData) -> ResumeData:
    r, universe = raw.model_copy(deep=True), skill_universe(master)
    trap = next(t for t in TRAPS if t not in universe)
    item = next(i for i in r.projects if i.bullets)
    b = item.bullets[0]
    def mark(text): item.bullets[0] = Bullet(id=b.id, text=text, source_id=b.id, rewritten=True)  # noqa: E731
    if kind == "skill_in_skills":
        r.skills.append(Skill(name=trap))
    elif kind == "skill_in_bullet":
        mark(b.text.rstrip(".") + f" using {trap}.")
    elif kind == "number":
        mark(b.text.rstrip(".") + ", improving speed by 73%.")
    elif kind == "inflated_qualifier":
        mark("Led " + b.text[0].lower() + b.text[1:])
    elif kind == "entity_title":
        item.title = "Distributed Payments Platform (Jan'26 \u2013 Apr'26)"
    elif kind == "date":
        item.title = item.title + " 2031"
    elif kind == "untraceable":
        item.bullets[0] = Bullet(id=b.id, text=b.text, source_id="does_not_exist", rewritten=False)
    elif kind == "unseen_token":
        mark(b.text.rstrip(".") + " via NovaQL.")
    return r


EXPECTED = {"skill_in_skills": {"skill"}, "skill_in_bullet": {"skill"}, "number": {"number"}, "inflated_qualifier": {"inflated_qualifier"},
            "entity_title": {"entity"}, "date": {"date", "entity"}, "untraceable": {"untraceable"}, "unseen_token": {"unseen_token"}}


def detection_test() -> dict:
    """Inject known fabrications into clean extractive output; measure how many the validator flags."""
    out = {k: [0, 0] for k in EXPECTED}
    clean_flagged = clean_total = 0
    for _rk, _jk, master, title, jd_text in _pairs():
        raw, _ = build_tailored(master, jd_text, title)
        clean_total += 1
        clean_flagged += not validate(master, raw).passed
        for kind, types in EXPECTED.items():
            rep = validate(master, _inject(kind, raw, master))
            out[kind][1] += 1
            out[kind][0] += any(v.type in types for v in rep.violations)
    return {"by_kind": {k: {"detected": d, "injected": n, "recall": round(d / n, 3)} for k, (d, n) in out.items()},
            "overall_recall": round(sum(d for d, _ in out.values()) / sum(n for _, n in out.values()), 3),
            "false_positive_rate_on_clean_outputs": round(clean_flagged / clean_total, 3)}


def render_markdown(res: dict) -> str:
    L = ["# Tailoring hallucination evaluation", "",
         "> SYNTHETIC fixtures (3 resumes x 3 job descriptions). " + ("The model is SIMULATED: it measures the validator, not a real LLM." if res["simulated"] else "Real LLM run."),
         f"> Runs per pair: {res['seeds']}. Each JD contains skills the candidate lacks ('traps').", "",
         "| Condition | n | Unsupported claim rate | Fabricated bullet rate | Trap capture | Extractive ratio | JD coverage |", "|---|---|---|---|---|---|---|"]
    for name, r in res["conditions"].items():
        L.append(f"| {name} | {r['n']} | {r['unsupported_claim_rate']:.3f} | {r['fabricated_bullet_rate']:.3f} | {r['trap_capture_rate']:.3f} | {r['extractive_ratio']:.3f} | {r['jd_coverage']:.3f} |")
    d = res["detection"]
    L += ["", "## Validator detection test (injected fabrications)", "", "| Fabrication kind | Detected / injected | Recall |", "|---|---|---|"]
    L += [f"| {k} | {v['detected']}/{v['injected']} | {v['recall']:.3f} |" for k, v in d["by_kind"].items()]
    L += ["", f"Overall recall: **{d['overall_recall']:.3f}**. False-positive rate on clean extractive outputs: **{d['false_positive_rate_on_clean_outputs']:.3f}**.", "",
          "Limits: the validator checks skills, numbers, dates, titles/organisations, leadership/scale wording and source traceability. "
          "It does not prove a rewritten sentence keeps its exact meaning. Fixtures are tiny and synthetic; do not report these numbers as real-world accuracy."]
    return "\n".join(L)
