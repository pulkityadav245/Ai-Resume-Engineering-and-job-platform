"""Orchestrates: bytes -> text -> structured JSON -> grounding."""
from app.schemas.resume import ParseResponse
from app.services import llm_parser
from app.services.grounding import ground_resume
from app.services.pdf_extract import extract_text
from app.services.rule_parser import parse_resume


def parse_upload(filename: str, data: bytes, use_llm: bool = True) -> ParseResponse:
    extracted = extract_text(filename, data)
    warnings = list(extracted.warnings)
    parser = "rule_based"
    resume = None
    if use_llm and llm_parser.llm_available():
        try:
            resume = llm_parser.parse_with_llm(extracted.text)
            parser = "llm"
        except Exception as e:  # bad JSON, API error -> fall back, never crash the upload
            warnings.append(f"LLM parsing failed ({type(e).__name__}); used rule-based parser.")
    if resume is None:
        resume = parse_resume(extracted.text)
    resume, issues = ground_resume(resume, extracted.text)
    resume.personal.links = list(dict.fromkeys([*resume.personal.links, *extracted.links]))
    if not resume.skills:
        warnings.append("No skills detected. Please add skills manually in the review step.")
    if not resume.projects and not resume.experience:
        warnings.append("No projects or experience detected. Check the section headings.")
    return ParseResponse(resume=resume, grounding_issues=issues, warnings=warnings, parser=parser)
