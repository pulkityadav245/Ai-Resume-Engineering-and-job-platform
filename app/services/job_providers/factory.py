from functools import lru_cache

from app.core import config
from app.services.job_providers.adzuna import AdzunaProvider
from app.services.job_providers.base import CachedProvider, JobProvider, ProviderError
from app.services.job_providers.mock import MockProvider


@lru_cache(maxsize=1)
def get_provider() -> JobProvider:
    """JOBS_PROVIDER=adzuna|mock. If unset: Adzuna when keys exist, otherwise the demo provider.
    The provider is cached process-wide so the TTL cache survives across requests."""
    choice = config.jobs_provider_choice()
    app_id, app_key = config.adzuna_credentials()
    have_keys = bool(app_id and app_key)
    if choice == "mock" or (not choice and not have_keys):
        inner: JobProvider = MockProvider()
    elif choice in ("", "adzuna"):
        if not have_keys:
            raise ProviderError("ADZUNA_APP_ID / ADZUNA_APP_KEY are not set")
        inner = AdzunaProvider(app_id, app_key, config.adzuna_country())
    else:
        raise ProviderError(f"Unknown JOBS_PROVIDER '{choice}'")
    return CachedProvider(inner, config.jobs_cache_ttl())
