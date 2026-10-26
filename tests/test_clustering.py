"""失败聚类与根因命名单元测试（不依赖浏览器）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mtct.clustering import (
    Failure,
    cluster_failures,
    evaluate_clusters,
    extract_failures,
)


def _failure(fault: str, page: str, rule: str, message: str, terminal: str) -> Failure:
    return Failure(
        case_key=f"{page}-layout",
        case_name=f"{page} 布局",
        terminal_id=terminal,
        fault=fault,
        status="failed",
        page=page,
        rules=[rule],
        messages=[message],
        selector=".market-card",
    )


def test_clusters_group_same_fault_across_terminals():
    failures = []
    for terminal in ["chromium-a", "chromium-b", "chromium-c"]:
        failures.append(_failure(
            "f1", "home", "no_overflow",
            "2/12 个元素超出视口：right=1800 > vw=1366", terminal,
        ))
        failures.append(_failure(
            "f2", "coin", "text_not_truncated",
            "1/3 个元素内容被裁切：scrollWidth 超限", terminal,
        ))

    clusters = cluster_failures(failures)
    assert len(clusters) == 2
    assert sorted(cluster.member_count for cluster in clusters) == [3, 3]
    assert all(len(cluster.terminals) == 3 for cluster in clusters)

    metrics = evaluate_clusters(failures, clusters)
    assert metrics["compression"] == 3.0
    assert metrics["ari_vs_fault"] == 1.0


def test_different_rules_stay_separate():
    failures = [
        _failure("f1", "home", "no_overflow", "元素超出视口", "t1"),
        _failure("f1", "home", "no_overflow", "元素超出视口", "t2"),
        _failure("f2", "home", "contrast_ratio", "对比度低于 3", "t1"),
        _failure("f2", "home", "contrast_ratio", "对比度低于 3", "t2"),
    ]
    clusters = cluster_failures(failures)
    assert len(clusters) == 2


def test_extract_failures_skips_passed_and_uses_page_map():
    results = [
        {"status": "passed"},
        {
            "status": "failed",
            "case_key": "home-layout",
            "case_name": "行情页",
            "terminal_id": "t1",
            "fault": "bench-001",
            "triage": None,
            "assertions": [
                {"rule": "no_overflow", "passed": False,
                 "message": "2 个元素超出视口", "target": ".market-card"},
                {"rule": "no_horizontal_scroll", "passed": True,
                 "message": "", "target": "document"},
            ],
        },
    ]
    failures = extract_failures(results, {"home-layout": "home"})
    assert len(failures) == 1
    assert failures[0].page == "home"
    assert failures[0].selector == ".market-card"
    assert failures[0].rules == ["no_overflow"]