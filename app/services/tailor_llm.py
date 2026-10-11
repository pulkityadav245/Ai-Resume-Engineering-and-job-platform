"""Optional model-based bullet rewriter (needs ANTHROPIC_API_KEY). NOT run against the live API yet.
Whatever it returns is still verified by factuality.enforce(); on any error the original bullet is kept."""
import os

PROMPT = """Rewrite ONE resume bullet for a job titled "{title}".
Hard rules:
- Keep every fact. Do NOT add skills, tools, numbers, dates, employers, results, or claims of leadership or scale.
- You may reorder words and use a stronger verb ONLY if the meaning stays identical.
- You may mention these skills only if the bullet already supports them: {skills}.
- Return only the rewritten bullet, one line, no quotes.

Bullet: {bullet}"""


def llm_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


class LLMRewriter:
    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

    def __call__(self, bullet: str, allowed_skills: list[str], jd_title: str) -> str:
        try:
            import anthropic
            msg = anthropic.Anthropic().messages.create(
                model=self.model, max_tokens=200,
                messages=[{"role": "user", "content": PROMPT.format(
                    title=jd_title or "the target role", skills=", ".join(allowed_skills) or "none", bullet=bullet)}])
            text = "".join(b.text for b in msg.content if b.type == "text").strip().strip('"')
            return text.splitlines()[0] if text else bullet
        except Exception:
            return bullet
