"""视觉比对与 AI 判定管线的单元测试。

不依赖网络与浏览器：只验证纯函数、降级行为与 JSON 校验逻辑。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mtct.ai.triage import NullTriage, _extract_json, build_triage
from mtct.visual.diff import compare_images


def _write_image(path: Path, color: tuple[int, int, int]) -> None:
    Image.fromarray(np.full((100, 120, 3), color, dtype=np.uint8)).save(path)


def test_diff_identical_passes(tmp_path):
    base = tmp_path / "a.png"
    actual = tmp_path / "b.png"
    _write_image(base, (255, 255, 255))
    _write_image(actual, (255, 255, 255))
    result = compare_images(base, actual, tolerance=0.0)
    assert result.passed is True
    assert result.diff_ratio == 0.0
    assert result.bbox is None


def test_diff_detects_change_and_bbox(tmp_path):
    base = tmp_path / "a.png"
    actual = tmp_path / "b.png"
    _write_image(base, (255, 255, 255))

    arr = np.full((100, 120, 3), 255, dtype=np.uint8)
    arr[40:60, 50:70] = (0, 0, 255)
    Image.fromarray(arr).save(actual)

    result = compare_images(base, actual, tolerance=0.001, out_dir=tmp_path)
    assert result.passed is False
    assert result.changed_pixels == 20 * 20
    assert result.bbox is not None
    assert result.diff_image and Path(result.diff_image).exists()
    assert result.crop_image and Path(result.crop_image).exists()


def test_diff_size_mismatch_fails(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.fromarray(np.full((10, 10, 3), 0, dtype=np.uint8)).save(a)
    Image.fromarray(np.full((20, 20, 3), 0, dtype=np.uint8)).save(b)
    result = compare_images(a, b)
    assert result.passed is False
    assert "尺寸不一致" in result.message


def test_extract_json_handles_fence():
    raw = '```json\n{"verdict": "true_bug", "category": "layout", "confidence": 0.9}\n```'
    parsed = _extract_json(raw)
    assert parsed["verdict"] == "true_bug"
    assert parsed["confidence"] == 0.9


def test_extract_json_returns_none_on_garbage():
    assert _extract_json("模型今天不想说话") is None


def test_null_triage_marks_needs_human():
    triage = NullTriage()
    assert triage.enabled is False
    result = asyncio.run(triage.triage("whatever.png", {"page": "home"}))
    assert result.verdict == "needs_human"
    assert "API Key" in result.reason


def test_build_triage_without_key_falls_back(monkeypatch):
    monkeypatch.delenv("MTCT_VLM_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    triage = build_triage("auto")
    assert triage.enabled is False


def test_build_triage_off_mode():
    assert build_triage("off").enabled is False