"""同源闸门：挂载目录/指纹/总字节漂移拦截，以及发布后再合并对账对齐。"""
import pytest

from app.services import files, plans, reconcile, rewrite, rulers, settings
from app.services.errors import ServiceError


def _publish(table, code, db, source=rulers.LEDGER_SOURCE):
    settings.update_setting(rulers.RULER_SOURCE_KEY, source, db_path=db)
    p = plans.create_plan(code, "同源计划", table, db_path=db)
    plans.attach_loose_files(p["id"], db_path=db)
    plans.publish_plan(p["id"], db_path=db)
    return p


def test_mount_dir_same_source_as_target_table(db):
    p = _publish("dw_payments", "CP-MOUNT1", db)
    with pytest.raises(ServiceError):
        rulers.mount_dir_for("  ")
    detail = plans.plan_detail(p["id"], db_path=db)
    assert detail["ruler"]["mount_dir"] == "lake/dw_payments"


def test_fingerprint_drift_after_re_attach_blocks_merge(db):
    # 独立新表，避免与种子计划争抢碎文件
    files.register_file("lake/lab_drift/a.parquet", "lab_drift", 100_000, db_path=db)
    files.register_file("lake/lab_drift/b.parquet", "lab_drift", 200_000, db_path=db)
    p = _publish("lab_drift", "CP-DRIFT1", db)
    # 发布后再登记同表碎文件并挂入 → 挂载指纹漂移
    files.register_file(
        "lake/lab_drift/c.parquet", "lab_drift", 123_456, db_path=db
    )
    plans.attach_loose_files(p["id"], db_path=db)
    with pytest.raises(ServiceError, match="挂载指纹"):
        rewrite.start_rewrite(p["id"], db_path=db)
    with pytest.raises(ServiceError, match="挂载指纹"):
        reconcile.run_reconcile(p["id"], db_path=db)


def test_merge_then_reconcile_aligned_uses_ruler_bytes(db):
    p = _publish("dw_payments", "CP-ALIGN1", db)
    job = rewrite.start_rewrite(p["id"], db_path=db)
    assert job["ruler_source"] == rulers.LEDGER_SOURCE
    assert job["ruler_bytes"] == 290_000 + 305_000
    assert job["merged_bytes"] == job["ruler_bytes"]
    report = reconcile.run_reconcile(p["id"], db_path=db)
    assert report["before_bytes"] == report["after_bytes"]
    assert report["aligned"] == 1
    assert report["ruler_source"] == rulers.LEDGER_SOURCE
    assert "对账对齐" in report["summary"]


def test_reconcile_without_job_is_not_aligned_chinese(db):
    p = _publish("dw_payments", "CP-NOJOB1", db)
    report = reconcile.run_reconcile(p["id"], db_path=db)
    assert report["aligned"] == 0
    assert report["after_bytes"] == 0
    assert "尚无成功合并任务" in report["summary"]


def test_snapshot_mode_full_chain_aligned(db):
    files.register_file("lake/lab_snap/a.parquet", "lab_snap", 42_000, db_path=db)
    files.register_file("lake/lab_snap/b.parquet", "lab_snap", 58_000, db_path=db)
    p = _publish("lab_snap", "CP-SNAPCHAIN", db, source=rulers.SNAPSHOT_SOURCE)
    job = rewrite.start_rewrite(p["id"], db_path=db)
    assert job["merged_bytes"] == 100_000
    report = reconcile.run_reconcile(p["id"], db_path=db)
    assert report["aligned"] == 1
    assert report["ruler_source"] == rulers.SNAPSHOT_SOURCE
    assert report["mount_dir"] == "lake/lab_snap"


def test_merge_without_ruler_blocked(db):
    # 手工造一个无标尺的已发布计划，模拟缺标尺
    p = plans.create_plan("CP-NORULE", "无标尺", "dw_payments", db_path=db)
    plans.attach_loose_files(p["id"], db_path=db)
    with __import__("app.db", fromlist=["get_db"]).get_db(db) as conn:
        conn.execute(
            "UPDATE compact_plans SET status='已发布' WHERE id=?", (p["id"],)
        )
    with pytest.raises(ServiceError, match="尚未点亮发布体积标尺"):
        rewrite.start_rewrite(p["id"], db_path=db)


def test_ruler_bytes_survive_in_db_rows(db):
    """库内可核对：凭证表、任务行、对账行三处总字节同源。"""
    p = _publish("dw_payments", "CP-DB1", db)
    rewrite.start_rewrite(p["id"], db_path=db)
    report = reconcile.run_reconcile(p["id"], db_path=db)
    from app.db import get_db

    with get_db(db) as conn:
        voucher = conn.execute(
            "SELECT total_bytes FROM volume_ruler_vouchers WHERE plan_id=?",
            (p["id"],),
        ).fetchone()["total_bytes"]
        job_bytes = conn.execute(
            "SELECT ruler_bytes FROM rewrite_jobs WHERE plan_id=?", (p["id"],)
        ).fetchone()["ruler_bytes"]
    assert voucher == job_bytes == report["before_bytes"]
