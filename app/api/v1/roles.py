from fastapi import APIRouter

from app.schemas.resume import ResumeData
from app.schemas.roles import RoleInferenceResponse
from app.services.role_inference import infer_roles

router = APIRouter(prefix="/roles", tags=["roles"])


@router.post("/infer", response_model=RoleInferenceResponse)
def infer(resume: ResumeData, top_n: int = 5):
    """Takes the (user-reviewed) Master Resume JSON and returns ranked target roles + evidence."""
    return infer_roles(resume, top_n=top_n)
