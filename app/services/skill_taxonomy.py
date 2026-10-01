"""Skill taxonomy: alias map + deterministic matching over free text."""
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "skills.json"

# An alias only matches when NOT glued to other word characters (so "Java" != "JavaScript",
# but "C++" and "Node.js" still work).
_L = r"(?<![A-Za-z0-9+#])"
_R = r"(?![A-Za-z0-9+#])"


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


@dataclass(frozen=True)
class SkillMatch:
    name: str
    category: str | None
    alias: str
    start: int


class Taxonomy:
    def __init__(self, raw: dict):
        self.skills = {s["name"]: s for s in raw["skills"]}
        self.implies: dict[str, list[str]] = raw.get("implies", {})
        self._patterns: list[tuple[str, re.Pattern]] = []
        for s in raw["skills"]:
            forms = {s["name"], *s.get("aliases", [])}
            for alias in forms:
                self._patterns.append((s["name"], self._compile(alias, re.IGNORECASE)))
            for alias in s.get("case_sensitive_aliases", []):
                self._patterns.append((s["name"], self._compile(alias, 0)))
        # "implies" keys (MERN, MEAN) are detected as pseudo-skills
        self._implier_patterns = {
            k: self._compile(k, re.IGNORECASE) for k in self.implies
        }

    @staticmethod
    def _compile(alias: str, flags: int) -> re.Pattern:
        # flexible whitespace/hyphen inside multi-word aliases
        body = re.escape(alias).replace(r"\ ", r"[\s\-]+")
        return re.compile(_L + body + _R, flags)

    def find(self, text: str) -> list[SkillMatch]:
        """All canonical skills mentioned in text (first occurrence of each)."""
        found: dict[str, SkillMatch] = {}
        for name, pat in self._patterns:
            m = pat.search(text)
            if m and (name not in found or m.start() < found[name].start):
                found[name] = SkillMatch(
                    name, self.skills[name].get("category"), m.group(0), m.start()
                )
        return sorted(found.values(), key=lambda s: s.start)

    def find_implied(self, text: str) -> dict[str, list[str]]:
        """{'MERN': ['MongoDB', ...]} for acronyms present in text."""
        return {k: v for k, v in self.implies.items() if self._implier_patterns[k].search(text)}

    def mentions(self, text: str, skill: str) -> bool:
        return any(n == skill and p.search(text) for n, p in self._patterns)

    def canonical(self, name: str) -> str | None:
        """Map any alias/spelling to its canonical skill name (None if unknown)."""
        n = normalize(name)
        for canon in self.skills:
            if normalize(canon) == n:
                return canon
        for canon, pat in self._patterns:
            if pat.fullmatch(name.strip()):
                return canon
        return None


@lru_cache(maxsize=1)
def get_taxonomy() -> Taxonomy:
    return Taxonomy(json.loads(DATA.read_text(encoding="utf-8")))
