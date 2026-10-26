"""布局与功能断言。

每条断言返回 AssertionResult：
- rule / target：规则名与目标选择器
- passed：是否通过
- message：一句人话解释（进报告，也是后面喂给 AI 的上下文）
- detail：原始测量数据（人工复核与阈值调优用）

原则：能用 DOM 几何量出来的，绝不交给 AI。
"""

from __future__ import annotations

from typing import Any

from ..core.models import AssertionResult


async def evaluate(blocks, page, console_errors: list[str]) -> list[AssertionResult]:
    results: list[AssertionResult] = []
    for block in blocks or []:
        kind = block.get("type")
        rules = block.get("rules") or []
        if kind == "layout":
            results.extend(await _layout(page, rules))
        elif kind == "functional":
            results.extend(await _functional(page, rules, console_errors))
        else:
            results.append(AssertionResult(str(kind), "", False, f"未知断言类型: {kind}"))
    return results


def _selectors(spec: dict[str, Any]) -> list[str]:
    selectors = spec.get("selectors")
    if isinstance(selectors, str):
        return [selectors]
    if isinstance(selectors, list):
        return [s for s in selectors if s]
    single = spec.get("selector")
    return [single] if single else []


async def _layout(page, rules: list[dict[str, Any]]) -> list[AssertionResult]:
    out: list[AssertionResult] = []
    for spec in rules:
        rule = spec.get("rule")
        if rule == "no_horizontal_scroll":
            out.extend(await _no_horizontal_scroll(page))
        elif rule == "no_overflow":
            out.extend(await _no_overflow(page, spec))
        elif rule == "text_not_truncated":
            out.extend(await _text_not_truncated(page, spec))
        elif rule == "in_viewport":
            out.extend(await _in_viewport(page, spec))
        elif rule == "no_overlap":
            out.extend(await _no_overlap(page, spec))
        elif rule == "contrast_ratio":
            out.extend(await _contrast_ratio(page, spec))
        else:
            out.append(AssertionResult(str(rule), "", False, f"未知布局规则: {rule}"))
    return out


async def _no_horizontal_scroll(page) -> list[AssertionResult]:
    data = await page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth,"
        " clientWidth: document.documentElement.clientWidth})"
    )
    passed = data["scrollWidth"] <= data["clientWidth"] + 1
    message = (
        ""
        if passed
        else f"出现横向溢出：scrollWidth={data['scrollWidth']} > clientWidth={data['clientWidth']}"
    )
    return [AssertionResult("no_horizontal_scroll", "document", passed, message, data)]


async def _no_overflow(page, spec: dict[str, Any]) -> list[AssertionResult]:
    out: list[AssertionResult] = []
    for sel in _selectors(spec):
        items = await page.evaluate(
            """(sel) => Array.from(document.querySelectorAll(sel)).map((el) => {
                const r = el.getBoundingClientRect();
                return {
                    text: (el.textContent || '').trim().slice(0, 20),
                    left: r.left, right: r.right, vw: window.innerWidth,
                };
            })""",
            sel,
        )
        bad = [it for it in items if it["right"] > it["vw"] + 1 or it["left"] < -1]
        message = (
            ""
            if not bad
            else f"{len(bad)}/{len(items)} 个元素超出视口："
            + "; ".join(f"「{b['text']}」right={b['right']:.0f} > vw={b['vw']}" for b in bad[:3])
        )
        out.append(
            AssertionResult(
                "no_overflow", sel, not bad, message,
                {"selector": sel, "bad_count": len(bad), "bad": bad[:5]},
            )
        )
    return out


async def _text_not_truncated(page, spec: dict[str, Any]) -> list[AssertionResult]:
    out: list[AssertionResult] = []
    for sel in _selectors(spec):
        items = await page.evaluate(
            """(sel) => Array.from(document.querySelectorAll(sel)).map((el) => ({
                text: (el.textContent || '').trim().slice(0, 24),
                scrollWidth: el.scrollWidth, clientWidth: el.clientWidth,
                scrollHeight: el.scrollHeight, clientHeight: el.clientHeight,
            }))""",
            sel,
        )
        bad = [
            it for it in items
            if it["scrollWidth"] > it["clientWidth"] + 1
            or it["scrollHeight"] > it["clientHeight"] + 1
        ]
        message = (
            ""
            if not bad
            else f"{len(bad)}/{len(items)} 个元素内容被裁切："
            + "; ".join(
                f"「{b['text']}」scroll={b['scrollWidth']}x{b['scrollHeight']} > client={b['clientWidth']}x{b['clientHeight']}"
                for b in bad[:3]
            )
        )
        out.append(
            AssertionResult(
                "text_not_truncated", sel, not bad, message,
                {"selector": sel, "bad_count": len(bad), "bad": bad[:5]},
            )
        )
    return out


async def _in_viewport(page, spec: dict[str, Any]) -> list[AssertionResult]:
    out: list[AssertionResult] = []
    for sel in _selectors(spec):
        items = await page.evaluate(
            """(sel) => Array.from(document.querySelectorAll(sel)).map((el) => {
                const r = el.getBoundingClientRect();
                return {text: (el.textContent || '').trim().slice(0, 20),
                        left: r.left, top: r.top, right: r.right, bottom: r.bottom,
                        vw: window.innerWidth, vh: window.innerHeight};
            })""",
            sel,
        )
        bad = [
            it for it in items
            if it["left"] < -1 or it["top"] < -1
            or it["right"] > it["vw"] + 1 or it["bottom"] > it["vh"] + 1
        ]
        message = (
            ""
            if not bad
            else f"{len(bad)}/{len(items)} 个元素不在视口内："
            + "; ".join(f"「{b['text']}」({b['left']:.0f},{b['top']:.0f})-({b['right']:.0f},{b['bottom']:.0f})" for b in bad[:3])
        )
        out.append(
            AssertionResult(
                "in_viewport", sel, not bad, message,
                {"selector": sel, "bad_count": len(bad), "bad": bad[:5]},
            )
        )
    return out


async def _no_overlap(page, spec: dict[str, Any]) -> list[AssertionResult]:
    pairs = spec.get("pairs") or []
    if not pairs:
        return [AssertionResult("no_overlap", "", False, "no_overlap 缺少 pairs 配置")]
    rows = await page.evaluate(
        """(pairs) => pairs.map((pair) => {
            const [a, b] = pair;
            const ea = document.querySelector(a);
            const eb = document.querySelector(b);
            if (!ea || !eb) return {a, b, missing: true, overlap: 0};
            const ra = ea.getBoundingClientRect();
            const rb = eb.getBoundingClientRect();
            const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
            const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
            return {a, b, missing: false, overlap: Math.max(0, w) * Math.max(0, h)};
        })""",
        pairs,
    )
    bad = [r for r in rows if r.get("missing") or r["overlap"] > 1]
    message = ""
    if bad:
        message = "元素发生重叠：" + "; ".join(
            f"{b['a']} × {b['b']}（重叠 {b['overlap']:.0f}px²）" if not b.get("missing")
            else f"{b['a']} 或 {b['b']} 不存在"
            for b in bad[:3]
        )
    return [
        AssertionResult("no_overlap", "pairs", not bad, message, {"pairs": pairs, "bad": bad[:5]})
    ]


async def _functional(page, rules: list[dict[str, Any]], console_errors: list[str]) -> list[AssertionResult]:
    out: list[AssertionResult] = []
    for spec in rules:
        rule = spec.get("rule")
        if rule == "no_console_error":
            passed = not console_errors
            message = (
                ""
                if passed
                else f"控制台/页面错误 {len(console_errors)} 条：" + " | ".join(console_errors[:3])
            )
            out.append(
                AssertionResult(
                    "no_console_error", "console", passed, message,
                    {"count": len(console_errors), "errors": console_errors[:10]},
                )
            )
        elif rule == "element_enabled":
            for sel in _selectors(spec):
                info = await page.evaluate(
                    """(sel) => {
                        const el = document.querySelector(sel);
                        if (!el) return {found: false};
                        return {
                            found: true,
                            disabled: Boolean(el.disabled),
                            ariaDisabled: el.getAttribute('aria-disabled'),
                        };
                    }""",
                    sel,
                )
                passed = bool(info.get("found")) and not info.get("disabled") and info.get("ariaDisabled") != "true"
                if passed:
                    message = ""
                elif not info.get("found"):
                    message = "元素不存在"
                else:
                    message = "元素不可交互（disabled）"
                out.append(AssertionResult("element_enabled", sel, passed, message, info))
        elif rule == "element_visible":
            for sel in _selectors(spec):
                visible = bool(await page.is_visible(sel))
                out.append(
                    AssertionResult(
                        "element_visible", sel, visible,
                        "" if visible else "元素不可见", {"visible": visible},
                    )
                )
        else:
            out.append(AssertionResult(str(rule), "", False, f"未知功能规则: {rule}"))
    return out

async def _contrast_ratio(page, spec: dict[str, Any]) -> list[AssertionResult]:
    """WCAG 对比度：阈值默认 3.0（大字号 AA），低于阈值判定可读性问题。"""
    threshold = float(spec.get("min_ratio", 3.0))
    out: list[AssertionResult] = []
    for sel in _selectors(spec):
        items = await page.evaluate(
            """(sel) => {
                const parse = (s) => {
                    const m = s && s.match(/rgba?\\(([^)]+)\\)/);
                    if (!m) return null;
                    const p = m[1].split(',').map((x) => parseFloat(x));
                    return { r: p[0], g: p[1], b: p[2], a: p[3] === undefined ? 1 : p[3] };
                };
                const lum = (c) => {
                    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
                    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
                };
                const ratio = (a, b) => {
                    const l1 = lum(a), l2 = lum(b);
                    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
                };
                const bgOf = (el) => {
                    let node = el;
                    while (node) {
                        const c = parse(getComputedStyle(node).backgroundColor);
                        if (c && c.a > 0.5) return c;
                        node = node.parentElement;
                    }
                    return { r: 255, g: 255, b: 255, a: 1 };
                };
                return Array.from(document.querySelectorAll(sel)).map((el) => {
                    const text = (el.textContent || '').trim();
                    if (!text) return { text: '', ratio: null };
                    const fg = parse(getComputedStyle(el).color);
                    if (!fg) return { text: text.slice(0, 20), ratio: null };
                    return { text: text.slice(0, 20), ratio: Math.round(ratio(fg, bgOf(el)) * 100) / 100 };
                });
            }""",
            sel,
        )
        bad = [it for it in items if it["ratio"] is not None and it["ratio"] < threshold]
        message = (
            ""
            if not bad
            else f"{len(bad)}/{len(items)} 个元素对比度低于 {threshold}："
            + "; ".join(f"「{b['text']}」{b['ratio']}:1" for b in bad[:3])
        )
        out.append(
            AssertionResult(
                "contrast_ratio", sel, not bad, message,
                {"selector": sel, "threshold": threshold, "bad": bad[:5]},
            )
        )
    return out
