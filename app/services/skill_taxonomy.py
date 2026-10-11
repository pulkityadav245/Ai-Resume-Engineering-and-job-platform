"""Skill taxonomy: alias map + deterministic matching over free text."""
import json
import os
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


_ALNUM = re.compile(r"[a-z0-9+#.]+")
MAX_NGRAM = 5
NOISY_SINGLE = {"management", "communication", "teamwork", "sales", "support", "design", "training", "service",
                "services", "analysis", "planning", "research", "marketing", "leadership", "quality", "safety"}


def norm_alias(s: str) -> str:
    """'Java (computer programming)' -> 'java computer programming' (token-normalised key)."""
    return " ".join(t.strip(".") for t in _ALNUM.findall(s.lower()) if t.strip("."))


@lru_cache(maxsize=1)
def _raw() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def curated_lookup() -> dict[str, str]:
    """normalised alias -> canonical name for the curated skills (case-insensitive aliases only)."""
    out: dict[str, str] = {}
    for sk in _raw()["skills"]:
        for a in {sk["name"], *sk.get("aliases", [])}:
            out.setdefault(norm_alias(a), sk["name"])
    return out


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
        self._vocab: dict[str, str] = {}              # imported alias (normalised) -> canonical skill
        self._vocab_by_name: dict[str, set[str]] = {}
        # "implies" keys (MERN, MEAN) are detected as pseudo-skills
        self._implier_patterns = {
            k: self._compile(k, re.IGNORECASE) for k in self.implies
        }

    @staticmethod
    def _compile(alias: str, flags: int) -> re.Pattern:
        # flexible whitespace/hyphen inside multi-word aliases
        body = re.escape(alias).replace(r"\ ", r"[\s\-]+")
        return re.compile(_L + body + _R, flags)

    def attach_vocab(self, vocab: dict[str, str]) -> None:
        """Add an imported vocabulary (alias -> canonical). Curated skills always win."""
        self._vocab = {a: c for a, c in vocab.items() if a and self._usable(a)}
        self._vocab_by_name = {}
        for a, c in self._vocab.items():
            self._vocab_by_name.setdefault(c, set()).add(a)

    @staticmethod
    def _usable(alias: str) -> bool:
        toks = alias.split()
        if len(toks) > MAX_NGRAM:
            return False
        return len(toks) > 1 or (len(alias) >= 4 and alias not in NOISY_SINGLE)

    def _vocab_find(self, text: str) -> list[SkillMatch]:
        if not self._vocab:
            return []
        toks = [(m.group().strip("."), m.start()) for m in _ALNUM.finditer(text.lower()) if m.group().strip(".")]
        out: dict[str, SkillMatch] = {}
        for i in range(len(toks)):
            for n in range(1, MAX_NGRAM + 1):
                if i + n > len(toks):
                    break
                gram = " ".join(t for t, _ in toks[i:i + n])
                canon = self._vocab.get(gram)
                if canon and canon not in out:
                    out[canon] = SkillMatch(canon, self.skills.get(canon, {}).get("category") or "imported", gram, toks[i][1])
        return list(out.values())

    def find(self, text: str) -> list[SkillMatch]:
        """All canonical skills mentioned in text (first occurrence of each)."""
        found: dict[str, SkillMatch] = {}
        for name, pat in self._patterns:
            m = pat.search(text)
            if m and (name not in found or m.start() < found[name].start):
                found[name] = SkillMatch(
                    name, self.skills[name].get("category"), m.group(0), m.start()
                )
        for m in self._vocab_find(text):
            found.setdefault(m.name, m)
        return sorted(found.values(), key=lambda s: s.start)

    def find_implied(self, text: str) -> dict[str, list[str]]:
        """{'MERN': ['MongoDB', ...]} for acronyms present in text."""
        return {k: v for k, v in self.implies.items() if self._implier_patterns[k].search(text)}

    def mentions(self, text: str, skill: str) -> bool:
        if any(n == skill and p.search(text) for n, p in self._patterns):
            return True
        return any(m.name == skill for m in self._vocab_find(text)) if skill in self._vocab_by_name else False

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
    tax = Taxonomy(_raw())
    if os.getenv("TAXONOMY_FROM_DB", "").lower() in ("1", "true", "yes"):      # opt-in: imported ESCO vocabulary
        from app.db.session import session_scope
        from app.services.taxonomy_import import load_vocab
        with session_scope() as s:
            tax.attach_vocab(load_vocab(s))
    return tax
