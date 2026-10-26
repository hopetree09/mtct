"""视觉差异的语义判定（AI 层）。

输入：像素 diff 裁片 + 上下文（页面 / 用例 / 终端 / 差异比例）
输出：结构化 JSON —— 真缺陷 / 渲染差异 / 环境噪声 / 拿不准

设计约束（对应说明书第 7 节）：
1. AI 只做定性，不做最终裁决；拿不准一律 needs_human；
2. 必须缓存：同一裁片 + 同一 prompt 版本不重复付费；
3. 必须有预算上限：单轮调用超限自动降级；
4. 未配置 API Key 时降级为 NullTriage，整条管线照常跑通。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, asdict
from typing import Protocol
from pathlib import Path

import httpx

PROMPT_VERSION = "triage-v1"
ALLOWED_VERDICTS = {"true_bug", "styling_noise", "env_noise", "needs_human"}
ALLOWED_CATEGORIES = {"layout", "i18n", "dpi", "color", "font", "functional", "loading", "unknown"}
ALLOWED_SEVERITIES = {"blocker", "major", "minor"}

SYSTEM_PROMPT = (
    "你是资深测试开发工程师，负责判断 UI 兼容性测试中的截图差异是否属于真实缺陷。"
    "只输出 JSON，不要输出任何其它文字。字段："
    "verdict（true_bug|styling_noise|env_noise|needs_human）、"
    "category（layout|i18n|dpi|color|font|functional|loading|unknown）、"
    "severity（blocker|major|minor）、confidence（0~1 的小数）、"
    "reason（一句中文解释，必须提到你看到的证据）。"
    "判定标准：布局错位、文字截断、控件重叠、功能不可用 → true_bug；"
    "仅阴影/圆角/抗锯齿等纯样式差异且不影响使用 → styling_noise；"
    "加载中、字体渲染、截图时机导致的变化 → env_noise；拿不准 → needs_human。"
)


@dataclass
class TriageResult:
    verdict: str
    category: str
    severity: str
    confidence: float
    reason: str
    model: str
    cached: bool = False
    prompt_version: str = PROMPT_VERSION

    def to_dict(self) -> dict:
        return asdict(self)



class TriageClient(Protocol):
    """判定客户端协议：真实模型与降级实现都满足它。"""

    enabled: bool

    async def triage(self, crop_path: str, context: dict) -> "TriageResult":
        ...


class NullTriage:
    """没有 API Key 或显式关闭 AI 时的降级实现。"""

    enabled = False
    model = "none"

    async def triage(self, crop_path: str, context: dict) -> TriageResult:
        return TriageResult(
            verdict="needs_human",
            category="unknown",
            severity="minor",
            confidence=0.0,
            reason="未配置多模态模型 API Key（MTCT_VLM_API_KEY / DASHSCOPE_API_KEY），"
                   "视觉差异交由人工复核",
            model="none",
        )


def _extract_json(text: str) -> dict | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


class OpenAIVLMTriage:
    """OpenAI 兼容协议的多模态判定客户端（DashScope / 智谱 / OpenAI 均可）。"""

    enabled = True

    def __init__(self, api_key: str, base_url: str, model: str,
                 cache_file: str | Path, max_calls: int = 200) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.cache_file = Path(cache_file)
        self.max_calls = max_calls
        self.calls = 0
        self._cache: dict[str, dict] = {}
        if self.cache_file.exists():
            try:
                self._cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._cache = {}

    def _save_cache(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(
            json.dumps(self._cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async def triage(self, crop_path: str, context: dict) -> TriageResult:
        raw = Path(crop_path).read_bytes()
        cache_key = hashlib.sha256(
            raw + json.dumps(context, sort_keys=True, ensure_ascii=False).encode()
            + PROMPT_VERSION.encode()
        ).hexdigest()

        if cache_key in self._cache:
            data = dict(self._cache[cache_key])
            data["cached"] = True
            return TriageResult(**data)

        if self.calls >= self.max_calls:
            return TriageResult(
                verdict="needs_human", category="unknown", severity="minor",
                confidence=0.0, reason=f"本轮 AI 预算已用尽（{self.max_calls} 次）",
                model=self.model,
            )

        self.calls += 1
        image_uri = "data:image/png;base64," + base64.b64encode(raw).decode()
        user_text = (
            f"页面：{context.get('page')}；用例：{context.get('case')}；"
            f"终端：{context.get('terminal')}；差异比例：{context.get('diff_ratio'):.4%}；"
            f"变化区域：{context.get('bbox')}。请判断这次视觉差异。"
        )
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_uri}},
                    ],
                },
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
            parsed = _extract_json(content) or {}
            verdict = parsed.get("verdict")
            if verdict not in ALLOWED_VERDICTS:
                verdict = "needs_human"
            result = TriageResult(
                verdict=verdict,
                category=parsed.get("category") if parsed.get("category") in ALLOWED_CATEGORIES else "unknown",
                severity=parsed.get("severity") if parsed.get("severity") in ALLOWED_SEVERITIES else "minor",
                confidence=float(parsed.get("confidence") or 0.0),
                reason=str(parsed.get("reason") or "模型未给出理由"),
                model=self.model,
            )
            self._cache[cache_key] = result.to_dict()
            self._save_cache()
            return result
        except Exception as exc:  # noqa: BLE001 - 任何调用失败都降级，不能中断评测
            return TriageResult(
                verdict="needs_human", category="unknown", severity="minor",
                confidence=0.0, reason=f"模型调用失败，降级人工：{type(exc).__name__}",
                model=self.model,
            )


def build_triage(mode: str = "auto", cache_file: str = "cache/triage.json"):
    """根据环境变量构建判定客户端：auto 有 Key 用真实模型，否则降级。"""
    if mode == "off":
        return NullTriage()
    api_key = os.environ.get("MTCT_VLM_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        return NullTriage()
    return OpenAIVLMTriage(
        api_key=api_key,
        base_url=os.environ.get(
            "MTCT_VLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        model=os.environ.get("MTCT_VLM_MODEL", "qwen-vl-plus"),
        cache_file=cache_file,
        max_calls=int(os.environ.get("MTCT_VLM_MAX_CALLS", "200")),
    )