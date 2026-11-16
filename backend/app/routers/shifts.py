from fastapi import APIRouter

from app.services import handover as svc

router = APIRouter(prefix="/shifts", tags=["班次"])


@router.get("")
def get_shifts():
    return svc.list_shifts()
