"""`python -m app.cli doctor`: checks Adzuna + LLM wiring with a handful of tiny real calls.
Never prints keys. Providers/LLM are injectable so the logic is testable offline."""
import asyncio
import os

from app.core import config
from app.services.grounding import ground_resume
from app.services.job_providers.adzuna import AdzunaProvider
from app.services.job_providers.base import JobProvider

# (query, location) pairs. They also answer an open question: does Adzuna India need ALL words of a
# specific title to match, or is a broad query needed?
ADZUNA_PROBES = [("developer", None), ("node.js developer", None), ("junior node.js developer", None),
                 ("graduate engineer trainee", None), ("react developer", "Bengaluru"), ("python developer", "Dehradun")]

SAMPLE_TEXT = """Asha Rao
asha@example.com
TECHNICAL SKILLS
Languages: Python, JavaScript
Web: React, Node.js
PROJECTS
- Notes App (Jan 2026)
- Built a notes app with React and Node.js
- Technologies Used: React, Node.js, MongoDB
EDUCATION
B.Tech Computer Science, Sample University 2022 - 2026
"""


def _short(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:160]}"


async def check_adzuna(provider: JobProvider, probes=ADZUNA_PROBES) -> list[dict]:
    rows = []
    for q, loc in probes:
        row = {"query": q, "where": loc or "all India"}
        try:
            jobs = await provider.search(q, loc, 1, 20)
            row.update(ok=True, n=len(jobs), links_ok=all(j.url.startswith("http") for j in jobs),
                       sample=f"{jobs[0].title} @ {jobs[0].company} ({jobs[0].location})" if jobs else "-")
        except Exception as e:
            row.update(ok=False, n=0, error=_short(e))
        rows.append(row)
    return rows


def check_llm(parse_fn) -> dict:
    try:
        resume = parse_fn(SAMPLE_TEXT)
        resume, issues = ground_resume(resume, SAMPLE_TEXT)
        return {"ok": True, "skills": len(resume.skills), "projects": len(resume.projects),
                "grounding_issues": [f"{i.value}: {i.reason}" for i in issues]}
    except Exception as e:
        return {"ok": False, "error": _short(e)}


def run_doctor(adzuna: JobProvider | None = None, llm_parse=None, out=print) -> int:
    problems = checked = 0
    app_id, app_key = config.adzuna_credentials()
    out("== Adzuna ==")
    if adzuna is None and app_id and app_key:
        adzuna = AdzunaProvider(app_id, app_key, config.adzuna_country())
    if adzuna is None:
        out("SKIP: ADZUNA_APP_ID / ADZUNA_APP_KEY not set in .env")
    else:
        checked += 1
        out(f"country={config.adzuna_country()} (keys present: {bool(app_id and app_key)})")
        for r in asyncio.run(check_adzuna(adzuna)):
            if r["ok"]:
                out(f"  OK   {r['n']:>2} results  q='{r['query']}' where={r['where']}  e.g. {r['sample']}"
                    + ("" if r["links_ok"] else "  [WARNING: some results have no valid link]"))
            else:
                problems += 1
                out(f"  FAIL q='{r['query']}' where={r['where']}: {r['error']}")
        out("  Tip: if broad queries return results but specific titles return 0, shorten the titles in roles.json.")
    out("== LLM parser ==")
    if llm_parse is None and os.getenv("ANTHROPIC_API_KEY"):
        from app.services.llm_parser import parse_with_llm
        llm_parse = parse_with_llm
    if llm_parse is None:
        out("SKIP: ANTHROPIC_API_KEY not set in .env (the rule-based parser will be used)")
    else:
        checked += 1
        r = check_llm(llm_parse)
        if r["ok"]:
            out(f"  OK   parsed {r['skills']} skills, {r['projects']} project(s); grounding issues: {r['grounding_issues'] or 'none'}")
        else:
            problems += 1
            out(f"  FAIL {r['error']}")
    out("RESULT: " + ("nothing configured yet: add keys to .env" if checked == 0 else
                      "all configured services work" if problems == 0 else f"{problems} problem(s) found"))
    return 1 if problems else 0
