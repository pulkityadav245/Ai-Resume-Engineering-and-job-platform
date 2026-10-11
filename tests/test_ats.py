import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.ats import ats_check
from app.services.ats_eval import DEFECTS, GOOD, run_ats_eval
from app.services.pdf_extract import extract_pdf
from app.services.rule_parser import parse_resume

client = TestClient(app)
EVAL = run_ats_eval()


def make_pdf(rows):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for x, y, text in rows:
        c.drawString(x, y, text)
    c.save()
    return buf.getvalue()


def test_clean_resume_scores_high_with_no_failing_check():
    assert EVAL["clean_score"] >= 90 and EVAL["clean_failing_checks"] == []


@pytest.mark.parametrize("defect", list(DEFECTS))
def test_each_injected_defect_fires_its_check_and_lowers_the_score(defect):
    r = EVAL["defects"][defect]
    assert r["fired"], r
    assert r["delta"] > 0, r


def test_report_structure_and_disclaimer():
    rep = ats_check(GOOD, parse_resume(GOOD), pages=1)
    ids = [c.id for c in rep.checks]
    assert len(ids) == len(set(ids)) and 0 <= rep.score <= 100 and "NOT the score of any specific company" in rep.disclaimer
    assert set(rep.categories) >= {"Parseability", "Contact", "Sections", "Format", "Content", "Keywords"}
    assert all(c.fix for c in rep.checks if c.status != "pass")
    assert not rep.jd_used and "jd_coverage" not in ids


def test_job_description_adds_coverage_and_reports_gap_without_inventing():
    jd = "Required: React, Node.js and Kubernetes. Nice to have: Docker."
    rep = ats_check(GOOD, parse_resume(GOOD), pages=1, jd_text=jd)
    c = next(x for x in rep.checks if x.id == "jd_coverage")
    assert rep.jd_used and "Kubernetes" in c.detail and 0 < c.score < 1
    assert "ONLY if you really have them" in c.fix


def test_scanned_pdf_pages_fail_parseability():
    rep = ats_check(GOOD, parse_resume(GOOD), pages=2, warnings=["Page 1 has no extractable text", "Page 2 has no extractable text"])
    assert next(c for c in rep.checks if c.id == "text_extractable").status == "fail"


def test_two_column_pdf_is_detected_and_single_column_is_not():
    two = make_pdf([(x, 800 - 14 * i, t) for i in range(25) for x, t in ((40, f"Skills Python Java line {i}"), (330, f"Projects built things {i}"))])
    one = make_pdf([(40, 800 - 14 * i, f"Skills Python Java and Git line number {i}") for i in range(25)])
    assert extract_pdf(two).layout["columns_suspected"] is True
    assert extract_pdf(one).layout["columns_suspected"] is False


def test_endpoint_returns_report_and_rejects_bad_files():
    pdf = make_pdf([(40, 800 - 13 * i, l) for i, l in enumerate(GOOD.splitlines())])
    r = client.post("/api/v1/ats/check", files={"file": ("cv.pdf", pdf, "application/pdf")}, data={"jd_text": "Required: React and Kubernetes."})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["jd_used"] and b["score"] >= 70 and b["top_fixes"]
    bad = client.post("/api/v1/ats/check", files={"file": ("cv.txt", b"hello", "text/plain")})
    assert bad.status_code == 422
