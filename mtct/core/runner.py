"""执行编排：终端 × 故障 × 用例。

串行执行（单机单浏览器），但结果模型/产物落盘/视觉比对/判定钩子都已定型；
后续接 Celery 只是把 run_case 投进队列，上层模型不变。
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..adapters.base import Adapter
from ..ai.triage import TriageClient
from ..assertions.layout import evaluate
from ..core.models import (
    AssertionResult,
    CaseResult,
    RunSummary,
    TestCase,
    TerminalProfile,
)
from ..visual.baseline import baseline_path
from ..visual.diff import compare_images


class ReadyTimeout(RuntimeError):
    """页面在超时内没有进入稳定态。"""


async def run_matrix(
    *,
    cases: list[TestCase],
    terminals: list[TerminalProfile],
    faults: list[str],
    adapter: Adapter,
    base_url: str,
    out_dir: str | Path,
    timeout_ms: int = 20000,
    on_progress: Callable[[CaseResult], None] | None = None,
    baselines: str | Path | None = None,
    triage: TriageClient | None = None,
    visual_tolerance: float = 0.00005,
) -> RunSummary:
    out_path = Path(out_dir)
    (out_path / "screens").mkdir(parents=True, exist_ok=True)

    summary = RunSummary(
        run_id=out_path.name,
        started_at=datetime.now().isoformat(timespec="seconds"),
        base_url=base_url,
        out_dir=str(out_path),
    )

    await adapter.start()
    try:
        for terminal in terminals:
            for fault in faults:
                for case in cases:
                    result = await execute_case(
                        adapter, terminal, case, fault, base_url, out_path, timeout_ms,
                        baselines=baselines, triage=triage,
                        visual_tolerance=visual_tolerance,
                    )
                    summary.results.append(result)
                    if on_progress:
                        on_progress(result)
    finally:
        await adapter.stop()

    return summary


async def execute_case(
    adapter: Adapter,
    terminal: TerminalProfile,
    case: TestCase,
    fault: str,
    base_url: str,
    out_dir: Path | str,
    timeout_ms: int = 20000,
    *,
    baselines: str | Path | None = None,
    triage: TriageClient | None = None,
    visual_tolerance: float = 0.00005,
) -> CaseResult:
    out_dir = Path(out_dir)
    started = time.perf_counter()
    page = context = None
    url = ""
    assertions: list[AssertionResult] = []
    screenshot_rel: str | None = None
    error: str | None = None
    triage_data: dict[str, Any] | None = None
    shot_path: Path | None = None

    try:
        page, context, console_errors, url = await adapter.open(
            terminal, base_url, case.path, fault
        )
        if case.wait_ready:
            try:
                await adapter.wait_ready(page, timeout_ms)
            except Exception as exc:  # noqa: BLE001 - 需要把原始错误带进报告
                raise ReadyTimeout(
                    f"就绪门控超时（{timeout_ms}ms）：页面未进入稳定态，"
                    f"可能是加载态卡死或接口失败。原始错误: {exc}"
                ) from exc

        assertions = await evaluate(case.assertions, page, console_errors)

        need_screenshot = bool(case.screenshot or case.visual)
        if need_screenshot:
            name = f"{case.key}__{terminal.id}__{fault}.png".replace(" ", "_")
            shot_path = out_dir / "screens" / name
            shot_path.parent.mkdir(parents=True, exist_ok=True)
            await adapter.screenshot(page, str(shot_path))
            if case.screenshot:
                screenshot_rel = f"screens/{name}"

        # 视觉比对：在"布局不变量"之后，补上像素级变化
        if case.visual and baselines and shot_path is not None:
            base_path = baseline_path(baselines, terminal, case.key)
            if not base_path.exists():
                assertions.append(
                    AssertionResult(
                        "visual_diff", str(base_path), True,
                        "基线不存在，跳过视觉比对（先执行 mtct baseline）",
                    )
                )
            else:
                tolerance = float(case.visual.get("tolerance", visual_tolerance))
                tag = f"{case.key}__{terminal.id}__{fault}".replace(" ", "_")
                diff = compare_images(
                    base_path, shot_path, tolerance=tolerance,
                    out_dir=out_dir / "diffs", tag=tag,
                )
                assertions.append(
                    AssertionResult(
                        "visual_diff", f"baseline:{base_path.name}",
                        diff.passed, diff.message, diff.to_dict(),
                    )
                )
                # AI 只处理"规则已判定有变化但拿不准性质"的样本
                if not diff.passed and triage is not None and triage.enabled \
                        and case.visual.get("triage", True):
                    triage_data = (
                        await triage.triage(
                            diff.crop_image or str(shot_path),
                            {
                                "page": case.page or case.path,
                                "case": case.key,
                                "terminal": terminal.id,
                                "diff_ratio": diff.diff_ratio,
                                "bbox": diff.bbox,
                            },
                        )
                    ).to_dict()

        status = "passed" if all(a.passed for a in assertions) else "failed"
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass

    return CaseResult(
        case_key=case.key,
        case_name=case.name,
        terminal_id=terminal.id,
        fault=fault,
        status=status,
        duration_ms=int((time.perf_counter() - started) * 1000),
        assertions=assertions,
        screenshot=screenshot_rel,
        error=error,
        url=url,
        triage=triage_data,
    )