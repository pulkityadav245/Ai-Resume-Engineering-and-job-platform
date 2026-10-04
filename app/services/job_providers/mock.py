"""Offline demo provider: FICTIONAL jobs from data/sample_jobs.json.
Lets the team develop/demo without API keys or quota. Never use as real results."""
import json
import re
from pathlib import Path

from app.schemas.jobs import Job
from app.services.job_providers.base import JobProvider

DATA = Path(__file__).resolve().parents[2] / "data" / "sample_jobs.json"
_TOK = re.compile(r"[a-z0-9+#.]+")


class MockProvider(JobProvider):
    name = "mock"

    def __init__(self):
        raw = json.loads(DATA.read_text(encoding="utf-8"))["jobs"]
        self.jobs = [Job(source=self.name, **j) for j in raw]

    async def search(self, query, location=None, page=1, per_page=20):
        q = {t.strip(".") for t in _TOK.findall(query.lower())} - {"developer", "engineer", "software"}
        if not q:
            q = {t.strip(".") for t in _TOK.findall(query.lower())}
        scored = []
        for j in self.jobs:
            title_toks = {t.strip(".") for t in _TOK.findall(j.title.lower())}
            body_toks = {t.strip(".") for t in _TOK.findall(j.description.lower())}
            s = 2 * len(q & title_toks) + len(q & body_toks)
            if location and location.lower() not in (j.location or "").lower():
                continue
            if s > 0:
                scored.append((s, j))
        scored.sort(key=lambda x: -x[0])
        start = (page - 1) * per_page
        return [j for _, j in scored][start:start + per_page]
