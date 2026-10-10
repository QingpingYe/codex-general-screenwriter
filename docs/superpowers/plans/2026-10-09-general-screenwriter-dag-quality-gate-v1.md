# General Writer DAG And Quality Gate V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 让类型包成为 run/workflow 的唯一结构来源，并给质量检查建立可注册、可快照、可聚合的 v1 契约。

**Architecture:** 扩展现有 `StageContract` 与 `TypePackDescriptor`，新增阶段运行语义和质量规则声明；用独立 builder 从类型包生成 creation/revision/optional workflow manifest；用独立质量报告模块聚合检查结果。现有绘本模板、旧 manifest 和 planned 类型执行门保持兼容。

**Tech Stack:** Python 3.10+ 标准库、frozen dataclasses、JSON、unittest、现有 `stage_dag.py` 与 `stage_dag_codex.py`。

**Spec:** `docs/superpowers/specs/2026-10-09-general-screenwriter-dag-quality-gate-design.md`

## Global Constraints

- 不把 `shortdrama` 或 `tv_longform` 在 `config/type-packs.json` 中激活；可以用内存中的 planned-pack 变体证明通用调度能力。
- 旧无 context 的 `pb-stage-run-v2`、旧 `pb-stage-task-v1`、旧 six artifact 和旧绘本入口继续可读，不自动补写 context/snapshot。
- planned 类型包仍不能生成公开 dispatch plan 或 task envelope。
- creation/revision 每个 run 仍只产出一个核心 artifact；`positioning` 仍是 user input。
- 只有 `approved` 解锁 persistence；`revision_requested` 创建新 run 并重跑检查；`cancelled` 终止。
- 默认仍是 dialog-only；质量报告只产生结构化结果，不写文件、不调用模型、不同步知识库。
- 质量规则只声明检查、目标、阶段、验证器和阻断策略；本计划不实现新的内容评估算法。
- 不新增第三方运行时依赖。

## Review Focus

- **隐藏的绘本耦合**：builder 不得引用 picturebook stage ID 或 owner；用非绘本内存包测试钉住，见 Task 4 的 `test_builds_nonpicturebook_core_run_from_type_pack`。
- **runtime 元数据缺失**：active v1 包的每个 stage 必须有 `stage_type/owner/gate`，否则 builder 失败；见 Task 1。
- **质量规则静默丢失**：snapshot 必须记录目标 artifact 实际适用的 rules；缺失、未知或跨包引用必须拒绝；见 Task 2。
- **require_user_confirmation 被当成 pass**：报告必须区分 hard blockers 和未接受的用户确认风险；见 Task 3。
- **历史快照被改写**：legacy manifest 不补字段；revision 继承或重建快照必须显式且可审计；见 Task 5。

---

### Task 1: Add stage runtime semantics to type packs

**Files:**
- Modify: `plugins/picturebook-screenwriter/scripts/type_registry.py`
- Modify: `plugins/picturebook-screenwriter/config/type-packs.json`
- Modify: `plugins/picturebook-screenwriter/tests/test_type_contract_models.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_type_registry.py`

**Interfaces:**
- `StageContract` 新增：
  - `stage_type: str | None = None`
  - `owner: str | None = None`
  - `gate: str = "none"`
- 允许的 `stage_type` 值固定为：`session_init`、`brief_gate`、`knowledge_load`、`delegation`、`creation`、`validation`、`synthesis`、`confirmation`、`persistence`、`delivery`。
- 完整 active v1 包的每个 core/optional stage 必须有非空 `stage_type` 和 `owner`；`gate` 必须是非空字符串。legacy 字符串 artifact 配置仍可读取但不可执行。

- [x] **Step 1: Write failing model tests**

```python
def test_stage_runtime_semantics_are_immutable():
    stage = StageContract(
        stage_id="draft", stage_type="creation", owner="writer",
        gate="none", produces_artifact_ids=("script",),
    )
    with self.assertRaises(FrozenInstanceError):
        stage.stage_type = "validation"

def test_full_active_v1_requires_runtime_semantics():
    for field in ("stage_type", "owner", "gate"):
        payload = valid_payload()
        payload["packs"][0]["stages"][1].pop(field)
        with self.subTest(field=field):
            with self.assertRaises(tr.TypeRegistryError):
                tr.parse_type_registry(payload)
```

- [x] **Step 2: Run focused model tests and observe failures**

Run: `python plugins/picturebook-screenwriter/tests/test_type_contract_models.py -v; python plugins/picturebook-screenwriter/tests/test_type_registry.py -v`

Expected: FAIL because `stage_type/owner/gate` do not exist and loader does not require them.

- [x] **Step 3: Implement runtime fields and validation**

Add the three frozen fields, parse them as optional keys, reject unknown values for `stage_type`, and require them on every stage of a full active v1 pack. Keep legacy descriptors readable without runtime semantics.

- [x] **Step 4: Update picturebook reference contract**

In `type-packs.json`, map every core and illustration stage to its existing runtime owner and gate. Do not change stage IDs, dependencies, confirmation gates, or artifact ownership. `confirmation_gate` remains `confirmation_required=true` and `gate=confirmation`; illustration keeps its two explicit confirmation gates.

- [x] **Step 5: Verify registry and type-pack regressions**

Run: `python plugins/picturebook-screenwriter/tests/test_type_contract_models.py -v; python plugins/picturebook-screenwriter/tests/test_type_registry.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_review_regression.py -v`

Expected: all pass.

- [x] **Step 6: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/type_registry.py plugins/picturebook-screenwriter/config/type-packs.json plugins/picturebook-screenwriter/tests/test_type_contract_models.py plugins/picturebook-screenwriter/tests/test_type_registry.py
git commit -m "feat: add stage runtime semantics to type packs"
```

### Task 2: Add quality rule descriptors and snapshots

**Files:**
- Modify: `plugins/picturebook-screenwriter/scripts/type_registry.py`
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag.py`
- Modify: `plugins/picturebook-screenwriter/config/type-packs.json`
- Modify: `plugins/picturebook-screenwriter/tests/test_type_contract_models.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_type_registry.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py`

**Interfaces:**
- New `QualityRuleDescriptor`:
  - `check_id: str`
  - `artifact_ids: tuple[str, ...]`
  - `stage_id: str`
  - `blocking_policy: str`
  - `validator: str | None`
- Allowed `blocking_policy`: `hard_block`, `require_user_confirmation`, `advisory`, `informational`.
- `TypePackDescriptor.quality_rules: tuple[QualityRuleDescriptor, ...] = ()`.
- Snapshot adds optional `quality_rules` as a list of compact dictionaries containing exactly: `check_id`, `artifact_ids`, `stage_id`, `blocking_policy`, `validator`.
- `build_resolution_snapshot(..., quality_rule_ids: Sequence[str] | None = None)` filters declared rules for the selected core artifact and rejects unknown or non-matching rules.

- [x] **Step 1: Write failing descriptor and snapshot tests**

Cover all of:
  - `QualityRuleDescriptor` is immutable and sequences are isolated;
  - duplicate `check_id` is rejected;
  - unknown `artifact_id`, `stage_id`, `validator`, or `blocking_policy` is rejected;
  - every rule artifact must be an active `workflow_output` core artifact and its `stage_id` must validate that artifact;
  - `build_resolution_snapshot` includes selected rules in `quality_rules`;
  - snapshot validation rejects unknown, duplicate, cross-medium, or stale quality-rule IDs for a current-version pack;
  - a legacy snapshot without `quality_rules` remains readable and does not gain the field.

- [x] **Step 2: Run focused tests and observe failures**

Run: `python plugins/picturebook-screenwriter/tests/test_type_contract_models.py -v; python plugins/picturebook-screenwriter/tests/test_type_registry.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py -v`

Expected: FAIL because the descriptor, config, and snapshot support are absent.

- [x] **Step 3: Implement parsing, validation, and snapshot support**

Parse `quality_rules` as an optional type-pack field. Validate references inside the same core type-pack namespace. Add `quality_rules` to the allowed snapshot fields and compact-rule shape. Only validate current-version rule references; archived snapshots remain read-only.

- [x] **Step 4: Add picturebook seed rules**

Add only rules that express current behavior:
  - `project_authority`: all five workflow-output core artifacts at `preflight`, `hard_block`, validator `pre_output-baseline`;
  - `knowledge_collision`: all five workflow-output core artifacts at `collision_check`, `hard_block`, validator `null`;
  - `craft_benchmark`: `script` at `qa`, `require_user_confirmation`, validator `craft-benchmark-check`.

Do not add new quality algorithms or pretend these declarations execute automatically.

- [x] **Step 5: Verify contract, snapshot, and dispatch regressions**

Run: `python plugins/picturebook-screenwriter/tests/test_type_contract_models.py -v; python plugins/picturebook-screenwriter/tests/test_type_registry.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py -v`

Expected: all pass.

- [x] **Step 6: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/type_registry.py plugins/picturebook-screenwriter/scripts/stage_dag.py plugins/picturebook-screenwriter/config/type-packs.json plugins/picturebook-screenwriter/tests/test_type_contract_models.py plugins/picturebook-screenwriter/tests/test_type_registry.py plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py
git commit -m "feat: add type pack quality rule contracts"
```

### Task 3: Add structured quality gate report

**Files:**
- Create: `plugins/picturebook-screenwriter/scripts/quality_gate_contract.py`
- Create: `plugins/picturebook-screenwriter/tests/test_quality_gate_contract.py`

**Interfaces:**
- `QualityCheckResult(check_id, artifact_id, stage_id, blocking_policy, status, message="", user_accepted=False, evidence=None)`
- `QualityGateReport(gate_id, scope, checks, blockers, requires_user_confirmation, warnings, passed, confirmation_ready)`
- `build_quality_gate_report(rules, results, *, gate_id="quality-gate-v1", scope="run") -> QualityGateReport`
- `quality_report_to_dict(report) -> dict`
- `quality_report_from_dict(payload) -> QualityGateReport`
- Result statuses: `pass`, `warn`, `fail`, `skipped`, `unknown`.
- Aggregation:
  - `hard_block` + `fail` => blocker; `passed=False`;
  - `require_user_confirmation` + `fail` without `user_accepted=True` => `requires_user_confirmation`; `confirmation_ready=False`;
  - `advisory` + `fail` => warning;
  - `informational` is recorded but does not block;
  - every declared rule must have at least one result; a missing rule becomes an `unknown` check and is treated as unresolved.

- [x] **Step 1: Write failing report tests**

Cover:
  - a pass report has `passed=True` and `confirmation_ready=True`;
  - a hard-block failure appears in `blockers`, `passed=False`, and `confirmation_ready=False`;
  - an unaccepted `require_user_confirmation` failure appears in `requires_user_confirmation` but not `blockers`, and `confirmation_ready=False`;
  - accepted user-confirmation risk is not a blocker and `confirmation_ready=True`;
  - advisory failure is only a warning;
  - missing, duplicate, unknown, or mismatched result check IDs produce a structured error or `unknown` unresolved result;
  - JSON round-trip preserves fields and result status.

- [x] **Step 2: Run report tests and observe failures**

Run: `python plugins/picturebook-screenwriter/tests/test_quality_gate_contract.py -v`

Expected: FAIL because `quality_gate_contract.py` does not exist.

- [x] **Step 3: Implement report aggregation and serialization**

Use the `QualityRuleDescriptor` from Task 2 to validate each raw result. The module must not import `stage_dag.py`, read files, call validators, or write output. It only validates structure and aggregates policy outcomes.

- [x] **Step 4: Run focused report tests**

Run: `python plugins/picturebook-screenwriter/tests/test_quality_gate_contract.py -v`

Expected: all pass.

- [x] **Step 5: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/quality_gate_contract.py plugins/picturebook-screenwriter/tests/test_quality_gate_contract.py
git commit -m "feat: add structured quality gate reports"
```

### Task 4: Build core creation and revision runs from type packs

**Files:**
- Create: `plugins/picturebook-screenwriter/scripts/creative_run_builder.py`
- Create: `plugins/picturebook-screenwriter/tests/test_creative_run_builder.py`
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag.py`

**Interfaces:**
- `CreativeRunRequest(type_pack, context, intent, target, run_id, project_root, delivery_form=None, workflow_id=None, workflow_inputs=None, root_run_id=None, revision_of_run_id=None, revision_iteration=None, revision_feedback=None, source_artifact_ref=None)`
- `build_creative_run(request: CreativeRunRequest) -> dict`
- `intent` accepts only `creation` or `revision`.
- For a core run, `workflow_id` is null, `target` is an active workflow-output core artifact, and `manifest.artifact_type=target`.
- For an optional workflow run, `workflow_id` is set, `target` is the workflow ID or one of its active artifacts, and manifest stages are exactly that workflow's stages.
- Stage runtime dictionaries use `stage_type/owner/gate` from `StageContract`; no picturebook owner or stage ID is hardcoded in the builder.
- Core revision reuses the same core stage graph; do not add hard-coded `revision_init` or `revision_delegate` for explicit-context runs. Legacy no-context revision keeps the existing template.

- [x] **Step 1: Write failing builder tests**

Use an in-memory `shortdrama`-context fixture pack with version `shortdrama-fixture-v1` and status `active`. It must not be written to `config/type-packs.json`.

Cover:
  - `build_creative_run` produces a validated manifest with the exact declared core stage IDs, owners, gates, stage types, dependency edges, target artifact, context, and `resolution_snapshot.quality_rules`;
  - the manifest is accepted by `stage_dag.validate_manifest`, and `stage_dag.ready_stages` returns its declared entry stage;
  - the same fixture supports a generic revision request with explicit parent/iteration/feedback/source ref and no picturebook-specific IDs;
  - `persistence` has the approved-only `when` condition and `confirmation_gate` is the only confirmation gate;
  - a planned type pack is rejected before manifest construction;
  - an input-only artifact, foreign artifact, unknown workflow, missing owner/stage metadata, or delivery form outside the target is rejected;
  - source manifests and input descriptors are deep-copied, so mutating the returned manifest does not mutate the request;
  - a legacy no-context revision still goes through the existing `stage_dag.build_revision_manifest` path unchanged.

- [x] **Step 2: Run builder tests and observe failures**

Run: `python plugins/picturebook-screenwriter/tests/test_creative_run_builder.py -v`

Expected: FAIL because `creative_run_builder.py` does not exist.

- [x] **Step 3: Implement the minimal builder**

The builder validates context, pack status, target/workflow selection, runtime stage metadata, revision lineage fields, and delivery form. It constructs the manifest, calls `build_resolution_snapshot`, adds applicable quality rules, and returns `stage_dag.validate_manifest` output. It must not touch the filesystem or call `assert_manifest_type_executable`; dispatch remains the public execution gate.

- [x] **Step 4: Extend explicit-context revision safely**

In `stage_dag.build_revision_manifest`, keep the existing template path for a parent without context. If the parent has context, rebuild the stage graph from the currently resolved executable type pack and target/workflow; reject a stale snapshot version or planned pack. Preserve parent/root IDs, iteration, feedback, source ref, and deep-copied context. Keep the no-context legacy behavior byte-compatible in structure.

- [x] **Step 5: Run builder, DAG, and revision regressions**

Run: `python plugins/picturebook-screenwriter/tests/test_creative_run_builder.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag_context.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py -v`

Expected: all pass.

- [x] **Step 6: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/creative_run_builder.py plugins/picturebook-screenwriter/scripts/stage_dag.py plugins/picturebook-screenwriter/tests/test_creative_run_builder.py
git commit -m "feat: build creative runs from type packs"
```

### Task 5: Wire dispatch snapshots and confirmation quality semantics

**Files:**
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag.py`
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag_codex.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_stage_dag.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py`

**Interfaces:**
- `resolution_snapshot.quality_rules` is copied into dispatch plans, task envelopes, sequential fallbacks, and revision manifests.
- `assert_manifest_type_executable` rejects a current-version snapshot whose `quality_rules` do not match the current type pack for the selected target/workflow.
- Codex confirmation behavior remains lead-owned; quality report state is advisory metadata for the lead, not an automatic outcome writer.

- [x] **Step 1: Write failing dispatch and snapshot isolation tests**

Cover:
  - a type-pack-built creation manifest exposes identical, isolated `quality_rules` in plan, task envelope, and fallback;
  - mutating one envelope does not mutate the manifest, parent, or sibling envelope;
  - a current-version snapshot with a missing, unknown, stale, or cross-target quality rule cannot dispatch;
  - an old snapshot without quality rules still validates and dispatches only when its other compatibility conditions pass;
  - planned media still cannot dispatch;
  - confirmation outcomes remain `approved`, `revision_requested`, and `cancelled`.

- [x] **Step 2: Run dispatch tests and observe failures**

Run: `python plugins/picturebook-screenwriter/tests/test_stage_dag.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py -v`

Expected: FAIL on missing quality-rule dispatch/isolation enforcement.

- [x] **Step 3: Implement snapshot propagation and execution checks**

Do not duplicate snapshot serialization. Reuse the existing deep-copy helpers and extend their allowed/validation behavior. Keep quality rules as contract metadata; the dispatch adapter does not evaluate them.

- [x] **Step 4: Verify public dispatch and compatibility gates**

Run: `python plugins/picturebook-screenwriter/tests/test_stage_dag.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag_context.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_execution_gate.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_review_regression.py -v`

Expected: all pass.

- [x] **Step 5: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/stage_dag.py plugins/picturebook-screenwriter/scripts/stage_dag_codex.py plugins/picturebook-screenwriter/tests/test_stage_dag.py plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py
git commit -m "feat: dispatch quality rule snapshots"
```

### Task 6: Update public contract and run full release regression

**Files:**
- Modify: `plugins/picturebook-screenwriter/config/plugin-contract.json`
- Modify: `plugins/picturebook-screenwriter/README.md`
- Modify: `plugins/picturebook-screenwriter/skills/picturebook-screenwriter/SKILL.md`
- Modify: `plugins/picturebook-screenwriter/tests/test_plugin_contract.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_skill_contract.py`
- Modify: `docs/CHANGELOG.md`

**Interfaces:**
- Add `creative_workflow` metadata declaring that explicit-context runs are built from type packs and that shortdrama/tv_longform remain planned.
- Add `quality_gate_contract` metadata with schema version `quality-gate-v1`, allowed blocking policies, and the statement that report aggregation does not execute validators.
- Preserve all existing `write_policy`, confirmation, illustration, and compatibility fields.

- [x] **Step 1: Add failing contract and skill assertions**

Assert that:
  - `quality_gate_contract.schema_version == "quality-gate-v1"`;
  - allowed blocking policies are the four values in Task 2;
  - contract explicitly says shortdrama/tv_longform remain planned;
  - operator text explains that quality reports inform the confirmation gate but never replace it or write files.

- [x] **Step 2: Run focused contract tests and observe failures**

Run: `python plugins/picturebook-screenwriter/tests/test_plugin_contract.py -v; python plugins/picturebook-screenwriter/tests/test_skill_contract.py -v`

Expected: FAIL because public metadata/docs are absent.

- [x] **Step 3: Update contract, README, skill, and changelog**

Document only the implemented boundary: type-pack-driven core/optional workflows, quality rule snapshots, structured reports, preserved confirmation semantics, and planned media that cannot dispatch. Do not advertise shortdrama or tv_longform creation.

- [x] **Step 4: Run all focused subsystem suites**

Run: `python plugins/picturebook-screenwriter/tests/test_type_contract_models.py -v; python plugins/picturebook-screenwriter/tests/test_type_registry.py -v; python plugins/picturebook-screenwriter/tests/test_quality_gate_contract.py -v; python plugins/picturebook-screenwriter/tests/test_creative_run_builder.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py -v`

Expected: all pass.

- [x] **Step 5: Run complete offline regression and release checks**

Run: `python .\scripts\run_plugin_tests.py`

Expected: exit 0; report all offline commands passed. Because Tasks 3-4 add two test files, the reported command count should increase from the current 64 by two unless later test consolidation is explicitly reviewed.

- [x] **Step 6: Review the diff and commit**

Confirm the diff does not include `.sdd-temp-screenwriter-foundation/`, remote writes, user artifacts, or activated planned media. Then commit.

```powershell
git add plugins/picturebook-screenwriter/config/plugin-contract.json plugins/picturebook-screenwriter/README.md plugins/picturebook-screenwriter/skills/picturebook-screenwriter/SKILL.md plugins/picturebook-screenwriter/tests/test_plugin_contract.py plugins/picturebook-screenwriter/tests/test_skill_contract.py docs/CHANGELOG.md
git commit -m "docs: declare creative workflow quality gate contract"
```

## Completion Checklist

- [x] Active type packs declare runtime stage semantics; legacy string packs remain readable but non-executable.
- [x] Quality rules are declared, validated, snapshotted, and dispatch-isolated.
- [x] Quality reports distinguish hard blockers, user-confirmation risks, warnings, and informational results.
- [x] A non-picturebook in-memory active pack can be built and scheduled by the generic kernel without registering or enabling a real new medium.
- [x] Explicit-context revision uses the type-pack stage graph; legacy no-context revision remains compatible.
- [x] Planned media cannot dispatch; picturebook behavior and confirmation gates remain unchanged.
- [x] Full offline regression, governance, and packaging checks pass.

## Plan Self-Review

- **Spec coverage:** stage runtime metadata, type-pack workflow generation, confirmation/revision rules, quality gate declaration/reporting, snapshots, dispatch compatibility, and old-run compatibility are mapped to Tasks 1-6. New-media type packs remain excluded by user decision and are covered only as an in-memory scheduler fixture.
- **Step scan:** every implementation task starts with named failing behavior, defines exact interfaces, and ends with a focused verification and commit.
- **Type consistency:** `StageContract`, `QualityRuleDescriptor`, `CreativeRunRequest`, `QualityCheckResult`, and `QualityGateReport` are reused consistently across later tasks.
- **Review Focus:** hidden picturebook coupling, missing runtime metadata, silent quality-rule loss, confirmation-risk flattening, and historical snapshot rewriting each have an owning test.
- **Proportion:** the plan stays at contract and kernel orchestration level; it does not write stage bodies, content checks, or new-media workflows.
