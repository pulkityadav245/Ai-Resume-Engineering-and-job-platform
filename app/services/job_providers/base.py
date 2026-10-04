import time
from abc import ABC, abstractmethod

from app.schemas.jobs import Job


class ProviderError(Exception):
    """Provider-side failure. Messages must never contain URLs/keys."""


class JobProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def search(self, query: str, location: str | None = None,
                     page: int = 1, per_page: int = 20) -> list[Job]: ...


class CachedProvider(JobProvider):
    """In-memory TTL cache so repeated searches don't burn API quota."""

    def __init__(self, inner: JobProvider, ttl_seconds: int):
        self.inner, self.ttl = inner, ttl_seconds
        self.name = inner.name
        self._store: dict[tuple, tuple[float, list[Job]]] = {}
        self.hits = 0
        self.misses = 0

    async def search(self, query, location=None, page=1, per_page=20):
        key = (query.strip().lower(), (location or "").strip().lower(), page, per_page)
        now = time.monotonic()
        cached = self._store.get(key)
        if cached and now - cached[0] < self.ttl:
            self.hits += 1
            return cached[1]
        self.misses += 1
        jobs = await self.inner.search(query, location, page, per_page)
        self._store[key] = (now, jobs)
        return jobs
