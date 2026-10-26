"""Playwright Web 适配器。

职责边界：
- 只负责把环境变成浏览器上下文：viewport / DPR / locale / 网络；
- 只负责确定性：冻结动画、等就绪、截图；
- 不做断言（assertions 模块），不做报告（reports 模块）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..core.models import TerminalProfile
from .base import Adapter


class WebAdapter(Adapter):
    def __init__(self, headless: bool = True, channel: str | None = None) -> None:
        self.headless = headless
        self.channel = channel
        self._pw: Any = None
        self._browser: Any = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        launch_kwargs: dict = {
            "headless": self.headless,
            "args": ["--disable-dev-shm-usage", "--force-color-profile=srgb"],
        }
        if self.channel:
            launch_kwargs["channel"] = self.channel
        try:
            self._browser = await self._pw.chromium.launch(**launch_kwargs)
        except Exception as exc:  # noqa: BLE001
            if self.channel:
                raise
            # 内置 Chromium 未安装时，自动回退到系统 Edge（Windows 自带），
            # 保证"还没下载内核也能先跑通链路"
            print(f"[mtct][warn] 内置 Chromium 启动失败，自动回退系统 Edge：{exc}")
            self._browser = await self._pw.chromium.launch(
                headless=self.headless,
                channel="msedge",
                args=["--disable-dev-shm-usage", "--force-color-profile=srgb"],
            )

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

    async def open(self, terminal: TerminalProfile, base_url: str, path: str, fault: str):
        assert self._browser is not None, "adapter 未启动"
        context = await self._browser.new_context(
            viewport={"width": terminal.width, "height": terminal.height},
            device_scale_factor=terminal.dpr,
            locale=terminal.locale,
            timezone_id="Asia/Shanghai",
            color_scheme="light",
        )
        page = await context.new_page()
        console_errors: list[str] = []

        def on_console(msg):
            if msg.type == "error":
                console_errors.append(f"[console.error] {msg.text}")

        def on_pageerror(exc):
            console_errors.append(f"[pageerror] {exc}")

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)

        if terminal.network == "weak3g":
            async def slow_route(route):
                await asyncio.sleep(0.35)
                await route.continue_()

            await page.route("**/*", slow_route)

        url = terminal.url(base_url, path, fault)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return page, context, console_errors, url

    async def wait_ready(self, page: Any, timeout_ms: int = 20000) -> None:
        await page.wait_for_function("() => window.__MTCT_READY__ === true", timeout=timeout_ms)
        await page.wait_for_selector('[data-testid="skeleton"]', state="detached", timeout=timeout_ms)

    async def screenshot(self, page: Any, path: str) -> None:
        await page.screenshot(path=path, full_page=False, animations="disabled")
