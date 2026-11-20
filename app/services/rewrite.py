"""重写合并：按计划执行合并任务。"""
from __future__ import annotations

from app.db import get_db
from app.services import rulers
from app.services.errors import ServiceError


def list_jobs(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT j.*, p.plan_code, p.target_table FROM rewrite_jobs j "
            "JOIN compact_plans p ON p.id=j.plan_id ORDER BY j.id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def _resolve_published_ruler(conn, plan: dict, db_path: str | None) -> dict:
    """合并落库前的标尺同源闸门：缺标尺/跨源/挂载漂移一律中文拦截。"""
    ruler = rulers.load_ruler(conn, plan, db_path=db_path)
    # 挂载目录与标尺须同源：挂载目录必须与冻结标尺一致，拧了就拦合并落库
    expect_mount = rulers.mount_dir_for(plan["target_table"])
    if ruler["mount_dir"] != expect_mount:
        raise ServiceError(
            f"挂载目录与标尺不同源：标尺锁定 {ruler['mount_dir']}，"
            f"当前挂载 {expect_mount}，已拦截合并落库"
        )
    # 发布后挂载若又被改动（再挂/撤文件），指纹与总字节会漂移
    current = rulers.current_mount_fingerprint(conn, plan)
    if current["mount_fingerprint"] != ruler["mount_fingerprint"]:
        raise ServiceError(
            "挂载指纹与冻结标尺不一致（挂载目录在发布后发生变动），"
            f"标尺 {ruler['total_bytes']} 字节 / 现挂载 {current['total_bytes']} 字节，"
            "已拦截合并落库"
        )
    if current["total_bytes"] != int(ruler["total_bytes"]):
        raise ServiceError(
            "挂载总字节与冻结标尺不一致，已拦截合并落库"
        )
    return ruler


def start_rewrite(plan_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        plan = conn.execute(
            "SELECT * FROM compact_plans WHERE id=?", (plan_id,)
        ).fetchone()
        if not plan:
            raise ServiceError("计划不存在", 404)
        if plan["status"] not in ("已发布", "执行中"):
            raise ServiceError("仅已发布计划可启动合并", 409)
        running = conn.execute(
            "SELECT id FROM rewrite_jobs WHERE plan_id=? AND status IN ('待执行','执行中')",
            (plan_id,),
        ).fetchone()
        if running:
            raise ServiceError("已有在途合并任务", 409)
        plan_dict = dict(plan)
        ruler = _resolve_published_ruler(conn, plan_dict, db_path)
        items = conn.execute(
            "SELECT f.* FROM plan_items i JOIN lake_files f ON f.id=i.file_id "
            "WHERE i.plan_id=? AND f.status='已入计划'",
            (plan_id,),
        ).fetchall()
        if not items:
            raise ServiceError("计划下无可合并碎文件", 409)
        total = sum(int(x["size_bytes"]) for x in items)
        if total != int(ruler["total_bytes"]):
            raise ServiceError(
                f"合并体积 {total} 字节与标尺冻结总字节 {ruler['total_bytes']} 不一致，"
                "已拦截合并落库"
            )
        cur = conn.execute(
            "INSERT INTO rewrite_jobs(plan_id, status, merged_bytes, ruler_source, "
            "ruler_bytes, message, started_at) "
            "VALUES (?, '执行中', 0, ?, ?, '合并进行中', datetime('now'))",
            (plan_id, ruler["ruler_source"], int(ruler["total_bytes"])),
        )
        job_id = cur.lastrowid
        conn.execute(
            "UPDATE compact_plans SET status='执行中' WHERE id=?", (plan_id,)
        )
        # 同步成功路径：合并字节严格取自同源冻结标尺
        for row in items:
            conn.execute(
                "UPDATE lake_files SET status='已合并' WHERE id=?", (row["id"],)
            )
        conn.execute(
            "UPDATE rewrite_jobs SET status='成功', merged_bytes=?, message=?, "
            "finished_at=datetime('now') WHERE id=?",
            (
                int(ruler["total_bytes"]),
                f"已合并 {len(items)} 个碎文件（标尺：{ruler['ruler_source_label']}）",
                job_id,
            ),
        )
        conn.execute(
            "UPDATE compact_plans SET status='已完成' WHERE id=?", (plan_id,)
        )
        return dict(
            conn.execute(
                "SELECT * FROM rewrite_jobs WHERE id=?", (job_id,)
            ).fetchone()
        )


def fail_open_job(job_id: int, reason: str, db_path: str | None = None) -> dict:
    """预留：标记失败（基线测试与切口）。"""
    with get_db(db_path) as conn:
        job = conn.execute(
            "SELECT * FROM rewrite_jobs WHERE id=?", (job_id,)
        ).fetchone()
        if not job:
            raise ServiceError("任务不存在", 404)
        conn.execute(
            "UPDATE rewrite_jobs SET status='失败', message=?, finished_at=datetime('now') "
            "WHERE id=?",
            (reason or "合并失败", job_id),
        )
        return dict(
            conn.execute(
                "SELECT * FROM rewrite_jobs WHERE id=?", (job_id,)
            ).fetchone()
        )
