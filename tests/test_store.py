import asyncio

import pytest
from fastapi.testclient import TestClient

from app.cli import main as cli_main
from app.data.india import normalize_city
from app.db import session as dbs
from app.main import app
from app.services.ingest import ingest, plan_titles
from app.services.job_providers.base import ProviderError
from app.services.job_providers.mock import MockProvider
from app.services.job_store import search_jobs_db, stats
from app.services.rule_parser import parse_resume
from tests.sample_resume import SAMPLE_RESUME

RESUME = parse_resume(SAMPLE_RESUME)
client = TestClient(app)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    monkeypatch.setenv("JOBS_PROVIDER", "mock")
    dbs.reset_engine_cache()
    yield
    dbs.reset_engine_cache()


def run_ingest(**kw):
    titles = kw.pop("titles", ["node.js developer", "react developer", "software engineer", "data analyst"])
    return asyncio.run(ingest(MockProvider(), titles, kw.pop("cities", [None]), **kw))


def test_normalize_city_aliases():
    assert normalize_city("Bangalore, Karnataka") == "Bengaluru"
    assert normalize_city("Gurgaon, Haryana") == "Gurugram"
    assert normalize_city("Remote, India") == "Remote"
    assert normalize_city("Springfield") is None and normalize_city(None) is None


def test_ingest_inserts_dedups_and_is_idempotent(db):
    first = run_ingest()
    assert first.inserted >= 8 and first.failed == 0
    assert first.duplicates >= 1                       # the demo set contains a duplicate posting
    second = run_ingest()
    assert second.inserted == 0 and second.updated >= first.inserted        # re-run adds nothing new


def test_ingest_survives_provider_failures(db):
    class Flaky(MockProvider):
        n = 0
        async def search(self, *a, **k):
            Flaky.n += 1
            if Flaky.n == 1:
                raise ProviderError("Adzuna rate limit reached; try again later")
            return await super().search(*a, **k)
    st = asyncio.run(ingest(Flaky(), ["node.js developer", "react developer"], [None]))
    assert st.failed == 1 and st.inserted > 0 and "rate limit" in st.errors[0]


def test_max_requests_cap(db):
    st = run_ingest(max_requests=2)
    assert st.requests == 2


def test_search_database_ranks_and_filters_city(db):
    run_ingest()
    with dbs.session_scope() as s:
        res = search_jobs_db(RESUME, s)
        assert res.provider == "database" and res.jobs and res.jobs[0].score >= 60
        assert [m.score for m in res.jobs] == sorted((m.score for m in res.jobs), reverse=True)
        blr = search_jobs_db(RESUME, s, location="Bangalore", min_score=0)
        assert blr.jobs and all("Bengaluru" in (m.job.location or "") for m in blr.jobs)
        senior = [m for m in res.jobs if m.job.title.startswith("Senior")]
        assert all(m.score <= 40 for m in senior)       # same level gates as the live path


def test_search_empty_database_warns(db):
    with dbs.session_scope() as s:
        res = search_jobs_db(RESUME, s)
    assert res.jobs == [] and "empty" in res.warnings[0]


def test_stats_and_api(db):
    run_ingest()
    st = client.get("/api/v1/jobs/stats").json()
    assert st["total_jobs"] >= 8 and st["by_source"][0]["name"] == "mock"
    assert any(s["name"] == "React" for s in st["top_skills"])
    r = client.post("/api/v1/jobs/search", json={"resume": RESUME.model_dump(), "source": "database", "max_results": 5})
    assert r.status_code == 200 and r.json()["provider"] == "database" and len(r.json()["jobs"]) <= 5


def test_plan_titles_all_and_one_role():
    allt, one = plan_titles(None), plan_titles(["Frontend Developer"])
    assert len(allt) > len(one) >= 3 and len(set(allt)) == len(allt)


def test_cli_dry_run_ingest_and_stats(db, capsys):
    assert cli_main(["ingest", "--dry-run", "--cities", "Pune,Dehradun", "--roles", "Frontend Developer"]) == 0
    assert "requests" in capsys.readouterr().out
    assert cli_main(["ingest", "--provider", "mock", "--cities", "all-india", "--roles", "Frontend Developer",
                     "--max-requests", "5"]) == 0
    assert cli_main(["stats"]) == 0
    assert '"total_jobs"' in capsys.readouterr().out


def test_doctor_skips_without_keys_and_reports_with_stand_ins(monkeypatch):
    from app.services.doctor import run_doctor
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False); monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    lines: list[str] = []
    assert run_doctor(out=lines.append) == 0 and sum(l.startswith("SKIP") for l in lines) == 2

    lines.clear()                                              # offline stand-ins for both services
    assert run_doctor(adzuna=MockProvider(), llm_parse=parse_resume, out=lines.append) == 0
    text = "\n".join(lines)
    assert "OK" in text and "parsed" in text and "all configured services work" in text

    class Down(MockProvider):
        async def search(self, *a, **k): raise ProviderError("Adzuna rejected the credentials")
    lines.clear()
    assert run_doctor(adzuna=Down(), llm_parse=lambda t: 1 / 0, out=lines.append) == 1
    assert "FAIL" in "\n".join(lines) and "credentials" in "\n".join(lines)
