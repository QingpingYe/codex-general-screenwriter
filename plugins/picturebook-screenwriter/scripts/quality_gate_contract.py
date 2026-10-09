"""Structured quality-gate report aggregation.

This module validates and aggregates quality-check results. It deliberately
does not execute validators, read files, or write output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from type_registry import (
    QualityRuleDescriptor, TypeRegistryError,
)


RESULT_STATUSES = {"pass", "warn", "fail", "skipped", "unknown"}
RESULT_FIELDS = {
    "check_id", "artifact_id", "stage_id", "blocking_policy", "status",
    "message", "user_accepted", "evidence",
}


class QualityGateContractError(ValueError):
    """Raised when check results do not match the declared quality contract."""


@dataclass(frozen=True)
class QualityCheckResult:
    check_id: str
    artifact_id: str
    stage_id: str
    blocking_policy: str
    status: str
    message: str = ""
    user_accepted: bool = False
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityGateReport:
    gate_id: str
    scope: str
    checks: tuple[QualityCheckResult, ...]
    blockers: tuple[QualityCheckResult, ...]
    requires_user_confirmation: tuple[QualityCheckResult, ...]
    warnings: tuple[QualityCheckResult, ...]
    passed: bool
    confirmation_ready: bool


def _validated_result(raw: Any, rules: Mapping[str, QualityRuleDescriptor]) -> QualityCheckResult:
    if not isinstance(raw, QualityCheckResult):
        raise QualityGateContractError("quality result must be a QualityCheckResult")
    rule = rules.get(raw.check_id)
    if rule is None:
        raise QualityGateContractError(f"unknown quality result check_id: {raw.check_id!r}")
    if raw.artifact_id not in rule.artifact_ids:
        raise QualityGateContractError(
            f"quality result {raw.check_id!r} targets artifact {raw.artifact_id!r}, "
            f"which is outside {list(rule.artifact_ids)!r}"
        )
    if raw.stage_id != rule.stage_id:
        raise QualityGateContractError(
            f"quality result {raw.check_id!r} must run at {rule.stage_id!r}"
        )
    if raw.blocking_policy != rule.blocking_policy:
        raise QualityGateContractError(
            f"quality result {raw.check_id!r} must use blocking_policy "
            f"{rule.blocking_policy!r}"
        )
    if raw.status not in RESULT_STATUSES:
        raise QualityGateContractError(
            f"quality result {raw.check_id!r} has invalid status {raw.status!r}"
        )
    if not isinstance(raw.message, str):
        raise QualityGateContractError(f"quality result {raw.check_id!r} message must be text")
    if type(raw.user_accepted) is not bool:
        raise QualityGateContractError(
            f"quality result {raw.check_id!r} user_accepted must be boolean"
        )
    if raw.evidence is not None and not isinstance(raw.evidence, Mapping):
        raise QualityGateContractError(
            f"quality result {raw.check_id!r} evidence must be an object"
        )
    return raw


def build_quality_gate_report(
    rules: Iterable[QualityRuleDescriptor],
    results: Iterable[QualityCheckResult],
    *,
    gate_id: str = "quality-gate-v1",
    scope: str = "run",
) -> QualityGateReport:
    rule_map = {}
    for rule in rules:
        if rule.check_id in rule_map:
            raise TypeRegistryError(f"duplicate quality rule: {rule.check_id!r}")
        rule_map[rule.check_id] = rule

    seen = set()
    validated = []
    for raw in results:
        result = _validated_result(raw, rule_map)
        if result.check_id in seen:
            raise QualityGateContractError(f"duplicate quality result: {result.check_id!r}")
        seen.add(result.check_id)
        validated.append(result)
    missing = sorted(set(rule_map) - seen)
    if missing:
        raise QualityGateContractError(f"missing quality results: {missing!r}")

    blockers = tuple(
        item for item in validated
        if item.blocking_policy == "hard_block" and item.status == "fail"
    )
    requires_user_confirmation = tuple(
        item for item in validated
        if item.blocking_policy == "require_user_confirmation"
        and item.status == "fail"
        and item.user_accepted is not True
    )
    warnings = tuple(
        item for item in validated
        if item.blocking_policy == "advisory" and item.status in {"warn", "fail"}
    )
    passed = not blockers
    confirmation_ready = passed and not requires_user_confirmation
    return QualityGateReport(
        gate_id=gate_id,
        scope=scope,
        checks=tuple(validated),
        blockers=blockers,
        requires_user_confirmation=requires_user_confirmation,
        warnings=warnings,
        passed=passed,
        confirmation_ready=confirmation_ready,
    )


def quality_report_to_dict(report: QualityGateReport) -> dict[str, Any]:
    def result_to_dict(item: QualityCheckResult) -> dict[str, Any]:
        return {
            "check_id": item.check_id,
            "artifact_id": item.artifact_id,
            "stage_id": item.stage_id,
            "blocking_policy": item.blocking_policy,
            "status": item.status,
            "message": item.message,
            "user_accepted": item.user_accepted,
            "evidence": dict(item.evidence or {}),
        }

    return {
        "gate_id": report.gate_id,
        "scope": report.scope,
        "checks": [result_to_dict(item) for item in report.checks],
        "blockers": [result_to_dict(item) for item in report.blockers],
        "requires_user_confirmation": [
            result_to_dict(item) for item in report.requires_user_confirmation
        ],
        "warnings": [result_to_dict(item) for item in report.warnings],
        "passed": report.passed,
        "confirmation_ready": report.confirmation_ready,
    }


def quality_report_from_dict(payload: Mapping[str, Any]) -> QualityGateReport:
    if not isinstance(payload, Mapping):
        raise QualityGateContractError("quality report must be an object")
    missing = {"gate_id", "scope", "checks", "passed", "confirmation_ready"} - set(payload)
    if missing:
        raise QualityGateContractError(f"quality report missing fields: {sorted(missing)!r}")
    checks = tuple(
        QualityCheckResult(
            check_id=item["check_id"],
            artifact_id=item["artifact_id"],
            stage_id=item["stage_id"],
            blocking_policy=item["blocking_policy"],
            status=item["status"],
            message=item.get("message", ""),
            user_accepted=item.get("user_accepted", False),
            evidence=item.get("evidence", {}),
        )
        for item in payload["checks"]
    )
    return QualityGateReport(
        gate_id=payload["gate_id"],
        scope=payload["scope"],
        checks=checks,
        blockers=tuple(item for item in checks if any(
            _same_result(item, blocker) for blocker in payload.get("blockers", [])
        )),
        requires_user_confirmation=tuple(item for item in checks if any(
            _same_result(item, risk)
            for risk in payload.get("requires_user_confirmation", [])
        )),
        warnings=tuple(item for item in checks if any(
            _same_result(item, warning) for warning in payload.get("warnings", [])
        )),
        passed=payload["passed"],
        confirmation_ready=payload["confirmation_ready"],
    )


def _same_result(item: QualityCheckResult, raw: Mapping[str, Any]) -> bool:
    return (
        item.check_id == raw.get("check_id")
        and item.artifact_id == raw.get("artifact_id")
        and item.stage_id == raw.get("stage_id")
        and item.status == raw.get("status")
    )
