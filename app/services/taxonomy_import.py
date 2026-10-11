"""G4: import user-supplied taxonomy CSVs (ESCO skills/occupations/relations, India's NCO 2015 titles).
Nothing is downloaded. Column names follow the published CSVs but are matched flexibly; a clear error lists
what was expected. NOT yet run against the real ESCO/NCO files, only against small fixtures."""
import csv
import json
import re
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import OccupationRow, OccupationSkillRow, SkillRow
from app.services.skill_taxonomy import curated_lookup, norm_alias


def _read(path: str | Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        rows = list(rd)
        return list(rd.fieldnames or []), rows


def _pick(fields: list[str], names: list[str]) -> str | None:
    low = {f.lower().strip(): f for f in fields}
    return next((low[n.lower()] for n in names if n.lower() in low), None)


def _require(fields: list[str], names: list[str], what: str) -> str:
    col = _pick(fields, names)
    if not col:
        raise ValueError(f"{what}: expected one of the columns {names}; found {fields}")
    return col


def _split_labels(raw: str | None) -> list[str]:
    return [a.strip() for a in re.split(r"[\n|;]", raw or "") if a.strip()]


def import_skills(s: Session, path: str | Path, kind: str = "esco", only_uris: set[str] | None = None) -> int:
    fields, rows = _read(path)
    label = _require(fields, ["preferredLabel", "preferred_label", "skill", "name", "label"], "skills CSV")
    alt, uri = _pick(fields, ["altLabels", "alt_labels", "aliases"]), _pick(fields, ["conceptUri", "uri"])
    n = 0
    for r in rows:
        name = (r.get(label) or "").strip()
        u = (r.get(uri) or "").strip() if uri else None
        if not name or (only_uris is not None and u not in only_uris):
            continue
        aliases = _split_labels(r.get(alt)) if alt else []
        row = s.scalar(select(SkillRow).where(SkillRow.name == name, SkillRow.source == kind))
        if row:
            row.aliases_json, row.uri = json.dumps(aliases), u or row.uri
        else:
            s.add(SkillRow(name=name, uri=u, aliases_json=json.dumps(aliases), source=kind))
        n += 1
    s.commit()
    return n


def import_occupations(s: Session, path: str | Path, kind: str = "esco",
                       relations_path: str | Path | None = None) -> dict[str, int]:
    fields, rows = _read(path)
    title = _require(fields, ["preferredLabel", "preferred_label", "Occupational Title", "title", "occupation"], "occupations CSV")
    code = _pick(fields, ["iscoGroup", "NCO 2015", "nco_2015", "code"])
    uri = _pick(fields, ["conceptUri", "uri"])
    occ = 0
    for r in rows:
        t = (r.get(title) or "").strip()
        if not t:
            continue
        c = (r.get(code) or "").strip() if code else None
        u = (r.get(uri) or "").strip() if uri else None
        row = s.scalar(select(OccupationRow).where(OccupationRow.title == t, OccupationRow.source == kind))
        if row:
            row.code, row.uri = c or row.code, u or row.uri
        else:
            s.add(OccupationRow(title=t, code=c, uri=u, source=kind))
        occ += 1
    s.commit()
    links = 0
    if relations_path:
        rf, rrows = _read(relations_path)
        o_uri = _require(rf, ["occupationUri", "occupation_uri"], "relations CSV")
        s_uri = _require(rf, ["skillUri", "skill_uri"], "relations CSV")
        rel = _pick(rf, ["relationType", "relation_type", "relation"])
        occ_by_uri = {u: i for i, u in s.execute(select(OccupationRow.id, OccupationRow.uri).where(OccupationRow.source == kind)) if u}
        skill_by_uri = {u: n for n, u in s.execute(select(SkillRow.name, SkillRow.uri).where(SkillRow.source == kind)) if u}
        s.execute(delete(OccupationSkillRow).where(OccupationSkillRow.occupation_id.in_(list(occ_by_uri.values()) or [-1])))
        for r in rrows:
            oid, sk = occ_by_uri.get((r.get(o_uri) or "").strip()), skill_by_uri.get((r.get(s_uri) or "").strip())
            if oid and sk:
                kind_rel = (r.get(rel) or "essential").strip().lower() if rel else "essential"
                s.add(OccupationSkillRow(occupation_id=oid, skill_name=sk,
                                         relation="optional" if kind_rel.startswith("opt") else "essential"))
                links += 1
        s.commit()
    return {"occupations": occ, "relations": links}


def load_vocab(s: Session) -> dict[str, str]:
    """normalised alias -> canonical skill. Labels that match a curated skill collapse onto it
    ('Python (computer programming)' -> 'Python'), so the same skill never has two names."""
    cur = curated_lookup()
    vocab: dict[str, str] = {}
    for name, alias_json in s.execute(select(SkillRow.name, SkillRow.aliases_json)):
        forms = {name, re.sub(r"\s*\([^)]*\)", "", name).strip(), *json.loads(alias_json or "[]")}
        keys = {norm_alias(f) for f in forms if f}
        canon = next((cur[k] for k in sorted(keys) if k in cur), name)
        for k in keys:
            if k:
                vocab.setdefault(k, canon)
    return vocab
