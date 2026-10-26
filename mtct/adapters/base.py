"""适配器协议。

Web 只是第一种终端；后续 Windows 原生、Linux、Android 都实现同一套协议，
上层 runner 不需要知道具体终端类型。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..core.models import TerminalProfile


class Adapter(ABC):
    @abstractmethod
    async def start(self) -> None:
        """启动底层运行时（浏览器/进程/设备）。"""

    @abstractmethod
    async def stop(self) -> None:
        """释放运行时资源。"""

    @abstractmethod
    async def open(self, terminal: TerminalProfile, base_url: str, path: str, fault: str):
        """打开终端会话并导航。返回 (page, context, console_errors, url)。"""

    @abstractmethod
    async def wait_ready(self, page: Any, timeout_ms: int = 20000) -> None:
        """等待被测应用进入稳定态（就绪门控）。"""

    @abstractmethod
    async def screenshot(self, page: Any, path: str) -> None:
        """截图存档。"""
