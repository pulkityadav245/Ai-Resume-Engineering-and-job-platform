from pydantic import BaseModel, Field


class KeywordWeight(BaseModel):
    skill: str
    weight: float
    normalized: float                      # weight / max weight, 0-1
    components: dict[str, float]           # why: e.g. {"skills_section": 1.0, "project_evidence": 4.0}
    evidence: list[str] = Field(default_factory=list)


class KeywordProfile(BaseModel):
    skills: list[KeywordWeight]
    total_weight: float
    weights_config: dict[str, float]       # the exact configuration used

    def vector(self) -> dict[str, float]:
        return {k.skill: k.normalized for k in self.skills}
