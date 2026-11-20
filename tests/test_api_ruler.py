"""HTTP 层：中文错误透出、发布响应标尺芯片、meta 标尺来源。"""
import json

from tornado.testing import AsyncHTTPTestCase

from app.config import Config
from app.main import make_app
from app.seed import reset_seed
from app.services import rulers


class RulerApiTest(AsyncHTTPTestCase):
    def get_app(self):
        return make_app()

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmp.name) / "t.db")
        self._old = Config.DEFAULT_DB
        Config.DEFAULT_DB = self.db_path
        import os

        os.environ["DATABASE_PATH"] = self.db_path
        reset_seed(self.db_path)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        Config.DEFAULT_DB = self._old
        import os

        os.environ.pop("DATABASE_PATH", None)
        self._tmp.cleanup()

    def _login(self):
        r = self.fetch(
            "/api/login",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"username": "admin", "password": "123456"}),
        )
        self.assertEqual(r.code, 200)
        cookie = r.headers.get_list("Set-Cookie")[0].split(";")[0]
        return {"Cookie": cookie, "Content-Type": "application/json"}

    def test_meta_reports_ruler_source(self):
        h = self._login()
        r = self.fetch("/api/meta", headers=h)
        j = json.loads(r.body)
        self.assertEqual(j["ruler_source"], rulers.LEDGER_SOURCE)
        self.assertEqual(j["ruler_source_label"], "旁路账册凭证")

    def test_publish_carries_ruler_chip_and_block_is_chinese(self):
        h = self._login()
        # 造独立表计划
        body = json.dumps(
            {"path": "lake/lab_http/a.parquet", "table_name": "lab_http", "size_bytes": 99_000}
        )
        self.fetch("/api/files", method="POST", headers=h, body=body)
        body = json.dumps(
            {"plan_code": "CP-HTTP1", "title": "HTTP计划", "target_table": "lab_http"}
        )
        r = self.fetch("/api/plans", method="POST", headers=h, body=body)
        pid = json.loads(r.body)["item"]["id"]
        self.fetch(f"/api/plans/{pid}/attach", method="POST", headers=h, body="{}")
        r = self.fetch(f"/api/plans/{pid}/publish", method="POST", headers=h, body="{}")
        self.assertEqual(r.code, 200)
        item = json.loads(r.body)["item"]
        self.assertEqual(item["ruler"]["ruler_source_label"], "旁路账册凭证")
        self.assertEqual(item["ruler"]["total_bytes"], 99_000)
        # 计划列表芯片同源
        r = self.fetch("/api/plans", headers=h)
        chips = [p["ruler"] for p in json.loads(r.body)["items"] if p["id"] == pid]
        self.assertTrue(chips[0]["same_source"])
        # 切到快照源后，旧计划合并被中文拦截
        self.fetch(
            "/api/settings",
            method="POST",
            headers=h,
            body=json.dumps(
                {"key": rulers.RULER_SOURCE_KEY, "value": rulers.SNAPSHOT_SOURCE}
            ),
        )
        r = self.fetch(f"/api/rewrite/plans/{pid}/start", method="POST", headers=h, body="{}")
        self.assertEqual(r.code, 400)
        j = json.loads(r.body)
        self.assertIn("标尺来源不一致", j["error"])

    def test_invalid_source_setting_chinese_400(self):
        h = self._login()
        r = self.fetch(
            "/api/settings",
            method="POST",
            headers=h,
            body=json.dumps({"key": rulers.RULER_SOURCE_KEY, "value": "nope"}),
        )
        self.assertEqual(r.code, 400)
        self.assertIn("体积标尺来源只允许", json.loads(r.body)["error"])
