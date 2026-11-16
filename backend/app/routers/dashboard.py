from fastapi import APIRouter

from app.services import handover as svc

router = APIRouter(tags=["总览"])


@router.get("/dashboard")
def get_dashboard():
    return svc.dashboard()
