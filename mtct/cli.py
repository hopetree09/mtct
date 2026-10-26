"""命令行入口：python -m mtct run ..."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .adapters.web_playwright import WebAdapter
from .benchmark import run_benchmark, write_json as write_bench_json, write_markdown as write_bench_markdown
from .ai.triage import build_triage
from .clustering import (
    cluster_failures,
    evaluate_clusters,
    extract_failures,
    llm_name_cluster,
    write_markdown as write_clusters_markdown,
)
from .visual.baseline import capture_baseline
from .core.models import TestCase
from .core.runner import run_matrix
from .matrix import profiles
from .reports import print_console, write_html, write_json

ROOT = Path(__file__).resolve().parent.parent


def load_cases(paths: list[str]) -> list[TestCase]:
    cases: list[TestCase] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            raise SystemExit(f"用例文件不存在: {raw}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            cases.extend(TestCase.from_dict(item) for item in data)
        else:
            cases.append(TestCase.from_dict(data))
    return cases


def _port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def ensure_server(base_url: str, demo_dir: str, auto_serve: bool):
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    if _port_open(host, port):
        print(f"复用已运行的演示站：{base_url}")
        return None
    if not auto_serve:
        raise SystemExit(f"演示站未运行：{base_url}。加 --serve 可自动启动。")
    demo = Path(demo_dir)
    if not demo.exists():
        raise SystemExit(f"演示站目录不存在: {demo}")
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", host,
         "--directory", str(demo)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        if _port_open(host, port):
            print(f"已启动演示站：{base_url}")
            return proc
        time.sleep(0.2)
    proc.terminate()
    raise SystemExit("演示站启动失败")


def cmd_run(args) -> int:
    cases = load_cases(args.cases)
    terminals = profiles.resolve(args.terminals)
    faults = [f.strip() for f in args.faults.split(",") if f.strip()] or ["none"]

    total = len(cases) * len(terminals) * len(faults)
    print(f"用例 {len(cases)} × 终端 {len(terminals)} × 故障 {len(faults)} = {total} 次执行")
    for terminal in terminals:
        print(
            f"  - {terminal.id:<30} {terminal.width}x{terminal.height} "
            f"dpr={terminal.dpr:g} lang={terminal.locale} net={terminal.network}"
        )

    server = ensure_server(args.base_url, args.demo_dir, args.serve)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) / run_id

    def on_progress(result) -> None:
        mark = {"passed": "PASS", "failed": "FAIL", "error": "ERR "}[result.status]
        extra = result.error or ", ".join(a.rule for a in result.failed_assertions)
        print(
            f"  [{mark}] {result.terminal_id:<30} {result.case_key:<16} "
            f"{result.fault:<24} {result.duration_ms:>5}ms  {extra}"
        )

    try:
        triage = build_triage(getattr(args, "triage", "auto"))
        if not triage.enabled:
            print("AI 判定：未配置模型 API Key，视觉变化将标记 needs_human")
        summary = asyncio.run(
            run_matrix(
                cases=cases,
                terminals=terminals,
                faults=faults,
                adapter=WebAdapter(headless=not args.headed, channel=args.channel),
                base_url=args.base_url,
                out_dir=out_dir,
                timeout_ms=args.timeout_ms,
                on_progress=on_progress,
                baselines=args.baselines,
                triage=triage,
                visual_tolerance=args.visual_tolerance,
            )
        )
    finally:
        if server is not None:
            server.terminate()

    print_console(summary)
    write_json(summary, out_dir / "report.json")
    write_html(summary, out_dir / "report.html")
    print(f"报告: {out_dir / 'report.html'}")

    if args.fail_on_failures and (summary.failed or summary.errors):
        return 1
    return 0


def cmd_eval(args) -> int:
    """跑 120 例缺陷基准集，输出检出率、漏检明细与基线误报。"""
    faults = json.loads(Path(args.faults).read_text(encoding="utf-8"))
    case_paths = [str(p) for p in sorted(Path(args.cases).glob("*.yaml"))]
    cases = load_cases(case_paths)
    by_page: dict[str, TestCase] = {}
    for case in cases:
        page = case.page or (case.path.strip("/").split("/")[0] or "home")
        by_page[page] = case

    missing = sorted({f["page"] for f in faults} - set(by_page))
    if missing:
        raise SystemExit(f"缺少这些页面的用例: {', '.join(missing)}")

    terminal = profiles.resolve([args.terminal])[0]
    print(f"基准集 {len(faults)} 条 × 终端 {terminal.id}，覆盖页面 {len(by_page)} 个")
    server = ensure_server(args.base_url, args.demo_dir, args.serve)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) / run_id

    def on_progress(fault, result) -> None:
        mark = "PASS" if result.status == "passed" else "FAIL"
        print(
            f"  [{mark}] {fault['id']} {fault['page']:<9} "
            f"{fault['category']:<10} {fault['selector']}"
        )

    try:
        summary = asyncio.run(
            run_benchmark(
                faults=faults,
                cases_by_page=by_page,
                terminal=terminal,
                adapter=WebAdapter(headless=not args.headed, channel=args.channel),
                base_url=args.base_url,
                out_dir=out_dir,
                timeout_ms=args.timeout_ms,
                on_progress=on_progress,
                baselines=args.baselines,
                triage=build_triage(getattr(args, "triage", "auto")),
                visual_tolerance=args.visual_tolerance,
            )
        )
    finally:
        if server is not None:
            server.terminate()

    write_bench_markdown(summary, out_dir / "report.md")
    write_bench_json(summary, out_dir / "report.json")

    print()
    print(
        f"基准集 {summary['total']} 条：检出 {summary['detected_any']}，"
        f"按预期规则检出 {summary['detected_expected']}，漏检 {summary['missed']}，"
        f"执行异常 {summary['errors']}，基线误报 {summary['false_positive']}"
    )
    print(
        f"recall_any = {summary['recall_any']:.1%}   "
        f"recall_expected = {summary['recall_expected']:.1%}   "
        f"耗时 {summary['duration_s']}s"
    )
    print("分类别：")
    for category, bucket in sorted(summary["by_category"].items()):
        rate = bucket["detected"] / bucket["total"] if bucket["total"] else 0
        print(f"  {category:<10} {bucket['detected']:>3}/{bucket['total']:<3} {rate:.0%}")
    print(f"报告: {out_dir / 'report.md'}")
    return 0


def cmd_baseline(args) -> int:
    """采集视觉基线：每个 (终端 visual_key × 用例) 一张截图。"""
    case_paths = [str(p) for p in sorted(Path(args.cases).glob("*.yaml"))]
    cases = load_cases(case_paths)
    terminals = profiles.resolve(args.terminals)
    print(f"采集基线：{len(terminals)} 终端 × {len(cases)} 用例 = {len(terminals) * len(cases)} 张")

    server = ensure_server(args.base_url, args.demo_dir, args.serve)
    adapter = WebAdapter(headless=not args.headed, channel=args.channel)

    async def _run() -> None:
        await adapter.start()
        try:
            for terminal in terminals:
                for case in cases:
                    path = await capture_baseline(
                        adapter, terminal, case, args.base_url, args.out
                    )
                    print(f"  [base] {terminal.id:<30} {case.key:<16} -> {path}")
        finally:
            await adapter.stop()

    try:
        asyncio.run(_run())
    finally:
        if server is not None:
            server.terminate()
    print(f"基线目录: {args.out}")
    return 0


def cmd_api(args) -> int:
    """启动 HTTP API：提交/查询/取消 Run，报告与看板。"""
    import uvicorn

    from .api.app import create_app

    app = create_app(
        db_path=args.db,
        cases_dir=args.cases,
        base_url=args.base_url,
        runs_dir=args.runs_dir,
        baselines=args.baselines,
        headless=not args.headed,
        channel=args.channel,
    )
    print(f"MTCT API: http://{args.host}:{args.port}/   docs: /docs")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_cluster(args) -> int:
    """对一次 Run 的失败用例做聚类 + 根因命名。"""
    run_dir = Path(args.run)
    report_path = run_dir / "report.json"
    if not report_path.exists():
        raise SystemExit(f"找不到 report.json：{report_path}（先跑一轮 run）")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    case_paths = [str(p) for p in sorted(Path(args.cases).glob("*.yaml"))]
    cases = load_cases(case_paths)
    page_of = {case.key: case.page for case in cases}

    failures = extract_failures(report.get("results", []), page_of)

    # 补上缺陷类别（仅用于评测对照，不进入聚类特征）
    faults_path = ROOT / "demo" / "web-app" / "data" / "faults.json"
    if faults_path.exists():
        labels = {
            item["id"]: item.get("category")
            for item in json.loads(faults_path.read_text(encoding="utf-8"))
        }
        for failure in failures:
            failure.category_hint = labels.get(failure.fault)

    clusters = cluster_failures(failures)

    if args.llm_name:
        for cluster in clusters:
            members = [failures[i] for i in cluster.members]
            refined = llm_name_cluster(cluster, members)
            if refined:
                cluster.label, cluster.root_cause, _reason = refined
    else:
        print("命名：模板规则（配置 MTCT_LLM_API_KEY 后加 --llm-name 可用模型命名）")

    metrics = evaluate_clusters(failures, clusters)
    out = Path(args.out) if args.out else run_dir
    (out / "clusters.json").write_text(
        json.dumps(
            {"metrics": metrics, "clusters": [c.to_dict() for c in clusters]},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    write_clusters_markdown(failures, clusters, metrics, out / "clusters.md")

    print()
    print(f"失败 {metrics['failures']} 条 → 根因簇 {metrics['clusters']} 个"
          f"（压缩比 {metrics['compression']}:1）")
    print("-" * 96)
    print(f"{'簇':<6}{'根因标签':<28}{'成员':>4}  影响终端")
    print("-" * 96)
    for cluster in clusters:
        print(f"{cluster.cluster_id:<6}{cluster.label:<28}{cluster.member_count:>4}  "
              f"{', '.join(cluster.terminals)}")
    print("-" * 96)
    if "ari_vs_fault" in metrics:
        print(f"ARI(vs 注入故障) = {metrics['ari_vs_fault']}   "
              f"ARI(vs 缺陷类别) = {metrics.get('ari_vs_category')}   "
              f"簇纯度 = {metrics.get('purity')}")
    print(f"报告: {out / 'clusters.md'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mtct", description="多终端兼容性测试系统")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="执行一轮兼容性回归")
    run.add_argument("--cases", nargs="+", required=True)
    run.add_argument("--terminals", default="default")
    run.add_argument("--faults", default="none")
    run.add_argument("--base-url", default="http://127.0.0.1:8765")
    run.add_argument("--out", default=str(ROOT / "runs"))
    run.add_argument("--headed", action="store_true")
    run.add_argument("--channel", default=None, help="使用已安装浏览器通道，如 msedge / chrome")
    run.add_argument("--serve", action="store_true", help="自动启动演示站静态服务")
    run.add_argument("--demo-dir", default=str(ROOT / "demo" / "web-app"))
    run.add_argument("--timeout-ms", type=int, default=20000)
    run.add_argument("--fail-on-failures", action="store_true")
    run.add_argument("--baselines", default=str(ROOT / "baselines"))
    run.add_argument("--visual-tolerance", type=float, default=0.00005)
    run.add_argument("--triage", choices=["auto", "off"], default="auto")

    ev = sub.add_parser("eval", help="跑缺陷基准集并计算检出率/误报")
    ev.add_argument("--faults", default=str(ROOT / "demo" / "web-app" / "data" / "faults.json"))
    ev.add_argument("--cases", default=str(ROOT / "cases"))
    ev.add_argument("--terminal", default="chromium-1366-dpr1-zh")
    ev.add_argument("--base-url", default="http://127.0.0.1:8765")
    ev.add_argument("--out", default=str(ROOT / "benchmark"))
    ev.add_argument("--headed", action="store_true")
    ev.add_argument("--channel", default=None)
    ev.add_argument("--serve", action="store_true")
    ev.add_argument("--demo-dir", default=str(ROOT / "demo" / "web-app"))
    ev.add_argument("--timeout-ms", type=int, default=20000)
    ev.add_argument("--baselines", default=str(ROOT / "baselines"))
    ev.add_argument("--visual-tolerance", type=float, default=0.00005)
    ev.add_argument("--triage", choices=["auto", "off"], default="auto")

    bl = sub.add_parser("baseline", help="采集/更新视觉基线")
    bl.add_argument("--cases", default=str(ROOT / "cases"))
    bl.add_argument("--terminals", default="default")
    bl.add_argument("--base-url", default="http://127.0.0.1:8765")
    bl.add_argument("--out", default=str(ROOT / "baselines"))
    bl.add_argument("--headed", action="store_true")
    bl.add_argument("--channel", default=None)
    bl.add_argument("--serve", action="store_true")
    bl.add_argument("--demo-dir", default=str(ROOT / "demo" / "web-app"))

    api = sub.add_parser("api", help="启动 HTTP API 服务")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--db", default=str(ROOT / "runs" / "mtct.db"))
    api.add_argument("--cases", default=str(ROOT / "cases"))
    api.add_argument("--runs-dir", default=str(ROOT / "runs" / "api"))
    api.add_argument("--baselines", default=str(ROOT / "baselines"))
    api.add_argument("--base-url", default="http://127.0.0.1:8765")
    api.add_argument("--headed", action="store_true")
    api.add_argument("--channel", default=None)

    cl = sub.add_parser("cluster", help="对一次 Run 的失败做聚类与根因命名")
    cl.add_argument("--run", required=True, help="Run 目录，例如 runs/20261022-...")
    cl.add_argument("--cases", default=str(ROOT / "cases"))
    cl.add_argument("--out", default=None)
    cl.add_argument("--llm-name", action="store_true", help="配置模型 Key 后用 LLM 重新命名")

    args = parser.parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "eval":
        return cmd_eval(args)
    if args.command == "baseline":
        return cmd_baseline(args)
    if args.command == "api":
        return cmd_api(args)
    if args.command == "cluster":
        return cmd_cluster(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())