"""Representative creation workflows over the real creative kernel.

Deterministic samples execute the registered content validators and aggregate
a real quality-gate report; declarative samples keep their skill-layer
evaluation. Rendering export previews happens in memory only: this module
never writes files.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import shortdrama_checks
import tv_longform_checks
from creative_run_builder import CreativeRunRequest, build_creative_run
from export_run import ExportRunnerError, render_export
from quality_gate_contract import (
    QualityCheckResult,
    QualityGateReport,
    build_quality_gate_report,
)
from screenwriter_context import context_from_dict
from type_registry import (
    QualityRuleDescriptor,
    load_type_registry,
    resolve_artifact,
    resolve_type_pack,
)


EXECUTIONS = ("deterministic", "declarative")
VALIDATOR_EXECUTORS = {
    "shortdrama-checks": shortdrama_checks.validate_shortdrama_rules,
    "tv-longform-checks": tv_longform_checks.validate_tv_longform_rules,
}
_BASE_REQUIRED = {
    "medium", "execution", "context", "target_artifact", "pipeline_stages",
    "workflow_inputs", "knowledge_scope", "quality_rules", "exports",
    "failure_reason",
}
_RULE_FIELDS = {
    "check_id", "artifact_ids", "stage_id", "blocking_policy", "validator",
}
_EXPECTED_FIELDS = {"confirmation_ready", "blocker_ids", "user_confirmation_ids"}


class SampleWorkflowError(ValueError):
    """Raised when a representative sample is malformed or drifts from its pack."""


@dataclass(frozen=True)
class SampleContract:
    medium: str
    execution: str
    context: Mapping[str, Any]
    target_artifact: str
    pipeline_stages: tuple[str, ...]
    workflow_inputs: tuple[Mapping[str, Any], ...]
    knowledge_scope: Mapping[str, Any]
    quality_rules: tuple[Mapping[str, Any], ...]
    exports: tuple[Mapping[str, Any], ...]
    expected: Mapping[str, Any] | None
    expected_results: tuple[Mapping[str, Any], ...]
    failure_reason: str | None


@dataclass(frozen=True)
class SampleWorkflowResult:
    medium: str
    execution: str
    pipeline_stages: tuple[str, ...]
    report: QualityGateReport
    confirmation_ready: bool
    failure_reason: str | None
    export_previews: Mapping[str, str]


def load_sample(path: Path) -> SampleContract:
    """Load and validate one representative sample fixture."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SampleWorkflowError(f"无法读取样例：{path}") from error
    if not isinstance(payload, Mapping):
        raise SampleWorkflowError(f"样例必须是对象：{path}")
    execution = payload.get("execution")
    if execution not in EXECUTIONS:
        raise SampleWorkflowError(f"样例 execution 非法：{execution!r}")
    required = set(_BASE_REQUIRED)
    required.add("expected" if execution == "deterministic" else "expected_results")
    allowed = set(required)
    if execution == "declarative":
        allowed.add("expected")
    if not required <= set(payload) or not set(payload) <= allowed:
        raise SampleWorkflowError(
            f"样例字段与 execution={execution} 不匹配：{path}"
        )
    stages = payload["pipeline_stages"]
    if (not isinstance(stages, list) or not stages
            or not all(isinstance(item, str) and item.strip() for item in stages)):
        raise SampleWorkflowError("pipeline_stages 必须是非空字符串数组")
    inputs = payload["workflow_inputs"]
    if not isinstance(inputs, list):
        raise SampleWorkflowError("workflow_inputs 必须是数组")
    for item in inputs:
        if (not isinstance(item, Mapping)
                or not isinstance(item.get("artifact_id"), str)
                or not item["artifact_id"].strip()):
            raise SampleWorkflowError("workflow_inputs 条目必须带 artifact_id")
    rules = payload["quality_rules"]
    if not isinstance(rules, list):
        raise SampleWorkflowError("quality_rules 必须是数组")
    for rule in rules:
        if not isinstance(rule, Mapping) or set(rule) != _RULE_FIELDS:
            raise SampleWorkflowError("quality_rules 条目字段非法")
    exports = payload["exports"]
    if not isinstance(exports, list):
        raise SampleWorkflowError("exports 必须是数组")
    for entry in exports:
        if (not isinstance(entry, Mapping)
                or set(entry) != {"exporter_id", "user_params"}
                or not isinstance(entry["user_params"], Mapping)):
            raise SampleWorkflowError("exports 条目字段非法")
    expected = payload.get("expected")
    if expected is not None:
        if not isinstance(expected, Mapping) or set(expected) != _EXPECTED_FIELDS:
            raise SampleWorkflowError("expected 字段非法")
        for key in ("blocker_ids", "user_confirmation_ids"):
            if not isinstance(expected[key], list):
                raise SampleWorkflowError(f"expected.{key} 必须是数组")
        expected = dict(expected)
    expected_results: tuple[Mapping[str, Any], ...] = ()
    if execution == "declarative":
        raw_results = payload["expected_results"]
        if not isinstance(raw_results, list):
            raise SampleWorkflowError("expected_results 必须是数组")
        for item in raw_results:
            if not isinstance(item, Mapping) or set(item) != {"check_id", "status"}:
                raise SampleWorkflowError("expected_results 条目字段非法")
        expected_results = tuple(dict(item) for item in raw_results)
    return SampleContract(
        medium=str(payload["medium"]),
        execution=execution,
        context=dict(payload["context"]),
        target_artifact=str(payload["target_artifact"]),
        pipeline_stages=tuple(stages),
        workflow_inputs=tuple(dict(item) for item in inputs),
        knowledge_scope=dict(payload["knowledge_scope"]),
        quality_rules=tuple(dict(rule) for rule in rules),
        exports=tuple(
            {"exporter_id": entry["exporter_id"],
             "user_params": dict(entry["user_params"])}
            for entry in exports
        ),
        expected=expected,
        expected_results=expected_results,
        failure_reason=payload["failure_reason"],
    )


def evaluate_sample(sample: SampleContract) -> QualityGateReport:
    """Declarative evaluation for samples whose validators live in skills."""
    if sample.execution != "declarative":
        raise SampleWorkflowError(
            "evaluate_sample 只服务 declarative 样例；确定性样例必须执行真实校验器"
        )
    expected = {item["check_id"]: item["status"] for item in sample.expected_results}
    descriptors = {
        rule["check_id"]: QualityRuleDescriptor(
            check_id=rule["check_id"],
            artifact_ids=tuple(rule["artifact_ids"]),
            stage_id=rule["stage_id"],
            blocking_policy=rule["blocking_policy"],
            validator=rule["validator"],
        )
        for rule in sample.quality_rules
    }
    if set(expected) != set(descriptors):
        raise SampleWorkflowError("declarative 样例必须覆盖全部声明规则的预期状态")
    results = [
        QualityCheckResult(
            check_id=rule["check_id"],
            artifact_id=sample.target_artifact,
            stage_id=rule["stage_id"],
            blocking_policy=rule["blocking_policy"],
            status=expected[rule["check_id"]],
            evidence={
                "source": "fixture",
                "execution": "fixture",
                "knowledge_scope": dict(sample.knowledge_scope),
            },
        )
        for rule in sorted(sample.quality_rules, key=lambda item: item["check_id"])
    ]
    return build_quality_gate_report(
        descriptors.values(),
        results,
        gate_id=f"{sample.medium}-sample",
        scope="sample",
    )


def run_sample_workflow(
    sample: SampleContract, sample_path: Path | None = None,
) -> SampleWorkflowResult:
    """Validate the declared pipeline, execute the sample, preview exports."""
    pack = resolve_type_pack(load_type_registry(), sample.medium)
    _check_rule_drift(sample, pack)
    _check_pipeline(sample, pack)
    if sample.execution == "deterministic":
        report = _execute_deterministic(sample, pack)
    else:
        report = evaluate_sample(sample)
    if sample.expected is not None:
        _check_expectations(sample, report)
    previews = _export_previews(sample)
    return SampleWorkflowResult(
        medium=sample.medium,
        execution=sample.execution,
        pipeline_stages=sample.pipeline_stages,
        report=report,
        confirmation_ready=report.confirmation_ready,
        failure_reason=sample.failure_reason,
        export_previews=previews,
    )


def _canonical_rule(rule) -> dict:
    if isinstance(rule, Mapping):
        return {
            "check_id": rule["check_id"],
            "artifact_ids": list(rule["artifact_ids"]),
            "stage_id": rule["stage_id"],
            "blocking_policy": rule["blocking_policy"],
            "validator": rule["validator"],
        }
    return {
        "check_id": rule.check_id,
        "artifact_ids": list(rule.artifact_ids),
        "stage_id": rule.stage_id,
        "blocking_policy": rule.blocking_policy,
        "validator": rule.validator,
    }


def _check_rule_drift(sample: SampleContract, pack) -> None:
    pack_rules = sorted(
        (
            _canonical_rule(rule) for rule in pack.quality_rules
            if sample.target_artifact in rule.artifact_ids
        ),
        key=lambda rule: rule["check_id"],
    )
    fixture_rules = sorted(
        (_canonical_rule(rule) for rule in sample.quality_rules),
        key=lambda rule: rule["check_id"],
    )
    if pack_rules != fixture_rules:
        raise SampleWorkflowError(
            f"样例规则与当前 {sample.medium} 类型包漂移：{sample.target_artifact}"
        )


def _check_pipeline(sample: SampleContract, pack) -> None:
    stage_map = {stage.stage_id: stage for stage in pack.stages}
    unknown = [
        stage_id for stage_id in sample.pipeline_stages
        if stage_id not in stage_map
    ]
    if unknown:
        raise SampleWorkflowError(f"pipeline_stages 引用未知阶段：{unknown}")
    seen: set[str] = set()
    for stage_id in sample.pipeline_stages:
        missing = [
            dep for dep in stage_map[stage_id].depends_on if dep not in seen
        ]
        if missing:
            raise SampleWorkflowError(
                f"阶段 {stage_id!r} 的依赖未在链中先行出现：{missing}"
            )
        seen.add(stage_id)
    if sample.pipeline_stages[-1] != "confirmation_gate":
        raise SampleWorkflowError("代表性阶段链必须以 confirmation_gate 结束")
    producers = [
        stage.stage_id for stage in pack.stages
        if sample.target_artifact in stage.produces_artifact_ids
    ]
    if not producers:
        raise SampleWorkflowError(
            f"目标产物 {sample.target_artifact!r} 不由任何阶段产出"
        )
    if not any(stage_id in seen for stage_id in producers):
        raise SampleWorkflowError(
            f"目标产物 {sample.target_artifact!r} 的产出阶段不在阶段链中"
        )
    artifact = resolve_artifact(pack, sample.target_artifact)
    if artifact.origin != "workflow_output":
        raise SampleWorkflowError(
            f"目标产物 {sample.target_artifact!r} 不是创作类产物"
        )


def _artifacts_by_id(sample: SampleContract) -> dict:
    artifacts = {}
    for payload in sample.workflow_inputs:
        artifacts[str(payload["artifact_id"])] = payload
    return artifacts


def _execute_deterministic(sample: SampleContract, pack) -> QualityGateReport:
    context = context_from_dict(dict(sample.context))
    try:
        build_creative_run(CreativeRunRequest(
            type_pack=pack,
            context=context,
            intent="creation",
            target=sample.target_artifact,
            run_id=f"sample-{sample.medium}",
            project_root=str(REPO_ROOT),
        ))
    except Exception as error:
        raise SampleWorkflowError(
            f"样例无法构建 run manifest：{error}"
        ) from error
    artifacts = _artifacts_by_id(sample)
    target = artifacts.get(sample.target_artifact)
    if target is None:
        raise SampleWorkflowError(
            f"workflow_inputs 缺少目标产物：{sample.target_artifact}"
        )
    descriptors = []
    results = []
    for rule in sorted(sample.quality_rules, key=lambda item: item["check_id"]):
        executor = VALIDATOR_EXECUTORS.get(rule["validator"])
        if executor is None:
            raise SampleWorkflowError(
                f"规则 {rule['check_id']!r} 没有可执行校验器："
                f"{rule['validator']!r}"
            )
        result = executor(
            rule["check_id"], target, context, references=artifacts,
        )
        results.append(replace(result, evidence={
            **dict(result.evidence),
            "execution": "validator",
        }))
        descriptors.append(QualityRuleDescriptor(
            check_id=rule["check_id"],
            artifact_ids=tuple(rule["artifact_ids"]),
            stage_id=rule["stage_id"],
            blocking_policy=rule["blocking_policy"],
            validator=rule["validator"],
        ))
    return build_quality_gate_report(
        descriptors,
        results,
        gate_id=f"{sample.medium}-sample",
        scope="sample",
    )


def _check_expectations(sample: SampleContract, report: QualityGateReport) -> None:
    expected = sample.expected or {}
    if bool(expected.get("confirmation_ready")) != report.confirmation_ready:
        raise SampleWorkflowError(
            f"{sample.medium} 样例确认状态与预期不符："
            f"实际 {report.confirmation_ready}"
        )
    blocker_ids = sorted(item.check_id for item in report.blockers)
    if list(expected.get("blocker_ids", [])) != blocker_ids:
        raise SampleWorkflowError(
            f"{sample.medium} 样例阻断项与预期不符：{blocker_ids}"
        )
    confirmation_ids = sorted(
        item.check_id for item in report.requires_user_confirmation
    )
    if list(expected.get("user_confirmation_ids", [])) != confirmation_ids:
        raise SampleWorkflowError(
            f"{sample.medium} 样例确认风险项与预期不符：{confirmation_ids}"
        )


def _export_previews(sample: SampleContract) -> Mapping[str, str]:
    previews = {}
    if not sample.exports:
        return previews
    payloads = _artifacts_by_id(sample)
    for entry in sample.exports:
        exporter_id = entry["exporter_id"]
        try:
            previews[exporter_id] = render_export(
                exporter_id, payloads, dict(entry["user_params"]),
            )
        except ExportRunnerError as error:
            raise SampleWorkflowError(
                f"导出预览失败：{exporter_id}: {error}"
            ) from error
    return previews
