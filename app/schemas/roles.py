from pydantic import BaseModel, Field


class RoleMatch(BaseModel):
    role: str
    score: float                         # 0-100, heuristic (see role_inference.py)
    matched_core: list[str]
    missing_core: list[str]
    matched_optional: list[str] = Field(default_factory=list)
    evidence: dict[str, list[str]]       # skill -> project/experience titles using it
    query_titles: list[str]              # titles to send to job-search APIs
    explanation: str


class RoleInferenceResponse(BaseModel):
    level: str                           # "fresher" | "experienced"
    roles: list[RoleMatch]
