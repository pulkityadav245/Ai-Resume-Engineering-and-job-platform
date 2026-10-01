from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.schemas.resume import ParseResponse
from app.schemas.roles import RoleInferenceResponse
from app.services.pdf_extract import ExtractionError
from app.services.resume_service import parse_upload
from app.services.role_inference import infer_roles

router = APIRouter(prefix="/analyze", tags=["analyze"])


class AnalyzeResponse(BaseModel):
    parse: ParseResponse
    roles: RoleInferenceResponse


@router.post("", response_model=AnalyzeResponse)
async def analyze(file: UploadFile = File(...)):
    """Convenience: upload a resume -> parsed JSON AND ranked target roles in one call."""
    data = await file.read()
    try:
        parsed = parse_upload(file.filename or "", data)
    except ExtractionError as e:
        raise HTTPException(422, str(e))
    return AnalyzeResponse(parse=parsed, roles=infer_roles(parsed.resume))
