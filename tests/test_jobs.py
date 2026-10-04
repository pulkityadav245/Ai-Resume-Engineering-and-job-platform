import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.jobs import Job
from app.services.job_matcher import (experience_required, extract_jd_skills, level_fit,
                                      match_job, title_relevance)
from app.services.job_providers.adzuna import AdzunaProvider
from app.services.job_providers.base import CachedProvider, ProviderError
from app.services.job_providers.factory import get_provider
from app.services.job_providers.mock import MockProvider
from app.services.job_search import dedup_key, search_jobs
from app.services.rule_parser import parse_resume
from tests.sample_resume import SAMPLE_RESUME

client = TestClient(app)
RESUME = parse_resume(SAMPLE_RESUME)      # MERN fresher with React/Node/Mongo/Docker/Jest...

MOCK_APP_KEY = "dummy_test_key"
ADZUNA_PAYLOAD = {"count": 2, "results": [
    {"id": "111", "title": "<strong>Node.js</strong> Developer", "description": "Build APIs with <strong>Node.js</strong> &amp; MongoDB.",
     "redirect_url": "https://www.adzuna.in/land/ad/111?utm=api", "created": "2026-09-30T10:00:00Z",
     "company": {"display_name": "Acme Pvt Ltd"}, "location": {"display_name": "Bengaluru, Karnataka"},
     "salary_min": 400000, "salary_max": 600000, "salary_is_predicted": "1", "contract_time": "full_time"},
    {"id": "222", "title": "No link job", "description": "x"},          # skipped: no redirect_url
]}


def adz(handler):
    return AdzunaProvider("ID", MOCK_APP_KEY, "in", transport=httpx.MockTransport(handler))


# ---------- Adzuna provider ----------
def test_adzuna_request_shape_and_mapping():
    seen = {}

    def handler(req: httpx.Request):
        seen["path"], seen["q"] = req.url.path, dict(req.url.params)
        return httpx.Response(200, json=ADZUNA_PAYLOAD)

    jobs = asyncio.run(adz(handler).search("node.js developer", "Bengaluru", 1, 20))
    assert seen["path"] == "/v1/api/jobs/in/search/1"
    assert seen["q"]["what"] == "node.js developer" and seen["q"]["where"] == "Bengaluru"
    assert seen["q"]["app_id"] == "ID" and seen["q"]["results_per_page"] == "20"
    assert len(jobs) == 1
    j = jobs[0]
    assert j.title == "Node.js Developer" and "&amp;" not in j.description and "<strong>" not in j.description
    assert j.company == "Acme Pvt Ltd" and j.salary_predicted is True and j.url.startswith("https://www.adzuna.in")


def test_adzuna_per_page_capped_at_50():
    seen = {}

    def handler(req):
        seen.update(dict(req.url.params)); return httpx.Response(200, json={"results": []})

    asyncio.run(adz(handler).search("x", per_page=500))
    assert seen["results_per_page"] == "50"


@pytest.mark.parametrize("status,needle", [(401, "credentials"), (429, "rate limit"), (500, "HTTP 500")])
def test_adzuna_errors_never_leak_key(status, needle):
    with pytest.raises(ProviderError) as e:
        asyncio.run(adz(lambda r: httpx.Response(status)).search("x"))
    assert needle in str(e.value) and MOCK_APP_KEY not in str(e.value)


def test_adzuna_network_error_is_provider_error_without_url():
    def boom(req): raise httpx.ConnectError("down", request=req)
    with pytest.raises(ProviderError) as e:
        asyncio.run(adz(boom).search("x"))
    assert "app_key" not in str(e.value) and MOCK_APP_KEY not in str(e.value)


def test_cache_prevents_second_api_call():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1; return httpx.Response(200, json=ADZUNA_PAYLOAD)

    cp = CachedProvider(adz(handler), ttl_seconds=60)
    asyncio.run(cp.search("Node.js Developer", "Delhi"))
    asyncio.run(cp.search("  node.js developer ", "delhi"))       # same after normalisation
    assert calls["n"] == 1 and cp.hits == 1 and cp.misses == 1


# ---------- matcher pieces ----------
def mk(title, desc="", **kw):
    return Job(source="t", external_id=title, title=title, description=desc, url="https://x.test/1", **kw)


def test_required_vs_preferred_classification():
    jd = extract_jd_skills(mk("Dev", "Required: React and Node.js. Nice to have: Docker and AWS."))
    assert jd["React"] == "required" and jd["Node.js"] == "required"
    assert jd["Docker"] == "preferred" and jd["AWS"] == "preferred"


def test_experience_years_parsing():
    assert experience_required(mk("x", "3-5 years of experience")) == 3
    assert experience_required(mk("x", "5+ years")) == 5
    assert experience_required(mk("x", "Freshers welcome")) is None


def test_level_fit_rules():
    assert level_fit("fresher", "Senior Engineer", None)[0] == 0.0
    assert level_fit("fresher", "Developer", 4)[0] == 0.2
    assert level_fit("fresher", "Developer", 2)[0] == 0.7
    assert level_fit("fresher", "Junior Developer", 0)[0] == 1.0
    assert level_fit("experienced", "Junior Developer", None)[0] == 0.6


def test_title_relevance():
    assert title_relevance("Backend Developer (Node.js)", ["Node.js Developer"]) == 1.0
    assert title_relevance("Marketing Manager", ["Node.js Developer"]) < 0.4


def test_match_reports_gaps_without_inventing_skills():
    job = mk("Junior Full Stack Developer", "Required: React, Node.js, Kubernetes. Nice to have: Kafka.")
    m = match_job(job, RESUME, "fresher", ["Full Stack Developer"], ["Full Stack Developer"])
    assert {"React", "Node.js"} <= set(m.matched_skills)
    assert m.missing_required == ["Kubernetes"] and m.missing_preferred == ["Kafka"]
    assert "Kubernetes" not in {s.name for s in RESUME.skills}       # resume untouched


def test_low_confidence_flag_when_snippet_has_no_skills():
    m = match_job(mk("Developer", "Great team, great culture."), RESUME, "fresher", ["Software Engineer"], ["x"])
    assert any("low confidence" in f for f in m.flags)


# ---------- dedup ----------
def test_dedup_key_ignores_case_punct_and_area():
    a = mk("Junior Developer!", company="Demo Corp", location="Bengaluru, Karnataka")
    b = mk("junior developer", company="demo corp.", location="Bengaluru")
    assert dedup_key(a) == dedup_key(b)


# ---------- full search flow on the demo provider ----------
def run_search(**kw):
    return asyncio.run(search_jobs(RESUME, MockProvider(), **kw))


def test_search_flow_ranks_relevant_fresher_jobs_first_and_dedups():
    res = run_search()
    assert res.provider == "mock" and res.level == "fresher"
    assert any("DEMO MODE" in w for w in res.warnings)
    titles = [m.job.title for m in res.jobs]
    assert res.after_dedup < res.total_fetched                                   # duplicates were dropped
    assert titles.count("Junior Full Stack Developer (MERN)") == 1
    top = res.jobs[0]
    assert top.score >= 60 and top.via_roles
    by_title = {m.job.title: m for m in res.jobs}
    if "Senior Full Stack Engineer" in by_title:                                 # fresher must not see seniors on top
        assert by_title["Senior Full Stack Engineer"].score < top.score
        assert by_title["Senior Full Stack Engineer"].level_fit == 0.0
    if "Java Spring Boot Developer" in by_title:
        assert by_title["Java Spring Boot Developer"].score < by_title["Junior Full Stack Developer (MERN)"].score
    assert [m.score for m in res.jobs] == sorted((m.score for m in res.jobs), reverse=True)


def test_search_with_custom_role_and_location_filter():
    res = run_search(roles=["react developer"], location="Remote")
    assert res.roles_used[0].queries == ["react developer"] and res.roles_used[0].role_score is None
    assert res.jobs and all("Remote" in (m.job.location or "") for m in res.jobs)


def test_search_empty_resume_returns_warning_not_crash():
    from app.schemas.resume import ResumeData
    res = asyncio.run(search_jobs(ResumeData(), MockProvider()))
    assert res.jobs == [] and "No target roles" in res.warnings[0]


def test_search_survives_provider_failure():
    class Broken(MockProvider):
        name = "broken"
        async def search(self, *a, **k): raise ProviderError("Adzuna rate limit reached; try again later")
    res = asyncio.run(search_jobs(RESUME, Broken()))
    assert res.jobs == [] and any("rate limit" in w for w in res.warnings)
    assert any("All provider searches failed" in w for w in res.warnings)


def test_partial_failure_still_returns_jobs():
    class Flaky(MockProvider):
        name = "flaky"
        n = 0
        async def search(self, *a, **k):
            Flaky.n += 1
            if Flaky.n == 1: raise ProviderError("boom")
            return await super().search(*a, **k)
    res = asyncio.run(search_jobs(RESUME, Flaky()))
    assert res.jobs and any("failed" in w for w in res.warnings)


# ---------- API ----------
@pytest.fixture(autouse=False)
def mock_env(monkeypatch):
    monkeypatch.setenv("JOBS_PROVIDER", "mock")
    get_provider.cache_clear()
    yield
    get_provider.cache_clear()


def test_api_jobs_search(mock_env):
    r = client.post("/api/v1/jobs/search", json={"resume": RESUME.model_dump(), "max_results": 5})
    assert r.status_code == 200, r.text
    b = r.json()
    assert len(b["jobs"]) <= 5 and b["jobs"][0]["job"]["url"].startswith("https://")
    assert b["roles_used"] and b["level"] == "fresher"


def test_api_503_when_adzuna_selected_without_keys(monkeypatch):
    monkeypatch.setenv("JOBS_PROVIDER", "adzuna")
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False); monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    get_provider.cache_clear()
    r = client.post("/api/v1/jobs/search", json={"resume": RESUME.model_dump()})
    get_provider.cache_clear()
    assert r.status_code == 503 and "ADZUNA" in r.json()["detail"]


def test_api_analyze_with_jobs(mock_env):
    from tests.test_pipeline import make_pdf
    r = client.post("/api/v1/analyze?include_jobs=true",
                    files={"file": ("cv.pdf", make_pdf(SAMPLE_RESUME), "application/pdf")})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["roles"]["roles"] and b["jobs"]["jobs"]


def test_fresher_level_gates_cap_scores():
    skills = "Required: React, Node.js, Express, MongoDB, JavaScript, Git, HTML, CSS, REST API."
    senior = match_job(mk("Senior Full Stack Developer", skills), RESUME, "fresher", ["Full Stack Developer"], ["x"])
    veteran = match_job(mk("Full Stack Developer", skills + " 5+ years of experience."), RESUME, "fresher", ["Full Stack Developer"], ["x"])
    entry = match_job(mk("Full Stack Developer", skills), RESUME, "fresher", ["Full Stack Developer"], ["x"])
    assert senior.score <= 40 and veteran.score <= 55 and entry.score > 80
