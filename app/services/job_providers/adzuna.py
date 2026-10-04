"""Adzuna provider. Docs: https://developer.adzuna.com/docs/search

GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
    ?app_id=..&app_key=..&what=..&where=..&results_per_page=..
Response: {"count": N, "results": [ {id,title,description,redirect_url,created,company{display_name},
           location{display_name},salary_min,salary_max,salary_is_predicted,contract_type,...} ]}
"""
import html
import re

import httpx

from app.schemas.jobs import Job
from app.services.job_providers.base import JobProvider, ProviderError

BASE = "https://api.adzuna.com/v1/api/jobs"
_TAG = re.compile(r"<[^>]+>")


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", s or ""))).strip()


def _to_float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class AdzunaProvider(JobProvider):
    name = "adzuna"

    def __init__(self, app_id: str, app_key: str, country: str = "in",
                 transport: httpx.AsyncBaseTransport | None = None, timeout: float = 15.0):
        self.app_id, self.app_key, self.country = app_id, app_key, country
        self._transport, self._timeout = transport, timeout

    async def search(self, query, location=None, page=1, per_page=20):
        params = {
            "app_id": self.app_id, "app_key": self.app_key,
            "results_per_page": min(per_page, 50),       # API max is 50
            "what": query, "content-type": "application/json",
        }
        if location:
            params["where"] = location
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                r = await client.get(f"{BASE}/{self.country}/search/{page}", params=params)
        except httpx.HTTPError as e:                       # never include the URL (it has the key)
            raise ProviderError(f"Adzuna request failed ({type(e).__name__})") from None
        if r.status_code in (401, 403):
            raise ProviderError("Adzuna rejected the credentials (check ADZUNA_APP_ID / ADZUNA_APP_KEY)")
        if r.status_code == 429:
            raise ProviderError("Adzuna rate limit reached; try again later")
        if r.status_code >= 400:
            raise ProviderError(f"Adzuna returned HTTP {r.status_code}")
        try:
            results = r.json().get("results", [])
        except ValueError:
            raise ProviderError("Adzuna returned invalid JSON") from None
        return [j for j in (self._map(x) for x in results) if j]

    def _map(self, x: dict) -> Job | None:
        url, title = x.get("redirect_url"), _clean(x.get("title"))
        if not url or not title:
            return None
        predicted = x.get("salary_is_predicted")
        return Job(
            source=self.name, external_id=str(x.get("id", url)), title=title,
            company=_clean((x.get("company") or {}).get("display_name")) or None,
            location=_clean((x.get("location") or {}).get("display_name")) or None,
            description=_clean(x.get("description")), url=url, posted_at=x.get("created"),
            salary_min=_to_float(x.get("salary_min")), salary_max=_to_float(x.get("salary_max")),
            salary_predicted=None if predicted is None else str(predicted) in ("1", "True", "true"),
            contract_type=x.get("contract_type") or x.get("contract_time"),
        )
