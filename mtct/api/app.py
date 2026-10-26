"""FastAPI 应用：Run 提交 / 查询 / 取消 / 报告 / 极简看板。"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..core.models import TestCase
from ..matrix import profiles
from .db import Database
from .service import RunService


class RunCreate(BaseModel):
    cases: list[str] = Field(..., min_length=1)
    terminals: list[str] = Field(default_factory=lambda: ["default"])
    faults: list[str] = Field(default_factory=lambda: ["none"])


def load_cases(cases_dir: Path) -> dict[str, TestCase]:
    out: dict[str, TestCase] = {}
    for path in sorted(cases_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        case = TestCase.from_dict(data)
        out[case.key] = case
    return out


def create_app(
    *,
    db_path: str | Path,
    cases_dir: str | Path,
    base_url: str,
    runs_dir: str | Path,
    baselines: str | Path,
    headless: bool = True,
    channel: str | None = None,
) -> FastAPI:
    db = Database(db_path)
    cases = load_cases(Path(cases_dir))
    service = RunService(
        db=db,
        cases=cases,
        base_url=base_url,
        runs_dir=runs_dir,
        baselines=baselines,
        adapter_kwargs={"headless": headless, "channel": channel},
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        service.start()
        try:
            yield
        finally:
            await service.stop()
            db.close()

    app = FastAPI(title="MTCT API", version="0.5.0", lifespan=lifespan)
    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(web_dir), html=True), name="ui")
    app.state.db = db
    app.state.service = service
    app.state.cases = cases

    def run_view(run: dict[str, Any]) -> dict[str, Any]:
        view = {
            "id": run["id"],
            "status": run["status"],
            "created_at": run["created_at"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
            "total": run["total"],
            "passed": run["passed"],
            "failed": run["failed"],
            "errors": run["errors"],
            "request": json.loads(run["request_json"]),
        }
        if run.get("report_path"):
            view["report_url"] = f"/api/runs/{run['id']}/report"
        return view

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {
            "cases": [
                {"key": c.key, "name": c.name, "page": c.page, "path": c.path}
                for c in cases.values()
            ],
            "terminals": [
                {"id": t.id, "width": t.width, "height": t.height,
                 "dpr": t.dpr, "locale": t.locale, "network": t.network}
                for t in profiles.resolve(["all"])
            ],
            "faults": ["none", "layout-card-overflow", "layout-btn-overlap",
                       "bench-001", "bench-031", "bench-091"],
        }

    @app.post("/api/runs", status_code=202)
    def create_run(
        payload: RunCreate,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        unknown = [key for key in payload.cases if key not in cases]
        if unknown:
            raise HTTPException(status_code=400, detail=f"未知用例: {', '.join(unknown)}")
        try:
            profiles.resolve(payload.terminals)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        request = {
            "cases": payload.cases,
            "terminals": payload.terminals,
            "faults": payload.faults,
        }
        run = service.submit(request, idempotency_key)
        if run["status"] != "queued":
            response.status_code = 200  # 幂等命中，返回已有 Run
        return run_view(run)

    @app.get("/api/runs")
    def list_runs(limit: int = 20) -> list[dict[str, Any]]:
        return [run_view(run) for run in db.list_runs(limit)]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        run = db.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run 不存在")
        view = run_view(run)
        items = db.list_case_results(run_id)
        for item in items:
            terminal = profiles.TERMINALS.get(item["terminal_id"])
            visual_key = terminal.visual_key if terminal else ""
            tag = f"{item['case_key']}__{item['terminal_id']}__{item['fault']}".replace(" ", "_")
            artifacts = {
                "diff": f"/api/runs/{run_id}/file?path=diffs/{quote(tag)}.diff.png",
                "crop": f"/api/runs/{run_id}/file?path=diffs/{quote(tag)}.crop.png",
            }
            if item.get("screenshot"):
                artifacts["actual"] = (
                    f"/api/runs/{run_id}/file?path={quote(item['screenshot'])}"
                )
            if visual_key:
                artifacts["baseline"] = (
                    f"/api/baselines/{quote(visual_key)}/{quote(item['case_key'])}"
                )
            item["artifacts"] = artifacts
        view["cases"] = items
        return view

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict[str, Any]:
        run = service.cancel(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run 不存在")
        return {"id": run_id, "status": run["status"], "cancel_requested": True}

    @app.get("/api/runs/{run_id}/clusters")
    def get_clusters(run_id: str) -> dict[str, Any]:
        data = service.get_clusters(run_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Run 不存在")
        return data

    @app.post("/api/runs/{run_id}/cluster")
    def rebuild_clusters(run_id: str) -> dict[str, Any]:
        data = service.recluster(run_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Run 不存在")
        return data

    @app.get("/api/runs/{run_id}/report")
    def get_report(run_id: str) -> FileResponse:
        run = db.get_run(run_id)
        if run is None or not run.get("report_path"):
            raise HTTPException(status_code=404, detail="报告尚未生成")
        path = Path(run["report_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="报告文件不存在")
        return FileResponse(path)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/ui/")

    @app.get("/api/runs/{run_id}/file")
    def run_file(run_id: str, path: str) -> FileResponse:
        """按相对路径读取 Run 产物（截图 / diff / 报告），限制在 Run 目录内。"""
        if db.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run 不存在")
        base = (Path(runs_dir) / run_id).resolve()
        target = (base / path).resolve()
        if not str(target).startswith(str(base)) or not target.is_file():
            raise HTTPException(status_code=404, detail="产物不存在")
        return FileResponse(target)

    @app.get("/api/baselines/{visual_key}/{case_key}")
    def baseline_file(visual_key: str, case_key: str) -> FileResponse:
        path = Path(baselines) / visual_key / f"{case_key}.png"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="基线不存在")
        return FileResponse(path)

    return app