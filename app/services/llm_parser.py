"""Optional LLM structuring step. Needs ANTHROPIC_API_KEY. The result ALWAYS goes through
grounding.ground_resume(), so the LLM can never add facts that are not in the resume text."""
import json
import os
import re

from app.schemas.resume import ResumeData

SYSTEM = """You convert resume text into JSON. Rules:
- Use ONLY information that appears in the text. Never invent skills, companies, dates or numbers.
- If a field is missing, use null or an empty list.
- Output ONLY valid JSON, no markdown fences, matching this shape:
{"personal":{"name":null,"email":null,"phone":null,"links":[]},
 "education":[{"id":"edu_1","degree":"","institute":null,"years":null,"score":null}],
 "skills":[{"name":"","category":null,"source":"skills_section"}],
 "projects":[{"id":"proj_1","title":"","bullets":[{"id":"proj_1_b1","text":""}],"skills_used":[]}],
 "experience":[{"id":"exp_1","title":"","bullets":[{"id":"exp_1_b1","text":""}],"skills_used":[]}],
 "coursework":[],"certifications":[],"achievements":[]}
Put subjects like DSA/OS/DBMS under "coursework" if the resume lists them as coursework.
Copy bullet text as written in the resume."""


def llm_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def parse_with_llm(text: str) -> ResumeData:
    import anthropic

    client = anthropic.Anthropic()
    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    msg = client.messages.create(
        model=model, max_tokens=4000, system=SYSTEM,
        messages=[{"role": "user", "content": f"Resume text:\n\n{text}"}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text")
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    return ResumeData.model_validate(json.loads(raw))
