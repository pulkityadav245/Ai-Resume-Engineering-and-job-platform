from fastapi import FastAPI
from app.api.v1 import analyze, resume, roles

app = FastAPI(title="JobHunt API", version="0.1.0")
app.include_router(resume.router, prefix="/api/v1")
app.include_router(roles.router, prefix="/api/v1")
app.include_router(analyze.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
