"""失败聚类与根因命名（AI 归因层）。

输入：一次 Run 的失败用例（断言 + 上下文）
输出：根因簇（成员、标签、根因描述、影响终端、证据）

特征只使用**可观测信息**（失败规则、断言消息模板、页面、目标元素、差异比例），
绝不使用注入故障标签，否则聚类指标就是作弊。

算法：TF-IDF（字符 n-gram，适配中文）+ HDBSCAN(cosine)。
HDBSCAN 把孤立失败标为噪声（-1），归入"零散失败"桶。

命名：默认模板命名；配置 `MTCT_LLM_API_KEY` 后可选用 LLM 重新命名，
无 Key 时明确降级，不阻塞流程。
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from sklearn.cluster import HDBSCAN, AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import adjusted_rand_score

RULE_LABELS = {
    "no_overflow": "元素溢出视口",
    "no_horizontal_scroll": "页面横向溢出",
    "no_overlap": "元素重叠",
    "text_not_truncated": "文案被裁切",
    "in_viewport": "元素不在视口内",
    "contrast_ratio": "对比度不足",
    "visual_diff": "视觉差异",
    "no_console_error": "控制台/页面异常",
    "element_enabled": "控件不可用",
    "element_visible": "内容不可见",
}


@dataclass
class Failure:
    case_key: str
    case_name: str
    terminal_id: str
    fault: str
    status: str
    page: str
    rules: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    selector: str = ""
    diff_ratio: float | None = None
    triage_verdict: str | None = None
    category_hint: str | None = None  # 仅用于评测，不进入特征

    @property
    def text(self) -> str:
        message = " ".join(_normalize(m) for m in self.messages[:2])
        return (
            f"page:{self.page} "
            f"rules:{' '.join(sorted(self.rules))} "
            f"target:{self.selector} "
            f"msg:{message}"
        )


@dataclass
class RootCauseCluster:
    cluster_id: str
    label: str
    root_cause: str
    rule: str
    page: str
    selector: str
    terminals: list[str]
    member_count: int
    sample_message: str
    members: list[int] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize(text: str) -> str:
    text = re.sub(r"\d+(\.\d+)?", "#", text or "")
    text = re.sub(r"[，。；：、（）()\[\]{}<>《》\"'`,.;:!?/\\|_\-+=*]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_failures(results: Iterable[dict[str, Any]],
                     page_of: dict[str, str] | None = None) -> list[Failure]:
    """"从 RunSummary.results（asdict 后的 dict）里抽取失败记录。"""
    page_of = page_of or {}
    failures: list[Failure] = []
    for result in results:
        if result.get("status") == "passed":
            continue
        assertions = result.get("assertions") or []
        failed = [a for a in assertions if not a.get("passed")]
        rules = [a.get("rule", "") for a in failed if a.get("rule")]
        messages = [a.get("message", "") for a in failed if a.get("message")]
        targets = [a.get("target", "") for a in failed if a.get("target")
                   and not str(a.get("target")).startswith("baseline:")]
        selector = Counter(targets).most_common(1)[0][0] if targets else ""
        diff_ratio = None
        for assertion in failed:
            if assertion.get("rule") == "visual_diff":
                detail = assertion.get("detail") or {}
                diff_ratio = detail.get("diff_ratio")
        case_key = result.get("case_key", "")
        triage = result.get("triage") or {}
        failures.append(
            Failure(
                case_key=case_key,
                case_name=result.get("case_name", ""),
                terminal_id=result.get("terminal_id", ""),
                fault=result.get("fault", ""),
                status=result.get("status", ""),
                page=page_of.get(case_key, case_key),
                rules=rules,
                messages=messages,
                selector=selector,
                diff_ratio=diff_ratio,
                triage_verdict=triage.get("verdict"),
            )
        )
    return failures


def cluster_failures(failures: list[Failure], min_cluster_size: int = 2) -> list[RootCauseCluster]:
    if not failures:
        return []

    texts = [f.text for f in failures]
    if len(failures) <= 2:
        labels = list(range(len(failures)))
    else:
        vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(2, 3), min_df=1, sublinear_tf=True
        )
        matrix = vectorizer.fit_transform(texts)
        try:
            labels = HDBSCAN(
                min_cluster_size=min_cluster_size, metric="cosine"
            ).fit_predict(matrix)
            if len(set(labels)) <= 1 and -1 in labels:
                labels = AgglomerativeClustering(
                    n_clusters=None, distance_threshold=0.35,
                    metric="cosine", linkage="average",
                ).fit_predict(matrix)
        except Exception:  # noqa: BLE001 - 聚类失败不能让整个 Run 处理失败
            labels = AgglomerativeClustering(
                n_clusters=None, distance_threshold=0.35,
                metric="cosine", linkage="average",
            ).fit_predict(matrix)

    labels = list(labels)
    groups: dict[str, list[int]] = {}
    for index, label in enumerate(labels):
        key = "noise" if int(label) == -1 else f"c{int(label)}"
        groups.setdefault(key, []).append(index)

    clusters: list[RootCauseCluster] = []
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    for number, (key, members) in enumerate(ordered, start=1):
        if key == "noise":
            cluster = RootCauseCluster(
                cluster_id="noise",
                label="零散失败（无法归为一类）",
                root_cause="特征相似度不足，建议人工逐条查看",
                rule="",
                page="",
                selector="",
                terminals=sorted({failures[i].terminal_id for i in members}),
                member_count=len(members),
                sample_message="",
                members=members,
                confidence=0.2,
            )
            clusters.append(cluster)
            continue
        clusters.append(_name_cluster(f"c{number}", members, failures))

    return clusters


def _name_cluster(cluster_id: str, members: list[int], failures: list[Failure]) -> RootCauseCluster:
    selected = [failures[i] for i in members]
    rule = Counter(rule for f in selected for rule in f.rules).most_common(1)
    rule = rule[0][0] if rule else "unknown"
    page = Counter(f.page for f in selected).most_common(1)[0][0]
    selector = Counter(f.selector for f in selected if f.selector).most_common(1)
    selector = selector[0][0] if selector else ""
    terminals = sorted({f.terminal_id for f in selected})
    messages = Counter(f.messages[0] for f in selected if f.messages)
    sample_message = messages.most_common(1)[0][0] if messages else ""
    label_text = RULE_LABELS.get(rule, rule)

    label = f"{page} · {label_text}"
    root_cause = (
        f"{page} 页 {('`' + selector + '` ') if selector else ''}出现「{label_text}」，"
        f"在 {len(terminals)} 个终端复现"
    )
    if sample_message:
        root_cause += f"；证据：{sample_message}"

    return RootCauseCluster(
        cluster_id=cluster_id,
        label=label,
        root_cause=root_cause,
        rule=rule,
        page=page,
        selector=selector,
        terminals=terminals,
        member_count=len(members),
        sample_message=sample_message,
        members=members,
        confidence=round(min(1.0, 0.55 + 0.15 * len(terminals)), 2),
    )


def evaluate_clusters(failures: list[Failure], clusters: list[RootCauseCluster]) -> dict[str, Any]:
    """用注入标签做离线评测：ARI（vs 故障 id / vs 类别）+ 压缩比 + 纯度。"""
    labels = np.zeros(len(failures), dtype=int)
    for cluster in clusters:
        for index in cluster.members:
            labels[index] = hash(cluster.cluster_id) % 100000
    result: dict[str, Any] = {
        "failures": len(failures),
        "clusters": len(clusters),
        "compression": round(len(failures) / len(clusters), 2) if clusters else 0.0,
    }
    if failures and any(f.fault for f in failures):
        true_fault = [f.fault for f in failures]
        result["ari_vs_fault"] = round(float(adjusted_rand_score(true_fault, labels)), 4)
    hints = [f.category_hint for f in failures]
    if hints and all(hints):
        result["ari_vs_category"] = round(float(adjusted_rand_score(hints, labels)), 4)
        purity = 0.0
        for cluster in clusters:
            categories = Counter(failures[i].category_hint for i in cluster.members)
            purity += categories.most_common(1)[0][1]
        result["purity"] = round(purity / len(failures), 4)
    return result


# ---------------- 可选：LLM 命名 ----------------

def llm_name_cluster(cluster: RootCauseCluster, members: list[Failure]) -> tuple[str, str, str] | None:
    """配置了文本模型 Key 时，用 LLM 重新命名；失败返回 None（保留模板命名）。"""
    api_key = os.environ.get("MTCT_LLM_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        return None
    base_url = os.environ.get(
        "MTCT_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).rstrip("/")
    model = os.environ.get("MTCT_LLM_MODEL", "qwen-plus")
    evidence = "\n".join(
        f"- {f.case_key} | {f.terminal_id} | rules={f.rules} | {f.messages[0] if f.messages else ''}"
        for f in members[:6]
    )
    prompt = (
        "你是测试开发工程师，请为下面这组失败用例起一个根因名称。"
        "只输出 JSON：{label: 不超过16字的中文短语, root_cause: 一句话根因说明, reason: 判断依据}\n\n"
        f"模板初步结论：{cluster.label}\n失败样例：\n{evidence}"
    )
    try:
        import httpx

        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        start, end = content.find("{"), content.rfind("}")
        payload = json.loads(content[start:end + 1])
        label = str(payload.get("label") or cluster.label)
        root = str(payload.get("root_cause") or cluster.root_cause)
        return label, root, str(payload.get("reason") or "")
    except Exception:  # noqa: BLE001 - 命名失败不影响聚类结果
        return None


def write_markdown(failures: list[Failure], clusters: list[RootCauseCluster],
                   metrics: dict[str, Any], path: str | Path) -> None:
    lines = [
        "# 失败聚类与根因报告",
        "",
        f"- 失败用例：**{metrics['failures']}**",
        f"- 根因簇：**{metrics['clusters']}**",
        f"- 压缩比：**{metrics['compression']}:1**",
    ]
    if "ari_vs_fault" in metrics:
        lines.append(f"- ARI（vs 注入故障）：**{metrics['ari_vs_fault']}**")
    if "ari_vs_category" in metrics:
        lines.append(f"- ARI（vs 缺陷类别）：**{metrics['ari_vs_category']}**")
    if "purity" in metrics:
        lines.append(f"- 簇纯度：**{metrics['purity']}**")
    lines += ["", "## 根因簇", ""]
    for cluster in clusters:
        lines += [
            f"### {cluster.cluster_id} · {cluster.label}（{cluster.member_count} 条）",
            "",
            f"- 根因：{cluster.root_cause}",
            f"- 影响终端：{', '.join(cluster.terminals)}",
            f"- 失败规则：`{cluster.rule}` · 目标元素：`{cluster.selector or '-'}`",
            "",
        ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")