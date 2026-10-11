# Changelog
- ATS-readiness checker with layout detection, defect-injection evaluation, endpoint `/api/v1/ats/check`.
- Tailoring engine (extractive + checked rewrite), claim-level factuality validator with enforcement, evaluation harness.
- Keyword profile (`/api/v1/resume/keywords`), title normalizer, taxonomy import, title profiles, job-type detection (module code + tests;
  voting and funnel endpoints are not built yet).
- Ingestion + database search, Adzuna provider with doctor command, UI served by FastAPI.
