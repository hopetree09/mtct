"""终端档案表（第一版：单内核多环境）。

真正的 pairwise 生成放在后续迭代；这一版先保证 3 个环境能跑通，
覆盖三种语言 + 两种分辨率 + 两档缩放，足以验证执行与断言链路。
"""

from __future__ import annotations

from ..core.models import TerminalProfile

TERMINALS: dict[str, TerminalProfile] = {
    "chromium-1366-dpr1-zh": TerminalProfile(
        id="chromium-1366-dpr1-zh", width=1366, height=768, dpr=1.0, locale="zh-CN"
    ),
    "chromium-1920-dpr1-vi": TerminalProfile(
        id="chromium-1920-dpr1-vi", width=1920, height=1080, dpr=1.0, locale="vi-VN"
    ),
    "chromium-1366-dpr2-en": TerminalProfile(
        id="chromium-1366-dpr2-en", width=1366, height=768, dpr=2.0, locale="en-US"
    ),
    "chromium-1366-dpr1-zh-weak": TerminalProfile(
        id="chromium-1366-dpr1-zh-weak",
        width=1366,
        height=768,
        dpr=1.0,
        locale="zh-CN",
        network="weak3g",
    ),
}

DEFAULT_TERMINALS = [
    "chromium-1366-dpr1-zh",
    "chromium-1920-dpr1-vi",
    "chromium-1366-dpr2-en",
]


def resolve(ids: list[str] | str) -> list[TerminalProfile]:
    """把 id 列表（或 'all' / 'default'）解析成终端档案。"""
    if isinstance(ids, str):
        ids = [s.strip() for s in ids.split(",") if s.strip()]
    out: list[TerminalProfile] = []
    for item in ids:
        if item == "all":
            return list(TERMINALS.values())
        if item == "default":
            out.extend(TERMINALS[t] for t in DEFAULT_TERMINALS)
            continue
        if item not in TERMINALS:
            raise KeyError(f"未知终端: {item}（可用: {', '.join(TERMINALS)}）")
        out.append(TERMINALS[item])
    seen: set[str] = set()
    unique = []
    for t in out:
        if t.id not in seen:
            seen.add(t.id)
            unique.append(t)
    return unique
