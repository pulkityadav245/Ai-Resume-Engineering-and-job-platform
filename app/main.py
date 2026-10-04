from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core import config  # noqa: F401  (loads .env)
from app.api.v1 import analyze, jobs, resume, roles

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="JobHunt API", version="0.1.0")
app.include_router(resume.router, prefix="/api/v1")
app.include_router(roles.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(analyze.router, prefix="/api/v1")

# Monolith: the UI is served by the same FastAPI process (http://127.0.0.1:8000/)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}
