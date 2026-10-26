"""核心数据模型：终端、用例、断言结果、执行结果。

设计原则：
- 终端是"可序列化的配置"，不是某台机器；
- 断言结果必须自解释（rule + target + message + detail），才能进入报告和 AI 判定；
- 执行结果不依赖 ORM，先跑通垂直切片，再接 PostgreSQL。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode


@dataclass(frozen=True)
class TerminalProfile:
    """一份终端环境声明：内核、分辨率、缩放、语言、网络。"""

    id: str
    engine: str = "chromium"
    width: int = 1366
    height: int = 768
    dpr: float = 1.0
    locale: str = "zh-CN"
    network: str = "normal"  # normal | weak3g

    @property
    def visual_key(self) -> str:
        """基线键：不含网络，弱网与正常网络共用同一套视觉基线。"""
        return f"{self.engine}-{self.width}x{self.height}-dpr{self.dpr:g}-{self.locale}"

    def url(self, base_url: str, path: str, fault: str = "none") -> str:
        params: dict[str, str] = {"lang": self.locale}
        if fault and fault != "none":
            params["fault"] = fault
        query = urlencode(params)
        path = path if path.startswith("/") else f"/{path}"
        return f"{base_url.rstrip('/')}/?{query}#{path}"


@dataclass
class TestCase:
    """一条用例：去哪一页、断言什么。DSL 的第一版。"""

    key: str
    name: str
    path: str
    page: str = ""
    assertions: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    wait_ready: bool = True
    screenshot: bool = True
    visual: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "") -> "TestCase":
        return cls(
            key=data["key"],
            name=data.get("name", data["key"]),
            path=data.get("path", "/home"),
            page=data.get("page", ""),
            assertions=data.get("assertions", []),
            tags=data.get("tags", []),
            wait_ready=data.get("wait_ready", True),
            visual=data.get("visual"),
            screenshot=data.get("screenshot", True),
        )


@dataclass
class AssertionResult:
    rule: str
    target: str
    passed: bool
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseResult:
    case_key: str
    case_name: str
    terminal_id: str
    fault: str
    status: str  # passed | failed | error
    duration_ms: int
    assertions: list[AssertionResult] = field(default_factory=list)
    screenshot: str | None = None
    error: str | None = None
    url: str = ""
    triage: dict[str, Any] | None = None

    @property
    def failed_assertions(self) -> list[AssertionResult]:
        return [a for a in self.assertions if not a.passed]


@dataclass
class RunSummary:
    run_id: str
    started_at: str
    base_url: str
    results: list[CaseResult] = field(default_factory=list)
    out_dir: str = ""

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "passed")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.status == "error")
