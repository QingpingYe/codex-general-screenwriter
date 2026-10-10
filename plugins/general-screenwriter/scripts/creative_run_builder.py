"""Build CreativeRun manifests from registered type-pack contracts."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import stage_dag
from screenwriter_context import CreativeContext, validate_context
from type_registry import (
    ArtifactDescriptor, StageContract, TypePackDescriptor, WorkflowContract,
    TypeRegistryError, assert_core_artifact_target, assert_type_pack_executable,
    resolve_workflow, resolve_workflow_artifact, validate_type_contract,
)


class CreativeRunBuilderError(ValueError):
    """Raised when a request cannot become a valid CreativeRun manifest."""


@dataclass(frozen=True)
class CreativeRunRequest:
    type_pack: TypePackDescriptor
    context: CreativeContext
    intent: str
    target: str
    run_id: str
    project_root: str
    delivery_form: str | None = None
    workflow_id: str | None = None
    workflow_inputs: list[dict] | None = None
    root_run_id: str | None = None
    revision_of_run_id: str | None = None
    revision_iteration: int | None = None
    revision_feedback: list[dict] | None = None
    source_artifact_ref: str | None = None
    skills_resolution: list[dict] | None = None
    used_user_skills: list[dict[str, str]] | None = None


def _required_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise CreativeRunBuilderError(f"{label} 必须是非空字符串")
    return value.strip()


def _resolve_target(
    pack: TypePackDescriptor, request: CreativeRunRequest,
) -> tuple[ArtifactDescriptor | None, WorkflowContract | None]:
    if request.workflow_id is not None:
        workflow = resolve_workflow(pack, request.workflow_id)
        if request.target == workflow.workflow_id:
            return None, workflow
        return resolve_workflow_artifact(workflow, request.target), workflow
    return assert_core_artifact_target(pack, request.target), None


def _validate_request(request: CreativeRunRequest) -> tuple[CreativeContext, ArtifactDescriptor | None, WorkflowContract | None]:
    if not isinstance(request, CreativeRunRequest):
        raise CreativeRunBuilderError("request must be CreativeRunRequest")
    if request.intent not in {"creation", "revision"}:
        raise CreativeRunBuilderError(f"unsupported intent: {request.intent!r}")
    _required_text(request.target, "target")
    _required_text(request.run_id, "run_id")
    _required_text(request.project_root, "project_root")
    try:
        validate_type_contract(request.type_pack)
        assert_type_pack_executable(request.type_pack)
        context = validate_context(request.context, require_project=True)
    except (TypeRegistryError, ValueError) as error:
        raise CreativeRunBuilderError(f"creative run request 无效：{error}") from error
    if context.medium_id != request.type_pack.medium_id:
        raise CreativeRunBuilderError("context.medium_id 与 type pack.medium_id 不一致")

    has_revision_fields = any((
        request.revision_of_run_id is not None,
        request.revision_iteration is not None,
        request.revision_feedback is not None,
        request.source_artifact_ref is not None,
    ))
    if request.intent == "creation":
        if has_revision_fields:
            raise CreativeRunBuilderError("creation run 不得提供 revision lineage")
        if request.root_run_id is not None and request.root_run_id != request.run_id:
            raise CreativeRunBuilderError("creation run 的 root_run_id 必须等于 run_id")
    else:
        _required_text(request.root_run_id, "root_run_id")
        _required_text(request.revision_of_run_id, "revision_of_run_id")
        _required_text(request.source_artifact_ref, "source_artifact_ref")
        if request.revision_iteration is None or request.revision_iteration < 2:
            raise CreativeRunBuilderError("revision_iteration 必须是 >= 2 的整数")
        if not isinstance(request.revision_feedback, list) or not request.revision_feedback:
            raise CreativeRunBuilderError("revision_feedback 必须是非空数组")
    return context, *_resolve_target(request.type_pack, request)


def _runtime_stage(
    pack: TypePackDescriptor, stage: StageContract, confirmation_stage: str | None,
) -> dict:
    if not stage.stage_type or not stage.owner or not stage.gate:
        raise CreativeRunBuilderError(f"stage {stage.stage_id!r} 缺少运行语义")
    when = None
    if confirmation_stage and confirmation_stage in stage.depends_on:
        if stage.stage_type == "persistence":
            when = {"stage_id": confirmation_stage, "outcome": "approved"}
    return {
        "stage_id": stage.stage_id,
        "assignee": stage.owner,
        "stage_type": stage.stage_type,
        "depends_on": list(stage.depends_on),
        "status": "pending",
        "gate": stage.gate,
        "outcome": None,
        "when": when,
        "input_refs": [],
        "output_refs": [],
        "skip_reason": None,
        "blocked_reason": None,
    }


def _build_stages(pack: TypePackDescriptor) -> list[dict]:
    stages = pack.stages
    confirmations = [item.stage_id for item in stages if item.stage_type == "confirmation"]
    if len(confirmations) != 1:
        raise CreativeRunBuilderError("core workflow 必须恰好有一个 confirmation gate")
    confirmation_stage = confirmations[0]
    return [_runtime_stage(pack, item, confirmation_stage) for item in stages]


def _snapshot(pack: TypePackDescriptor, artifact: ArtifactDescriptor | None,
              workflow: WorkflowContract | None, request: CreativeRunRequest) -> dict:
    quality_rule_ids = None
    if artifact is not None:
        quality_rule_ids = [
            rule.check_id for rule in pack.quality_rules
            if artifact.artifact_id in rule.artifact_ids
        ]
    return stage_dag.build_resolution_snapshot(
        pack, artifact, workflow,
        delivery_form=request.delivery_form,
        quality_rule_ids=quality_rule_ids,
        workflow_inputs=(
            copy.deepcopy(request.workflow_inputs)
            if request.workflow_inputs is not None else None
        ),
        skills=(
            copy.deepcopy(request.skills_resolution)
            if request.skills_resolution is not None else None
        ),
        used_user_skills=(
            copy.deepcopy(request.used_user_skills)
            if request.used_user_skills is not None else None
        ),
    )


def build_creative_run(request: CreativeRunRequest) -> dict:
    """Validate the request and return a dispatch-ready manifest structure."""
    try:
        context, artifact, workflow = _validate_request(request)
        pack = request.type_pack
        snapshot = _snapshot(pack, artifact, workflow, request)
        manifest = {
            "schema_version": stage_dag.RUN_SCHEMA,
            "run_id": request.run_id,
            "root_run_id": (
                request.root_run_id if request.root_run_id is not None
                else request.run_id
            ),
            "revision_of_run_id": request.revision_of_run_id,
            "iteration": (
                request.revision_iteration if request.intent == "revision" else 1
            ),
            "intent": request.intent,
            "artifact_type": request.target,
            "mode": "full",
            "project_root": request.project_root,
            "status": "pending",
            "outcome": None,
            "revision_feedback": (
                copy.deepcopy(request.revision_feedback)
                if request.revision_feedback is not None else []
            ),
            "source_artifact_ref": request.source_artifact_ref,
            "context": stage_dag.context_to_dict(context),
            "resolution_snapshot": snapshot,
            "stages": _build_stages(pack),
        }
        return stage_dag.validate_manifest(manifest)
    except (CreativeRunBuilderError, TypeRegistryError, stage_dag.StageDagError, TypeError, ValueError) as error:
        if isinstance(error, stage_dag.StageDagError):
            raise
        raise stage_dag.StageDagError(f"无法构建 creative run：{error}") from error
