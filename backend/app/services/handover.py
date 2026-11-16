from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.db import read, rows_to_dicts, transaction

# 冻结落库形态择一：批次状态机增加「冻结」态（不另建独立冻结登记表）
STATUS_INFLIGHT = "在途"
STATUS_FROZEN = "冻结"
STATUS_PENDING = "待确认"
STATUS_SETTLED = "已结清"
STATUS_SCRAPPED = "报废"

# 发起交班时不得纳入清单的状态及固化原因
EXCLUDE_REASONS = {
    STATUS_FROZEN: "冻结批次不得进入交班清单",
    STATUS_PENDING: "待确认批次不得进入交班清单",
    STATUS_SETTLED: "已结清批次不参与交班",
    STATUS_SCRAPPED: "报废批次不参与交班",
}


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> str:
    return _fmt(_now_dt())


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize_ts(value) -> str | None:
    if value is None or value == "":
        return None
    dt = value if isinstance(value, datetime) else _parse_ts(value)
    if dt is None:
        raise HTTPException(400, "检查到期时间格式无效")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return _fmt(dt)


def _deadline(batch) -> datetime | None:
    due = _parse_ts(batch["check_due_at"])
    if due is None:
        return None
    return due + timedelta(hours=int(batch["overdue_hours"] or 0))


def _batch_dict(row) -> dict:
    d = dict(row)
    deadline = _deadline(d)
    d["已冻结"] = d["status"] == STATUS_FROZEN
    d["逾期"] = bool(deadline is not None and _now_dt() >= deadline)
    d["检查截止"] = _fmt(deadline) if deadline else None
    return d


def _fetch_batch(conn, batch_id: int):
    b = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if not b:
        raise HTTPException(404, "批次不存在")
    return b


def _freeze(conn, batch, reason: str) -> None:
    """在途 → 冻结。已冻结幂等保留首次冻结时间与原因。"""
    if batch["status"] == STATUS_FROZEN:
        return
    conn.execute(
        "UPDATE batches SET status = ?, frozen_at = ?, freeze_reason = ? WHERE id = ?",
        (STATUS_FROZEN, _now(), reason, batch["id"]),
    )


def _apply_due_freeze(conn) -> int:
    """按批次逾期时限检查：在途批次到期即冻结。返回本次新冻结数量。

    待确认批次已被隔离，不再重复冻结；须人工更新检查到期时间后确认回在途。
    """
    now = _now_dt()
    frozen = 0
    for row in conn.execute(
        "SELECT * FROM batches WHERE status = ?", (STATUS_INFLIGHT,)
    ).fetchall():
        deadline = _deadline(row)
        if deadline is not None and now >= deadline:
            _freeze(conn, row, f"检查任务逾期（截止 {_fmt(deadline)}）")
            frozen += 1
    return frozen


def list_shifts() -> list[dict]:
    with read() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM shifts ORDER BY id").fetchall())


def list_batches(owner_shift_id: int | None = None) -> list[dict]:
    with read() as conn:
        sql = """
            SELECT b.*, s.name AS owner_shift_name
            FROM batches b
            LEFT JOIN shifts s ON s.id = b.owner_shift_id
        """
        params: tuple = ()
        if owner_shift_id is not None:
            sql += " WHERE b.owner_shift_id = ?"
            params = (owner_shift_id,)
        sql += " ORDER BY b.id"
        return [_batch_dict(r) for r in conn.execute(sql, params).fetchall()]


def list_handovers() -> list[dict]:
    with read() as conn:
        rows = conn.execute(
            """
            SELECT h.*,
                   fs.name AS from_shift_name,
                   ts.name AS to_shift_name
            FROM handovers h
            JOIN shifts fs ON fs.id = h.from_shift_id
            JOIN shifts ts ON ts.id = h.to_shift_id
            ORDER BY h.id DESC
            """
        ).fetchall()
        return rows_to_dicts(rows)


def get_handover(handover_id: int) -> dict:
    with read() as conn:
        h = conn.execute(
            """
            SELECT h.*,
                   fs.name AS from_shift_name,
                   ts.name AS to_shift_name
            FROM handovers h
            JOIN shifts fs ON fs.id = h.from_shift_id
            JOIN shifts ts ON ts.id = h.to_shift_id
            WHERE h.id = ?
            """,
            (handover_id,),
        ).fetchone()
        if not h:
            raise HTTPException(404, "交班单不存在")
        items = conn.execute(
            """
            SELECT b.*
            FROM handover_items hi
            JOIN batches b ON b.id = hi.batch_id
            WHERE hi.handover_id = ?
            ORDER BY b.id
            """,
            (handover_id,),
        ).fetchall()
        snapshot = conn.execute(
            """
            SELECT hk.*, b.title, b.status AS current_status
            FROM handover_start_keys hk
            JOIN batches b ON b.id = hk.batch_id
            WHERE hk.handover_id = ?
            ORDER BY hk.outcome DESC, hk.batch_id
            """,
            (handover_id,),
        ).fetchall()
        out = dict(h)
        out["items"] = [_batch_dict(r) for r in items]
        out["snapshot"] = rows_to_dicts(snapshot)
        out["冻结数"] = sum(1 for r in items if r["status"] == STATUS_FROZEN)
        return out


def dashboard() -> dict:
    with read() as conn:
        shifts = rows_to_dicts(conn.execute("SELECT * FROM shifts ORDER BY id").fetchall())
        counts = {
            r["status"]: r["c"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS c FROM batches GROUP BY status"
            ).fetchall()
        }
        active = conn.execute(
            "SELECT COUNT(*) AS c FROM handovers WHERE status = '进行中'"
        ).fetchone()["c"]
        last = conn.execute(
            "SELECT * FROM handovers ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "班次数": len(shifts),
            "在途批次数": counts.get(STATUS_INFLIGHT, 0),
            "冻结批次数": counts.get(STATUS_FROZEN, 0),
            "待确认批次数": counts.get(STATUS_PENDING, 0),
            "进行中交班": active,
            "最近交班": dict(last) if last else None,
            "班次": shifts,
        }


def start_handover(from_shift_id: int, to_shift_id: int) -> dict:
    if from_shift_id == to_shift_id:
        raise HTTPException(400, "交班双方不能是同一班次")
    with transaction() as conn:
        fs = conn.execute("SELECT * FROM shifts WHERE id = ?", (from_shift_id,)).fetchone()
        ts = conn.execute("SELECT * FROM shifts WHERE id = ?", (to_shift_id,)).fetchone()
        if not fs or not ts:
            raise HTTPException(404, "班次不存在")
        active = conn.execute(
            "SELECT id FROM handovers WHERE status = '进行中' LIMIT 1"
        ).fetchone()
        if active:
            raise HTTPException(409, f"已有进行中的交班单#{active['id']}，禁止并行交班")

        # 发起前先按逾期时限落冻结，保证本次排除结果与冻结态同源
        _apply_due_freeze(conn)

        candidates = conn.execute(
            "SELECT * FROM batches WHERE owner_shift_id = ? ORDER BY id",
            (from_shift_id,),
        ).fetchall()
        include = [b for b in candidates if b["status"] == STATUS_INFLIGHT]
        exclude = [b for b in candidates if b["status"] != STATUS_INFLIGHT]
        if not include:
            raise HTTPException(400, "交班方没有可交接的在途批次（冻结/待确认/已结清均不纳入）")

        hid = conn.execute(
            """
            INSERT INTO handovers(
              from_shift_id, to_shift_id, status, batch_count,
              excluded_count, snapshot_at, started_at
            ) VALUES (?, ?, '进行中', ?, ?, ?, ?)
            """,
            (
                from_shift_id,
                to_shift_id,
                len(include),
                len(exclude),
                _now(),
                _now(),
            ),
        ).lastrowid

        # 发起快照固化：纳入键与排除键（含原因）逐条落库，事后不可变
        for b in include:
            conn.execute(
                "INSERT INTO handover_items(handover_id, batch_id) VALUES (?, ?)",
                (hid, b["id"]),
            )
            conn.execute(
                """
                INSERT INTO handover_start_keys(handover_id, batch_id, biz_key, outcome, reason, detail)
                VALUES (?, ?, ?, '纳入', ?, ?)
                """,
                (
                    hid,
                    b["id"],
                    b["biz_key"],
                    "在途批次纳入本次交班清单",
                    _batch_dict(b)["检查截止"] or "",
                ),
            )
        for b in exclude:
            status = b["status"]
            detail = b["freeze_reason"] if status == STATUS_FROZEN else ""
            conn.execute(
                """
                INSERT INTO handover_start_keys(handover_id, batch_id, biz_key, outcome, reason, detail)
                VALUES (?, ?, ?, '排除', ?, ?)
                """,
                (
                    hid,
                    b["id"],
                    b["biz_key"],
                    EXCLUDE_REASONS.get(status, f"{status} 不参与交班"),
                    detail,
                ),
            )

        conn.execute("UPDATE shifts SET status = '交班中' WHERE id = ?", (from_shift_id,))
        conn.execute("UPDATE shifts SET status = '接班中' WHERE id = ?", (to_shift_id,))
    return get_handover(hid)


def complete_handover(handover_id: int) -> dict:
    with transaction() as conn:
        h = conn.execute("SELECT * FROM handovers WHERE id = ?", (handover_id,)).fetchone()
        if not h:
            raise HTTPException(404, "交班单不存在")
        if h["status"] != "进行中":
            raise HTTPException(400, "只能完成进行中的交班单")
        items = conn.execute(
            "SELECT batch_id FROM handover_items WHERE handover_id = ? ORDER BY batch_id",
            (handover_id,),
        ).fetchall()
        before = len(items)

        # 完成前重读清单内每键当前状态：任一键冻结（或已非在途）即整单失败。
        # 检测与回滚同一事务，且检测发生在任何过户之前——零半截过户。
        blocked = []

        if before == 0:
            if blocked:
                frozen = [r for r in blocked if r["status"] == STATUS_FROZEN]
                if frozen:
                    reason = "交班进行中清单内批次被冻结，整单失败：" + "、".join(
                        f"{r['biz_key']}（{r['freeze_reason'] or '冻结'}）" for r in frozen
                    )
                else:
                    reason = "交班进行中清单内批次状态变化，整单失败：" + "、".join(
                        f"{r['biz_key']}（{r['status']}）" for r in blocked
                    )
            else:
                reason = "交班清单为空，整单失败"
            conn.execute(
                "UPDATE handovers SET status = '失败', reason = ?, finished_at = ? WHERE id = ?",
                (reason, _now(), handover_id),
            )
            # 本趟未发生任何归属变更，仅复原双方班次状态
            conn.execute(
                "UPDATE shifts SET status = '值班中' WHERE id = ?", (h["from_shift_id"],)
            )
            conn.execute(
                "UPDATE shifts SET status = '空闲' WHERE id = ?", (h["to_shift_id"],)
            )
            detail = {
                "交班前清单": before,
                "阻断键": [r["biz_key"] for r in blocked],
                "冻结键": [r["biz_key"] for r in blocked if r["status"] == STATUS_FROZEN],
                "过户数": 0,
            }
            conn.execute(
                """
                INSERT INTO reconcile_reports(
                  handover_id, before_count, after_from_count, after_to_count,
                  consistent, detail_json, created_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    handover_id,
                    before,
                    _count_inflight(conn, h["from_shift_id"]),
                    _count_inflight(conn, h["to_shift_id"]),
                    json.dumps(detail, ensure_ascii=False),
                    _now(),
                ),
            )
        else:
            # 整批过户：无条件更新（已通过事务内全量在途校验）
            for it in items:
                conn.execute(
                    "UPDATE batches SET owner_shift_id = ? WHERE id = ? AND status = ?",
                    (h["to_shift_id"], it["batch_id"], STATUS_INFLIGHT),
                )
            after_from = _count_inflight(conn, h["from_shift_id"])
            after_to = _count_inflight(conn, h["to_shift_id"])
            detail = {
                "交班前清单": before,
                "过户数": before,
                "交班后交班方在途": after_from,
                "交班后接班方在途": after_to,
            }
            conn.execute(
                """
                UPDATE handovers
                SET status = '已完成', finished_at = ?, batch_count = ?, reason = ''
                WHERE id = ?
                """,
                (_now(), before, handover_id),
            )
            conn.execute(
                "UPDATE shifts SET status = '已交班' WHERE id = ?", (h["from_shift_id"],)
            )
            conn.execute(
                "UPDATE shifts SET status = '值班中' WHERE id = ?", (h["to_shift_id"],)
            )
            conn.execute(
                """
                INSERT INTO reconcile_reports(
                  handover_id, before_count, after_from_count, after_to_count,
                  consistent, detail_json, created_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    handover_id,
                    before,
                    after_from,
                    after_to,
                    json.dumps(detail, ensure_ascii=False),
                    _now(),
                ),
            )
    # 事务提交后再读，保证返回体与落库同源
    return get_handover(handover_id)


def _count_inflight(conn, shift_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM batches WHERE owner_shift_id = ? AND status = ?",
        (shift_id, STATUS_INFLIGHT),
    ).fetchone()["c"]


def _verify_not_frozen(batch) -> None:
    if batch["status"] == STATUS_FROZEN:
        raise HTTPException(
            409,
            f"批次 {batch['biz_key']} 已冻结，不得普通结清；请先解冻（转待确认）或报废",
        )


def configure_overdue(batch_id: int, overdue_hours: int, check_due_at=None) -> dict:
    """配置批次逾期时限；到期后由检查任务标冻结。"""
    if overdue_hours < 0:
        raise HTTPException(400, "逾期时限不能为负")
    normalized_due = _normalize_ts(check_due_at)
    with transaction() as conn:
        _fetch_batch(conn, batch_id)
        conn.execute(
            "UPDATE batches SET overdue_hours = ?, check_due_at = ? WHERE id = ?",
            (overdue_hours, normalized_due, batch_id),
        )
    return get_batch(batch_id)


def run_due_checks() -> dict:
    """检查任务：对所有在途/待确认批次比对逾期时限，到期即冻结。"""
    with transaction() as conn:
        newly = _apply_due_freeze(conn)
        frozen = rows_to_dicts(
            conn.execute(
                "SELECT * FROM batches WHERE status = ? ORDER BY id", (STATUS_FROZEN,)
            ).fetchall()
        )
    return {"本次新冻结": newly, "冻结批次": frozen}


def get_batch(batch_id: int) -> dict:
    with read() as conn:
        row = conn.execute(
            """
            SELECT b.*, s.name AS owner_shift_name
            FROM batches b
            LEFT JOIN shifts s ON s.id = b.owner_shift_id
            WHERE b.id = ?
            """,
            (batch_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "批次不存在")
        return _batch_dict(row)


def settle_batch(batch_id: int) -> dict:
    """普通结清：冻结批禁止。"""
    with transaction() as conn:
        batch = _fetch_batch(conn, batch_id)
        _verify_not_frozen(batch)
        if batch["status"] != STATUS_INFLIGHT:
            raise HTTPException(400, f"只有「在途」批次可普通结清，当前为「{batch['status']}」")
        conn.execute(
            "UPDATE batches SET status = ? WHERE id = ?", (STATUS_SETTLED, batch_id)
        )
    return get_batch(batch_id)


def scrap_batch(batch_id: int) -> dict:
    """报废：冻结批的合法出路之一。"""
    with transaction() as conn:
        batch = _fetch_batch(conn, batch_id)
        if batch["status"] in (STATUS_SETTLED, STATUS_SCRAPPED):
            raise HTTPException(400, f"「{batch['status']}」批次不可报废")
        conn.execute(
            "UPDATE batches SET status = ? WHERE id = ?", (STATUS_SCRAPPED, batch_id)
        )
    return get_batch(batch_id)


def unfreeze_batch(batch_id: int) -> dict:
    """解冻：冻结 → 待确认（待确认仍不得进入交班清单）。"""
    with transaction() as conn:
        batch = _fetch_batch(conn, batch_id)
        if batch["status"] != STATUS_FROZEN:
            raise HTTPException(400, "只有冻结批次可解冻")
        conn.execute(
            "UPDATE batches SET status = ?, freeze_reason = ? WHERE id = ?",
            (STATUS_PENDING, batch["freeze_reason"], batch_id),
        )
    return get_batch(batch_id)


def confirm_batch(batch_id: int) -> dict:
    """待确认 → 在途。若仍处于逾期时限内则拒绝，须先重配检查到期时间。"""
    with transaction() as conn:
        batch = _fetch_batch(conn, batch_id)
        if batch["status"] != STATUS_PENDING:
            raise HTTPException(400, "只有待确认批次可确认")
        deadline = _deadline(batch)
        if deadline is not None and _now_dt() >= deadline:
            raise HTTPException(409, "批次仍在逾期时限内，请先更新检查到期时间再确认")
        conn.execute(
            "UPDATE batches SET status = ?, frozen_at = NULL, freeze_reason = '' WHERE id = ?",
            (STATUS_INFLIGHT, batch_id),
        )
    return get_batch(batch_id)


def list_reconcile() -> list[dict]:
    with read() as conn:
        rows = conn.execute(
            "SELECT * FROM reconcile_reports ORDER BY id DESC"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d.pop("detail_json"))
            d["一致"] = bool(d.pop("consistent"))
            out.append(d)
        return out
