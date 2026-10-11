from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.resume import ResumeData

ViolationType = Literal["skill", "number", "entity", "date", "inflated_qualifier", "unseen_token", "untraceable"]


class Violation(BaseModel):
    type: ViolationType
    severity: Literal["error", "warning"]
    value: str
    where: str
    reason: str


class FactualityReport(BaseModel):
    claims_checked: int
    unsupported: int                       # error-level violations
    warnings: int
    unsupported_claim_rate: float          # unsupported / claims_checked
    by_type: dict[str, int]
    traceability_coverage: float           # bullets whose source bullet exists in the Master Resume
    extractive_ratio: float                # bullets identical to their source bullet
    violations: list[Violation]
    passed: bool                           # no error-level violation


class TraceEntry(BaseModel):
    output_id: str
    source_id: str | None
    rewritten: bool


class Coverage(BaseModel):
    before: float          # weighted share of JD skills present in the Master Resume
    after: float           # ... in the tailored resume
    ceiling: float         # best possible WITHOUT inventing anything (only skills the candidate already has)


class TailorRequest(BaseModel):
    resume: ResumeData
    jd_text: str = Field(min_length=20)
    jd_title: str | None = None
    mode: Literal["extractive", "rewrite"] = "extractive"   # rewrite needs ANTHROPIC_API_KEY
    max_projects: int = Field(3, ge=1, le=10)
    max_bullets: int = Field(3, ge=1, le=6)
    max_achievements: int = Field(3, ge=0, le=10)


class TailorResponse(BaseModel):
    tailored: ResumeData
    trace: list[TraceEntry]
    jd_skills: dict[str, str]              # skill -> required | preferred (heuristic split)
    matched_skills: list[str]
    skill_gap: list[str]                   # JD skills the candidate does NOT have. Never added to the resume.
    coverage: Coverage
    changes: list[str]
    factuality: FactualityReport           # final output (always passes)
    factuality_before_enforcement: FactualityReport | None = None
