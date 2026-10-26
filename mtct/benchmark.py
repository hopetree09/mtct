"""基准集评测：对每条注入缺陷跑一次，计算检出率与误报。

指标口径（与说明书第 8 节一致）：
- recall_any           : 只要有断言失败/就绪门控拦截，就算"检出"
- recall_expected      : 失败断言里包含该故障预期的检出规则
- visual_missed        : expected_detector=visual 的故障，规则引擎抓不到（留给像素 diff + AI）
- false_positive       : 无故障（none）基线跑出的失败数，必须为 0
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .adapters.base import Adapter
from .core.models import CaseResult, TestCase, TerminalProfile
from .core.runner import execute_case


async def run_benchmark(
    *,
    faults: list[dict[str, Any]],
    cases_by_page: dict[str, TestCase],
    terminal: TerminalProfile,
    adapter: Adapter,
    base_url: str,
    out_dir: str | Path,
    timeout_ms: int = 20000,
    on_progress: Callable[[dict[str, Any], CaseResult], None] | None = None,
    baselines: str | Path | None = None,
    triage=None,
    visual_tolerance: float = 0.00005,
) -> dict[str, Any]:
    out = Path(out_dir)
    (out / "screens").mkdir(parents=True, exist_ok=True)
    started = datetime.now()

    # 评测不需要截图，省时间省磁盘
    cases_by_page = {p: replace(c, screenshot=False) for p, c in cases_by_page.items()}

    baseline_results: dict[str, CaseResult] = {}
    records: list[dict[str, Any]] = []

    await adapter.start()
    try:
        for page, case in cases_by_page.items():
            baseline_results[page] = await execute_case(
                adapter, terminal, case, "none", base_url, out, timeout_ms,
                baselines=baselines, triage=triage, visual_tolerance=visual_tolerance,
            )

        for fault in faults:
            case = cases_by_page.get(fault["page"])
            if case is None:
                continue
            result = await execute_case(
                adapter, terminal, case, fault["id"], base_url, out, timeout_ms,
                baselines=baselines, triage=triage, visual_tolerance=visual_tolerance,
            )
            records.append({"fault": fault, "result": result})
            if on_progress:
                on_progress(fault, result)
    finally:
        await adapter.stop()

    return summarize(faults, records, baseline_results, terminal, started, out)


def summarize(
    faults: list[dict[str, Any]],
    records: list[dict[str, Any]],
    baselines: dict[str, CaseResult],
    terminal: TerminalProfile,
    started: datetime,
    out: Path,
) -> dict[str, Any]:
    triage_counts: dict[str, int] = {}
    detected_any = 0
    detected_expected = 0
    errors = 0
    missed: list[dict[str, Any]] = []
    by_category: dict[str, dict[str, int]] = {}

    for record in records:
        fault = record["fault"]
        result: CaseResult = record["result"]
        category = fault["category"]
        bucket = by_category.setdefault(category, {"total": 0, "detected": 0})
        bucket["total"] += 1

        failed_rules = [a.rule for a in result.assertions if not a.passed]
        expected = fault.get("expected_detector", "")
        detected = False

        if result.status == "error":
            if expected == "ready_gate":
                detected = True
                detected_expected += 1
            else:
                errors += 1
        elif failed_rules:
            detected = True
            if expected in failed_rules:
                detected_expected += 1

        if result.triage:
            verdict = result.triage.get("verdict", "unknown")
            triage_counts[verdict] = triage_counts.get(verdict, 0) + 1

        if detected:
            detected_any += 1
            bucket["detected"] += 1
        else:
            missed.append({
                "id": fault["id"],
                "page": fault["page"],
                "category": category,
                "selector": fault["selector"],
                "expected_detector": expected,
                "note": fault["note"],
                "status": result.status,
            })

    baseline_failures = [
        {"page": page, "case": r.case_key,
         "failed": [a.rule for a in r.assertions if not a.passed],
         "error": r.error}
        for page, r in baselines.items()
        if r.status != "passed"
    ]

    total = len(records)
    return {
        "terminal": terminal.id,
        "started_at": started.isoformat(timespec="seconds"),
        "duration_s": round((datetime.now() - started).total_seconds(), 1),
        "total": total,
        "detected_any": detected_any,
        "detected_expected": detected_expected,
        "missed": len(missed),
        "errors": errors,
        "false_positive": len(baseline_failures),
        "recall_any": round(detected_any / total, 4) if total else 0.0,
        "recall_expected": round(detected_expected / total, 4) if total else 0.0,
        "by_category": by_category,
        "missed_items": missed,
        "triage_counts": triage_counts,
        "baseline_failures": baseline_failures,
        "out_dir": str(out),
    }


def write_markdown(summary: dict[str, Any], path: str | Path) -> None:
    lines = [
        "# MTCT 缺陷基准集评测报告",
        "",
        f"- 终端：`{summary['terminal']}`",
        f"- 开始时间：{summary['started_at']}",
        f"- 总耗时：{summary['duration_s']}s",
        f"- 故障总数：**{summary['total']}**",
        f"- 检出（任意断言）：**{summary['detected_any']}**（recall_any = {summary['recall_any']:.1%}）",
        f"- 按预期规则检出：**{summary['detected_expected']}**（recall_expected = {summary['recall_expected']:.1%}）",
        f"- 漏检：{summary['missed']}",
        f"- 执行异常（非门控）：{summary['errors']}",
        f"- **基线误报：{summary['false_positive']}**",
        "",
        "## 分类别",
        "",
        "| 类别 | 故障数 | 检出 | 检出率 |",
        "|---|---|---|---|",
    ]
    for category, bucket in sorted(summary["by_category"].items()):
        rate = bucket["detected"] / bucket["total"] if bucket["total"] else 0
        lines.append(f"| {category} | {bucket['total']} | {bucket['detected']} | {rate:.1%} |")

    lines += ["", "## 漏检明细", ""]
    if summary["missed_items"]:
        lines += ["| id | 页面 | 类别 | 选择器 | 期望检出 |", "|---|---|---|---|---|"]
        for item in summary["missed_items"]:
            lines.append(
                f"| {item['id']} | {item['page']} | {item['category']} | "
                f"`{item['selector']}` | {item['expected_detector']} |"
            )
    else:
        lines.append("无")

    lines += ["", "## AI 判定分布", ""]
    if summary.get("triage_counts"):
        lines += ["| verdict | 数量 |", "|---|---|"]
        for verdict, count in sorted(summary["triage_counts"].items()):
            lines.append(f"| {verdict} | {count} |")
    else:
        lines.append("未启用 AI 判定（未配置 API Key 或 `--triage off`）")
    lines += ["", "## 基线误报", ""]
    if summary["baseline_failures"]:
        lines += ["| 页面 | 用例 | 失败断言 |", "|---|---|---|"]
        for item in summary["baseline_failures"]:
            lines.append(
                f"| {item['page']} | {item['case']} | {', '.join(item['failed']) or item['error']} |"
            )
    else:
        lines.append("无（无故障基线下 6 个页面全部通过）")

    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(summary: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )