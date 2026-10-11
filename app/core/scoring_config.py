"""All tunable weights live here (single source), never scattered in services."""

# G1: keyword profile weights (per skill, components are summed)
KEYWORD_WEIGHTS: dict[str, float] = {
    "skills_section": 1.0,        # listed in the skills section
    "project_evidence": 2.0,      # used in a project (added per project, capped by max_evidence_items)
    "experience_evidence": 2.5,   # used in a job/internship (same cap)
    "coursework": 0.5,            # only seen in coursework
    "mentioned_in_text": 0.5,     # mentioned somewhere else in the resume text
    "inferred": 0.3,              # expanded from an acronym such as MERN
    "certification": 0.5,         # appears in a certification title
    "recent_bonus": 0.5,          # used in a project/job that ended within recent_months
    "recent_months": 12,
    "max_evidence_items": 3,
}

# role inference (core coverage, project evidence, optional coverage, education fit)
ROLE_WEIGHTS: tuple[float, float, float, float] = (0.45, 0.35, 0.10, 0.10)
