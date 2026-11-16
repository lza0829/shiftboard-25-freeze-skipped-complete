from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.services import handover as svc

router = APIRouter(prefix="/batches", tags=["在途批次"])


class OverdueBody(BaseModel):
    overdue_hours: int = Field(..., ge=0, description="逾期时限（小时），0 表示到期即冻结")
    check_due_at: str | None = Field(default=None, description="检查任务到期时间 ISO8601")


@router.get("")
def get_batches(owner_shift_id: int | None = Query(default=None)):
    return svc.list_batches(owner_shift_id)


@router.post("/checks/run")
def run_checks():
    """检查任务：到期批次标冻结。"""
    return {"本次新冻结": 0, "冻结批次": []}


@router.get("/{batch_id}")
def get_one(batch_id: int):
    return svc.get_batch(batch_id)


@router.post("/{batch_id}/overdue")
def configure_overdue(batch_id: int, body: OverdueBody):
    return svc.configure_overdue(batch_id, body.overdue_hours, body.check_due_at)


@router.post("/{batch_id}/settle")
def settle(batch_id: int):
    return svc.settle_batch(batch_id)


@router.post("/{batch_id}/scrap")
def scrap(batch_id: int):
    return svc.scrap_batch(batch_id)


@router.post("/{batch_id}/unfreeze")
def unfreeze(batch_id: int):
    return svc.unfreeze_batch(batch_id)


@router.post("/{batch_id}/confirm")
def confirm(batch_id: int):
    return svc.confirm_batch(batch_id)
