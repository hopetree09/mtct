"""报告输出：控制台摘要 + JSON + HTML。

第一版 HTML 刻意做得简单，但它决定了后面"证据链"的形态：
每条失败断言都要能看到 规则 / 目标 / 原因 / 截图。
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from pathlib import Path

from ..core.models import RunSummary

STATUS_LABEL = {"passed": "通过", "failed": "不通过", "error": "执行异常"}
STATUS_CLASS = {"passed": "pass", "failed": "fail", "error": "err"}


def summary_dict(summary: RunSummary) -> dict:
    return {
        "run_id": summary.run_id,
        "started_at": summary.started_at,
        "base_url": summary.base_url,
        "total": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "errors": summary.errors,
        "results": [asdict(r) for r in summary.results],
    }


def write_json(summary: RunSummary, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(summary_dict(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def print_console(summary: RunSummary) -> None:
    print()
    print(f"RUN {summary.run_id}    base={summary.base_url}")
    print("-" * 118)
    print(f"{'终端':<30}{'用例':<16}{'故障':<24}{'状态':<8}{'耗时':>7}  失败断言")
    print("-" * 118)
    for r in summary.results:
        failed = ", ".join(a.rule for a in r.failed_assertions)
        tail = failed or (r.error or "")
        print(
            f"{r.terminal_id:<30}{r.case_key:<16}{r.fault:<24}"
            f"{STATUS_LABEL.get(r.status, r.status):<8}{r.duration_ms:>6}ms  {tail}"
        )
    print("-" * 118)
    print(
        f"合计 {summary.total}：通过 {summary.passed}，不通过 {summary.failed}，异常 {summary.errors}"
    )


def write_html(summary: RunSummary, path: str | Path) -> None:
    rows = []
    for r in summary.results:
        detail_items = "".join(
            f"<li><code>{html.escape(a.rule)}</code> · {html.escape(a.target)}："
            f"{html.escape(a.message)}</li>"
            for a in r.failed_assertions
        )
        detail_html = f"<ul class='detail'>{detail_items}</ul>" if detail_items else ""
        if r.error:
            detail_html += f"<div class='detail err'>{html.escape(r.error)}</div>"
        shot = (
            f"<a href='{html.escape(r.screenshot)}'><img src='{html.escape(r.screenshot)}' alt='screenshot'/></a>"
            if r.screenshot
            else ""
        )
        rows.append(
            "<tr>"
            f"<td class='mono'>{html.escape(r.terminal_id)}</td>"
            f"<td>{html.escape(r.case_name)}<div class='sub'>{html.escape(r.case_key)}</div></td>"
            f"<td class='mono'>{html.escape(r.fault)}</td>"
            f"<td><span class='badge {STATUS_CLASS.get(r.status, 'err')}'>"
            f"{STATUS_LABEL.get(r.status, r.status)}</span></td>"
            f"<td class='num'>{r.duration_ms} ms</td>"
            f"<td>{detail_html}{shot}</td>"
            "</tr>"
        )

    doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>MTCT 兼容性报告 · {html.escape(summary.run_id)}</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --border:#e5e7eb; --text:#16181d; --muted:#6b7280;
        --pass:#15803d; --fail:#b91c1c; --err:#b45309; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text);
       font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }}
.wrap {{ max-width:1280px; margin:0 auto; padding:28px 24px 60px; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
.meta {{ color:var(--muted); font-size:12px; margin-bottom:20px; }}
.cards {{ display:flex; gap:12px; margin-bottom:20px; flex-wrap:wrap; }}
.card {{ background:var(--card); border:1px solid var(--border); border-radius:12px;
        padding:14px 18px; min-width:140px; }}
.card .k {{ color:var(--muted); font-size:12px; }}
.card .v {{ font-size:24px; font-weight:700; }}
table {{ width:100%; border-collapse:collapse; background:var(--card);
        border:1px solid var(--border); border-radius:12px; overflow:hidden; }}
th,td {{ text-align:left; padding:10px 12px; border-bottom:1px solid var(--border);
        vertical-align:top; font-size:13px; }}
th {{ background:#fafbfc; color:var(--muted); font-weight:600; }}
tr:last-child td {{ border-bottom:0; }}
.mono {{ font-family:"Courier New",monospace; font-size:12px; }}
.sub {{ color:var(--muted); font-size:11px; }}
.num {{ text-align:right; white-space:nowrap; }}
.badge {{ display:inline-block; padding:1px 9px; border-radius:999px; font-size:12px; font-weight:700; }}
.badge.pass {{ color:var(--pass); background:#e8f7ee; }}
.badge.fail {{ color:var(--fail); background:#fdecec; }}
.badge.err  {{ color:var(--err);  background:#fef3e2; }}
.detail {{ margin:6px 0 0; padding-left:18px; color:#7f1d1d; }}
.detail.err {{ color:#92400e; }}
img {{ max-width:220px; border:1px solid var(--border); border-radius:8px; margin-top:8px; display:block; }}
</style></head>
<body><div class="wrap">
<h1>多终端兼容性测试报告</h1>
<div class="meta">RUN {html.escape(summary.run_id)} · 开始于 {html.escape(summary.started_at)} · 被测地址 {html.escape(summary.base_url)}</div>
<div class="cards">
  <div class="card"><div class="k">执行总数</div><div class="v">{summary.total}</div></div>
  <div class="card"><div class="k">通过</div><div class="v" style="color:var(--pass)">{summary.passed}</div></div>
  <div class="card"><div class="k">不通过</div><div class="v" style="color:var(--fail)">{summary.failed}</div></div>
  <div class="card"><div class="k">执行异常</div><div class="v" style="color:var(--err)">{summary.errors}</div></div>
</div>
<table>
<thead><tr><th>终端</th><th>用例</th><th>故障</th><th>结果</th><th>耗时</th><th>失败断言 / 证据</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</div></body></html>"""
    Path(path).write_text(doc, encoding="utf-8")