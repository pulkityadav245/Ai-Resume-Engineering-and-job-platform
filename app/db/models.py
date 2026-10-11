from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobRow(Base):
    """One stored job posting. Unique per (source, external_id) AND per dedup_key (cross-source)."""
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_job_source_ext"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    external_id: Mapped[str] = mapped_column(String(128))
    dedup_key: Mapped[str] = mapped_column(String(400), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)   # canonical Indian city
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_predicted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    contract_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skills_json: Mapped[str] = mapped_column(Text, default="{}")    # {skill: required|preferred}, computed at ingest
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class TitleProfileRow(Base):
    """G5: per canonical job title, the TF-IDF weighted skill profile mined from stored jobs."""
    __tablename__ = "title_profiles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    n_jobs: Mapped[int] = mapped_column(Integer)
    profile_json: Mapped[str] = mapped_column(Text)            # {"skill": weight} (L2-normalised)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SkillRow(Base):
    """G4: imported vocabulary skill (ESCO ...) with its alternative labels."""
    __tablename__ = "vocab_skills"
    __table_args__ = (UniqueConstraint("name", "source", name="uq_vocab_skill"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    uri: Mapped[str | None] = mapped_column(String(400), nullable=True, index=True)
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    source: Mapped[str] = mapped_column(String(16), default="esco")


class OccupationRow(Base):
    """G4: imported occupation title (ESCO / NCO 2015)."""
    __tablename__ = "vocab_occupations"
    __table_args__ = (UniqueConstraint("title", "source", name="uq_vocab_occ"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    uri: Mapped[str | None] = mapped_column(String(400), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(16), default="esco")


class OccupationSkillRow(Base):
    __tablename__ = "vocab_occupation_skills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occupation_id: Mapped[int] = mapped_column(Integer, index=True)
    skill_name: Mapped[str] = mapped_column(String(300))
    relation: Mapped[str] = mapped_column(String(16), default="essential")    # essential | optional
