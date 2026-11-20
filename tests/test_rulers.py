"""体积标尺：两套互斥落点、单次落盘、不可变、跨源拦截。"""
import json
import sqlite3
import threading

import pytest

from app.db import get_db
from app.services import plans, rulers, settings
from app.services.errors import ServiceError


def _new_plan(db, table="dw_payments", code="CP-R1"):
    p = plans.create_plan(code, "标尺计划", table, db_path=db)
    plans.attach_loose_files(p["id"], db_path=db)
    return p


def test_ledger_voucher_writes_fingerprint_and_bytes(db):
    settings.update_setting(
        rulers.RULER_SOURCE_KEY, rulers.LEDGER_SOURCE, db_path=db
    )
    p = _new_plan(db)
    out = plans.publish_plan(p["id"], db_path=db)
    assert out["status"] == "已发布"
    assert out["ruler_source"] == rulers.LEDGER_SOURCE
    with get_db(db) as conn:
        v = conn.execute(
            "SELECT * FROM volume_ruler_vouchers WHERE plan_id=?", (p["id"],)
        ).fetchone()
    assert v is not None
    assert v["mount_dir"] == "lake/dw_payments"
    assert v["total_bytes"] == 290_000 + 305_000
    assert len(v["mount_fingerprint"]) == 64
    # 计划列表亮标尺来源芯片，同源
    listed = [x for x in plans.list_plans(db) if x["id"] == p["id"]][0]
    assert listed["ruler"]["ruler_source_label"] == "旁路账册凭证"
    assert listed["ruler"]["same_source"] is True
    assert listed["ruler"]["total_bytes"] == v["total_bytes"]


def test_snapshot_file_is_immutable_and_rejects_rewrite(db):
    settings.update_setting(
        rulers.RULER_SOURCE_KEY, rulers.SNAPSHOT_SOURCE, db_path=db
    )
    p = _new_plan(db, table="dw_users", code="CP-SNAP1")
    plans.publish_plan(p["id"], db_path=db)
    path = rulers.snapshot_dir(db) / f"plan_{p['id']}.ruler.json"
    assert path.exists()
    assert oct(path.stat().st_mode & 0o777) == "0o444"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["mount_dir"] == "lake/dw_users"
    assert payload["total_bytes"] == 180_000 + 195_000 + 210_000
    assert payload["ruler_source"] == rulers.SNAPSHOT_SOURCE
    # 锁死只读：直接写被系统拒绝
    with pytest.raises(PermissionError):
        with open(path, "w", encoding="utf-8") as f:
            f.write("{}")
    # 服务层也拒再次落盘
    with pytest.raises(ServiceError, match="锁死只读"):
        with get_db(db) as conn:
            plan = dict(
                conn.execute(
                    "SELECT * FROM compact_plans WHERE id=?", (p["id"],)
                ).fetchone()
            )
            mount = rulers.compute_mount(conn, plan)
            rulers.write_ruler(conn, plan, mount, rulers.SNAPSHOT_SOURCE, db)


def test_only_one_landing_point_open(db):
    # 默认 ledger：发布后凭证表有行，快照目录无该计划文件
    settings.update_setting(
        rulers.RULER_SOURCE_KEY, rulers.LEDGER_SOURCE, db_path=db
    )
    p = _new_plan(db, code="CP-ONLY1")
    plans.publish_plan(p["id"], db_path=db)
    with get_db(db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) c FROM volume_ruler_vouchers WHERE plan_id=?",
            (p["id"],),
        ).fetchone()["c"]
    assert n == 1
    assert not (
        rulers.snapshot_dir(db) / f"plan_{p['id']}.ruler.json"
    ).exists()


def test_voucher_unique_constraint_blocks_double_write(db):
    settings.update_setting(
        rulers.RULER_SOURCE_KEY, rulers.LEDGER_SOURCE, db_path=db
    )
    p = _new_plan(db, code="CP-DUP1")
    plans.publish_plan(p["id"], db_path=db)
    with get_db(db) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO volume_ruler_vouchers(plan_id, plan_code, mount_dir, "
                "total_bytes, file_count, mount_fingerprint, ruler_source) "
                "VALUES (?,?,?,?,?,?,?)",
                (p["id"], p["plan_code"], "lake/x", 1, 1, "f", "ledger_voucher"),
            )


def test_switch_source_blocks_old_plan_with_chinese_message(db):
    settings.update_setting(
        rulers.RULER_SOURCE_KEY, rulers.LEDGER_SOURCE, db_path=db
    )
    p = _new_plan(db, code="CP-SW1")
    plans.publish_plan(p["id"], db_path=db)
    settings.update_setting(
        rulers.RULER_SOURCE_KEY, rulers.SNAPSHOT_SOURCE, db_path=db
    )
    from app.services import reconcile, rewrite

    with pytest.raises(ServiceError, match="标尺来源不一致"):
        rewrite.start_rewrite(p["id"], db_path=db)
    with pytest.raises(ServiceError, match="标尺来源不一致"):
        reconcile.run_reconcile(p["id"], db_path=db)
    # 切回同源即恢复
    settings.update_setting(
        rulers.RULER_SOURCE_KEY, rulers.LEDGER_SOURCE, db_path=db
    )
    job = rewrite.start_rewrite(p["id"], db_path=db)
    assert job["status"] == "成功"


def test_invalid_ruler_source_rejected(db):
    with pytest.raises(ServiceError, match="体积标尺来源只允许"):
        settings.update_setting(
            rulers.RULER_SOURCE_KEY, "guesswork", db_path=db
        )


def test_concurrent_publish_serialized_by_exclusive_lock(db):
    settings.update_setting(
        rulers.RULER_SOURCE_KEY, rulers.LEDGER_SOURCE, db_path=db
    )
    plans_a = plans.create_plan("CP-LOCK-A", "并发A", "dw_users", db_path=db)
    plans.attach_loose_files(plans_a["id"], db_path=db)
    plans_b = plans.create_plan("CP-LOCK-B", "并发B", "dw_payments", db_path=db)
    plans.attach_loose_files(plans_b["id"], db_path=db)
    errors = []
    results = []

    def pub(pid):
        try:
            out = plans.publish_plan(pid, db_path=db)
            results.append(out["id"])
        except ServiceError as exc:  # 串行后第二个仍应成功；报错则记录
            errors.append(str(exc))

    t1 = threading.Thread(target=pub, args=(plans_a["id"],))
    t2 = threading.Thread(target=pub, args=(plans_b["id"],))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors
    assert sorted(results) == sorted([plans_a["id"], plans_b["id"]])
    with get_db(db) as conn:
        n = conn.execute(
            "SELECT COUNT(*) c FROM volume_ruler_vouchers"
        ).fetchone()["c"]
    assert n == 2
    # 锁文件存在且为同一把
    assert (_parent(db) / "ruler_publish.lock").exists()


def _parent(db_path):
    from pathlib import Path

    return Path(db_path).parent
