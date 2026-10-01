"""Pydantic schemas = the shared API contract for the whole team."""
from typing import Literal
from pydantic import BaseModel, Field

SkillSource = Literal["skills_section", "coursework", "project_text", "inferred"]


class Bullet(BaseModel):
    id: str
    text: str


class Personal(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    links: list[str] = Field(default_factory=list)


class Education(BaseModel):
    id: str
    degree: str
    institute: str | None = None
    years: str | None = None
    score: str | None = None           # CGPA / percentage as written


class Skill(BaseModel):
    name: str                          # canonical name, e.g. "React"
    category: str | None = None
    source: SkillSource = "skills_section"
    inferred_from: str | None = None   # e.g. "MERN" when source == "inferred"


class Project(BaseModel):
    id: str
    title: str
    bullets: list[Bullet] = Field(default_factory=list)
    skills_used: list[str] = Field(default_factory=list)


class Experience(BaseModel):
    id: str
    title: str
    bullets: list[Bullet] = Field(default_factory=list)
    skills_used: list[str] = Field(default_factory=list)


class ResumeData(BaseModel):
    personal: Personal = Field(default_factory=Personal)
    education: list[Education] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    coursework: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)


class GroundingIssue(BaseModel):
    field: str
    value: str
    action: Literal["removed", "flagged"]
    reason: str


class ParseResponse(BaseModel):
    resume: ResumeData
    grounding_issues: list[GroundingIssue]
    warnings: list[str]
    parser: Literal["rule_based", "llm"]
