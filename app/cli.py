"""python -m app.cli ingest --provider adzuna --cities top --roles all --pages 1 --max-requests 100
   python -m app.cli stats"""
import argparse
import asyncio
import json
import os

from app.data.india import CITIES, INGEST_CITIES
from app.db.session import session_scope
from app.services.ingest import ingest, plan_titles
from app.services.job_providers.factory import get_provider
from app.services.job_store import stats


def _cities(arg: str) -> list[str | None]:
    if arg == "top":
        return list(INGEST_CITIES)
    if arg == "all-india":
        return [None]
    names = [c.strip() for c in arg.split(",") if c.strip()]
    bad = [c for c in names if c not in CITIES]
    if bad:
        raise SystemExit(f"Unknown city: {bad}. Known: {sorted(CITIES)}")
    return names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest", help="fetch jobs from a provider into the database")
    ing.add_argument("--provider", choices=["adzuna", "mock"], help="default: from env / keys")
    ing.add_argument("--cities", default="top", help="'top', 'all-india' or comma list, e.g. Pune,Dehradun")
    ing.add_argument("--roles", default="all", help="'all' or comma list of role names from roles.json")
    ing.add_argument("--pages", type=int, default=1)
    ing.add_argument("--per-page", type=int, default=20)
    ing.add_argument("--max-requests", type=int, default=100, help="hard cap on provider calls (protects quota)")
    ing.add_argument("--dry-run", action="store_true", help="only print how many requests would be made")
    sub.add_parser("stats", help="show what is stored")
    ev = sub.add_parser("eval-tailoring", help="hallucination metrics for resume tailoring (writes a Markdown report)")
    ev.add_argument("--seeds", type=int, default=10)
    ev.add_argument("--p", type=float, default=0.5, help="fabrication probability of the SIMULATED model")
    ev.add_argument("--llm", action="store_true", help="use the real LLM rewriter (needs ANTHROPIC_API_KEY)")
    ev.add_argument("--out", default="eval/tailoring_report.md")
    ea = sub.add_parser("eval-ats", help="defect-injection check of the ATS-readiness checker")
    ea.add_argument("--out", default="eval/ats_report.md")
    sub.add_parser("doctor", help="check Adzuna + LLM keys with a few tiny real calls")
    a = ap.parse_args(argv)

    if a.cmd == "eval-tailoring":
        from pathlib import Path
        from app.services.tailor_eval import render_markdown, run_tailoring_eval
        from app.services.tailor_llm import llm_available
        if a.llm and not llm_available():
            raise SystemExit("--llm needs ANTHROPIC_API_KEY in .env")
        md = render_markdown(run_tailoring_eval(a.seeds, a.p, a.llm))
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
        print(md)
        return 0

    if a.cmd == "eval-ats":
        from pathlib import Path
        from app.services.ats_eval import render_markdown as ats_md, run_ats_eval
        md = ats_md(run_ats_eval())
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md, encoding="utf-8")
        print(md)
        return 0

    if a.cmd == "doctor":
        from app.services.doctor import run_doctor
        return run_doctor()

    if a.cmd == "stats":
        with session_scope() as s:
            print(json.dumps(stats(s), indent=2))
        return 0

    if a.provider:
        os.environ["JOBS_PROVIDER"] = a.provider
        get_provider.cache_clear()
    titles = plan_titles(None if a.roles == "all" else [r.strip() for r in a.roles.split(",")])
    cities = _cities(a.cities)
    planned = len(titles) * len(cities) * a.pages
    print(f"{len(titles)} titles x {len(cities)} cities x {a.pages} page(s) = {planned} requests "
          f"(cap {a.max_requests}, will run {min(planned, a.max_requests)})")
    if a.dry_run:
        return 0
    provider = get_provider()
    print(f"provider: {provider.name}")
    st = asyncio.run(ingest(provider, titles, cities, a.pages, a.per_page, a.max_requests))
    print(st)
    return 1 if st.failed == st.requests and st.requests else 0


if __name__ == "__main__":
    raise SystemExit(main())
