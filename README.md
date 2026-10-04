# JobHunt backend (FastAPI) - Module 1: Resume parsing + Role inference | Module 2: Job search

## Run
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q                                              # 25 tests
uvicorn app.main:app --reload                          # docs: http://127.0.0.1:8000/docs
```
Optional LLM parsing: copy `.env.example` to `.env`, set `ANTHROPIC_API_KEY`
(export it or load it with your shell/dotenv). Without a key the deterministic parser is used.

## Endpoints
| Method | Path | Does |
|---|---|---|
| POST | `/api/v1/resume/parse` | upload PDF/DOCX -> structured JSON + grounding issues + warnings |
| POST | `/api/v1/analyze?include_jobs=true&location=..` | one call: upload -> parsed JSON + ranked roles (+ jobs) |
| POST | `/api/v1/jobs/search` | Master Resume JSON -> target roles (or your own) -> open jobs, ranked by fit |
| POST | `/api/v1/roles/infer` | Master Resume JSON -> ranked roles + evidence + job-search query titles |

## Pipeline
`file -> pdf_extract -> (llm_parser | rule_parser) -> grounding -> ResumeData -> role_inference`

* `skill_taxonomy.py` + `data/skills.json`: alias map, word-boundary matching (Java != JavaScript, C != C++).
* `grounding.py`: removes any skill/skills_used not present in the source text, flags invented numbers,
  institutes and titles. Reused later to validate tailored resumes.
* `role_inference.py` + `data/roles.json`: explainable scoring (weights are heuristic, NOT validated).
* `MERN`/`MEAN` expand to their parts only as `source="inferred"` with `inferred_from` set.

## Known limitations
* Scanned (image) PDFs are rejected; OCR is not implemented.
* Rule parser relies on common section headings and bullet characters; two-column or table-heavy
  resumes may parse badly -> the UI must show a review/edit step before saving the Master Resume.
* `llm_parser.py` has NOT been run against the live API yet (no key in the dev sandbox). Its output
  is always grounded, and any failure falls back to the rule parser.
* Taxonomy covers ~60 skills and roles.json 9 roles: extend these as you test real resumes.
* `POST /api/v1/resume/debug` shows raw extracted text + detected sections (use it when a parse looks wrong).

## Module 2: job search
`resume -> infer_roles -> query titles (fresher titles first) -> provider (Adzuna | mock) -> dedup -> job_matcher -> ranked`

* **Providers** (`services/job_providers/`): `AdzunaProvider` (live), `MockProvider` (FICTIONAL demo jobs, offline),
  `CachedProvider` (TTL cache, default 12h, protects API quota). Add new sources by subclassing `JobProvider`.
* **Setup:** get free keys at https://developer.adzuna.com/ and put `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` in `.env`.
  Without keys the API runs in DEMO MODE (response contains a warning). `JOBS_PROVIDER=mock|adzuna` forces one.
* **Quota:** one search = top_roles x 2 provider calls (default 6). Repeats are served from cache.
* **Scoring** (`job_matcher.py`): 45% skills (required 1.0 / preferred 0.5) + 30% title relevance + 15% project evidence
  + 10% level fit. Fresher + senior title is capped at 40; fresher + 3+ years asked is capped at 55. Heuristic, not validated.
* **Skill gap:** every job lists `missing_required` / `missing_preferred`. Nothing is ever added to the resume.
* Always link users to `job.url` (provider ToS). `salary_predicted=true` means the provider estimated the pay.

## Known limitations (Module 2)
* Adzuna LIVE calls are NOT tested against the real API here (no keys in the dev sandbox). Provider code is tested
  against a mocked HTTP transport shaped from Adzuna's docs; verify with real keys first.
* Job boards usually return a description SNIPPET, so skills later in the posting are invisible; jobs with <2 detected
  skills are flagged "low confidence".
* Required/preferred split is a sentence-level keyword heuristic.
* Indian-market coverage/quality of Adzuna results is unverified.
* Not built yet: S3 upload, database, auth, ATS check, JD analyzer (full), tailoring, tracker, UI.

## UI (served by the same FastAPI app)
Open http://127.0.0.1:8000/ after `uvicorn app.main:app --reload` (API docs stay at /docs).
Files: `app/static/index.html`, `style.css`, `app.js` -- no build step. To add a feature, write a view
function in `app.js` and add one object to the `FEATURES` array (ATS, Tailor and Tracker are placeholders).
