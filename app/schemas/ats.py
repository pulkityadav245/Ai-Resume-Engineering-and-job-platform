from typing import Literal

from pydantic import BaseModel, Field


class ATSCheck(BaseModel):
    id: str
    category: str
    name: str
    weight: float
    score: float                       # 0-1
    status: Literal["pass", "warn", "fail"]
    detail: str
    fix: str | None = None


class ATSReport(BaseModel):
    score: int                         # 0-100, weighted
    score_exact: float = 0.0           # same score with 2 decimals (for comparisons and evaluation)
    label: str
    categories: dict[str, float]       # category -> 0-100
    checks: list[ATSCheck]
    top_fixes: list[str]
    jd_used: bool
    disclaimer: str = Field(default="JobHunt ATS-readiness score: a transparent heuristic checklist. "
                                    "It is NOT the score of any specific company's ATS.")
