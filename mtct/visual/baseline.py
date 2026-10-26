"""视觉基线管理：一套基线对应一个 terminal.visual_key + case.key。

基线键不含网络、不含故障模式：弱网终端与正常网络共用同一套基线，
门控通过后的画面应当一致。
"""

from __future__ import annotations

from pathlib import Path

from ..adapters.base import Adapter
from ..core.models import TerminalProfile, TestCase

DEFAULT_BASELINE_DIR = "baselines"


def baseline_path(root: str | Path, terminal: TerminalProfile, case_key: str) -> Path:
    return Path(root) / terminal.visual_key / f"{case_key}.png"


async def capture_baseline(
    adapter: Adapter,
    terminal: TerminalProfile,
    case: TestCase,
    base_url: str,
    root: str | Path,
) -> Path:
    page, context, _errors, _url = await adapter.open(
        terminal, base_url, case.path, "none"
    )
    try:
        if case.wait_ready:
            await adapter.wait_ready(page)
        path = baseline_path(root, terminal, case.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await adapter.screenshot(page, str(path))
        return path
    finally:
        await context.close()