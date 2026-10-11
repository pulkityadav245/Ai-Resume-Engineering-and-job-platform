"""G3: raw job title -> (canonical title, level). Rules + abbreviations; no ML.
'Sr. SDE-2 (Payments) - Bengaluru' -> Software Engineer, level 'senior'-ish via roman/digit rules."""
import re
from dataclasses import dataclass

LEVEL_WORDS = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "intern", "internship", "interns",
               "trainee", "fresher", "freshers", "graduate", "entry", "level", "campus", "associate"}
GENERIC = {"developer", "engineer", "software", "programmer"}
DOMAINS = {"frontend", "backend", "full stack", "react", "python", "java", "node.js", "android", "ios", "web", "mobile", ".net", "php"}
DEV_DOMAINS = ("frontend", "backend", "full stack", "web", "mobile", "android", "ios", "react", "node.js",
               "python", "java", "javascript", ".net", "mern", "mean", "php", "angular", "django", "flask")
CASE = {"node.js": "Node.js", "react": "React", "python": "Python", "java": "Java", ".net": ".NET", "ui": "UI",
        "ux": "UX", "qa": "QA", "ml": "ML", "ai": "AI", "devops": "DevOps", "ios": "iOS", "javascript": "JavaScript",
        "sql": "SQL", "mern": "MERN", "mean": "MEAN", "c++": "C++", "php": "PHP", "angular": "Angular", "sde": "SDE"}
# ordered (pattern, replacement) rewrites applied to the cleaned lowercase title
SYNONYMS = [
    (r"\bsoftware development engineer in test\b|\bsdet\b|\bsoftware engineer in test\b", "software test engineer"),
    (r"\bsoftware development engineer\b|\bsoftware developer\b|\bsde\b|\bswe\b|\bprogrammer analyst\b|\bsoftware programmer\b",
     "software engineer"),
    (r"\bfull[\s-]?stack\b", "full stack"), (r"\bfront[\s-]?end\b", "frontend"), (r"\bback[\s-]?end\b", "backend"),
    (r"\bnode(?:\.?\s?js)?\b", "node.js"), (r"\breact(?:\.?js)?\b", "react"), (r"\bdot\s?net\b", ".net"),
    (r"\bdev[\s-]?ops\b", "devops"), (r"\bsys\s?admin\b", "system administrator"),
]
_SPECIAL_FRESHER = re.compile(r"\bgraduate engineer trainee\b|^get$|\bgraduate engineer\b")


@dataclass(frozen=True)
class CanonicalTitle:
    title: str
    level: str          # intern | fresher | junior | mid | senior | unspecified
    raw: str


def detect_level(text: str) -> str:
    t = text.lower()
    if re.search(r"\bintern(s|ship)?\b", t):
        return "intern"
    if re.search(r"\b(fresher|freshers|trainee|graduate|entry[- ]level|campus)\b", t):
        return "fresher"
    if re.search(r"\b(senior|sr|lead|principal|staff)\b", t) or re.search(r"\b(?:iii|3)\s*$", t) or re.search(r"\bsde[-\s]?(?:iii|3)\b", t):
        return "senior"
    if re.search(r"\b(?:ii|2)\s*$", t) or re.search(r"\bsde[-\s]?(?:ii|2)\b", t):
        return "mid"
    if re.search(r"\b(junior|jr|associate)\b", t) or re.search(r"\b(?:i|1)\s*$", t) or re.search(r"\bsde[-\s]?(?:i|1)\b", t):
        return "junior"
    return "unspecified"


def _titlecase(s: str) -> str:
    return " ".join(CASE.get(w, w.capitalize()) for w in s.split())


def canonical_title(raw: str) -> CanonicalTitle:
    s = (raw or "").lower().replace("\u2013", "-").replace("\u2014", "-").strip()
    level = detect_level(s)
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s)                      # (MERN), [Remote]
    s = re.sub(r"\bsde[-\s]?(?:iii|ii|i|[123])\b", "sde", s)         # SDE-2 -> sde (level already taken)
    parts = [p.strip() for p in re.split(r"\s+[-|@]\s+|\s*\|\s*|,|\bat\b", s) if p.strip()]
    head = parts[0] if parts else s
    toks = [t.rstrip(".") for t in re.findall(r"[a-z0-9+#.]+", head) if t.strip(".")]
    domain_override = None
    if len(parts) > 1 and all(t in GENERIC or t in LEVEL_WORDS for t in toks):
        second = parts[1]
        for pat, rep in SYNONYMS:
            second = re.sub(pat, rep, second)
        second = " ".join(w for w in re.findall(r"[a-z0-9+#.]+", second) if w not in LEVEL_WORDS)
        if second in DOMAINS:                                        # 'Software Engineer - Backend' -> Backend Developer
            domain_override = second + " developer"
        else:
            head = head + " " + parts[1]
    if _SPECIAL_FRESHER.search(head):
        return CanonicalTitle("Graduate Engineer Trainee", "fresher", raw)
    head = re.sub(r"[-/]", " ", head) if "full-stack" not in head else head
    toks = [t.strip(".") if t.endswith(".") and not t.endswith("js.") else t for t in re.findall(r"[a-z0-9+#.]+", head)]
    toks = [t for t in toks if t and t not in LEVEL_WORDS and t not in {"i", "ii", "iii", "1", "2", "3", "iv"}]
    cleaned = " ".join(toks)
    for pat, rep in SYNONYMS:
        cleaned = re.sub(pat, rep, cleaned)
    if cleaned.endswith("engineer") and any(d in cleaned for d in DEV_DOMAINS):
        cleaned = cleaned[: -len("engineer")] + "developer"
    if domain_override:
        cleaned = domain_override
    cleaned = re.sub(r"\s+", " ", cleaned).strip() or re.sub(r"\s+", " ", raw.lower()).strip()
    return CanonicalTitle(_titlecase(cleaned), level, raw)
