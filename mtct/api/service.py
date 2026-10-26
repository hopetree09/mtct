"""Run 服务：提交 → 队列 → 执行 → 增量落库 → 报告。

为什么先不上 Celery：
- 单机、单浏览器，asyncio.Queue + 单 worker 已经能表达"排队 + 状态机 + 取消"；
- 接口与 DB 模型不变，后续把 _execute 换成 Celery task 即可，迁移成本可控。

可靠性设计：
- 每个用例执行完立刻 upsert 落库（进程崩溃也能看到跑到哪了）；
- 幂等键命中直接返回已有 Run，不重复执行；
- 取消通过 DB 标记 + 每用例回调检查，最多延迟一个用例。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from dataclasses import asdict

from ..adapters.web_playwright import WebAdapter
from ..clustering import cluster_failures, evaluate_clusters, extract_failures
from ..core.models import TestCase
from ..core.runner import run_matrix
from ..matrix import profiles
from ..reports import write_html, write_json
from .db import Database


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class RunCancelled(Exception):
    """用户在用例间隙取消了 Run。"""


class RunService:
    def __init__(
        self,
        *,
        db: Database,
        cases: dict[str, TestCase],
        base_url: str,
        runs_dir: str | Path,
        baselines: str | Path,
        visual_tolerance: float = 0.00005,
        adapter_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self.db = db
        self.cases = cases
        self.base_url = base_url
        self.runs_dir = Path(runs_dir)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.baselines = str(baselines)
        self.visual_tolerance = visual_tolerance
        self.adapter_kwargs = adapter_kwargs or {}
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._current_run: str | None = None

    # ---------- 生命周期 ----------

    def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._loop(), name="mtct-run-worker")

    async def stop(self) -> None:
        await self.queue.put(None)
        if self._worker is not None:
            try:
                await asyncio.wait_for(self._worker, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._worker.cancel()
            self._worker = None

    # ---------- 提交 ----------

    def submit(self, request: dict[str, Any], idempotency_key: str | None) -> dict[str, Any]:
        if idempotency_key:
            existing = self.db.get_run_by_idempotency(idempotency_key)
            if existing:
                return existing
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.db.create_run(run_id, request, idempotency_key, now())
        self.queue.put_nowait(run_id)
        return self.db.get_run(run_id)  # type: ignore[return-value]

    def cancel(self, run_id: str) -> dict[str, Any] | None:
        run = self.db.get_run(run_id)
        if run is None:
            return None
        self.db.request_cancel(run_id)
        return self.db.get_run(run_id)

    # ---------- 队列 ----------

    async def _loop(self) -> None:
        while True:
            run_id = await self.queue.get()
            if run_id is None:
                return
            self._current_run = run_id
            try:
                if self.db.cancel_requested(run_id):
                    self.db.finish_run(run_id, "cancelled", now(), 0, 0, 0, 0, None)
                    continue
                await self._execute(run_id)
            except Exception as exc:  # noqa: BLE001 - 服务不能因单次 Run 崩溃
                print(f"[mtct] run {run_id} failed: {exc}")
                counts = self._counts(run_id)
                self.db.finish_run(
                    run_id, "failed", now(), counts["total"], counts["passed"],
                    counts["failed"], counts["errors"], None,
                )
            finally:
                self._current_run = None

    async def _execute(self, run_id: str) -> None:
        run = self.db.get_run(run_id)
        if run is None:
            return
        request = json.loads(run["request_json"])
        cases = [self.cases[key] for key in request["cases"]]
        terminals = profiles.resolve(request.get("terminals") or ["default"])
        faults = list(request.get("faults") or ["none"])
        out_dir = self.runs_dir / run_id

        self.db.mark_started(run_id, now())

        def on_progress(result) -> None:
            if self.db.cancel_requested(run_id):
                raise RunCancelled()
            self.db.upsert_case_result(run_id, result)

        try:
            summary = await run_matrix(
                cases=cases,
                terminals=terminals,
                faults=faults,
                adapter=WebAdapter(**self.adapter_kwargs),
                base_url=self.base_url,
                out_dir=out_dir,
                on_progress=on_progress,
                baselines=self.baselines,
                triage=None,
                visual_tolerance=self.visual_tolerance,
            )
        except RunCancelled:
            counts = self._counts(run_id)
            self.db.finish_run(
                run_id, "cancelled", now(), counts["total"], counts["passed"],
                counts["failed"], counts["errors"], None,
            )
            return

        write_json(summary, out_dir / "report.json")
        write_html(summary, out_dir / "report.html")
        self._persist_clusters(run_id, [asdict(r) for r in summary.results])
        self.db.finish_run(
            run_id, "finished", now(), summary.total, summary.passed,
            summary.failed, summary.errors, str(out_dir / "report.html"),
        )

    def _persist_clusters(self, run_id: str, results: list[dict]) -> None:
        page_of = {case.key: case.page for case in self.cases.values()}
        failures = extract_failures(results, page_of)
        clusters = cluster_failures(failures)
        metrics = evaluate_clusters(failures, clusters)
        self.db.save_clusters(run_id, [c.to_dict() for c in clusters], metrics)

    def get_clusters(self, run_id: str) -> dict | None:
        run = self.db.get_run(run_id)
        if run is None:
            return None
        metrics = json.loads(run.get("cluster_metrics_json") or "{}")
        return {"metrics": metrics, "clusters": self.db.list_clusters(run_id)}

    def recluster(self, run_id: str) -> dict | None:
        if self.db.get_run(run_id) is None:
            return None
        self._persist_clusters(run_id, self.db.list_case_results(run_id))
        return self.get_clusters(run_id)

    def _counts(self, run_id: str) -> dict[str, int]:
        results = self.db.list_case_results(run_id)
        return {
            "total": len(results),
            "passed": sum(1 for r in results if r["status"] == "passed"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "errors": sum(1 for r in results if r["status"] == "error"),
        }