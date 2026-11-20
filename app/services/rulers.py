"""体积标尺：计划发布时单次落盘的冻结挂载体积。

两套互斥落点（台参数 volume_ruler_source 单选，两套落点不同开）：
- snapshot_file 物化不可变快照：JSON 快照写一次后锁死只读，拒再改；
- ledger_voucher 旁路压实账册：写入计划凭证表 volume_ruler_vouchers，
  按 plan_id 唯一记录挂载指纹与总字节。

挂载目录由计划目标表同源派生（lake/<目标表>），标尺与挂载目录必须同源。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.db import get_db
from app.services.errors import ServiceError

SNAPSHOT_SOURCE = "snapshot_file"
LEDGER_SOURCE = "ledger_voucher"
RULER_SOURCE_KEY = "volume_ruler_source"
RULER_SOURCE_LABELS = {
    SNAPSHOT_SOURCE: "物化不可变快照",
    LEDGER_SOURCE: "旁路账册凭证",
}
VALID_SOURCES = (SNAPSHOT_SOURCE, LEDGER_SOURCE)
DEFAULT_SOURCE = LEDGER_SOURCE


def source_label(source: str) -> str:
    return RULER_SOURCE_LABELS.get(source, source or "未知标尺")


def mount_dir_for(target_table: str) -> str:
    """挂载目录与计划目标表同源派生，不允许另拧。"""
    table = (target_table or "").strip()
    if not table:
        raise ServiceError("目标表为空，无法同源派生挂载目录")
    return f"lake/{table}"


def active_ruler_source(db_path: str | None = None) -> str:
    with get_db(db_path) as conn:
        return active_source_from_conn(conn)


def active_source_from_conn(conn) -> str:
    row = conn.execute(
        "SELECT value FROM lab_settings WHERE key=?", (RULER_SOURCE_KEY,)
    ).fetchone()
    source = (row["value"] if row else DEFAULT_SOURCE).strip()
    if source not in VALID_SOURCES:
        raise ServiceError(f"台参数体积标尺来源非法：{source}")
    return source


def _base_dir(db_path: str | None) -> Path:
    from app.config import Config

    return Path(db_path or Config.database()).parent


def snapshot_dir(db_path: str | None = None) -> Path:
    return _base_dir(db_path) / "ruler_snapshots"


def _snapshot_path(plan_id: int, db_path: str | None = None) -> Path:
    return snapshot_dir(db_path) / f"plan_{plan_id}.ruler.json"


@contextmanager
def publish_lock(db_path: str | None = None):
    """发布排他锁：两侧仓管同点发布时，缺锁会双写标尺互相覆盖。"""
    lock_path = _base_dir(db_path) / "ruler_publish.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def compute_mount(conn, plan: dict) -> dict:
    """按当前 plan_items 计算挂载目录、总字节与挂载指纹。"""
    mount_dir = mount_dir_for(plan["target_table"])
    rows = conn.execute(
        "SELECT f.path, f.size_bytes FROM plan_items i "
        "JOIN lake_files f ON f.id=i.file_id WHERE i.plan_id=? ORDER BY f.path",
        (plan["id"],),
    ).fetchall()
    if not rows:
        raise ServiceError("空计划不可发布：挂载目录无碎文件，无法冻结体积标尺")
    total_bytes = sum(int(r["size_bytes"]) for r in rows)
    digest = hashlib.sha256()
    for r in rows:
        digest.update(f"{r['path']}:{int(r['size_bytes'])}\n".encode("utf-8"))
    return {
        "mount_dir": mount_dir,
        "total_bytes": total_bytes,
        "file_count": len(rows),
        "mount_fingerprint": digest.hexdigest(),
    }


def _write_snapshot(plan: dict, mount: dict, source: str, db_path: str | None) -> None:
    path = _snapshot_path(plan["id"], db_path)
    if path.exists():
        raise ServiceError(
            f"物化不可变快照已存在且锁死只读：{path.name}，拒绝再次落盘修改"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "plan_id": plan["id"],
        "plan_code": plan["plan_code"],
        "ruler_source": source,
        "mount_dir": mount["mount_dir"],
        "total_bytes": mount["total_bytes"],
        "file_count": mount["file_count"],
        "mount_fingerprint": mount["mount_fingerprint"],
    }
    tmp = path.with_suffix(".tmp")
    if tmp.exists():
        tmp.chmod(0o600)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o444)  # 锁死只读，拒再改
    os.replace(tmp, path)


def _write_voucher(
    conn, plan: dict, mount: dict, source: str
) -> None:
    try:
        conn.execute(
            "INSERT INTO volume_ruler_vouchers(plan_id, plan_code, mount_dir, "
            "total_bytes, file_count, mount_fingerprint, ruler_source) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                plan["id"],
                plan["plan_code"],
                mount["mount_dir"],
                mount["total_bytes"],
                mount["file_count"],
                mount["mount_fingerprint"],
                source,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ServiceError(
            f"计划凭证表已存在计划 {plan['plan_code']} 的挂载指纹与总字节，"
            "旁路账册标尺拒绝重复写入"
        ) from exc


def write_ruler(
    conn, plan: dict, mount: dict, source: str, db_path: str | None = None
) -> dict:
    """按选定标尺单次落盘；两套落点互斥，不会同开。"""
    if source == SNAPSHOT_SOURCE:
        _write_snapshot(plan, mount, source, db_path)
    elif source == LEDGER_SOURCE:
        _write_voucher(conn, plan, mount, source)
    else:
        raise ServiceError(f"未知体积标尺来源：{source}")
    return {
        "ruler_source": source,
        "ruler_source_label": source_label(source),
        "mount_dir": mount["mount_dir"],
        "total_bytes": mount["total_bytes"],
        "file_count": mount["file_count"],
        "mount_fingerprint": mount["mount_fingerprint"],
    }


def load_ruler(
    conn,
    plan: dict,
    expected_source: str | None = None,
    db_path: str | None = None,
) -> dict:
    """按（选定的）标尺读冻结总字节；来源不同源或标尺缺失一律中文报错。"""
    expected = expected_source or active_ruler_source(db_path)
    plan_source = (plan["ruler_source"] or "").strip()
    if not plan_source:
        raise ServiceError(
            f"计划 {plan['plan_code']} 尚未点亮发布体积标尺，合并落库已拦截"
        )
    if plan_source != expected:
        raise ServiceError(
            "标尺来源不一致：计划发布时为「"
            f"{source_label(plan_source)}」，当前台参数为「{source_label(expected)}」，"
            "请切回同源标尺后再操作"
        )
    if plan_source == SNAPSHOT_SOURCE:
        path = _snapshot_path(plan["id"], db_path)
        if not path.exists():
            raise ServiceError(
                f"物化不可变快照缺失：{path.name}，无法读取冻结挂载总字节"
            )
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        ruler = dict(payload)
    else:
        row = conn.execute(
            "SELECT * FROM volume_ruler_vouchers WHERE plan_id=?", (plan["id"],)
        ).fetchone()
        if not row:
            raise ServiceError(
                f"计划凭证表缺少计划 {plan['plan_code']} 的挂载指纹与总字节，"
                "旁路账册标尺不可用"
            )
        ruler = dict(row)
    ruler["ruler_source_label"] = source_label(plan_source)
    return ruler


def current_mount_fingerprint(conn, plan: dict) -> dict:
    """重算当前挂载指纹，供合并/对账时发现挂载漂移。"""
    return compute_mount(conn, plan)


def plan_ruler_chip(conn, plan: dict, db_path: str | None = None) -> dict:
    """计划列表/详情的标尺来源芯片；列表只读，不因跨源直接抛错。"""
    source = (plan["ruler_source"] or "").strip()
    active = active_source_from_conn(conn)
    if not source:
        return {
            "ruler_source": "",
            "ruler_source_label": "未冻结",
            "active_source": active,
            "active_source_label": source_label(active),
            "same_source": False,
            "frozen": False,
        }
    frozen = None
    if source == SNAPSHOT_SOURCE:
        path = _snapshot_path(plan["id"], db_path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    frozen = json.load(f)
            except (OSError, json.JSONDecodeError):
                frozen = None
    else:
        row = conn.execute(
            "SELECT total_bytes, mount_dir, file_count, mount_fingerprint "
            "FROM volume_ruler_vouchers WHERE plan_id=?",
            (plan["id"],),
        ).fetchone()
        if row:
            frozen = dict(row)
    return {
        "ruler_source": source,
        "ruler_source_label": source_label(source),
        "active_source": active,
        "active_source_label": source_label(active),
        "same_source": source == active,
        "frozen": frozen is not None,
        "total_bytes": int(frozen["total_bytes"]) if frozen else 0,
        "mount_dir": frozen["mount_dir"] if frozen else "",
        "file_count": int(frozen["file_count"]) if frozen else 0,
        "mount_fingerprint": frozen["mount_fingerprint"] if frozen else "",
    }
