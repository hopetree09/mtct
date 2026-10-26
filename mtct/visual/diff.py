"""像素级视觉比对。

只做三件事：找不同、量化差异、裁出证据。
不判断"这是不是 bug"——那是规则层和 AI 判定层的事。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
from PIL import Image

PIXEL_THRESHOLD = 3  # 单通道差超过该值才算"变化"，过滤轻微抗锯齿噪声
PADDING = 12          # 裁片外扩，给 AI/人工留上下文


@dataclass
class DiffResult:
    passed: bool
    diff_ratio: float
    changed_pixels: int
    total_pixels: int
    bbox: list[int] | None
    message: str
    diff_image: str | None = None
    crop_image: str | None = None
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def compare_images(
    baseline_path: str | Path,
    actual_path: str | Path,
    tolerance: float = 0.0005,
    out_dir: str | Path | None = None,
    tag: str = "diff",
) -> DiffResult:
    base = Image.open(baseline_path).convert("RGB")
    actual = Image.open(actual_path).convert("RGB")

    if base.size != actual.size:
        return DiffResult(
            passed=False,
            diff_ratio=1.0,
            changed_pixels=0,
            total_pixels=0,
            bbox=None,
            message=f"截图尺寸不一致：基线 {base.size} vs 实际 {actual.size}",
        )

    width, height = base.size
    a = np.asarray(base).astype(np.int16)
    b = np.asarray(actual).astype(np.int16)
    delta = np.abs(a - b).max(axis=2)
    mask = delta > PIXEL_THRESHOLD

    changed = int(mask.sum())
    total = int(mask.size)
    ratio = changed / total if total else 0.0

    bbox = None
    diff_image = None
    crop_image = None

    if changed:
        ys, xs = np.where(mask)
        x0 = max(0, int(xs.min()) - PADDING)
        y0 = max(0, int(ys.min()) - PADDING)
        x1 = min(width - 1, int(xs.max()) + PADDING)
        y1 = min(height - 1, int(ys.max()) + PADDING)
        bbox = [x0, y0, x1, y1]

        if out_dir is not None:
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            vis = np.asarray(base).copy()
            vis[mask] = [255, 0, 0]
            diff_path = out / f"{tag}.diff.png"
            crop_path = out / f"{tag}.crop.png"
            Image.fromarray(vis).save(diff_path)
            Image.fromarray(b.astype(np.uint8)[y0:y1 + 1, x0:x1 + 1]).save(crop_path)
            diff_image = str(diff_path)
            crop_image = str(crop_path)

    passed = ratio <= tolerance
    if passed:
        message = f"视觉无显著变化（差异 {ratio:.4%}，容差 {tolerance:.4%}）"
    else:
        message = (
            f"视觉差异 {ratio:.4%}（{changed}/{total} 像素，阈值 {PIXEL_THRESHOLD}），"
            f"超过容差 {tolerance:.4%}；区域 {bbox}"
        )

    return DiffResult(
        passed=passed,
        diff_ratio=round(ratio, 6),
        changed_pixels=changed,
        total_pixels=total,
        bbox=bbox,
        message=message,
        diff_image=diff_image,
        crop_image=crop_image,
        width=width,
        height=height,
    )