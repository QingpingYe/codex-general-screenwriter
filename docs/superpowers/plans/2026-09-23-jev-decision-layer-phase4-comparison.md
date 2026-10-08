# Jev 辅助决策层 Phase 4（对比验收）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让同一个 `benchmark_case_id` 下的「普通 LLM」与「Jev 辅助」两次运行能并排比较，产出速度、token、成本、升级率与分歧报告；把 Jev 侧的 trace 与用户从 CC Switch 手工读到的 LLM 用量合并，并在**用户明确要求导出**时才写成文件。报告只给建议，`experimental` → `calibrated` 的决定仍由人做。

**Architecture:** 新增 `jev-decision-runtime/scripts/comparison.py`（比较资格闸、报告模型、Markdown/JSON 渲染）与 `compare_cli.py`（CLI）。LLM 侧用量由用户提供，本插件**不读 CC Switch 数据库**——它的 schema 不是稳定公共契约，而且会引入个人环境路径。导出复用既有的 `session-export` 能力与它的守卫：绝对输出目录、不写入插件目录、不写入密钥。

**Tech Stack:** Python 3.10+（CI 用 3.12），**仅标准库**，`unittest`。

**Spec:** `docs/superpowers/specs/2026-09-23-jev-assisted-decision-layer-design.md`（§10、§15 Phase 4、§16）

**前置计划：**
- `docs/superpowers/plans/2026-09-23-jev-assisted-decision-layer-phase1.md`
- `docs/superpowers/plans/2026-09-23-jev-decision-layer-phase2-knowledge-relevance.md`
- `docs/superpowers/plans/2026-09-23-jev-decision-layer-phase3-text-quality-prefilter.md`

## Global Constraints

Phase 1–3 的全局约束全部继续生效。此外：

- **不读 CC Switch 数据库。** 不引用它的文件路径、不解析它的 schema、不假设它的版本。LLM 侧用量只能由用户以 JSON 提供。
- **只有用户明确要求时才写文件。** 默认只在对话里展示运行摘要；导出需要有显式的输出目录参数。这是 `prompt_only`，必须在技能指令与 `docs/ENFORCEMENT.md` 里如实标注。
- **输出目录必须是用户提供的绝对路径，且不在插件目录内。** 沿用 `session-export` 的既有守卫措辞与行为。
- **没有共享 identity 的两次运行不并排比较。** 缺任一字段就报 `comparable: false` 并列出原因，不得"尽力比较"。
- **校准状态不自动翻转。** 报告只给 `keep_experimental` / `review_thresholds` / `eligible_for_calibrated` 的建议与依据；改 `decision-policies.json` 的是人。

---

## Review Focus

Phase 4 的风险集中在"合并"这一步：一旦把不该相加的东西加了进去，报告给出的速度与成本结论就是错的，而看报告的人不会知道。以下五类输入是 spec 已经隐含、原本没有测试固定住、最容易造成这种静默失真的。每一条都在 Task 2 里补了一条测试。

1. **同一个 operation 的多次 attempt。** 换 key、`outcome_unknown` 之后重跑都会在 `jev/<operation_id>/trace/` 下留下第二条 trace；两条都计入会把"清空数/升级数"翻倍，而这两个数正是升级率与校准建议的输入。（固定位置：`test_two_attempts_of_one_operation_count_their_verdicts_once`。）
2. **`fallback_used: true` 的运行。** 那是用户中途改回普通 LLM 的混合路径，不是 Jev 辅助样本；把它算进 Jev 侧的耗时与成本会同时美化两边。（固定位置：`test_a_fallback_run_is_not_a_jev_sample`。）
3. **run 目录里残留的上一个 case 的 trace。** 复用一个目录跑第二次时，旧 trace 的 token 与成本会静默加进新 case。（固定位置：`test_traces_from_another_case_are_not_summed_in`。）
4. **用户手写的成本是 JSON 数字而不是字符串。** 手工抄 CC Switch 数值时最容易写 `"estimated_cost_usd": 1.2345`，二进制浮点会污染账单口径。（固定位置：`test_a_numeric_cost_is_refused_with_a_quoting_hint`。）
5. **两侧跑的 operation 不一样。** 一边只跑了红线预筛、另一边还跑了知识筛选，耗时与 token 的对比就没有意义；报告必须写出 Jev 侧实际跑过哪些 operation，让人一眼看出不对等。（固定位置：`test_the_report_names_the_operations_the_jev_side_ran`。）

---

## Phase 1–3 已经提供、本计划直接使用的接口

| 接口 | 位置 |
|---|---|
| `pb-decision-trace-v1` 字段（`benchmark_case_id`、`operation`、`elapsed_ms`、`input_tokens`、`output_tokens`、`estimated_cost_usd`、`request_count`、`escalated_count`、`screened_clear_count`、`status`、`fallback_used`、`error_class`、`item_count`、`question_count`） | `skills/jev-decision-runtime/scripts/telemetry.py`（写入 `jev/<operation_id>/trace/NNNN.json`） |
| `operation_policy`、`load_policy`、`default_policy_path` | `decision_contract.py` |
| `reject_credential_arguments`、`CREDENTIAL_ARGUMENT_PREFIXES` | `jev_runner.py` |
| `export_session(session_id, messages, files, images, output_dir, plugin_root) -> Path`（要求绝对路径、插件目录外、无密钥字段） | `skills/session-export/scripts/export_session.py` |
| `screening.summarise` 的比率键 | `skills/pre_output-baseline/scripts/screening.py` |

---

## File Structure

**新增：**

| 文件 | 职责 |
|---|---|
| `skills/jev-decision-runtime/scripts/comparison.py` | 比较资格闸、报告模型、Markdown/JSON 渲染、校准建议 |
| `skills/jev-decision-runtime/scripts/test_comparison.py` | 测试 |
| `skills/jev-decision-runtime/scripts/compare_cli.py` | CLI：合并 trace 与用户用量、写报告 |
| `skills/jev-decision-runtime/scripts/test_compare_cli.py` | 测试 |
| `skills/jev-decision-runtime/references/comparison-procedure.md` | 人工比较步骤（含从 CC Switch 读数的说明） |
| `plugins/picturebook-screenwriter/tests/test_comparison_integration.py` | 端到端比较 |

**修改：**

| 文件 | 改动 |
|---|---|
| `skills/jev-decision-runtime/SKILL.md` | `## 对比验收` 段 |
| `skills/session-export/SKILL.md` | 说明比较报告也走本能力 |
| `docs/ENFORCEMENT.md` | 新增分级行 |
| `docs/CHANGELOG.md`、`plugins/picturebook-screenwriter/README.md` | 新能力 |
| `plugins/picturebook-screenwriter/tests/test_plugin_contract.py` | 断言契约声明了比较报告边界 |

---

### Task 1: 比较资格闸与报告模型

spec §10.3：两次运行只有五个字段全一致时才并排比较：`benchmark_case_id`、输入知识 revision vector、草稿 hash、policy/rule version、目标年龄/体裁/页数参数。这必须是**硬闸**——缺一项就不比较，而不是"尽力比较"。

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/comparison.py`
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_comparison.py`

**Interfaces:**
- Consumes: `telemetry.canonical_json`、`telemetry.sha256_hex`
- Produces:
  - `comparison.IDENTITY_FIELDS = ("benchmark_case_id", "input_revision_vector_sha256", "draft_sha256", "policy_version", "rule_version", "artifact_params")`
  - `comparison.COMPARISON_SCHEMA = "pb-path-comparison-v1"`
  - `comparison.CalibrationStatus = ("experimental", "calibrated")`
  - `comparison.validate_identity(payload) -> None`（抛 `ValueError`）
  - `comparison.identity_digest(identity) -> str` —— 规范化 identity 的 sha256
  - `comparison.comparability(llm_identity, jev_identity) -> tuple[bool, tuple[str, ...]]`
  - `comparison.CaseMetrics`（frozen dataclass：`path`、`elapsed_ms`、`request_count`、`input_tokens`、`output_tokens`、`cache_tokens`、`estimated_cost_usd`、`knowledge_items_entered`、`quality_items_entered`、`issues_found`、`misses_or_disagreements`、`notes`）
  - `comparison.build_report(*, identity, comparable, reasons, llm, jev_assisted, calibration) -> dict`
  - `comparison.report_to_markdown(report) -> str`
  - `comparison.describe_metric(name, llm_value, jev_value) -> str`

- [ ] **Step 1: 写失败测试**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_comparison.py`：

```python
import unittest

from comparison import (
    COMPARISON_SCHEMA,
    IDENTITY_FIELDS,
    CaseMetrics,
    build_report,
    comparability,
    describe_metric,
    identity_digest,
    report_to_markdown,
    validate_identity,
)


def identity(**overrides):
    payload = {
        "benchmark_case_id": "sha256:" + "0" * 64,
        "input_revision_vector_sha256": "a" * 64,
        "draft_sha256": "b" * 64,
        "policy_version": "text-quality-prefilter-v1",
        "rule_version": "text-quality-prefilter-rules-v1",
        "artifact_params": {"age_band": "3-6", "genre": "温情", "page_count": 32},
    }
    payload.update(overrides)
    return payload


def metrics(path, **overrides):
    payload = {
        "path": path,
        "elapsed_ms": 1000,
        "request_count": 4,
        "input_tokens": 8000,
        "output_tokens": 600,
        "cache_tokens": 0,
        "estimated_cost_usd": "0.000344400000",
        "knowledge_items_entered": 20,
        "quality_items_entered": 12,
        "issues_found": 3,
        "misses_or_disagreements": None,
        "notes": (),
    }
    payload.update(overrides)
    return CaseMetrics(**payload)


class IdentityTests(unittest.TestCase):
    def test_the_required_fields_are_the_five_the_spec_names(self):
        self.assertEqual(IDENTITY_FIELDS, (
            "benchmark_case_id", "input_revision_vector_sha256", "draft_sha256",
            "policy_version", "rule_version", "artifact_params",
        ))

    def test_a_complete_identity_validates(self):
        validate_identity(identity())

    def test_each_missing_field_is_refused(self):
        for field in IDENTITY_FIELDS:
            with self.subTest(field=field):
                broken = identity()
                del broken[field]
                with self.assertRaises(ValueError):
                    validate_identity(broken)

    def test_an_empty_artifact_params_object_is_refused(self):
        with self.assertRaises(ValueError):
            validate_identity(identity(artifact_params={}))

    def test_the_identity_digest_ignores_key_order(self):
        self.assertEqual(
            identity_digest(identity()),
            identity_digest(identity(artifact_params={
                "page_count": 32, "genre": "温情", "age_band": "3-6",
            })),
        )

    def test_the_identity_digest_changes_with_a_revision_vector(self):
        self.assertNotEqual(
            identity_digest(identity()),
            identity_digest(identity(input_revision_vector_sha256="c" * 64)),
        )


class ComparabilityTests(unittest.TestCase):
    def test_matching_identities_are_comparable(self):
        comparable, reasons = comparability(identity(), identity())
        self.assertTrue(comparable)
        self.assertEqual(reasons, ())

    def test_a_different_benchmark_case_is_not_comparable(self):
        comparable, reasons = comparability(
            identity(), identity(benchmark_case_id="sha256:" + "1" * 64)
        )
        self.assertFalse(comparable)
        self.assertIn("benchmark_case_id", reasons[0])

    def test_a_different_draft_is_not_comparable(self):
        comparable, reasons = comparability(identity(), identity(draft_sha256="d" * 64))
        self.assertFalse(comparable)
        self.assertTrue(any("draft_sha256" in reason for reason in reasons))

    def test_every_mismatched_field_is_reported(self):
        comparable, reasons = comparability(
            identity(),
            identity(policy_version="text-quality-prefilter-v2",
                     rule_version="text-quality-prefilter-rules-v2",
                     input_revision_vector_sha256="e" * 64),
        )
        self.assertFalse(comparable)
        self.assertEqual(len(reasons), 3)

    def test_different_artifact_params_are_not_comparable(self):
        comparable, reasons = comparability(
            identity(),
            identity(artifact_params={"age_band": "6-8", "genre": "温情", "page_count": 32}),
        )
        self.assertFalse(comparable)
        self.assertTrue(any("artifact_params" in reason for reason in reasons))


class ReportTests(unittest.TestCase):
    def report(self, **overrides):
        payload = build_report(
            identity=identity(),
            comparable=True,
            reasons=(),
            llm=metrics("llm", input_tokens=54000, estimated_cost_usd="1.234500000000",
                        request_count=12, elapsed_ms=180000),
            jev_assisted=metrics("jev_assisted"),
            calibration=(),
        )
        payload.update(overrides)
        return payload

    def test_the_report_declares_its_schema(self):
        self.assertEqual(self.report()["schema_version"], COMPARISON_SCHEMA)

    def test_the_report_keeps_both_paths_side_by_side(self):
        report = self.report()
        self.assertEqual(report["llm"]["path"], "llm")
        self.assertEqual(report["jev_assisted"]["path"], "jev_assisted")

    def test_the_report_carries_the_comparability_verdict(self):
        report = build_report(identity=identity(), comparable=False,
                              reasons=("benchmark_case_id differs",),
                              llm=metrics("llm"), jev_assisted=metrics("jev_assisted"),
                              calibration=())
        self.assertFalse(report["comparable"])
        self.assertEqual(report["comparability_reasons"],
                         ["benchmark_case_id differs"])

    def test_markdown_names_every_metric_pair(self):
        text = report_to_markdown(self.report())
        self.assertIn("## 路径对比", text)
        self.assertIn("input_tokens", text)
        self.assertIn("estimated_cost_usd", text)

    def test_markdown_states_when_the_runs_are_not_comparable(self):
        text = report_to_markdown(build_report(
            identity=identity(), comparable=False, reasons=("draft_sha256 differs",),
            llm=metrics("llm"), jev_assisted=metrics("jev_assisted"), calibration=(),
        ))
        self.assertIn("不可比较", text)
        self.assertIn("draft_sha256 differs", text)

    def test_an_all_clear_markdown_report_omits_the_warning(self):
        self.assertNotIn("不可比较", report_to_markdown(self.report()))


class DescribeMetricTests(unittest.TestCase):
    def test_a_known_ratio_is_described_as_a_ratio(self):
        self.assertEqual(describe_metric("input_tokens", 8000, 4000), "8000 → 4000 (0.50×)")

    def test_a_zero_jev_side_does_not_divide_by_zero(self):
        self.assertIn("n/a", describe_metric("elapsed_ms", 1000, 0))

    def test_a_missing_value_is_reported_as_unknown(self):
        self.assertIn("unknown", describe_metric("cache_tokens", 100, None))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_comparison.py`
Expected: FAIL —— `ModuleNotFoundError: No module named 'comparison'`

- [ ] **Step 3: 实现 `comparison.py`**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/comparison.py`：

```python
"""Side-by-side comparison of the plain-LLM and Jev-assisted execution paths."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from telemetry import canonical_json, sha256_hex

COMPARISON_SCHEMA = "pb-path-comparison-v1"

# Two runs may only be compared when they describe the same work. Anything less
# than all of these makes the numbers describe different tasks.
IDENTITY_FIELDS = (
    "benchmark_case_id",
    "input_revision_vector_sha256",
    "draft_sha256",
    "policy_version",
    "rule_version",
    "artifact_params",
)

CALIBRATION_STATUSES = ("experimental", "calibrated")

CALIBRATION_SUGGESTIONS = (
    "keep_experimental",
    "review_thresholds",
    "eligible_for_calibrated",
)

# The metric pairs the spec's comparison table requires, in report order.
METRIC_NAMES = (
    "elapsed_ms",
    "request_count",
    "input_tokens",
    "output_tokens",
    "cache_tokens",
    "estimated_cost_usd",
    "knowledge_items_entered",
    "quality_items_entered",
    "issues_found",
    "misses_or_disagreements",
)


def validate_identity(payload: Any) -> None:
    if not isinstance(payload, Mapping):
        raise ValueError("identity must be an object")
    for field_name in IDENTITY_FIELDS:
        if field_name not in payload:
            raise ValueError(f"identity is missing {field_name!r}")
    for field_name in IDENTITY_FIELDS:
        if field_name == "artifact_params":
            continue
        value = payload[field_name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"identity.{field_name} must be a non-empty string")
    params = payload["artifact_params"]
    if not isinstance(params, Mapping) or not params:
        raise ValueError("identity.artifact_params must be a non-empty object")


def identity_digest(identity: Mapping[str, Any]) -> str:
    """A stable digest of the shared case identity."""

    return "sha256:" + sha256_hex(canonical_json(dict(identity)))


def comparability(
    llm_identity: Mapping[str, Any], jev_identity: Mapping[str, Any]
) -> tuple[bool, tuple[str, ...]]:
    """Decide whether two runs may be placed side by side.

    Every mismatch is reported rather than short-circuiting, so a user fixing
    one field does not have to re-run to discover the next.
    """

    reasons = []
    for field_name in IDENTITY_FIELDS:
        left = llm_identity.get(field_name)
        right = jev_identity.get(field_name)
        if canonical_json(left) != canonical_json(right):
            reasons.append(
                f"{field_name} differs: llm={canonical_json(left)} "
                f"jev_assisted={canonical_json(right)}"
            )
    return (not reasons), tuple(reasons)


@dataclass(frozen=True)
class CaseMetrics:
    path: str
    elapsed_ms: int | None = None
    request_count: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_tokens: int | None = None
    estimated_cost_usd: str | None = None
    knowledge_items_entered: int | None = None
    quality_items_entered: int | None = None
    issues_found: int | None = None
    misses_or_disagreements: int | None = None
    notes: tuple[str, ...] = ()


def _metrics_dict(metrics: CaseMetrics) -> dict:
    payload = asdict(metrics)
    payload["notes"] = list(payload["notes"])
    return payload


def build_report(
    *,
    identity: Mapping[str, Any],
    comparable: bool,
    reasons: Sequence[str],
    llm: CaseMetrics,
    jev_assisted: CaseMetrics,
    calibration: Sequence[Mapping[str, Any]],
) -> dict:
    return {
        "schema_version": COMPARISON_SCHEMA,
        "identity": dict(identity),
        "identity_digest": identity_digest(identity),
        "comparable": bool(comparable),
        "comparability_reasons": list(reasons),
        "llm": _metrics_dict(llm),
        "jev_assisted": _metrics_dict(jev_assisted),
        "calibration": [dict(entry) for entry in calibration],
    }


def describe_metric(name: str, llm_value: Any, jev_value: Any) -> str:
    """Describe one metric pair without pretending a missing value is zero."""

    if llm_value is None:
        return f"{name}: llm=unknown jev_assisted={jev_value}"
    if jev_value is None:
        return f"{name}: llm={llm_value} jev_assisted=unknown"
    if name == "estimated_cost_usd":
        left, right = Decimal(str(llm_value)), Decimal(str(jev_value))
        if right == 0:
            return f"{name}: {llm_value} → {jev_value} (n/a)"
        return f"{name}: {llm_value} → {jev_value} ({(left / right):.2f}×)"
    if isinstance(llm_value, (int, float)) and isinstance(jev_value, (int, float)):
        if jev_value == 0:
            return f"{name}: {llm_value} → {jev_value} (n/a)"
        return f"{name}: {llm_value} → {jev_value} ({llm_value / jev_value:.2f}×)"
    return f"{name}: {llm_value} → {jev_value}"


def report_to_markdown(report: Mapping[str, Any]) -> str:
    lines = ["## 路径对比", ""]
    if not report.get("comparable"):
        lines.append("**两次运行不可比较，下列数值仅供排查，不得作为结论。**")
        lines.append("")
        lines.append("不可比较原因：")
        lines.extend(f"- {reason}" for reason in report.get("comparability_reasons", ()))
        lines.append("")
    lines.append(f"case digest: {report.get('identity_digest', '')}")
    lines.append("")
    lines.append("| 指标 | 普通 LLM | Jev 辅助 |")
    lines.append("| --- | --- | --- |")
    llm = report.get("llm", {})
    jev = report.get("jev_assisted", {})
    for name in METRIC_NAMES:
        lines.append(f"| {name} | {llm.get(name)} | {jev.get(name)} |")
    lines.append("")
    for name in METRIC_NAMES:
        lines.append(f"- {describe_metric(name, llm.get(name), jev.get(name))}")
    for entry in report.get("calibration", ()):
        lines.extend([
            "",
            f"- 校准建议：{entry.get('operation')} "
            f"{entry.get('current')} → {entry.get('suggestion')}（{entry.get('reason')}）",
        ])
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_comparison.py`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/comparison.py plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_comparison.py
git commit -m "feat(jev): gate and render a two-path comparison report" -m "Two runs are comparable only when the case identity matches field by field; every mismatch is reported so the user sees all of them at once." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: 合并 trace 与用户提供的 LLM 用量

spec §10.2：Jev 侧来自 trace；LLM 侧由用户从 CC Switch 手工读出并填入，本插件不访问它的数据库。两侧按同一个 `benchmark_case_id` 对齐。

**Files:**
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/comparison.py`
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_comparison.py`

**Interfaces:**
- Consumes: Task 1 的 `CaseMetrics`、`validate_identity`、`comparability`、`build_report`
- Produces:
  - `comparison.TRACE_GLOB = "jev/*/trace/*.json"`
  - `comparison.load_traces(run_dir) -> tuple[dict, ...]`
  - `comparison.jev_metrics(traces, *, measurable_only=True) -> CaseMetrics`
  - `comparison.load_llm_usage(path) -> tuple[dict, CaseMetrics]`
  - `comparison.calibration_suggestions(policy, report) -> tuple[dict, ...]`
  - `comparison.build_case_report(*, run_dir, llm_usage_path, policy) -> dict`
  - 报告额外带 `traces`（计入本 case 的 operation 数）与 `foreign_traces`（被排除的其它 case 的 trace 数）两个计数

- [ ] **Step 1: 写失败测试**

在 `test_comparison.py` 的 import 块补充：

```python
from comparison import (
    build_case_report,
    calibration_suggestions,
    jev_metrics,
    load_llm_usage,
    load_traces,
)
```

在文件末尾追加：

```python
import json
import tempfile
from pathlib import Path

from decision_contract import default_policy_path, load_policy
from jev_runner import write_atomic


def trace(operation, **overrides):
    payload = {
        "schema_version": "pb-decision-trace-v1",
        "run_id": "20260923-example-0001",
        "benchmark_case_id": "sha256:" + "0" * 64,
        "execution_mode": "jev_assisted",
        "operation": operation,
        "started_at": "2026-09-23T10:30:00.000+08:00",
        "finished_at": "2026-09-23T10:30:00.412+08:00",
        "elapsed_ms": 412,
        "input_sha256": "a" * 64,
        "item_count": 10,
        "question_count": 40,
        "screened_clear_count": 6,
        "escalated_count": 4,
        "request_count": 1,
        "input_tokens": 2000,
        "output_tokens": 100,
        "estimated_cost_usd": "0.000084000000",
        "price_usd_per_million_input_tokens": "0.042",
        "price_snapshot_date": "2026-09-23",
        "resolved_model": "jev-1.13.0",
        "status": "succeeded",
        "fallback_used": False,
        "error_class": None,
    }
    payload.update(overrides)
    return payload


LLM_USAGE = {
    "identity": identity(),
    "model_label": "gpt-5-codex",
    "source": "cc-switch-manual-entry",
    "elapsed_ms": 180000,
    "request_count": 12,
    "input_tokens": 54000,
    "output_tokens": 9000,
    "cache_tokens": 12000,
    "estimated_cost_usd": "1.234500000000",
    "knowledge_items_entered": 180,
    "quality_items_entered": 160,
    "issues_found": 7,
    "misses_or_disagreements": 1,
}


class TraceLoadingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, operation, attempt, payload):
        write_atomic(
            self.run_dir / "jev" / operation / "trace" / f"{attempt:04d}.json", payload
        )

    def test_traces_are_read_from_the_run_directory(self):
        self._write("text_quality_prefilter", 1, trace("text_quality_prefilter"))
        traces = load_traces(self.run_dir)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["operation"], "text_quality_prefilter")

    def test_an_empty_run_directory_yields_no_traces(self):
        self.assertEqual(load_traces(self.run_dir), ())

    def test_two_attempts_of_one_operation_count_their_verdicts_once(self):
        # A resumed or retried operation writes one trace per attempt. Summing
        # them would double the cleared and escalated totals the whole
        # comparison is built on, so only the terminal attempt is counted.
        self._write("text_quality_prefilter", 1, trace(
            "text_quality_prefilter", status="failed",
            screened_clear_count=0, escalated_count=0,
        ))
        self._write("text_quality_prefilter", 2, trace("text_quality_prefilter"))
        traces = load_traces(self.run_dir)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["status"], "succeeded")
        metrics = jev_metrics(traces)
        self.assertEqual(metrics.issues_found, 4)
        self.assertIn("screened_clear=6", metrics.notes)

    def test_a_fallback_run_is_not_a_jev_sample(self):
        # A run that switched back to the plain LLM mid-way measures a hybrid
        # path, not the Jev-assisted path, so its time and cost must stay out
        # of the Jev side of the comparison.
        metrics = jev_metrics((
            trace("text_quality_prefilter"),
            trace("knowledge_relevance", fallback_used=True, input_tokens=99_000,
                  estimated_cost_usd="9.000000000000", elapsed_ms=500_000),
        ))
        self.assertEqual(metrics.input_tokens, 2000)
        self.assertEqual(metrics.elapsed_ms, 412)

    def test_the_report_names_the_operations_the_jev_side_ran(self):
        metrics = jev_metrics((
            trace("knowledge_relevance"),
            trace("text_quality_prefilter"),
        ))
        self.assertIn(
            "operations=knowledge_relevance,text_quality_prefilter", metrics.notes
        )

    def test_jev_metrics_sum_the_traces(self):
        metrics = jev_metrics((
            trace("text_quality_prefilter"),
            trace("knowledge_relevance", input_tokens=1000, request_count=2,
                  estimated_cost_usd="0.000042000000", elapsed_ms=200),
        ))
        self.assertEqual(metrics.path, "jev_assisted")
        self.assertEqual(metrics.input_tokens, 3000)
        self.assertEqual(metrics.request_count, 3)
        self.assertEqual(metrics.elapsed_ms, 612)
        self.assertEqual(metrics.estimated_cost_usd, "0.000126000000")

    def test_a_waiting_trace_does_not_pollute_the_measurement(self):
        # A waiting run never dispatched, so it must not enter the speed and
        # cost sample at all.
        metrics = jev_metrics((
            trace("text_quality_prefilter"),
            trace("knowledge_relevance", status="waiting_for_jev_key",
                  input_tokens=None, output_tokens=None,
                  estimated_cost_usd=None, elapsed_ms=90_000, request_count=0),
        ))
        self.assertEqual(metrics.input_tokens, 2000)
        self.assertEqual(metrics.elapsed_ms, 412)

    def test_an_ambiguous_outcome_is_counted_but_not_as_cost(self):
        metrics = jev_metrics((
            trace("text_quality_prefilter", status="outcome_unknown",
                  input_tokens=None, estimated_cost_usd=None),
        ))
        self.assertEqual(metrics.estimated_cost_usd, "0.000000000000")

    def test_jev_metrics_report_the_escalation_volume(self):
        metrics = jev_metrics((
            trace("text_quality_prefilter"),
            trace("text_quality_prefilter", attempt=2, escalated_count=7,
                  screened_clear_count=3, item_count=10),
        ))
        self.assertEqual(metrics.quality_items_entered, 10)
        self.assertEqual(metrics.notes and True, True)


class LlmUsageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "llm-usage.json"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, payload):
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return self.path

    def test_a_complete_entry_is_read_into_metrics_and_identity(self):
        loaded_identity, metrics = load_llm_usage(self._write(LLM_USAGE))
        self.assertEqual(loaded_identity["benchmark_case_id"], "sha256:" + "0" * 64)
        self.assertEqual(metrics.path, "llm")
        self.assertEqual(metrics.input_tokens, 54000)
        self.assertEqual(metrics.cache_tokens, 12000)
        self.assertEqual(metrics.estimated_cost_usd, "1.234500000000")

    def test_an_entry_without_an_identity_is_refused(self):
        payload = dict(LLM_USAGE)
        del payload["identity"]
        with self.assertRaises(ValueError):
            load_llm_usage(self._write(payload))

    def test_the_source_must_name_a_manual_entry(self):
        # If this ever records a database path, the plugin has started reading
        # a private store it promised not to touch.
        payload = dict(LLM_USAGE, source="cc-switch-sqlite:/home/u/.cc-switch.db")
        with self.assertRaises(ValueError):
            load_llm_usage(self._write(payload))

    def test_metrics_may_be_absent_and_read_as_null(self):
        payload = dict(LLM_USAGE)
        for name in ("cache_tokens", "misses_or_disagreements", "estimated_cost_usd"):
            payload[name] = None
        _, metrics = load_llm_usage(self._write(payload))
        self.assertIsNone(metrics.cache_tokens)
        self.assertIsNone(metrics.misses_or_disagreements)
        self.assertIsNone(metrics.estimated_cost_usd)


class CalibrationSuggestionTests(unittest.TestCase):
    def _report(self, escalated, screened_clear, failed=0):
        return {
            "comparable": True,
            "jev_assisted": {
                "path": "jev_assisted",
                "quality_items_entered": escalated + screened_clear,
                "notes": [f"escalated={escalated}", f"screened_clear={screened_clear}",
                          f"runtime_failure={failed}"],
            },
        }

    def test_an_experimental_operation_with_any_failure_stays_experimental(self):
        suggestions = calibration_suggestions(
            load_policy(default_policy_path()),
            self._report(escalated=1, screened_clear=9, failed=1),
        )
        entry = next(s for s in suggestions if s["operation"] == "text_quality_prefilter")
        self.assertEqual(entry["suggestion"], "keep_experimental")

    def test_a_very_high_escalation_rate_suggests_reviewing_thresholds(self):
        suggestions = calibration_suggestions(
            load_policy(default_policy_path()),
            self._report(escalated=10, screened_clear=0),
        )
        entry = next(s for s in suggestions if s["operation"] == "text_quality_prefilter")
        self.assertEqual(entry["suggestion"], "review_thresholds")

    def test_an_experimental_operation_is_never_auto_promoted(self):
        suggestions = calibration_suggestions(
            load_policy(default_policy_path()),
            self._report(escalated=1, screened_clear=99),
        )
        entry = next(s for s in suggestions if s["operation"] == "text_quality_prefilter")
        self.assertEqual(entry["current"], "experimental")
        self.assertIn(entry["suggestion"], ("eligible_for_calibrated", "keep_experimental"))
        self.assertNotEqual(entry["current"], entry["suggestion"])

    def test_every_operation_gets_a_suggestion(self):
        suggestions = calibration_suggestions(
            load_policy(default_policy_path()), self._report(1, 9)
        )
        self.assertEqual(len(suggestions), 2)

    def test_an_incomparable_report_still_produces_suggestions(self):
        report = self._report(1, 9)
        report["comparable"] = False
        suggestions = calibration_suggestions(load_policy(default_policy_path()), report)
        self.assertTrue(suggestions)


class BuildCaseReportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name)
        write_atomic(
            self.run_dir / "jev" / "text_quality_prefilter" / "trace" / "0001.json",
            trace("text_quality_prefilter"),
        )
        self.usage_path = self.run_dir / "llm-usage.json"
        self.usage_path.write_text(json.dumps(LLM_USAGE, ensure_ascii=False),
                                   encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_matching_identities_produce_a_comparable_report(self):
        report = build_case_report(
            run_dir=self.run_dir, llm_usage_path=self.usage_path,
            policy=load_policy(default_policy_path()),
        )
        self.assertTrue(report["comparable"])
        self.assertEqual(report["comparability_reasons"], [])

    def test_a_mismatched_draft_produces_an_incomparable_report(self):
        payload = json.loads(self.usage_path.read_text(encoding="utf-8"))
        payload["identity"]["draft_sha256"] = "z" * 64
        self.usage_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        report = build_case_report(
            run_dir=self.run_dir, llm_usage_path=self.usage_path,
            policy=load_policy(default_policy_path()),
        )
        self.assertFalse(report["comparable"])
        self.assertTrue(any("draft_sha256" in reason
                            for reason in report["comparability_reasons"]))

    def test_traces_from_another_case_are_not_summed_in(self):
        # Reusing a run directory for a second case leaves the earlier traces
        # behind. Summing them would silently inflate this case's tokens and
        # cost while still reporting the two runs as comparable.
        write_atomic(
            self.run_dir / "jev" / "knowledge_relevance" / "trace" / "0001.json",
            trace("knowledge_relevance", benchmark_case_id="sha256:" + "f" * 64),
        )
        report = build_case_report(
            run_dir=self.run_dir, llm_usage_path=self.usage_path,
            policy=load_policy(default_policy_path()),
        )
        self.assertTrue(report["comparable"])
        self.assertEqual(report["traces"], 1)
        self.assertEqual(report["foreign_traces"], 1)
        self.assertEqual(report["jev_assisted"]["input_tokens"], 2000)

    def test_a_numeric_cost_is_refused_with_a_quoting_hint(self):
        # The likely mistake while copying numbers out of CC Switch by hand is
        # writing a JSON number. A binary float would then leak into the cost
        # column, so the entry is refused and the fix is spelled out.
        payload = json.loads(self.usage_path.read_text(encoding="utf-8"))
        payload["estimated_cost_usd"] = 1.2345
        self.usage_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        with self.assertRaises(ValueError) as raised:
            build_case_report(
                run_dir=self.run_dir, llm_usage_path=self.usage_path,
                policy=load_policy(default_policy_path()),
            )
        self.assertIn("decimal string", str(raised.exception))

    def test_an_empty_run_directory_reports_no_jev_measurement(self):
        empty = self.run_dir / "empty"
        empty.mkdir()
        report = build_case_report(
            run_dir=empty, llm_usage_path=self.usage_path,
            policy=load_policy(default_policy_path()),
        )
        self.assertIsNone(report["jev_assisted"]["input_tokens"])

    def test_the_report_carries_the_calibration_suggestions(self):
        report = build_case_report(
            run_dir=self.run_dir, llm_usage_path=self.usage_path,
            policy=load_policy(default_policy_path()),
        )
        self.assertEqual(len(report["calibration"]), 2)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_comparison.py`
Expected: FAIL —— `ImportError: cannot import name 'build_case_report'`

- [ ] **Step 3: 实现合并与建议**

在 `comparison.py` 末尾追加。注意 `value not in` 之类的判断必须容忍 `None`：

```python
TRACE_GLOB = "jev/*/trace/*.json"

# A waiting run never dispatched a request, so its "elapsed" is the user's own
# configuration time. Counting it would corrupt the speed comparison the whole
# report exists to produce.
UNMEASURED_STATUSES = ("waiting_for_jev_key", "waiting_for_jev_access")


def load_traces(run_dir: Any) -> tuple[dict, ...]:
    """Read the terminal trace of every operation under a run directory.

    A resumed or retried operation writes one trace per attempt, and only the
    terminal attempt may contribute verdict counts: adding attempts together
    would double the cleared and escalated totals this whole report rests on.
    The failure paths carry null usage anyway, so nothing billable is lost.
    """

    root = Path(run_dir)
    if not root.is_dir():
        return ()
    terminal: dict[str, tuple[int, dict]] = {}
    for path in sorted(root.glob(TRACE_GLOB)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        attempt = int(path.stem) if path.stem.isdigit() else 0
        operation = path.parent.parent.name
        if operation not in terminal or attempt > terminal[operation][0]:
            terminal[operation] = (attempt, payload)
    return tuple(payload for _, payload in terminal.values())


def _sum_optional(values) -> int | None:
    present = [value for value in values if isinstance(value, int)]
    if not present:
        return None
    return sum(present)


def _sum_cost(values) -> str | None:
    present = [Decimal(str(value)) for value in values if value is not None]
    if not present:
        return None
    return str(sum(present, Decimal("0.000000000000")))


def jev_metrics(traces, *, measurable_only: bool = True) -> CaseMetrics:
    """Fold the traces into one measurement of the Jev-assisted path."""

    traces = tuple(traces)
    if measurable_only:
        measured = tuple(
            item for item in traces
            if item.get("status") not in UNMEASURED_STATUSES
            # A run that switched back to the plain LLM mid-way measured a
            # hybrid path, so it is not a Jev-assisted sample either.
            and item.get("fallback_used") is not True
        )
    else:
        measured = traces
    if not measured:
        return CaseMetrics(path="jev_assisted")
    item_counts = [
        item.get("item_count") for item in measured
        if isinstance(item.get("item_count"), int)
    ]
    screened = _sum_optional(item.get("screened_clear_count") for item in measured)
    escalated = _sum_optional(item.get("escalated_count") for item in measured)
    failed = len([item for item in measured if item.get("status") != "succeeded"])
    notes = []
    if escalated is not None:
        notes.append(f"escalated={escalated}")
    if screened is not None:
        notes.append(f"screened_clear={screened}")
    notes.append(f"runtime_failure={failed}")
    operations = sorted({
        str(item.get("operation")) for item in measured if item.get("operation")
    })
    if operations:
        # Naming the operations makes an unbalanced pair visible: a side that
        # only ran the red-line prefilter cannot be compared on cost with a
        # side that also screened the knowledge base.
        notes.append("operations=" + ",".join(operations))
    return CaseMetrics(
        path="jev_assisted",
        elapsed_ms=_sum_optional(item.get("elapsed_ms") for item in measured),
        request_count=_sum_optional(item.get("request_count") for item in measured),
        input_tokens=_sum_optional(item.get("input_tokens") for item in measured),
        output_tokens=_sum_optional(item.get("output_tokens") for item in measured),
        cache_tokens=0,
        estimated_cost_usd=_sum_cost(
            item.get("estimated_cost_usd") for item in measured
        ),
        knowledge_items_entered=max(item_counts) if item_counts else None,
        quality_items_entered=max(item_counts) if item_counts else None,
        issues_found=(escalated + failed) if escalated is not None else None,
        misses_or_disagreements=None,
        notes=tuple(notes),
    )


_LLM_USAGE_FIELDS = (
    "elapsed_ms", "request_count", "input_tokens", "output_tokens", "cache_tokens",
    "estimated_cost_usd", "knowledge_items_entered", "quality_items_entered",
    "issues_found", "misses_or_disagreements",
)


def load_llm_usage(path: Any) -> tuple[dict, CaseMetrics]:
    """Read the user-supplied plain-LLM usage entry.

    The plugin never reads CC Switch's own store: its schema is not a stable
    public contract and reading it would hard-code a personal environment path.
    """

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("llm usage entry must be a JSON object")
    validate_identity(payload.get("identity"))
    source = str(payload.get("source", ""))
    if not source.startswith("cc-switch-manual-entry") and source != "manual":
        raise ValueError(
            "llm usage source must be a manual entry; this plugin does not read "
            "the CC Switch database"
        )
    cost = payload.get("estimated_cost_usd")
    if cost is not None and not isinstance(cost, str):
        raise ValueError(
            "estimated_cost_usd must be a quoted decimal string, for example "
            '"1.234500000000": a JSON number is parsed as a binary float, and '
            "this report is not allowed to disagree with the invoice"
        )
    values = {name: payload.get(name) for name in _LLM_USAGE_FIELDS}
    return dict(payload["identity"]), CaseMetrics(
        path="llm",
        notes=(f"model={payload.get('model_label')}", f"source={source}"),
        **values,
    )


# Escalation above this share means the thresholds are clearing too little for
# the screening to earn its cost, which is a threshold question, not a
# calibration question.
HIGH_ESCALATION_RATIO = 0.8


def _note_value(notes, name: str) -> int | None:
    for note in notes or ():
        key, separator, value = str(note).partition("=")
        if separator and key == name:
            try:
                return int(value)
            except ValueError:
                return None
    return None


def calibration_suggestions(policy: Mapping[str, Any], report: Mapping[str, Any]) -> tuple[dict, ...]:
    """Suggest a calibration action per operation.

    The suggestion is advisory only. Flipping `calibration_status` changes how
    much the plain LLM re-checks, so it stays a human decision recorded in the
    policy file.
    """

    jev = report.get("jev_assisted") or {}
    notes = jev.get("notes") or ()
    escalated = _note_value(notes, "escalated")
    screened_clear = _note_value(notes, "screened_clear")
    failed = _note_value(notes, "runtime_failure") or 0
    total = None
    if escalated is not None and screened_clear is not None:
        total = escalated + screened_clear
    suggestions = []
    for operation in OPERATIONS:
        entry = operation_policy(policy, operation)
        current = entry["calibration_status"]
        suggestion = "keep_experimental"
        reason = "尚无足够的本地测量"
        if not report.get("comparable"):
            reason = "两次运行不可比较，本次数据不能用于校准"
        elif failed:
            reason = f"本次有 {failed} 项运行失败，失败项不得计入校准"
        elif total:
            ratio = escalated / total
            if ratio > HIGH_ESCALATION_RATIO:
                suggestion = "review_thresholds"
                reason = f"升级率 {ratio:.0%} 过高，先复核阈值"
            elif current == "experimental":
                suggestion = "eligible_for_calibrated"
                reason = "本次无失败且升级率可接受，可提交人工复核后转为 calibrated"
        suggestions.append({
            "operation": operation,
            "current": current,
            "suggestion": suggestion,
            "reason": reason,
        })
    return tuple(suggestions)


def build_case_report(*, run_dir: Any, llm_usage_path: Any, policy: Mapping[str, Any]) -> dict:
    """Assemble one comparison from a run directory and a manual usage entry."""

    llm_identity, llm = load_llm_usage(llm_usage_path)
    traces = load_traces(run_dir)
    case_ids = {trace.get("benchmark_case_id") for trace in traces if trace.get("benchmark_case_id")}
    jev_identity = dict(llm_identity)
    if case_ids:
        jev_identity["benchmark_case_id"] = sorted(case_ids)[0]
    comparable, reasons = comparability(llm_identity, jev_identity)
    # A run directory reused for a second case still holds the earlier traces.
    # They are excluded from the numbers (a stale trace must not inflate this
    # case's tokens or cost) but counted, so the mismatch stays visible.
    own = tuple(
        trace for trace in traces
        if trace.get("benchmark_case_id") in (None, jev_identity["benchmark_case_id"])
    )
    jev = jev_metrics(own)
    report = build_report(
        identity=llm_identity, comparable=comparable, reasons=reasons,
        llm=llm, jev_assisted=jev,
        calibration=calibration_suggestions(policy, {"comparable": comparable,
                                                     "jev_assisted": _metrics_dict(jev)}),
    )
    report["traces"] = len(own)
    report["foreign_traces"] = len(traces) - len(own)
    return report
```

在 `comparison.py` 顶部补齐新增的 import，最终 import 块为：

```python
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from decision_contract import OPERATIONS, operation_policy
from telemetry import canonical_json, sha256_hex
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_comparison.py`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/comparison.py plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_comparison.py
git commit -m "feat(jev): merge decision traces with manually entered plain-LLM usage" -m "The plugin never reads the CC Switch store; the user supplies the LLM side, waiting runs are excluded from the speed sample, and calibration only ever gets a suggestion." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: 比较报告 CLI 与导出门

spec §10.3 与 §16：只有用户明确要求导出时才写文件，且必须使用用户提供的绝对目录，不得写入插件目录。这些规则与 `session-export` 完全一致，因此复用它的守卫而不是另立一套。

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/compare_cli.py`
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_compare_cli.py`

**Interfaces:**
- Consumes: Task 1/2 的 `build_case_report`、`report_to_markdown`、`COMPARISON_SCHEMA`；`jev_runner.reject_credential_arguments`；`session-export/scripts/export_session.export_session`
- Produces:
  - `compare_cli.OUT_OF_PLUGIN_ERROR = "output directory must be outside the plugin"`
  - `compare_cli.require_explicit_output_dir(output_dir, plugin_root) -> Path`
  - `compare_cli.main(argv=None, stdout=None, stderr=None) -> int`

- [ ] **Step 1: 写失败测试**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_compare_cli.py`：

```python
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills" / "session-export" / "scripts"))

from compare_cli import (
    OUT_OF_PLUGIN_ERROR,
    main,
    require_explicit_output_dir,
)
from comparison import COMPARISON_SCHEMA
from decision_contract import default_policy_path
from jev_runner import write_atomic

from test_comparison import LLM_USAGE, identity, trace


class OutputDirGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.plugin = self.root / "plugin"
        self.plugin.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_relative_directory_is_refused(self):
        with self.assertRaisesRegex(ValueError, "absolute"):
            require_explicit_output_dir(Path("exports"), self.plugin)

    def test_the_plugin_directory_is_refused(self):
        with self.assertRaisesRegex(ValueError, "outside the plugin"):
            require_explicit_output_dir(self.plugin, self.plugin)

    def test_a_directory_inside_the_plugin_is_refused(self):
        inside = self.plugin / "reports"
        with self.assertRaisesRegex(ValueError, "outside the plugin"):
            require_explicit_output_dir(inside, self.plugin)

    def test_an_absolute_directory_outside_the_plugin_is_accepted(self):
        outside = self.root / "exports"
        self.assertEqual(require_explicit_output_dir(outside, self.plugin),
                         outside.resolve())


class CompareCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.run_dir = self.root / "run"
        write_atomic(
            self.run_dir / "jev" / "text_quality_prefilter" / "trace" / "0001.json",
            trace("text_quality_prefilter"),
        )
        self.usage = self.root / "llm-usage.json"
        self.usage.write_text(json.dumps(LLM_USAGE, ensure_ascii=False),
                              encoding="utf-8")
        self.out_dir = self.root / "exports"
        self.out_dir.mkdir()
        self.plugin = self.root / "plugin"
        self.plugin.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _argv(self, *extra):
        return [
            "--run-dir", str(self.run_dir),
            "--llm-usage", str(self.usage),
            "--output-dir", str(self.out_dir),
            "--plugin-root", str(self.plugin),
            "--policy", str(default_policy_path()),
            *extra,
        ]

    def _main(self, argv, stdout=None):
        out = io.StringIO() if stdout is None else stdout
        err = io.StringIO()
        code = main(argv, stdout=out, stderr=err)
        return code, out.getvalue(), err.getvalue()

    def test_without_an_output_directory_only_json_is_printed(self):
        code, out, _ = self._main([
            "--run-dir", str(self.run_dir), "--llm-usage", str(self.usage),
            "--policy", str(default_policy_path()),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["schema_version"], COMPARISON_SCHEMA)
        self.assertFalse(list(self.root.rglob("*-audit")))

    def test_an_explicit_output_directory_writes_both_renderings(self):
        code, out, _ = self._main(self._argv())
        self.assertEqual(code, 0)
        bundle = self.out_dir / "path-comparison-audit"
        self.assertTrue((bundle / "comparison.json").is_file())
        self.assertTrue((bundle / "comparison.md").is_file())
        self.assertTrue((bundle / "manifest.json").is_file())
        self.assertEqual(
            json.loads((bundle / "comparison.json").read_text(encoding="utf-8"))["schema_version"],
            COMPARISON_SCHEMA,
        )

    def test_a_relative_output_directory_exits_with_a_usage_error(self):
        code, _, err = self._main([
            "--run-dir", str(self.run_dir), "--llm-usage", str(self.usage),
            "--output-dir", "exports", "--plugin-root", str(self.plugin),
            "--policy", str(default_policy_path()),
        ])
        self.assertEqual(code, 1)
        self.assertIn("absolute", err)

    def test_writing_into_the_plugin_is_refused(self):
        code, _, err = self._main([
            "--run-dir", str(self.run_dir), "--llm-usage", str(self.usage),
            "--output-dir", str(self.plugin), "--plugin-root", str(self.plugin),
            "--policy", str(default_policy_path()),
        ])
        self.assertEqual(code, 1)
        self.assertIn(OUT_OF_PLUGIN_ERROR, err)

    def test_credential_arguments_are_refused_without_echoing_the_value(self):
        out, err = io.StringIO(), io.StringIO()
        code = main(
            ["--api-key=SUPER-SECRET", "--run-dir", str(self.run_dir)],
            stdout=out, stderr=err,
        )
        self.assertEqual(code, 2)
        self.assertNotIn("SUPER-SECRET", err.getvalue())
        self.assertNotIn("SUPER-SECRET", out.getvalue())

    def test_no_written_file_contains_a_credential_field_name(self):
        self._main(self._argv())
        for path in (self.out_dir / "path-comparison-audit").rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                for forbidden in ("api_key", "authorization", "password", "secret"):
                    self.assertNotIn(forbidden, text.lower())

    def test_usage_errors_exit_two(self):
        code, _, _ = self._main([])
        self.assertEqual(code, 2)

    def test_a_missing_llm_usage_file_is_reported_as_an_error(self):
        code, _, err = self._main([
            "--run-dir", str(self.run_dir),
            "--llm-usage", str(self.root / "nope.json"),
            "--policy", str(default_policy_path()),
        ])
        self.assertEqual(code, 1)
        self.assertIn("error", err.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_compare_cli.py`
Expected: FAIL —— `ModuleNotFoundError: No module named 'compare_cli'`

- [ ] **Step 3: 实现 `compare_cli.py`**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/compare_cli.py`：

```python
"""CLI for the two-path comparison report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from comparison import build_case_report, report_to_markdown
from decision_contract import ContractError, default_policy_path, load_policy
from jev_client import JevClientError
from jev_runner import reject_credential_arguments
from telemetry import now_iso

# The session-export helper owns the audit bundle layout; this CLI composes it
# rather than duplicating the format.
_SESSION_EXPORT_SCRIPTS = Path(__file__).resolve().parents[2] / "session-export" / "scripts"
if str(_SESSION_EXPORT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SESSION_EXPORT_SCRIPTS))

from export_session import export_session  # noqa: E402

OUT_OF_PLUGIN_ERROR = "output directory must be outside the plugin"
SESSION_ID = "path-comparison"


def require_explicit_output_dir(output_dir, plugin_root) -> Path:
    """Validate a user-supplied export directory.

    The two rules mirror session-export: the caller must name the directory
    absolutely, and it must not land inside the installed plugin.
    """

    output_dir = Path(output_dir)
    if not output_dir.is_absolute():
        raise ValueError("output directory must be an absolute path")
    resolved = output_dir.resolve()
    plugin_root = Path(plugin_root).resolve()
    if resolved == plugin_root or plugin_root in resolved.parents:
        raise ValueError(OUT_OF_PLUGIN_ERROR)
    return resolved


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="compare_cli.py")
    parser.add_argument("--run-dir", required=True,
                        help="the jev_assisted run directory holding the traces")
    parser.add_argument("--llm-usage", required=True,
                        help="the plain-LLM usage entry, read out of CC Switch by hand")
    parser.add_argument("--output-dir",
                        help="absolute directory to export into; omit to only print")
    parser.add_argument("--plugin-root", help="plugin install root, for the boundary check")
    parser.add_argument("--policy")
    return parser


def main(argv=None, stdout=None, stderr=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr

    refusal = reject_credential_arguments(arguments)
    if refusal is not None:
        print(refusal, file=err)
        return 2

    parser = _build_parser()
    if not arguments:
        parser.print_usage(err)
        return 2
    try:
        args = parser.parse_args(arguments)
    except SystemExit as exit_error:
        return 2 if exit_error.code else 0

    try:
        policy = load_policy(args.policy or default_policy_path())
        report = build_case_report(
            run_dir=Path(args.run_dir), llm_usage_path=Path(args.llm_usage),
            policy=policy,
        )
        if args.output_dir:
            if not args.plugin_root:
                raise ValueError("--plugin-root is required when exporting")
            bundle = _export(args, report)
            report["exported_to"] = str(bundle)
    except (ContractError, JevClientError, OSError, ValueError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False),
              file=err)
        return 1

    print(json.dumps(report, ensure_ascii=False, sort_keys=True), file=out)
    return 0


def _export(args, report) -> Path:
    """Write the report through the session-export bundle helper."""

    output_dir = require_explicit_output_dir(args.output_dir, args.plugin_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = export_session(
        SESSION_ID, [], ["comparison.json", "comparison.md"], [],
        output_dir, Path(args.plugin_root),
    )
    (bundle / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (bundle / "comparison.md").write_text(
        report_to_markdown(report) + f"\n生成时间：{now_iso()}\n", encoding="utf-8"
    )
    return bundle


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_compare_cli.py`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/compare_cli.py plugins/picturebook-screenwriter/skills/jev-decision-runtime/scripts/test_compare_cli.py
git commit -m "feat(jev): export the comparison report only to an explicit outside directory" -m "Reuses the session-export bundle and its guards, prints JSON by default, and refuses relative or in-plugin destinations." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: 比较步骤文档、分级与端到端验收

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/references/comparison-procedure.md`
- Create: `plugins/picturebook-screenwriter/tests/test_comparison_integration.py`
- Modify: `plugins/picturebook-screenwriter/skills/jev-decision-runtime/SKILL.md`
- Modify: `plugins/picturebook-screenwriter/skills/session-export/SKILL.md`
- Modify: `docs/ENFORCEMENT.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `plugins/picturebook-screenwriter/README.md`
- Modify: `plugins/picturebook-screenwriter/tests/test_plugin_contract.py`

**Interfaces:**
- Consumes: Task 1–3 的全部公开 API
- Produces: 无（文档与验收）

- [ ] **Step 1: 写失败测试**

在 `test_plugin_contract.py` 的 `JevPhase3DocumentationTests` 之后新增：

```python
class JevPhase4DocumentationTests(unittest.TestCase):
    def test_contract_declares_the_comparison_boundary(self):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        comparison = contract["jev_comparison"]
        self.assertEqual(comparison["cc_switch_access"], "forbidden")
        self.assertEqual(comparison["llm_usage_source"], "manual_entry")
        self.assertEqual(comparison["export_gate"], "explicit_user_request")
        self.assertEqual(comparison["output_dir"], "user_supplied_absolute")
        self.assertEqual(comparison["calibration_change"], "human_only")

    def test_runtime_skill_documents_the_comparison(self):
        text = (ROOT / "skills" / "jev-decision-runtime" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("## 对比验收", text)
        self.assertIn("不读 CC Switch", text)

    def test_enforcement_matrix_documents_the_comparison_gates(self):
        text = ENFORCEMENT.read_text(encoding="utf-8")
        for required in ("comparison.py", "compare_cli.py", "cc-switch", "comparable"):
            with self.subTest(required=required):
                self.assertIn(required, text)

    def test_the_procedure_reference_exists(self):
        path = ROOT / "skills" / "jev-decision-runtime" / "references" / "comparison-procedure.md"
        self.assertTrue(path.is_file())
        self.assertIn("CC Switch", path.read_text(encoding="utf-8"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python plugins/picturebook-screenwriter/tests/test_plugin_contract.py`
Expected: FAIL —— `KeyError: 'jev_comparison'`

- [ ] **Step 3: 在契约中声明比较边界**

在 `plugins/picturebook-screenwriter/config/plugin-contract.json` 的 `jev_runtime` 块之后新增：

```json
  "jev_comparison": {
    "cc_switch_access": "forbidden",
    "llm_usage_source": "manual_entry",
    "export_gate": "explicit_user_request",
    "output_dir": "user_supplied_absolute",
    "comparability": "all_identity_fields_must_match",
    "calibration_change": "human_only"
  },
```

- [ ] **Step 4: 写比较步骤参考**

创建 `plugins/picturebook-screenwriter/skills/jev-decision-runtime/references/comparison-procedure.md`：

```markdown
# 两条路径的比较步骤

同一份 `benchmark_case_id` 分别跑一次普通 LLM 与一次 Jev 辅助，才能并排比较。

## 1. 让两次运行共享同一个 case identity

`case identity` 的六个字段必须逐字一致：

| 字段 | 来源 |
| --- | --- |
| `benchmark_case_id` | Jev 请求里的同名字段（`telemetry.benchmark_case_id()` 产出） |
| `input_revision_vector_sha256` | 权威知识版本向量的 sha256 |
| `draft_sha256` | 被审草稿的 sha256 |
| `policy_version` | `decision-policies.json` 里该 operation 的 `policy_version` |
| `rule_version` | 该 operation 的规则版本 |
| `artifact_params` | `age_band`、`genre`、`page_count` |

任一不一致，报告会标 `comparable: false` 并列出原因。**不得把不可比较的数字当成结论。**

## 2. 从 CC Switch 手工读出 LLM 侧用量

本插件不读 CC Switch 的数据库，也不依赖它的存储结构。请在 CC Switch 里按下面的顺序筛出这次运行，然后手抄成 JSON：

1. 用本次 trace 的 `started_at` / `finished_at` 作为时间窗过滤请求。
2. 只看发起本次运行的那个 Codex 会话与模型。
3. 汇总 `model`、`input_tokens`、`output_tokens`、`cache_tokens`、请求数与估算成本。

写成：

```json
{
  "identity": { "...": "与第 1 步完全一致" },
  "model_label": "gpt-5-codex",
  "source": "cc-switch-manual-entry",
  "elapsed_ms": 180000,
  "request_count": 12,
  "input_tokens": 54000,
  "output_tokens": 9000,
  "cache_tokens": 12000,
  "estimated_cost_usd": "1.234500000000",
  "knowledge_items_entered": 180,
  "quality_items_entered": 160,
  "issues_found": 7,
  "misses_or_disagreements": 1
}
```

`source` 必须是 `cc-switch-manual-entry` 或 `manual`；写下任何像数据库路径的值都会被拒绝，那意味着这个插件开始读它承诺不碰的私有存储。

## 3. 生成报告

```bash
python scripts/compare_cli.py \
    --run-dir <jev_assisted 的 run 目录> \
    --llm-usage <上一步的 JSON> \
    [--output-dir <绝对导出目录> --plugin-root <插件根>]
```

不带 `--output-dir` 时只把 JSON 打到 stdout，不写任何文件。带 `--output-dir` 时目录必须是绝对路径且不在插件目录内，报告会写进 `<output-dir>/path-comparison-audit/`。

## 4. 怎么读报告

- `screened_clear` 与 `escalated` 来自 Jev 侧 trace；`runtime_failure` 是未能完成的项数。
- **升级率过高说明阈值太严**（`review_thresholds`），而不是"Jev 不行"。
- **`fallback_used: true` 的那次运行不得计入性能比较**——它是用户显式切换路径，不是同一条路径的样本。
- 缺 `usage` 的 trace 其 token 与成本为 `null`，报告不会用字符数替它编一个数。

## 5. 转 calibrated 的条件

报告只给建议（`keep_experimental` / `review_thresholds` / `eligible_for_calibrated`），**不会自己改状态**。要转 `calibrated` 必须同时满足：

1. 测量用的是同一 case identity，报告 `comparable: true`。
2. 本次运行没有 `runtime_failure`。
3. 按 `references/calibration-samples.md` 用 `calibrate.py` 选出了满足假阴性预算的阈值。
4. 人工复核升级项与漏检，确认可接受。

改的是 `decision-policies.json` 里该 operation 的 `calibration_status` 与 band。不同 operation 不共享阈值。
```

- [ ] **Step 5: 更新技能文档与分级**

在 `skills/jev-decision-runtime/SKILL.md` 的 `## 路由` 段之后追加：

```markdown
## 对比验收

`scripts/compare_cli.py` 把 Jev 侧 trace 与用户手工提供的普通 LLM 用用量合并成一份并排报告。

- **不读 CC Switch 数据库。** 它的 schema 不是稳定公共契约，读它会把这个插件绑到别人的私有存储与个人环境路径上。LLM 侧的 token 与成本由用户按 `references/comparison-procedure.md` 手工读出并填入。
- **两次运行只有在六个 case identity 字段全一致时才比较**，否则报告标 `comparable: false` 并逐条列出差异。
- **默认不写文件**，只在对话里展示。只有用户明确要求导出并给出绝对输出目录时，才通过 `session-export` 的能力写出报告；目录必须在插件目录之外。
- **校准状态不由本技能改变。** 报告只给建议；`experimental` → `calibrated` 是需要人工复核的决定。
- `fallback_used: true` 的样本与凭证等待期间的耗时不计入性能比较。
```

在 `skills/session-export/SKILL.md` 的 `## Boundary` 列表之后追加：

```markdown
路径对比报告也通过本技能写出：`jev-decision-runtime/scripts/compare_cli.py` 复用同一个绝对路径与插件外两个守卫。除报告本身外，它不写任何其它内容。
```

在 `docs/ENFORCEMENT.md` 矩阵末尾追加：

```markdown
| 比较的六个 identity 字段必须全一致 | `runtime_required` | `skills/jev-decision-runtime/scripts/comparison.py` | `comparability()` 逐字段比对，任一不同即 `comparable: false` 并列出原因。 |
| 不读 CC Switch 数据库 | `runtime_required` | `skills/jev-decision-runtime/scripts/comparison.py` | `load_llm_usage()` 只接受 `source` 为手工条目的 JSON；写下数据库来源路径即被拒绝。 |
| 报告导出目录 | `runtime_required` | `skills/jev-decision-runtime/scripts/compare_cli.py` | 必须是绝对路径且不在插件目录内，否则拒绝写出。 |
| 命令行凭证参数拒绝 | `runtime_required` | 同 `jev_runner.py` 的 `reject_credential_arguments` | 参数解析前拒绝，且不回显参数值。 |
| 凭证等待与路径切换不计入性能样本 | `script_checked` | `skills/jev-decision-runtime/scripts/comparison.py` | `UNMEASURED_STATUSES` 的 trace 被排除在耗时与成本之外，但 `fallback_used` 的识别仍依赖 trace 的真实取值。 |
| 只有用户明确要求才导出 | `prompt_only` | 技能指令 | 直接调用 CLI 并给 `--output-dir` 不会被阻止。 |
| 校准状态只由人更改 | `prompt_only` | `references/comparison-procedure.md` + 技能指令 | 脚本只给建议，无法阻止有人手改策略文件。 |
```

在 `docs/CHANGELOG.md` 的 `## [Unreleased]` → `### Added` 末尾追加：

```markdown
- 两条执行路径的并排对比报告：按 case identity 校验可比性、合并 Jev trace 与手工录入的普通 LLM 用量、给出校准建议，且仅在显式要求时导出。
```

在 `plugins/picturebook-screenwriter/README.md` 的 `## 已支持` 列表末尾追加：

```markdown
- 路径对比报告：并排比较普通 LLM 与 Jev 辅助的耗时、token、成本、升级率与分歧，仅在用户明确要求时导出
```

- [ ] **Step 6: 写端到端验收**

创建 `plugins/picturebook-screenwriter/tests/test_comparison_integration.py`：

```python
"""Phase 4 integration: the comparison report and its export boundary."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
for _relative in ("jev-decision-runtime", "knowledge-loader", "pre_output-baseline",
                  "session-export"):
    sys.path.insert(0, str(ROOT / "skills" / _relative / "scripts"))

from compare_cli import main as compare_main  # noqa: E402
from comparison import COMPARISON_SCHEMA, build_case_report, report_to_markdown  # noqa: E402
from decision_contract import default_policy_path, load_policy  # noqa: E402
from jev_runner import write_atomic  # noqa: E402

CASE_ID = "sha256:" + "0" * 64


def identity():
    return {
        "benchmark_case_id": CASE_ID,
        "input_revision_vector_sha256": "a" * 64,
        "draft_sha256": "b" * 64,
        "policy_version": "text-quality-prefilter-v1",
        "rule_version": "text-quality-prefilter-rules-v1",
        "artifact_params": {"age_band": "3-6", "genre": "温情", "page_count": 32},
    }


def trace(operation, **overrides):
    payload = {
        "schema_version": "pb-decision-trace-v1",
        "run_id": "20260923-integration-0001",
        "benchmark_case_id": CASE_ID,
        "execution_mode": "jev_assisted",
        "operation": operation,
        "started_at": "2026-09-23T10:30:00.000+08:00",
        "finished_at": "2026-09-23T10:30:00.400+08:00",
        "elapsed_ms": 400,
        "input_sha256": "a" * 64,
        "item_count": 32,
        "question_count": 160,
        "screened_clear_count": 21,
        "escalated_count": 11,
        "request_count": 4,
        "input_tokens": 8200,
        "output_tokens": 640,
        "estimated_cost_usd": "0.000344400000",
        "price_usd_per_million_input_tokens": "0.042",
        "price_snapshot_date": "2026-09-23",
        "resolved_model": "jev-1.13.0",
        "status": "succeeded",
        "fallback_used": False,
        "error_class": None,
    }
    payload.update(overrides)
    return payload


def llm_usage(**overrides):
    payload = {
        "identity": identity(),
        "model_label": "gpt-5-codex",
        "source": "cc-switch-manual-entry",
        "elapsed_ms": 180000,
        "request_count": 12,
        "input_tokens": 54000,
        "output_tokens": 9000,
        "cache_tokens": 12000,
        "estimated_cost_usd": "1.234500000000",
        "knowledge_items_entered": 180,
        "quality_items_entered": 160,
        "issues_found": 7,
        "misses_or_disagreements": 1,
    }
    payload.update(overrides)
    return payload


class Phase4IntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.run_dir = self.root / "run"
        write_atomic(
            self.run_dir / "jev" / "text_quality_prefilter" / "trace" / "0001.json",
            trace("text_quality_prefilter"),
        )
        write_atomic(
            self.run_dir / "jev" / "knowledge_relevance" / "trace" / "0001.json",
            trace("knowledge_relevance", input_tokens=4000, output_tokens=300,
                  request_count=2, elapsed_ms=200, estimated_cost_usd="0.000168000000"),
        )
        self.usage = self.root / "llm-usage.json"
        self.usage.write_text(json.dumps(llm_usage(), ensure_ascii=False),
                              encoding="utf-8")
        self.plugin = self.root / "plugin"
        self.plugin.mkdir()
        self.policy = load_policy(default_policy_path())

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_report_sums_both_jev_traces(self):
        report = build_case_report(run_dir=self.run_dir, llm_usage_path=self.usage,
                                   policy=self.policy)
        self.assertTrue(report["comparable"])
        self.assertEqual(report["jev_assisted"]["input_tokens"], 12200)
        self.assertEqual(report["jev_assisted"]["request_count"], 6)
        self.assertEqual(report["jev_assisted"]["elapsed_ms"], 600)
        self.assertEqual(report["jev_assisted"]["estimated_cost_usd"],
                         "0.000512400000")

    def test_the_llm_side_comes_from_the_manual_entry(self):
        report = build_case_report(run_dir=self.run_dir, llm_usage_path=self.usage,
                                   policy=self.policy)
        self.assertEqual(report["llm"]["input_tokens"], 54000)
        self.assertEqual(report["llm"]["cache_tokens"], 12000)

    def test_a_shared_case_id_makes_the_runs_comparable(self):
        report = build_case_report(run_dir=self.run_dir, llm_usage_path=self.usage,
                                   policy=self.policy)
        self.assertEqual(report["comparability_reasons"], [])

    def test_a_different_policy_version_makes_them_incomparable(self):
        payload = llm_usage()
        payload["identity"]["policy_version"] = "text-quality-prefilter-v2"
        self.usage.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        report = build_case_report(run_dir=self.run_dir, llm_usage_path=self.usage,
                                   policy=self.policy)
        self.assertFalse(report["comparable"])
        self.assertTrue(any("policy_version" in reason
                            for reason in report["comparability_reasons"]))

    def test_the_markdown_warns_loudly_when_runs_are_not_comparable(self):
        payload = llm_usage()
        payload["identity"]["draft_sha256"] = "z" * 64
        self.usage.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        text = report_to_markdown(build_case_report(
            run_dir=self.run_dir, llm_usage_path=self.usage, policy=self.policy
        ))
        self.assertIn("不可比较", text)

    def test_a_waiting_trace_is_excluded_from_the_speed_sample(self):
        write_atomic(
            self.run_dir / "jev" / "knowledge_relevance" / "trace" / "0002.json",
            trace("knowledge_relevance", status="waiting_for_jev_key",
                  input_tokens=None, output_tokens=None, estimated_cost_usd=None,
                  elapsed_ms=600_000, request_count=0),
        )
        report = build_case_report(run_dir=self.run_dir, llm_usage_path=self.usage,
                                   policy=self.policy)
        self.assertEqual(report["jev_assisted"]["elapsed_ms"], 600)

    def test_the_calibration_suggestion_never_flips_the_status_itself(self):
        report = build_case_report(run_dir=self.run_dir, llm_usage_path=self.usage,
                                   policy=self.policy)
        for entry in report["calibration"]:
            with self.subTest(operation=entry["operation"]):
                self.assertEqual(entry["current"], "experimental")
                self.assertIn(entry["suggestion"],
                              ("keep_experimental", "review_thresholds",
                               "eligible_for_calibrated"))
        self.assertEqual(
            self.policy["operations"]["text_quality_prefilter"]["calibration_status"],
            "experimental",
        )

    def test_printing_only_writes_nothing(self):
        code, out, _ = _run_cli([
            "--run-dir", str(self.run_dir), "--llm-usage", str(self.usage),
            "--policy", str(default_policy_path()),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["schema_version"], COMPARISON_SCHEMA)
        self.assertFalse(list(self.root.rglob("*-audit")))

    def test_exporting_writes_the_report_outside_the_plugin(self):
        exports = self.root / "exports"
        exports.mkdir()
        code, _, _ = _run_cli([
            "--run-dir", str(self.run_dir), "--llm-usage", str(self.usage),
            "--output-dir", str(exports), "--plugin-root", str(self.plugin),
            "--policy", str(default_policy_path()),
        ])
        self.assertEqual(code, 0)
        bundle = exports / "path-comparison-audit"
        self.assertTrue((bundle / "comparison.json").is_file())
        self.assertTrue((bundle / "comparison.md").is_file())
        self.assertIn("路径对比",
                      (bundle / "comparison.md").read_text(encoding="utf-8"))

    def test_exporting_into_the_plugin_is_refused(self):
        code, _, err = _run_cli([
            "--run-dir", str(self.run_dir), "--llm-usage", str(self.usage),
            "--output-dir", str(self.plugin), "--plugin-root", str(self.plugin),
            "--policy", str(default_policy_path()),
        ])
        self.assertEqual(code, 1)
        self.assertIn("outside the plugin", err)

    def test_a_database_sourced_usage_entry_is_refused(self):
        payload = llm_usage(source="cc-switch-sqlite:/home/u/.cc-switch.db")
        self.usage.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        code, _, err = _run_cli([
            "--run-dir", str(self.run_dir), "--llm-usage", str(self.usage),
            "--policy", str(default_policy_path()),
        ])
        self.assertEqual(code, 1)
        self.assertIn("manual", err)


def _run_cli(argv):
    import io

    stdout, stderr = io.StringIO(), io.StringIO()
    code = compare_main(argv, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 7: 运行端到端与聚合校验**

Run: `python plugins/picturebook-screenwriter/tests/test_comparison_integration.py`
Expected: PASS

Run: `python scripts/run_plugin_tests.py`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add plugins/picturebook-screenwriter/skills/jev-decision-runtime plugins/picturebook-screenwriter/skills/session-export/SKILL.md plugins/picturebook-screenwriter/config/plugin-contract.json plugins/picturebook-screenwriter/README.md plugins/picturebook-screenwriter/tests
git add -f docs/ENFORCEMENT.md docs/CHANGELOG.md
git status
git commit -m "docs(jev): document the comparison procedure and pin its export boundary" -m "Records the manual CC Switch reading step, the six-field comparability gate, and the human-only calibration decision, with an end-to-end acceptance test." -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## 四个阶段完成后的状态

Jev 辅助决策层按 spec §16 的十三条验收标准落地：

1. 顶层工作流第一响应必定询问执行选择（Phase 1，Task 11）。
2. 选普通 LLM 后无行为回归，也不探测 Jev key（Phase 1）。
3. 只有两个 operation 调 Jev，生成与终审仍归普通 LLM（Phase 2、Phase 3）。
4. required 权威知识不可能被过滤（Phase 2 的 `required_marking` + `recall`，Phase 2 集成测试）。
5. Jev/API/解析失败不可能产生 PASS、clear 或知识删除（Phase 3 的 `screening` + 三个阶段的集成测试）。
6. 全部项目红线都被覆盖，代理命中与权威判断分层（Phase 3 Task 1、Task 3、Task 6）。
7. 每个 operation 产出可审计的模型版本、策略版本、概率、路由、时间、usage 与成本（Phase 1 `telemetry` + Phase 2/3 的 routes）。
8. 同一 `benchmark_case_id` 可并排比较（Phase 4）。
9. trace 与错误输出不含 key、Authorization、完整正文或图片数据（Phase 1 断言，Phase 4 导出后复验）。
10. 缺 key 时进入可恢复等待并从校验过的恢复点续跑（Phase 1 Task 8）。
11. 403、来源变化与结果未知各有独立状态（Phase 1 Task 6/8/9）。
12. 没有全局 `typesafe-ai` skill 也能独立运行（Phase 1 全程不依赖它）。
13. 全部既有离线测试通过，新增测试覆盖成功、灰区、失败、凭证恢复与显式切换（四个阶段的聚合校验）。

`docs/ENFORCEMENT.md` 里每个门都有如实分级，`docs/CHANGELOG.md` 记录了缺陷修复与新增能力。

**仍未实现：** spec §17 的后续 operation（`collision_disambiguation`、`illustration_risk_prefilter`、`staging_evidence_check`、`revision_impact_classification`）。每一个都必须独立完成问题设计、中文样本、阈值校准与验收，不能因为运行器已存在就默认启用。

---

## Self-Review

**1. Spec coverage（spec §15 Phase 4 的每一条）**

| spec 要求 | 覆盖任务 |
|---|---|
| 同一 benchmark case 分别运行普通 LLM 与 Jev 辅助 | Task 1（case identity 闸） |
| 合并 Jev trace 与用户从 CC Switch 获得的 LLM usage | Task 2 |
| 输出速度、成本、升级率和分歧报告 | Task 1（渲染）、Task 2（比率与建议） |
| 逐 operation 决定保持 experimental、调整阈值或标记 calibrated | Task 2（`calibration_suggestions`）、Task 4（人工复核条件） |

spec §10.2 的"不直接访问 CC Switch 数据库"由 Task 2 的 `load_llm_usage` 强制（`source` 非手工条目即拒绝），Task 4 的集成测试断言写下数据库路径会被拒绝；§10.3 的五个可比字段对应 Task 1 的 `IDENTITY_FIELDS`（spec 写"目标年龄、体裁和页数参数"为一项，这里合并为 `artifact_params` 一整个对象，逐字段比对）；§16 的第 8、9 条由 Task 1 与 Task 4 覆盖。

**2. Placeholder scan**

无 `TBD`/`TODO`。Task 2 的 Step 3 有一处"删掉未使用的 `field`"的收尾说明——是机械清理，已在最终代码块里给出正确 import 行。

**3. Type consistency**

- `IDENTITY_FIELDS` 是 Task 1 定义的六字段元组，被 `validate_identity`、`comparability`、`identity_digest`、`load_llm_usage` 与 Task 4 的契约断言共同引用；任何一处增删都会同时影响五处，这正是要的
- `CaseMetrics` 的 12 个字段在 Task 1 定义，Task 2 的 `jev_metrics` 与 `load_llm_usage` 都构造它，`report_to_markdown` 用 `METRIC_NAMES` 渲染其中的 10 个（`path` 与 `notes` 不进入对比表）
- `build_report` 的 `calibration` 参数接收 `calibration_suggestions(...)` 的返回值（`tuple[dict, ...]`），其元素键为 `operation`/`current`/`suggestion`/`reason`，与 `report_to_markdown` 读取的键一致
- `jev_metrics` 的 `notes` 形如 `("escalated=11", "screened_clear=21", "runtime_failure=0")`，`calibration_suggestions` 的 `_note_value` 按同一 `key=value` 约定解析
- `compare_cli.main(argv, stdout, stderr)` 的三参签名与 Phase 1–3 的 CLI 一致；`require_explicit_output_dir` 的错误文案与 `export_session` 的既有措辞对齐（`absolute path` / `outside the plugin`）
- Task 4 的契约断言读取 `contract["jev_comparison"]` 的五个键，与 Task 4 Step 3 写入的块逐一对应

**4. Review Focus**

开头的五条都落成了会先失败的测试（全部在 Task 2，因为合并步骤是这一阶段唯一容易产生静默失真的地方）：同一 operation 的多次 attempt 只按终态计判定（`test_two_attempts_of_one_operation_count_their_verdicts_once`）；`fallback_used` 的运行不进 Jev 样本（`test_a_fallback_run_is_not_a_jev_sample`）；别的 case 的 trace 不计入本次数值（`test_traces_from_another_case_are_not_summed_in`）；手写的数字成本被拒绝并给出加引号提示（`test_a_numeric_cost_is_refused_with_a_quoting_hint`）；报告写明 Jev 侧跑过的 operation（`test_the_report_names_the_operations_the_jev_side_ran`）。

---

# 附录：实现差异与裁决记录（实施完成后补记）

本计划在实施过程中被逐任务审查与整支终审推翻过若干处示例代码与承诺。以下差异以**已提交的代码与其测试**为准；计划正文里对应的片段已过时。

## Task 1（资格闸与报告模型）

- `describe_metric` 的描述是**裸的**（`"8000 → 4000 (0.50×)"`，比值是 `jev/llm`），指标名由 `report_to_markdown` 作为行标签补上；计划代码块里的 `f"{name}: …"` 前缀形式与其自带测试矛盾，以测试为准。副作用：`name` 形参在函数体内不再使用（签名由计划钉死，接受为 smell）。
- `comparability` 对**任一字段在任一侧缺失或为 `null`** 都记一条指明字段与侧别的 reason（计划用 `.get()` 相等比较，会让"两侧都缺同一字段"被判定为可比较）。
- `identity_digest` 只摘要 `IDENTITY_FIELDS`，缺闸位字段时 `ValueError` 指名（不是摘要整个 mapping）。
- Markdown 表格里的缺失值渲染成 `未测得（普通 LLM）` / `未测得（Jev 辅助）`，不打印裸 `None`。

## Task 2（合并 trace 与手工用量）

- 未测得的成本保持 `None`（不是 `"0.000000000000"`）：`outcome_unknown` 表示"已发出、可能已计费"，折成 0 等于把没人测过的账单当成测过的。
- Jev 侧 identity 只有 `benchmark_case_id`、`policy_version` 能从运行目录核验；其余四字段从普通 LLM 侧的声明复制，报告用 `identity_attestation` 标为"仅凭人工声明"。计划里靠扰动 `draft_sha256` 制造不可比较的用例因此不成立，已改为扰动 `benchmark_case_id`。
- `load_traces` 先剔除**从未派发的 attempt**（等待状态）再取终态 attempt。
- **trace 的 `escalated_count` / `screened_clear_count` 现在真的有生产者**：共享 runner 新增 `verdicts=` 钩子，两个 operation 在派发时把自己的路由结果写进 trace（计划假设这两项已由 Phase 1–3 提供，实际是恒 0 的占位）。`resume` 路径仍不传钩子，因此由 resume 而来的批次**不带判定计数**——报告用 `traces_without_verdicts` 点名这类 trace 并**收回** `eligible_for_calibrated`/`review_thresholds`（fail-closed：宁可收回建议，也不给出错的建议）。
- 校准建议**逐 operation** 用自己的计数（计划代码块用 run 级混合比率，会把"阈值过松"的 operation 反向建议为"可转 calibrated"）；本次未测量的 operation 不出建议。
- `knowledge_items_entered` / `quality_items_entered` 各自取自己 operation 的升级数并驱动两行（计划的 `max(item_counts)` 让两行恒相等，且底层是"引用到的权威页数"而非"进入普通 LLM 的项数"）。
- 去重与分组按 `run_id`；一个目录里出现多个 `run_id` 会判 `comparable: false` 并列出，不再静默相加。
- 声明 case id 无法从运行目录核验时（目录里只有别的 case 的 trace、或唯一 trace 的 case id 为 `null`、或声明的 case 不在目录里任何 trace 中）**补 reason**，不再报 `comparable: true`。

## Task 3（CLI 与导出门）

- `--plugin-root` 是**必需**参数（计划示例命令行未写，照抄会失败）；导出产物固定在 `<output-dir>/path-comparison-audit`。
- 输出目录闸同时拒绝落在**脚本自身插件根**内的目标（不只调用方声明的那个根），并把**真**插件根交给 `session-export` 作为纵深防御。
- parser 的 usage/error/exit 消息走**注入的** `stdout`/`stderr`；目录校验前置成 pre-flight（读策略/算报告之前）。
- `exported_to` 同时进 stdout 与落盘产物（含 `comparison.md` 页脚）。

## Task 4（文档与验收）

- ENFORCEMENT 的 case identity 一行**拆成两行**：两个可核验字段 `runtime_required` + 四个仅凭人工声明 `prompt_only`。计划里"六个字段全一致 `runtime_required`"高估了运行时的核验范围。
- 凭据行的措辞不再承诺"永不回显"：命中旗标形状闸者在解析前被拒，其它未识别参数由 argparse 报错并**会**回显，因此凭据绝不能放在命令行。
- 来源表新增一行披露**升级项回流普通 LLM 的请求数/token/成本**（该行当时写的是"没有槽位"；槽位已在收尾补记里落地，见文末）；`cache_tokens` 在无可测 trace 时是 `null` 而不是 `0`。
- `resume` 不传路由这一开放项在 procedure 里如实写明。

## 尚未实现（保持无主）

- `calibrate.py` 需要的 `outcomes.json` 仍无产出者；`eligible_for_calibrated` 目前只是"值得人工试算"的信号。
- `resume` 路径不传 operation 的路由（彻底做法需要 runner 或 operation 侧的注册表）。
- 入口技能 `skills/picturebook-screenwriter/SKILL.md` 不提对比路径，发现性只靠 runtime skill 与 procedure。
- Phase 3 的宽窗重复计费与红线回退噪声仍只影响文档层面（未改代码）。

## 收尾补记：成本槽位（2026-09-28）

上表"尚未实现"里 spec §10.3 的那条已落地：`comparison.py` 现在有 `llm_*` 六个槽位（升级项回流普通 LLM 的耗时、请求数、input/output/cache token 与成本）与两个总账字段（`total_elapsed_ms`、`total_estimated_cost_usd`）。手工条目新增可选的 `upgraded_llm_usage` 块提供回流那段；块里拼错的键、非对象的块、写成 JSON 数字的成本都会被拒绝。任一半未测得时总账保持 `null` 并写明原因，不会退化成预筛那一半的账单。同一波还按审查结论把 `references/comparison-procedure.md` 里被冲突升级修复证伪的等式改成 `升级包大小 = escalated + runtime_failure + summary.escalated_by_proxy_conflict`。

## 提交署名

- 本阶段提交沿用 `Co-Authored-By: Claude Sonnet 5 <…>`（计划约定），实际作者是 Codex；与更早的 `Co-Authored-By: Codex <noreply@openai.com>` 提交并存，不改写历史。
