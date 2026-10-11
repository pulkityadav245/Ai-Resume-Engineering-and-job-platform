import random
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.resume import Bullet, Skill
from app.services.factuality import enforce, validate
from app.services.keyword_profile import build_keyword_profile
from app.services.rule_parser import parse_resume
from app.services.tailor import build_tailored, tailor_resume
from app.services.tailor_eval import SimulatedModel, detection_test, run_tailoring_eval
from app.services.title_normalizer import canonical_title
from tests.sample_resume import SAMPLE_RESUME

client = TestClient(app)
MASTER = parse_resume(SAMPLE_RESUME)
JD = "We need a developer. Required: React, Node.js, MongoDB and Kubernetes. Nice to have: Docker, AWS."


# ---------- extractive tailoring ----------
def test_extractive_tailoring_never_adds_the_gap_skill_and_passes_validation():
    r = tailor_resume(MASTER, JD, "Full Stack Developer")
    assert "Kubernetes" in r.skill_gap and "Kubernetes" not in {s.name for s in r.tailored.skills}
    assert set(r.matched_skills) >= {"React", "Node.js", "MongoDB"}
    assert r.factuality.passed and r.factuality.extractive_ratio == 1.0 and r.factuality.traceability_coverage == 1.0
    assert r.coverage.after <= r.coverage.ceiling < 1.0
    assert all(t.source_id for t in r.trace) and not any(t.rewritten for t in r.trace)


def test_skills_are_reordered_jd_relevant_first_and_projects_limited():
    r = tailor_resume(MASTER, JD, "Full Stack Developer", max_projects=1)
    assert [s.name for s in r.tailored.skills][:3] == ["React", "Node.js", "MongoDB"]
    assert len(r.tailored.projects) == 1 and r.tailored.projects[0].title.startswith("TaskBoard")


# ---------- model rewrite + enforcement ----------
def fabricator(bullet, allowed, title):
    return bullet.rstrip(".") + " using Kubernetes, improving speed by 87% for enterprise clients."


def test_hallucinating_rewriter_is_caught_and_reverted():
    r = tailor_resume(MASTER, JD, "Full Stack Developer", mode="rewrite", rewriter=fabricator)
    b4 = r.factuality_before_enforcement
    assert not b4.passed and {"skill", "number", "inflated_qualifier"} <= set(b4.by_type)
    assert r.factuality.passed
    src = {b.id: b.text for it in MASTER.projects for b in it.bullets}
    assert all(b.text == src[b.id] for it in r.tailored.projects for b in it.bullets)
    assert "Kubernetes" not in " ".join(b.text for it in r.tailored.projects for b in it.bullets)


def test_enforcement_guarantee_holds_for_many_random_fabrications():
    for seed in range(40):
        raw, _ = build_tailored(MASTER, JD, "Full Stack Developer", "rewrite", SimulatedModel(0.7, seed))
        final, _before, after = enforce(MASTER, raw)
        assert after.passed, (seed, after.violations[:3])


def test_faithful_rewrite_is_accepted():
    def faithful(b, allowed, t):
        return b                                    # identical text: nothing new to verify
    r = tailor_resume(MASTER, JD, mode="rewrite", rewriter=faithful)
    assert r.factuality.passed and r.factuality_before_enforcement.passed


# ---------- validator checks ----------
def _raw():
    return build_tailored(MASTER, JD, "Full Stack Developer")[0]


def test_validator_flags_each_fabrication_kind():
    r = _raw()
    r.skills.append(Skill(name="Kubernetes"))
    assert "skill" in validate(MASTER, r).by_type
    r = _raw()
    r.projects[0].title = "Payments Platform (Jan'26)"
    assert "entity" in validate(MASTER, r).by_type
    r = _raw()
    r.education[0].degree = "PhD in Physics"
    assert "entity" in validate(MASTER, r).by_type
    r = _raw()
    b = r.projects[0].bullets[0]
    r.projects[0].bullets[0] = Bullet(id=b.id, text=b.text, source_id="nope", rewritten=False)
    assert "untraceable" in validate(MASTER, r).by_type


def test_detection_test_catches_every_injected_kind_without_false_positives():
    d = detection_test()
    assert d["overall_recall"] == 1.0 and d["false_positive_rate_on_clean_outputs"] == 0.0


def test_tailoring_eval_shows_validator_effect():
    res = run_tailoring_eval(seeds=3, p=0.5)
    a, b, c = (v for v in res["conditions"].values())
    assert b["fabricated_bullet_rate"] > 0.2 and c["fabricated_bullet_rate"] == 0 and a["fabricated_bullet_rate"] == 0
    assert c["trap_capture_rate"] == 0 and b["trap_capture_rate"] > 0 and res["simulated"]


# ---------- API ----------
def test_tailor_endpoint_extractive_and_rewrite_needs_key(monkeypatch):
    body = {"resume": MASTER.model_dump(), "jd_text": JD, "jd_title": "Full Stack Developer"}
    r = client.post("/api/v1/tailor", json=body)
    assert r.status_code == 200 and r.json()["factuality"]["passed"] and "Kubernetes" in r.json()["skill_gap"]
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.post("/api/v1/tailor", json={**body, "mode": "rewrite"}).status_code == 503
    assert client.post("/api/v1/tailor", json={**body, "jd_text": "short"}).status_code == 422


# ---------- keyword profile (G1) ----------
def test_keyword_profile_rewards_evidence_recency_and_certificates():
    from tests.test_pipeline import NESTED
    m = parse_resume(NESTED)
    w = {k.skill: k for k in build_keyword_profile(m, today=date(2025, 6, 1)).skills}
    assert "project_evidence" in w["MongoDB"].components and w["MongoDB"].weight > w["React"].weight
    assert "recent_bonus" in w["MongoDB"].components
    assert any("certification" in k.components for k in build_keyword_profile(m).skills)
    old = {k.skill: k for k in build_keyword_profile(m, today=date(2030, 1, 1)).skills}
    assert "recent_bonus" not in old["MongoDB"].components
    assert build_keyword_profile(m).skills[0].normalized == 1.0


# ---------- title normalizer (G3) ----------
CASES = [("Sr. SDE-2 (Payments) - Bengaluru", "Software Engineer", "senior"), ("Junior Full Stack Developer (MERN)", "Full Stack Developer", "junior"),
         ("Software Developer II", "Software Engineer", "mid"), ("SDE-1", "Software Engineer", "junior"),
         ("Associate Software Engineer", "Software Engineer", "junior"), ("Graduate Engineer Trainee", "Graduate Engineer Trainee", "fresher"),
         ("Node JS Developer", "Node.js Developer", "unspecified"), ("Front-End Developer", "Frontend Developer", "unspecified"),
         ("Backend Engineer | Pune", "Backend Developer", "unspecified"), ("Python Developer Intern", "Python Developer", "intern"),
         ("Software Engineer - Backend", "Backend Developer", "unspecified"), ("Developer - React", "React Developer", "unspecified"),
         ("Senior Java Developer", "Java Developer", "senior"), ("DevOps Engineer", "DevOps Engineer", "unspecified"),
         ("Data Analyst Intern", "Data Analyst", "intern"), ("Machine Learning Engineer", "Machine Learning Engineer", "unspecified")]


@pytest.mark.parametrize("raw,title,level", CASES)
def test_title_normalizer(raw, title, level):
    c = canonical_title(raw)
    assert (c.title, c.level) == (title, level)
