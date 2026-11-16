from fastapi import APIRouter

from app.services import handover as svc

router = APIRouter(prefix="/reconcile", tags=["交班对账"])


@router.get("")
def get_reports():
    return svc.list_reconcile()
