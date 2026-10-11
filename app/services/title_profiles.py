"""G5: data-driven title profiles. For each canonical title, which skills do its job postings ask for
(TF-IDF over titles), then predict titles for a resume by cosine similarity. Explainable by construction."""
import json
import math
from collections import Counter, defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import JobRow, TitleProfileRow
from app.schemas.keywords import KeywordProfile
from app.services.title_normalizer import canonical_title


def build_title_profiles(s: Session, min_jobs: int = 2) -> int:
    counts: dict[str, Counter] = defaultdict(Counter)
    n_jobs: Counter = Counter()
    for title, blob in s.execute(select(JobRow.title, JobRow.skills_json).where(JobRow.is_active.is_(True))):
        ct = canonical_title(title).title
        n_jobs[ct] += 1
        counts[ct].update(json.loads(blob or "{}").keys())
    titles = [t for t, n in n_jobs.items() if n >= min_jobs and counts[t]]
    df = Counter(sk for t in titles for sk in counts[t])
    s.execute(delete(TitleProfileRow))
    for t in titles:
        vec = {sk: (c / n_jobs[t]) * (math.log((1 + len(titles)) / (1 + df[sk])) + 1) for sk, c in counts[t].items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        s.add(TitleProfileRow(title=t, n_jobs=n_jobs[t],
                              profile_json=json.dumps({k: round(v / norm, 5) for k, v in vec.items()})))
    s.commit()
    return len(titles)


def predict_titles(s: Session, kp: KeywordProfile, top_k: int = 5) -> list[dict]:
    q = kp.vector()
    qn = math.sqrt(sum(v * v for v in q.values())) or 1.0
    out = []
    for row in s.scalars(select(TitleProfileRow)):
        vec = json.loads(row.profile_json)
        contrib = {k: q[k] * w / qn for k, w in vec.items() if k in q}       # profile vectors are unit length
        if not contrib:
            continue
        top = sorted(contrib.items(), key=lambda kv: -kv[1])[:3]
        out.append({"title": row.title, "score": round(sum(contrib.values()), 4), "n_jobs": row.n_jobs,
                    "why": [{"skill": k, "contribution": round(v, 4)} for k, v in top]})
    return sorted(out, key=lambda x: -x["score"])[:top_k]
