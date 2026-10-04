"""Settings come from environment variables; a local .env file is loaded automatically."""
import os

from dotenv import load_dotenv

load_dotenv()  # no-op if .env is missing; real env vars always win


def adzuna_credentials() -> tuple[str | None, str | None]:
    return os.getenv("ADZUNA_APP_ID"), os.getenv("ADZUNA_APP_KEY")


def adzuna_country() -> str:
    return os.getenv("ADZUNA_COUNTRY", "in").lower()


def jobs_provider_choice() -> str:
    return os.getenv("JOBS_PROVIDER", "").lower()      # "adzuna" | "mock" | "" (auto)


def jobs_cache_ttl() -> int:
    return int(os.getenv("JOBS_CACHE_TTL_SECONDS", str(12 * 3600)))
