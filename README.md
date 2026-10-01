# JobHunt backend (FastAPI) - Module 1: Resume parsing + Role inference

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
| POST | `/api/v1/analyze` | one call: upload -> parsed JSON + ranked roles |
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
* Not built yet: S3 upload, database, auth, job search (Adzuna) -- next modules.
