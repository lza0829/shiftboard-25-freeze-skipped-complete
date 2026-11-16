"""交班台验收测试：基础主链 + 逾期批次冻结保护。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["DATA_DIR"] = str(ROOT / "backend" / "data_test")
os.environ["FIXTURES_DIR"] = str(ROOT / "fixtures")

db_path = Path(os.environ["DATA_DIR"]) / "app.db"
if db_path.exists():
    db_path.unlink()

from app.main import app  # noqa: E402


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def past(hours: int = 1) -> str:
    return iso(datetime.now(timezone.utc) - timedelta(hours=hours))


def future(hours: int = 24) -> str:
    return iso(datetime.now(timezone.utc) + timedelta(hours=hours))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def batch(client, bid: int) -> dict:
    r = client.get(f"/api/batches/{bid}")
    assert r.status_code == 200, r.text
    return r.json()


def set_due(client, bid: int, hours: int, due: str | None):
    r = client.post(
        f"/api/batches/{bid}/overdue",
        json={"overdue_hours": hours, "check_due_at": due},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["项目"] == "交班台"


def test_overdue_check_freezes(client):
    # 批次 1 已到期（截止在过去，时限 0）→ 检查任务标冻结
    set_due(client, 1, 0, past())
    res = client.post("/api/batches/checks/run")
    assert res.status_code == 200, res.text
    assert res.json()["本次新冻结"] >= 1
    b = batch(client, 1)
    assert b["status"] == "冻结"
    assert b["已冻结"] is True
    assert b["frozen_at"]
    assert "逾期" in b["freeze_reason"]


def test_frozen_cannot_settle(client):
    r = client.post("/api/batches/1/settle")
    assert r.status_code == 409
    assert "冻结" in r.text
    assert batch(client, 1)["status"] == "冻结"


def test_settle_inflight_still_works(client):
    set_due(client, 2, 10, future(2))
    r = client.post("/api/batches/2/settle")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "已结清"


def test_unfreeze_to_pending_then_confirm(client):
    r = client.post("/api/batches/1/unfreeze")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "待确认"
    # 仍处逾期时限内 → 确认被拒
    r = client.post("/api/batches/1/confirm")
    assert r.status_code == 409
    # 重配检查到期时间后可确认 → 回到在途
    set_due(client, 1, 10, future(5))
    r = client.post("/api/batches/1/confirm")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "在途"


def test_start_excludes_frozen_and_pending_and_is_snapshotted(client):
    # 制造三类排除：冻结(3)、待确认(4)、已结清(2)
    set_due(client, 3, 0, past())
    set_due(client, 4, 0, past())
    client.post("/api/batches/checks/run")
    assert batch(client, 3)["status"] == "冻结"
    assert batch(client, 4)["status"] == "冻结"
    client.post("/api/batches/4/unfreeze")
    assert batch(client, 4)["status"] == "待确认"
    # 待确认若已重配检查到期时间，则不会被下一次检查再次冻结
    set_due(client, 4, 10, future(5))
    assert batch(client, 4)["status"] == "待确认"

    started = client.post(
        "/api/handovers/start", json={"from_shift_id": 1, "to_shift_id": 3}
    )
    assert started.status_code == 200, started.text
    h = started.json()
    assert h["batch_count"] == 1
    assert [b["biz_key"] for b in h["items"]] == ["B20261115-01"]
    assert h["excluded_count"] == 3

    snap = {(s["biz_key"], s["outcome"]): s for s in h["snapshot"]}
    assert snap[("B20261115-01", "纳入")]
    assert snap[("B20261115-03", "排除")]["reason"].startswith("冻结")
    assert snap[("B20261114-09", "排除")]["reason"].startswith("待确认")
    assert snap[("B20261115-02", "排除")]["reason"].startswith("已结清")


def test_complete_fails_whole_order_if_item_frozen_midflight(client):
    hid = client.get("/api/handovers").json()[0]["id"]
    assert client.get(f"/api/handovers/{hid}").json()["status"] == "进行中"
    assert batch(client, 1)["owner_shift_id"] == 1

    # 交班进行中：检查任务把清单内批次 1 冻结
    set_due(client, 1, 0, past())
    client.post("/api/batches/checks/run")
    assert batch(client, 1)["status"] == "冻结"

    done = client.post(f"/api/handovers/{hid}/complete")
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["status"] == "失败"
    assert "冻结" in out["reason"]
    # 零半截过户：归属未变
    assert batch(client, 1)["owner_shift_id"] == 1

    report = client.get("/api/reconcile").json()[0]
    assert report["一致"] is False
    assert report["detail"]["过户数"] == 0
    assert report["detail"]["冻结键"] == ["B20261115-01"]


def test_start_rejects_when_all_keys_excluded(client):
    r = client.post("/api/handovers/start", json={"from_shift_id": 1, "to_shift_id": 2})
    assert r.status_code == 400
    assert "没有可交接" in r.text


def test_scrap_is_valid_frozen_exit(client):
    r = client.post("/api/batches/1/scrap")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "报废"
    rows = client.get("/api/batches", params={"owner_shift_id": 1}).json()
    assert all(b["biz_key"] != "B20261115-01" for b in rows if b["status"] == "在途")


def test_list_marks_frozen_same_source(client):
    rows = client.get("/api/batches").json()
    frozen = [b for b in rows if b["已冻结"]]
    assert frozen
    assert all(b["status"] == "冻结" for b in frozen)
    assert all(b["status"] == "冻结" for b in rows if b["已冻结"])
    # 冻结原因与列表状态同源
    assert all(b["freeze_reason"] for b in frozen)


def test_pending_not_refrozen_by_check(client):
    # 批次 4 待确认；即便检查时限仍是过去，也不应被检查任务重复冻结
    assert batch(client, 4)["status"] == "待确认"
    client.post("/api/batches/checks/run")
    assert batch(client, 4)["status"] == "待确认"


def test_normal_handover_still_completes(client):
    client.post("/api/batches/3/scrap")
    set_due(client, 4, 10, future(5))
    client.post("/api/batches/4/confirm")
    assert batch(client, 4)["status"] == "在途"

    started = client.post(
        "/api/handovers/start", json={"from_shift_id": 1, "to_shift_id": 2}
    )
    assert started.status_code == 200, started.text
    h = started.json()
    assert h["batch_count"] == 1
    # 已报废(1、3)与已结清(2)仍是本班次名下，但均被固化排除
    assert h["excluded_count"] == 3

    done = client.post(f"/api/handovers/{h['id']}/complete")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "已完成"
    assert batch(client, 4)["owner_shift_id"] == 2
    assert client.get("/api/reconcile").json()[0]["一致"] is True
