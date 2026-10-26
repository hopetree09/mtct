"""生成 120 例缺陷基准集 + 6 个页面的基准用例（可复现）。

运行：
    python scripts/gen_benchmark.py

输出：
    demo/web-app/data/faults.json   # 120 条故障规格（演示站按 id 注入）
    cases/*.yaml                    # 6 个页面基准用例（选择器与故障同源）

设计：
- 故障一律用 inline style 注入，确定性、无副作用、可重复；
- 分两类：规则可检出（layout/i18n/contrast/zoom/functional/loading）
  与仅视觉可检出（visual，留给像素 diff + AI 判定）；
- 用例里的选择器与故障选择器由同一份清单生成，避免"故障测了但没断言"。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DATA = ROOT / "demo" / "web-app" / "data"
CASES = ROOT / "cases"

PAGES = [
    {
        "page": "home", "key": "home-layout", "name": "行情页布局（基准）", "path": "/home",
        "overflow": [".market-card", ".search-box", ".tabs", ".toolbar", ".market-grid"],
        "truncate": [".page-head h1", ".market-card .pair", ".market-card .price",
                     ".market-card .change", ".tab-btn"],
        "contrast": [".page-sub", ".market-card .meta", ".market-card .change", ".tab-btn"],
        "primary": "[data-testid=tab-all]",
        "visible": [".market-grid"],
        "overlap": [[".market-card:nth-of-type(1)", ".market-card:nth-of-type(2)"],
                    [".market-card:nth-of-type(2)", ".market-card:nth-of-type(3)"]],
        "visual": [(".market-card", {"boxShadow": "none"}),
                   (".brand-mark", {"opacity": "0.85"})],
    },
    {
        "page": "coin", "key": "coin-layout", "name": "币种详情布局（基准）", "path": "/coin/BTC",
        "overflow": [".panel", ".coin-stats", ".coin-header", ".price-big", ".coin-actions"],
        "truncate": [".price-big", ".stat-label", ".stat-value", ".coin-actions .btn",
                     ".page-head h1"],
        "contrast": [".page-sub", ".stat-label", ".stat-value"],
        "primary": ".btn-buy", "visible": [], "overlap": [],
        "visual": [(".panel", {"boxShadow": "none"}), (".coin-logo", {"opacity": "0.8"})],
    },
    {
        "page": "trade", "key": "trade-layout", "name": "交易页布局（基准）", "path": "/trade/BTC",
        "overflow": [".trade-panel", ".orderbook", ".order-input-row", ".trade-total",
                     ".trade-submit"],
        "truncate": [".trade-submit", ".order-tabs .tab-btn", ".hint", ".trade-total",
                     ".page-head h1"],
        "contrast": [".page-sub", ".hint", ".trade-total", ".ob-row"],
        "primary": ".trade-submit",
        "visible": [".orderbook"],
        "overlap": [[".order-input-row", ".trade-submit"],
                    [".trade-total", ".trade-submit"]],
        "visual": [(".trade-panel", {"borderColor": "#3b5bfd"}),
                   (".orderbook", {"background": "#fbfcff"})],
    },
    {
        "page": "kyc", "key": "kyc-layout", "name": "KYC 表单布局（基准）", "path": "/kyc",
        "overflow": [".kyc-card", ".upload-box", ".field-row", ".field",
                     "[data-testid=kyc-submit]"],
        "truncate": [".field label", ".upload-box", "[data-testid=kyc-submit]",
                     ".page-head h1", ".kyc-card"],
        "contrast": [".page-sub", ".field label", ".upload-box"],
        "primary": "[data-testid=kyc-submit]", "visible": [], "overlap": [],
        "visual": [(".upload-box", {"borderStyle": "solid"}),
                   (".kyc-card", {"borderRadius": "0"})],
    },
    {
        "page": "login", "key": "login-form", "name": "登录表单布局（基准）", "path": "/login",
        "overflow": [".login-card", ".login-actions", ".field", ".login-sub", ".auth-wrap"],
        "truncate": [".login-card h1", ".login-sub", ".field label", ".login-actions",
                     ".login-card"],
        "contrast": [".login-sub", ".field label", ".login-card"],
        "primary": "[data-testid=login-submit]", "visible": [], "overlap": [],
        "visual": [(".login-card", {"boxShadow": "none"}),
                   (".login-sub", {"letterSpacing": "0.4px"})],
    },
    {
        "page": "settings", "key": "settings-layout", "name": "设置页布局（基准）",
        "path": "/settings",
        "overflow": [".settings-card", ".setting-row", ".seg", ".setting-label",
                     ".setting-control"],
        "truncate": [".page-head h1", ".setting-label", ".setting-desc", ".seg button",
                     ".settings-card"],
        "contrast": [".page-sub", ".setting-desc", ".setting-label"],
        "primary": "[data-testid=theme-dark]",
        "visible": [".settings-card"], "overlap": [],
        "visual": [(".settings-card", {"borderColor": "#d1d5db"}),
                   (".switch", {"background": "#e0e7ff"})],
    },
]

SEVERITIES = ["blocker", "major", "major", "minor"]
faults: list[dict] = []
seq = 0


def add(page, category, selector, styles=None, action=None, detector="", note="",
        severity="major"):
    global seq
    seq += 1
    faults.append({
        "id": f"bench-{seq:03d}",
        "page": page,
        "category": category,
        "severity": severity,
        "selector": selector,
        "styles": styles or {},
        "action": action,
        "expected_detector": detector,
        "note": note,
    })


# 1) 布局溢出
for spec in PAGES:
    for i, sel in enumerate(spec["overflow"]):
        add(spec["page"], "layout", sel,
            styles={"width": "1800px", "minWidth": "1800px"},
            detector="no_overflow", severity=SEVERITIES[i % 4],
            note=f"{sel} 宽度被撑到 1800px，超出 1366 视口")

# 2) 国际化截断（18px 才能保证中文短标签也被裁）
for spec in PAGES:
    for i, sel in enumerate(spec["truncate"]):
        add(spec["page"], "i18n", sel,
            styles={"maxWidth": "18px", "overflow": "hidden",
                    "whiteSpace": "nowrap", "textOverflow": "clip"},
            detector="text_not_truncated", severity=SEVERITIES[i % 4],
            note=f"{sel} 被限宽 18px，长文案被裁切")

# 3) 对比度不足
for spec in PAGES:
    for i, sel in enumerate(spec["contrast"]):
        add(spec["page"], "contrast", sel, styles={"color": "#f2f2f2"},
            detector="contrast_ratio", severity=SEVERITIES[i % 4],
            note=f"{sel} 前景色接近背景色，对比度低于 3:1")

# 4) 窄视口 / 缩放错位
scroll_specs = [(s["page"], "2200px") for s in PAGES] + [
    ("home", "1800px"), ("coin", "2600px"), ("trade", "3000px"), ("login", "2400px"),
]
for i, (page, width) in enumerate(scroll_specs):
    add(page, "zoom", ".app",
        styles={"width": width, "maxWidth": "none"},
        detector="no_horizontal_scroll", severity=SEVERITIES[i % 4],
        note=f"容器宽度固定 {width}，窄视口下出现横向滚动")

# 5) 仅视觉可检出
for spec in PAGES:
    for sel, styles in spec["visual"]:
        add(spec["page"], "visual", sel, styles=styles, detector="visual_diff",
            severity="minor", note=f"{sel} 视觉样式变化，需要像素比对")

# 6) 功能 / 加载态
for spec in PAGES:
    add(spec["page"], "functional", "body", action="console-error",
        detector="no_console_error", note="页面抛出未捕获异常")
for spec in PAGES:
    add(spec["page"], "functional", spec["primary"], action="disable",
        detector="element_enabled", severity="blocker",
        note=f"{spec['primary']} 被置为 disabled")
for page, target in [("home", ".market-grid"), ("trade", ".orderbook"),
                     ("settings", ".settings-card")]:
    add(page, "functional", target, action="hide", detector="element_visible",
        severity="blocker", note=f"{target} 被隐藏")
for page in ["home", "coin", "trade"]:
    add(page, "loading", "body", action="skeleton-stuck",
        detector="ready_gate", severity="blocker", note="骨架屏永不消失")

assert len(faults) == 120, f"expected 120, got {len(faults)}"
DEMO_DATA.mkdir(parents=True, exist_ok=True)
(DEMO_DATA / "faults.json").write_text(
    json.dumps(faults, ensure_ascii=False, indent=2), encoding="utf-8"
)


def q(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def build_case(spec):
    lines = [
        f"key: {spec['key']}",
        f"page: {spec['page']}",
        f"name: {spec['name']}",
        f"path: {spec['path']}",
        "tags: [benchmark, layout]",
        "assertions:",
        "  - type: layout",
        "    rules:",
        "      - rule: no_horizontal_scroll",
        "      - rule: no_overflow",
        "        selectors: [" + ", ".join(q(s) for s in spec["overflow"]) + "]",
    ]
    if spec["overlap"]:
        lines += ["      - rule: no_overlap", "        pairs:"]
        for a, b in spec["overlap"]:
            lines.append(f"          - [{q(a)}, {q(b)}]")
    lines += [
        "      - rule: text_not_truncated",
        "        selectors: [" + ", ".join(q(s) for s in spec["truncate"]) + "]",
        "      - rule: contrast_ratio",
        "        min_ratio: 3.0",
        "        selectors: [" + ", ".join(q(s) for s in spec["contrast"]) + "]",
        "  - type: functional",
        "    rules:",
        "      - rule: element_enabled",
        f"        selectors: [{q(spec['primary'])}]",
    ]
    if spec["visible"]:
        lines += ["      - rule: element_visible",
                  "        selectors: [" + ", ".join(q(s) for s in spec["visible"]) + "]"]
    lines.append("      - rule: no_console_error")
    return "\n".join(lines) + "\n"


CASES.mkdir(parents=True, exist_ok=True)
for spec in PAGES:
    (CASES / f"{spec['key']}.yaml").write_text(build_case(spec), encoding="utf-8")

counts = {}
for fault in faults:
    counts[fault["category"]] = counts.get(fault["category"], 0) + 1
print("faults:", len(faults), counts, "cases:", len(PAGES))