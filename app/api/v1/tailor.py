from fastapi import APIRouter, HTTPException

from app.schemas.tailor import TailorRequest, TailorResponse
from app.services.tailor import tailor_resume
from app.services.tailor_llm import LLMRewriter, llm_available

router = APIRouter(prefix="/tailor", tags=["tailor"])


@router.post("", response_model=TailorResponse)
def tailor(req: TailorRequest):
    """Master Resume + job description -> tailored resume built ONLY from the Master Resume.
    mode=extractive never writes new text. mode=rewrite uses a model, then the validator reverts anything unsupported."""
    rewriter = None
    if req.mode == "rewrite":
        if not llm_available():
            raise HTTPException(503, "mode=rewrite needs ANTHROPIC_API_KEY. Use mode=extractive, which needs no key.")
        rewriter = LLMRewriter()
    return tailor_resume(req.resume, req.jd_text, req.jd_title, req.mode, rewriter, max_projects=req.max_projects,
                         max_bullets=req.max_bullets, max_achievements=req.max_achievements)
