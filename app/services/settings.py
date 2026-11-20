"""台参数：压实阈值、对账模式与体积标尺来源。"""
from __future__ import annotations

from app.db import get_db
from app.services import rulers
from app.services.errors import ServiceError


def list_settings(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT key, value, label FROM lab_settings ORDER BY key"
        ).fetchall()
        return [dict(r) for r in rows]


def update_setting(key: str, value: str, db_path: str | None = None) -> dict:
    key = (key or "").strip()
    value = (value or "").strip()
    if not key or not value:
        raise ServiceError("参数键与值不能为空")
    if key == rulers.RULER_SOURCE_KEY and value not in rulers.VALID_SOURCES:
        raise ServiceError(
            "体积标尺来源只允许「"
            + "」或「".join(rulers.source_label(s) for s in rulers.VALID_SOURCES)
            + f"」之一，收到：{value}"
        )
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM lab_settings WHERE key=?", (key,)
        ).fetchone()
        if not row:
            raise ServiceError("参数不存在", 404)
        conn.execute(
            "UPDATE lab_settings SET value=? WHERE key=?", (value, key)
        )
        return dict(
            conn.execute(
                "SELECT key, value, label FROM lab_settings WHERE key=?", (key,)
            ).fetchone()
        )
