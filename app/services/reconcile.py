"""体积对账：以发布时冻结的体积标尺为同源标尺对照合并结果。"""
from __future__ import annotations

from app.db import get_db
from app.services import rulers
from app.services.errors import ServiceError


def list_reports(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT r.*, p.plan_code, p.target_table FROM volume_reports r "
            "JOIN compact_plans p ON p.id=r.plan_id ORDER BY r.id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def run_reconcile(plan_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        plan = conn.execute(
            "SELECT * FROM compact_plans WHERE id=?", (plan_id,)
        ).fetchone()
        if not plan:
            raise ServiceError("计划不存在", 404)
        plan_dict = dict(plan)
        # 对账页采用哪套标尺完全跟选定标尺走；缺标尺/跨源中文报错，不猜现行目录
        ruler = rulers.load_ruler(conn, plan_dict, db_path=db_path)
        expect_mount = rulers.mount_dir_for(plan["target_table"])
        if ruler["mount_dir"] != expect_mount:
            raise ServiceError(
                f"挂载目录与标尺不同源：标尺锁定 {ruler['mount_dir']}，"
                f"当前挂载 {expect_mount}，已拦截对账落库"
            )
        current = rulers.current_mount_fingerprint(conn, plan_dict)
        if current["mount_fingerprint"] != ruler["mount_fingerprint"]:
            raise ServiceError(
                "挂载指纹与冻结标尺不一致（挂载目录在发布后发生变动），"
                f"标尺 {ruler['total_bytes']} 字节 / 现挂载 {current['total_bytes']} 字节，"
                "已拦截对账落库"
            )
        before_b = int(ruler["total_bytes"])  # 同源冻结总字节，不跟现行目录猜数
        item_count = conn.execute(
            "SELECT COUNT(*) AS c FROM plan_items WHERE plan_id=?", (plan_id,)
        ).fetchone()["c"]
        job = conn.execute(
            "SELECT * FROM rewrite_jobs WHERE plan_id=? AND status='成功' "
            "ORDER BY id DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        after = int(job["merged_bytes"]) if job else 0
        aligned = bool(job) and after == before_b
        label = ruler["ruler_source_label"]
        summary = (
            f"计划 {plan['plan_code']}：按{label}冻结挂载 {ruler['mount_dir']} "
            f"{before_b} 字节 / {ruler['file_count']} 文件，"
        )
        if not job:
            summary += "尚无成功合并任务，合并后字节记 0；请先执行重写合并再对账"
        elif aligned:
            summary += f"合并后记 {after} 字节，同源总字节一致，对账对齐"
        else:
            summary += (
                f"合并后记 {after} 字节，与标尺 {before_b} 字节不一致，"
                "体积不一致须人工核对"
            )
        cur = conn.execute(
            "INSERT INTO volume_reports(plan_id, before_bytes, after_bytes, "
            "file_count, ruler_source, mount_dir, mount_fingerprint, aligned, summary) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                plan_id,
                before_b,
                after,
                int(item_count),
                ruler["ruler_source"],
                ruler["mount_dir"],
                ruler["mount_fingerprint"],
                1 if aligned else 0,
                summary,
            ),
        )
        out = dict(
            conn.execute(
                "SELECT * FROM volume_reports WHERE id=?", (cur.lastrowid,)
            ).fetchone()
        )
        out["ruler_source_label"] = label
        return out
