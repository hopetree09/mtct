"""API 冒烟测试：不启动浏览器，只验证契约与校验。

真正的执行链路由 `mtct run` / `mtct eval` 覆盖；
这里守住的是 HTTP 契约（健康检查、元数据、参数校验）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mtct.api.app import create_app


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        db_path=tmp_path / "test.db",
        cases_dir=ROOT / "cases",
        base_url="http://127.0.0.1:8765",
        runs_dir=tmp_path / "runs",
        baselines=tmp_path / "baselines",
        headless=True,
    )
    return TestClient(app)


def test_healthz(tmp_path):
    with _client(tmp_path) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_meta_lists_cases_and_terminals(tmp_path):
    with _client(tmp_path) as client:
        data = client.get("/api/meta").json()
        assert len(data["cases"]) == 6
        assert any(t["id"] == "chromium-1366-dpr1-zh" for t in data["terminals"])


def test_create_run_rejects_unknown_case(tmp_path):
    with _client(tmp_path) as client:
        resp = client.post("/api/runs", json={"cases": ["not-exist"]})
        assert resp.status_code == 400
        assert "未知用例" in resp.json()["detail"]


def test_runs_list_empty(tmp_path):
    with _client(tmp_path) as client:
        assert client.get("/api/runs").json() == []