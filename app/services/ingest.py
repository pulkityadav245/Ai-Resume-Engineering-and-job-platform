"""Ingestion: provider -> many (query x city x page) requests -> normalise -> store.
Run from the CLI/scheduler, NOT per user request. Quota is respected via max_requests + concurrency."""
import asyncio
from dataclasses import dataclass, field

from app.db.session import session_scope
from app.services.job_providers.base import JobProvider, ProviderError
from app.services.job_store import upsert_jobs
from app.services.role_inference import get_role_profiles


@dataclass
class IngestStats:
    requests: int = 0
    failed: int = 0
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)


def plan_titles(roles: list[str] | None = None) -> list[str]:
    """All query + fresher titles of the chosen role profiles (None/'all' = every profile), de-duplicated."""
    wanted = None if not roles or roles == ["all"] else {r.lower() for r in roles}
    out: list[str] = []
    for p in get_role_profiles():
        if wanted is None or p["name"].lower() in wanted:
            for t in [*p.get("fresher_titles", []), *p["query_titles"]]:
                if t not in out:
                    out.append(t)
    return out


async def ingest(provider: JobProvider, titles: list[str], cities: list[str | None], pages: int = 1,
                 per_page: int = 20, max_requests: int = 100, concurrency: int = 4) -> IngestStats:
    combos = [(t, c, p) for t in titles for c in cities for p in range(1, pages + 1)][:max_requests]
    sem = asyncio.Semaphore(concurrency)

    async def one(t, c, p):
        async with sem:
            try:
                return await provider.search(t, c, p, per_page)
            except Exception as e:                               # one bad request must not stop the run
                return e

    results = await asyncio.gather(*[one(*x) for x in combos])
    st = IngestStats(requests=len(combos))
    with session_scope() as s:
        for res in results:
            if isinstance(res, Exception):
                st.failed += 1
                msg = str(res) if isinstance(res, ProviderError) else f"unexpected error ({type(res).__name__})"
                if msg not in st.errors:
                    st.errors.append(msg)
                continue
            st.fetched += len(res)
            r = upsert_jobs(s, res)
            st.inserted += r["inserted"]; st.updated += r["updated"]; st.duplicates += r["duplicates"]
    return st
