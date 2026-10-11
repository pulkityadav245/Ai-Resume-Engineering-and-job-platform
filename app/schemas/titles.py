from typing import Literal

from pydantic import BaseModel, Field


class MethodVote(BaseModel):
    method: str
    title: str
    score: float
    why: str


class VotedTitle(BaseModel):
    title: str
    methods: list[str]
    confidence: Literal["high", "medium", "low"]     # high = at least 2 independent methods agree
    score: float
    votes: list[MethodVote]
    note: str | None = None


class VoteResponse(BaseModel):
    titles: list[VotedTitle]
    methods_used: list[str]
    methods_skipped: dict[str, str] = Field(default_factory=dict)
    top_keywords: list[str] = Field(default_factory=list)
