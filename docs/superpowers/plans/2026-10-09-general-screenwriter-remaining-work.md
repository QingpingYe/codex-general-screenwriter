# General Screenwriter Remaining Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已完成的基础内核上，补齐知识 v2、用户技能治理、绘本迁移收尾、短剧/长篇类型包、跨类型质量样例、输出契约、迁移工具和发布门。

**Architecture:** 通用内核已经由 `stage_dag` / `creative_run_builder` / `type_registry` 承担调度与契约，后续不重建运行内核。知识 v2 与用户技能作为解析层接入 `resolution_snapshot`；短剧和长篇通过各自 type pack 表达结构；质量样例、导出器契约、迁移报告和发布门负责验收与发布。

**Tech Stack:** Python 3.10+ 标准库、frozen dataclasses、JSON、`unittest`、既有 `stage_dag.py` / `stage_dag_codex.py` / `creative_run_builder.py` / `type_registry.py` / knowledge-loader 与 Feishu knowledge store。

**Specs:**

- `docs/superpowers/plans/2026-10-09-general-screenwriter-upgrade-outline.md`
- `docs/superpowers/specs/2026-10-09-general-screenwriter-domain-model-design.md`
- `docs/superpowers/specs/2026-10-09-general-screenwriter-type-pack-contract-design.md`
- `docs/superpowers/specs/2026-10-09-general-screenwriter-knowledge-scope-design.md`
- `docs/superpowers/specs/2026-10-09-general-screenwriter-dag-quality-gate-design.md`
- `docs/superpowers/specs/2026-10-09-general-screenwriter-user-skill-governance-design.md`
- `docs/superpowers/specs/2026-10-09-general-screenwriter-picturebook-migration-design.md`
- `docs/superpowers/specs/2026-10-09-general-screenwriter-other-media-type-packs-design.md`
- `docs/superpowers/specs/2026-10-09-general-screenwriter-quality-output-release-design.md`

## Current Verified Baseline

- Foundation, type-pack v1, optional illustration isolation, knowledge scope read-only parser, generic creative run builder, and quality-gate report contract are implemented on `main`.
- `git log --oneline -20` shows the latest work is contained in commits for creative workflow, quality rules, type-pack snapshots, knowledge scope, and planned-medium gating.
- `python .\scripts\run_plugin_tests.py` currently passes 66 offline commands; governance and packaging checks also pass.
- `plugins/picturebook-screenwriter/config/type-packs.json` still has `shortdrama` and `tv_longform` as `planned`; they are not dispatchable.
- Knowledge loading currently supports optional `## knowledge-scope` metadata and scope-chain filtering, but `page_codec.py` remains schema v1 and dependency records are still primarily v1-compatible.
- There is no user-skill registry, no complete v2 knowledge write path, no shortdrama/tv_longform executable pack, no cross-media quality samples, no exporter contract, no migration report tool, and no unified release gate for this upgrade.

## Global Constraints

- 旧 `picturebook-screenwriter` 入口、旧 `pb-stage-run-v2`、旧 `pb-stage-task-v1`、旧六类产物、旧插画流程和旧三段知识 key 必须继续可读。
- 旧无 context 的 run manifest 不得自动补写 context 或 resolution snapshot。
- 默认写盘策略仍是 `dialog_only`；只有用户批准确认门或明确请求导出时才允许写文件。
- 不新增第三方运行时依赖；质量报告只聚合结果，不动态导入校验器，也不调用模型。
- 用户技能不得替换系统技能、type pack 硬约束或确认门；实验技能必须显式启用且不得静默进入后续 run。
- 新媒介 type pack 只有在产物、阶段、质量规则、代表性样例和兼容回归都齐备后才能从 `planned` 改为 `active`。
- 每次实际生效的 type pack、知识页和技能都必须写入隔离、可审计的 resolution snapshot。
- 迁移工具只生成报告与建议，不做静默改写。

## Review Focus

- **旧绘本兼容**：无 context、旧产物、旧插画 run 在所有新契约落地后仍可读取；Task 6 的迁移矩阵测试覆盖。
- **技能越权**：实验技能不能覆盖 system/type_pack 规则、确认门或写盘策略；Task 4/5 的 conflict 与 dispatch 测试覆盖。
- **知识静默合并**：不同 authority 的冲突知识页必须进入 conflicts，不能拼接或默认选择；Task 1/2 的冲突测试覆盖。
- **跨媒介耦合**：通用 builder/scheduler 不允许硬编码短剧、长篇或绘本阶段 ID；Task 6/7/8 的 generic-kernel 测试覆盖。
- **历史快照**：resolution snapshot 在 revision、dispatch plan、task envelope 中必须深拷贝；旧快照不得被改写；Task 5 的隔离测试覆盖。
- **导出失败**：导出器在缺参数、超限、覆盖已有文件或输入校验失败时必须失败关闭；Task 10 的导出测试覆盖。

---

### Task 1: Complete the read-only knowledge v2 resolution layer

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/knowledge_scope.py`
- Create: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_knowledge_scope.py`
- Modify: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/load_knowledge.py`
- Modify: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/dependencies.py`

**Interfaces:**
- Consumes: existing `ScopeRef`, `expand_scope_chain`, `parse_scope_envelope`, `KnowledgeEvidenceBundle`.
- Produces:
  - `build_scope_ref(context) -> ScopeRef`
  - `resolve_knowledge(bundle, query) -> KnowledgeResolution`
  - `KnowledgeResolution(matches, conflicts, warnings, scope_chain, knowledge_schema)`
  - `build_dependency_record(bundle, artifact_id, artifact_type, resolution) -> DependencyRecord`
  - `DependencyRecord.knowledge_schema == "knowledge-scope-v2"`

- [ ] **Step 1: Write the failing resolution tests**

Cover all of:

```python
def test_scope_ref_is_built_from_creative_context():
    ref = build_scope_ref(CreativeContext("shortdrama", ("mystery",),
        series_id="s1", project_id="p1", episode_id="e1"))
    assert ref.medium_id == "shortdrama"
    assert ref.project_id == "p1"

def test_lower_project_fact_wins_without_hiding_series_conflict():
    resolution = resolve_knowledge(bundle, query)
    assert resolution.matches == (project_page,)
    assert resolution.conflicts == (expected_conflict,)

def test_user_experiment_cannot_override_system_authority():
    resolution = resolve_knowledge(bundle, query)
    assert system_page in resolution.matches
    assert experiment_page in resolution.rejected
```

The tests must also prove that an old v1 page without scope metadata still loads and that `depends_on` does not mutate the input bundle.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_knowledge_scope.py -v`

Expected: FAIL because `knowledge_scope.py` and `KnowledgeResolution` do not exist.

- [ ] **Step 3: Implement deterministic resolution**

Build the task → scene → episode → season → project → series → genre → medium → global chain. Match scope nodes, detect same-topic conflicts across authorities, and reject `user_experiment` pages attempting to override `system` or `type_pack` authority. Keep matches immutable and ordered from the nearest applicable scope to broader scope.

- [ ] **Step 4: Extend dependency records without changing the old parser**

Add optional `skills` and `knowledge_schema` fields to `DependencyRecord`; preserve every v1 field and keep records without these fields parseable. The v2 record must carry the full scope chain and page revisions.

- [ ] **Step 5: Run knowledge regression**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_knowledge_scope.py -v; python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_load_knowledge.py -v; python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_dependencies.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/knowledge_scope.py plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_knowledge_scope.py plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/load_knowledge.py plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/dependencies.py
git commit -m "feat: add knowledge scope v2 resolution"
```

### Task 2: Add compatible v2 page metadata to the knowledge store

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/feishu-knowledge-store/scripts/knowledge_schema_v2.py`
- Create: `plugins/picturebook-screenwriter/skills/feishu-knowledge-store/scripts/test_knowledge_schema_v2.py`
- Modify: `plugins/picturebook-screenwriter/skills/feishu-knowledge-store/scripts/page_codec.py`
- Modify: `plugins/picturebook-screenwriter/skills/feishu-knowledge-store/scripts/store_cli.py`

**Interfaces:**
- Produces:
  - `parse_scope_page(body, metadata) -> ScopeEnvelope | None`
  - `render_scope_page(body, scope) -> str`
  - `validate_scope_page(candidate) -> ScopePageCandidate`
  - `scope_key(scope, page_type) -> str`
  - `KnowledgeMigrationReport(source_kind, source_version, target_version, matched, missing, ambiguous, manual_actions, rollback)`

`page_codec.py` must keep accepting schema v1 pages exactly as today; v2 support is additive.

- [ ] **Step 1: Write failing v2 metadata tests**

Cover:

```python
def test_v1_page_is_unchanged_when_v2_scope_is_absent():
    page = parse_remote_page(render_remote_page("# 标题\n正文", v1_metadata))
    assert parse_scope_page(page.body, page.metadata) is None

def test_v2_scope_requires_consistent_scope_and_page_type():
    with pytest.raises(SchemaError):
        parse_scope_page(v2_body, v1_metadata)
```

Also cover `supersedes` cycles, missing source refs, malformed authority, and a migration report that reports ambiguity without rewriting data.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/skills/feishu-knowledge-store/scripts/test_knowledge_schema_v2.py -v`

Expected: FAIL because v2 helpers are absent.

- [ ] **Step 3: Implement additive parser, renderer, and migration report**

Parse at most one `## knowledge-scope` envelope, validate scope/authority/page-type consistency, and expose a deterministic report object. Do not change the existing system metadata heading or v1 key logic.

- [ ] **Step 4: Run store and knowledge-loop regression**

Run: `python plugins/picturebook-screenwriter/skills/feishu-knowledge-store/scripts/test_knowledge_schema_v2.py -v; python plugins/picturebook-screenwriter/skills/feishu-knowledge-store/scripts/test_page_codec.py -v; python plugins/picturebook-screenwriter/tests/test_knowledge_loop.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add plugins/picturebook-screenwriter/skills/feishu-knowledge-store/scripts/knowledge_schema_v2.py plugins/picturebook-screenwriter/skills/feishu-knowledge-store/scripts/test_knowledge_schema_v2.py plugins/picturebook-screenwriter/skills/feishu-knowledge-store/scripts/page_codec.py plugins/picturebook-screenwriter/skills/feishu-knowledge-store/scripts/store_cli.py
git commit -m "feat: add compatible knowledge schema v2 pages"
```

### Task 3: Add user-skill contract and registry

**Files:**
- Create: `plugins/picturebook-screenwriter/scripts/user_skill_contract.py`
- Create: `plugins/picturebook-screenwriter/config/user-skills.example.json`
- Create: `plugins/picturebook-screenwriter/tests/test_user_skill_contract.py`
- Modify: `plugins/picturebook-screenwriter/config/plugin-contract.json`

**Interfaces:**
- `UserSkillDescriptor(skill_id, version, title, description, author, owner, status, created_at, updated_at, skill_type, scopes, allowed_stages, input_contract, output_contract, depends_on, conflicts_with, precedence, execution_policy, content_refs, audit)`
- `parse_user_skill_registry(payload) -> UserSkillRegistry`
- `load_user_skill_registry(path) -> UserSkillRegistry`
- `validate_user_skill_descriptor(descriptor, type_pack) -> UserSkillDescriptor`
- `descriptor_to_dict(descriptor) -> dict`
- `descriptor_from_dict(payload) -> UserSkillDescriptor`

Allowed statuses are `draft`, `active`, `disabled`, `retired`; allowed skill types are `prompt_skill`, `checklist_skill`, `validator_skill`, `exporter_skill`; allowed execution policies are `dialog_only`, `advisory`, `blocking_validator`, `export_only`, `interactive`.

- [ ] **Step 1: Write failing registry tests**

Cover:

```python
def test_rejects_draft_skill_in_active_resolution_scope():
    with self.assertRaises(UserSkillContractError):
        parse_user_skill_registry({"skills": [draft_skill_payload]})

def test_rejects_retired_skill_reactivation():
    with self.assertRaises(UserSkillContractError):
        validate_user_skill_descriptor(retired_skill, pack)

def test_rejects_precedence_above_system():
    with self.assertRaises(UserSkillContractError):
        descriptor_from_dict(skill_with_system_override)
```

Also cover duplicate `skill_id` versions, unknown stages, empty scopes, invalid content refs, missing audit records, and cross-pack references.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_user_skill_contract.py -v`

Expected: FAIL because the module is absent.

- [ ] **Step 3: Implement descriptors and registry validation**

Parse user skill JSON without importing content or validators. Validate IDs, versions, lifecycle transitions, scope refs, stage references, dependency references, conflicts, execution policy, and audit history. Store content only as references plus hashes.

- [ ] **Step 4: Add contract metadata**

Add `user_skill_contract` to `plugin-contract.json` with schema version `user-skill-contract-v1`, the four skill types, five execution policies, and the statement that user skills cannot replace system rules.

- [ ] **Step 5: Run contract tests**

Run: `python plugins/picturebook-screenwriter/tests/test_user_skill_contract.py -v; python plugins/picturebook-screenwriter/tests/test_plugin_contract.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/user_skill_contract.py plugins/picturebook-screenwriter/config/user-skills.example.json plugins/picturebook-screenwriter/config/plugin-contract.json plugins/picturebook-screenwriter/tests/test_user_skill_contract.py
git commit -m "feat: add user skill contract"
```

### Task 4: Resolve skills by scope, stage, artifact, and authority

**Files:**
- Create: `plugins/picturebook-screenwriter/scripts/user_skill_resolver.py`
- Create: `plugins/picturebook-screenwriter/tests/test_user_skill_resolver.py`

**Interfaces:**
- `SkillQuery(scope_ref, stage_id, intent, artifact_targets, include_experimental=False, exclude_skill_ids=())`
- `SkillResolution(matches, conflicts, rejected, snapshot)`
- `SkillSnapshot(skill_id, version, authority, scopes, stage_id, execution_policy, status, content_hash)`
- `resolve_skills(registry, context, type_pack, query) -> SkillResolution`
- `resolution_snapshot_to_dict(resolution) -> list[dict]`

- [ ] **Step 1: Write failing resolver tests**

Cover:

```python
def test_matches_only_declared_scope_and_stage():
    resolution = resolve_skills(registry, context, pack, query)
    assert [item.skill_id for item in resolution.matches] == ["project-hook-check"]

def test_project_skill_wins_and_series_conflict_is_reported():
    resolution = resolve_skills(registry, context, pack, query)
    assert resolution.matches == (project_skill,)
    assert resolution.conflicts == (expected_conflict,)

def test_experimental_skill_requires_explicit_include():
    assert experimental_skill not in resolve_skills(
        registry, context, pack, query_with_experiments_disabled,
    ).matches
```

Also cover missing dependencies, cross-stage rejection, disabled skills, conflict reporting without merge, and stable deterministic ordering.

- [ ] **Step 2: Run resolver tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_user_skill_resolver.py -v`

Expected: FAIL because resolver is absent.

- [ ] **Step 3: Implement resolution and conflict audit**

Use the knowledge scope chain for matching. Resolve dependencies before matches. Reject skills that violate higher authority, wrong stage, unknown artifact, disabled lifecycle, or failed dependency. Produce isolated snapshots and rejected/conflict records.

- [ ] **Step 4: Run resolver and contract tests**

Run: `python plugins/picturebook-screenwriter/tests/test_user_skill_resolver.py -v; python plugins/picturebook-screenwriter/tests/test_user_skill_contract.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/user_skill_resolver.py plugins/picturebook-screenwriter/tests/test_user_skill_resolver.py
git commit -m "feat: resolve scoped user skills"
```

### Task 5: Persist and dispatch skill snapshots safely

**Files:**
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag.py`
- Modify: `plugins/picturebook-screenwriter/scripts/creative_run_builder.py`
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag_codex.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_stage_dag_context.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_creative_run_builder.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py`

**Interfaces:**
- `build_resolution_snapshot(..., skills: Sequence[Mapping] | None = None) -> dict`
- `CreativeRunRequest(..., skills_resolution: Sequence[Mapping] | None = None)`
- `resolution_snapshot.skills` is a list of compact `SkillSnapshot` dictionaries.
- Dispatch plan, task envelope, sequential fallback, and revision manifest each receive isolated deep copies.
- `DependencyRecord` gains optional `skills_resolution`.

- [ ] **Step 1: Write failing snapshot and dispatch tests**

Cover:

```python
def test_skills_snapshot_is_deep_copied_into_dispatch_outputs():
    plan = build_dispatch_plan(manifest)
    task = format_task_envelope(manifest, manifest["stages"][1])
    plan["resolution_snapshot"]["skills"][0]["skill_id"] = "mutated"
    assert manifest["resolution_snapshot"]["skills"][0]["skill_id"] == "project-hook-check"

def test_legacy_manifest_does_not_gain_skills_snapshot():
    plan = build_dispatch_plan(legacy_manifest)
    assert "skills" not in plan.get("resolution_snapshot", {})
```

Also cover revision inheritance, historical snapshot read-only behavior, unknown skill snapshots rejected before dispatch, and experimental skills not silently dispatched.

- [ ] **Step 2: Run focused tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_creative_run_builder.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag_context.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py -v`

Expected: FAIL on missing skills snapshot handling.

- [ ] **Step 3: Extend snapshot parsing, validation, and deep copies**

Validate compact skill snapshot fields and ensure dispatch checks skill IDs against the current registry only when a registry is available. Historical snapshots without skills remain readable. Do not mutate old manifests.

- [ ] **Step 4: Run full dispatch regression**

Run: `python plugins/picturebook-screenwriter/tests/test_creative_run_builder.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_review_regression.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/stage_dag.py plugins/picturebook-screenwriter/scripts/creative_run_builder.py plugins/picturebook-screenwriter/scripts/stage_dag_codex.py plugins/picturebook-screenwriter/tests/test_stage_dag_context.py plugins/picturebook-screenwriter/tests/test_creative_run_builder.py plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py
git commit -m "feat: persist scoped skill snapshots"
```

### Task 6: Lock picturebook migration compatibility

**Files:**
- Create: `plugins/picturebook-screenwriter/tests/test_picturebook_migration_matrix.py`
- Modify: `plugins/picturebook-screenwriter/config/plugin-contract.json`
- Modify: `plugins/picturebook-screenwriter/README.md`
- Modify: `docs/CHANGELOG.md`

**Interfaces:**
- Contract field `picturebook_migration` records `text_core_status: migrated`, `illustration_workflow_status: migrated`, `knowledge_adapter_status: v1_compatible`, and the legacy aliases listed in the design.
- The regression matrix is executable, not documentation-only.

- [ ] **Step 1: Write the failing migration matrix test**

Cover exactly the design matrix:

```python
def test_legacy_no_context_run_remains_picturebook():
    assert extract_context(_creation_template_manifest()).medium_id == "picturebook"

def test_new_picturebook_revision_inherits_isolated_snapshot():
    child = build_revision_manifest(parent, feedback, artifact_ref, "child-run")
    assert child["revision_of_run_id"] == parent["run_id"]

def test_illustration_mixed_into_core_is_rejected():
    with self.assertRaises(TypeRegistryError):
        validate_type_contract(mixed_contract)
```

Also cover old illustration run readability, planned media rejection, empty active picturebook rejection, missing illustration script provenance rejection, and v1 knowledge-key compatibility.

- [ ] **Step 2: Run the focused test to verify coverage gaps**

Run: `python plugins/picturebook-screenwriter/tests/test_picturebook_migration_matrix.py -v`

Expected: FAIL on the missing executable matrix or remaining compatibility gap.

- [ ] **Step 3: Fix only migration gaps**

Do not add new content features. If a legacy path is already compatible, pin it with a test; if not, adjust the narrow compatibility boundary and preserve the old representation.

- [ ] **Step 4: Run picturebook and foundation regression**

Run: `python plugins/picturebook-screenwriter/tests/test_picturebook_migration_matrix.py -v; python plugins/picturebook-screenwriter/tests/test_screenwriter_foundation.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_execution_gate.py -v`

Expected: PASS.

- [ ] **Step 5: Update docs and commit**

```powershell
git add plugins/picturebook-screenwriter/tests/test_picturebook_migration_matrix.py plugins/picturebook-screenwriter/config/plugin-contract.json plugins/picturebook-screenwriter/README.md docs/CHANGELOG.md
git commit -m "test: lock picturebook migration matrix"
```

### Task 7: Implement the shortdrama minimal type pack

**Files:**
- Create: `plugins/picturebook-screenwriter/scripts/shortdrama_checks.py`
- Create: `plugins/picturebook-screenwriter/tests/test_shortdrama_type_pack.py`
- Modify: `plugins/picturebook-screenwriter/config/type-packs.json`
- Modify: `plugins/picturebook-screenwriter/config/plugin-contract.json`

**Interfaces:**
- Artifacts: `positioning`, `episode_outline`, `hook_sheet`, `beat_sheet`, `scene_table`, `episode_script`.
- Stages: `session_init`, `brief_gate`, `knowledge_load`, `episode_design`, `hook_design`, `beat_design`, `scene_design`, `episode_script_delegate`, `hook_check`, `pacing_check`, `dialogue_check`, `quality_gate`, `confirmation_gate`, `persistence`.
- `validate_shortdrama_rules(check_id, artifact, context) -> QualityCheckResult`
- `config/plugin-contract.json` must report `shortdrama` as active only after this task's regression passes.

- [ ] **Step 1: Write failing contract and check tests**

Use an explicit `shortdrama` context with `project_id` and `delivery_form="episode_script"`. Cover:

```python
def test_shortdrama_core_run_is_built_from_type_pack():
    manifest = build_creative_run(shortdrama_request("episode_script"))
    assert stage_dag.ready_stages(manifest) == ["session_init"]

def test_missing_closing_hook_fails_user_confirmation_risk():
    result = validate_shortdrama_rules("closing_hook", failing_episode, context)
    assert result.status == "fail"
```

Also cover opening hook, turning point, pacing density, conflict closure, character state, format, duration, duplicate stage IDs, and planned/active gating.

- [ ] **Step 2: Run shortdrama tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_shortdrama_type_pack.py -v`

Expected: FAIL because the pack is planned and checks are absent.

- [ ] **Step 3: Implement pure structural checks**

No model calls, network calls, or file writes. Return `QualityCheckResult` objects. Keep content-evaluation boundaries explicit and do not create an over-clever natural-language scorer.

- [ ] **Step 4: Activate the pack in the registry**

Set `shortdrama` active only after contract, check, run-builder, and dispatch tests pass. Keep `tv_longform` planned.

- [ ] **Step 5: Run cross-kernel and dispatch regression**

Run: `python plugins/picturebook-screenwriter/tests/test_shortdrama_type_pack.py -v; python plugins/picturebook-screenwriter/tests/test_creative_run_builder.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py -v; python plugins/picturebook-screenwriter/tests/test_type_pack_review_regression.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/shortdrama_checks.py plugins/picturebook-screenwriter/tests/test_shortdrama_type_pack.py plugins/picturebook-screenwriter/config/type-packs.json plugins/picturebook-screenwriter/config/plugin-contract.json
git commit -m "feat: add shortdrama type pack"
```

### Task 8: Implement the tv_longform minimal type pack

**Files:**
- Create: `plugins/picturebook-screenwriter/scripts/tv_longform_checks.py`
- Create: `plugins/picturebook-screenwriter/tests/test_tv_longform_type_pack.py`
- Modify: `plugins/picturebook-screenwriter/config/type-packs.json`
- Modify: `plugins/picturebook-screenwriter/config/plugin-contract.json`

**Interfaces:**
- Artifacts: `series_bible`, `character_arc_map`, `timeline_ledger`, `season_arc`, `episode_list`, `episode_outline`, `scene_table`, `episode_script`, `continuity_ledger`.
- Stages: `session_init`, `brief_gate`, `series_load`, `season_design`, `episode_design`, `scene_design`, `episode_script_delegate`, `continuity_check`, `foreshadow_check`, `character_state_check`, `quality_gate`, `confirmation_gate`, `persistence`.
- `validate_tv_longform_rules(check_id, artifact, context) -> QualityCheckResult`

- [ ] **Step 1: Write failing longform tests**

Cover series/season/episode/scene context construction, series bible, season arc, single-episode minimal path, continuity ledger, foreshadow source/return, character state, timeline consistency, and revision carrying updated context/snapshot.

```python
def test_tv_longform_minimal_run_requires_continuity_input():
    manifest = build_creative_run(longform_request("episode_script"))
    assert stage_dag.ready_stages(manifest) == ["session_init"]

def test_conflicting_character_state_is_reported_not_merged():
    result = validate_tv_longform_rules("character_state", failing_episode, context)
    assert result.status == "fail"
    assert result.evidence["conflicts"] == ["s1:e1:character-state"]
```

- [ ] **Step 2: Run longform tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_tv_longform_type_pack.py -v`

Expected: FAIL because the pack is planned and checks are absent.

- [ ] **Step 3: Implement continuity and structural checks**

Use deterministic ledger comparison for character state, timeline, foreshadow, recovery, scene transitions, and series constraints. No content synthesis or model calls.

- [ ] **Step 4: Activate the pack after regression**

Set `tv_longform` active only after the full longform suite, run builder, dispatch, and compatibility regressions pass.

- [ ] **Step 5: Run cross-media regression**

Run: `python plugins/picturebook-screenwriter/tests/test_tv_longform_type_pack.py -v; python plugins/picturebook-screenwriter/tests/test_shortdrama_type_pack.py -v; python plugins/picturebook-screenwriter/tests/test_creative_run_builder.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/tv_longform_checks.py plugins/picturebook-screenwriter/tests/test_tv_longform_type_pack.py plugins/picturebook-screenwriter/config/type-packs.json plugins/picturebook-screenwriter/config/plugin-contract.json
git commit -m "feat: add tv longform type pack"
```

### Task 9: Add cross-media representative samples and regression

**Files:**
- Create: `plugins/picturebook-screenwriter/tests/test_cross_media_samples.py`
- Create: `plugins/picturebook-screenwriter/tests/fixtures/picturebook-pass.json`
- Create: `plugins/picturebook-screenwriter/tests/fixtures/picturebook-fail.json`
- Create: `plugins/picturebook-screenwriter/tests/fixtures/shortdrama-pass.json`
- Create: `plugins/picturebook-screenwriter/tests/fixtures/shortdrama-fail.json`
- Create: `plugins/picturebook-screenwriter/tests/fixtures/tv-longform-pass.json`
- Create: `plugins/picturebook-screenwriter/tests/fixtures/tv-longform-fail.json`
- Modify: `docs/CHANGELOG.md`

**Interfaces:**
- Each fixture declares `context`, `target_artifact`, `workflow_inputs`, `knowledge_scope`, `quality_rules`, `expected_results`, and `failure_reason`.
- `load_sample(path) -> SampleContract`
- `evaluate_sample(sample) -> QualityGateReport`

- [ ] **Step 1: Write failing sample-loader and regression tests**

Each media must have one pass sample and one fail sample. The fail sample must show why it does not confirm; it must not be presented as passing.

```python
def test_shortdrama_fail_sample_is_confirmation_blocked():
    report = evaluate_sample(load_sample(SHORTDRAMA_FAIL))
    assert report.confirmation_ready is False
```

Also cover snapshot traceability, knowledge authority, type-pack version, expected blockers, warnings, and no default file writes.

- [ ] **Step 2: Run sample tests to verify failures**

Run: `python plugins/picturebook-screenwriter/tests/test_cross_media_samples.py -v`

Expected: FAIL until fixtures and evaluator wiring are complete.

- [ ] **Step 3: Add fixtures and evaluator**

Use pure JSON fixtures and the existing quality-gate aggregation. Do not create binary media or model-generated examples.

- [ ] **Step 4: Run all media suites**

Run: `python plugins/picturebook-screenwriter/tests/test_cross_media_samples.py -v; python plugins/picturebook-screenwriter/tests/test_shortdrama_type_pack.py -v; python plugins/picturebook-screenwriter/tests/test_tv_longform_type_pack.py -v; python plugins/picturebook-screenwriter/tests/test_picturebook_migration_matrix.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add plugins/picturebook-screenwriter/tests/test_cross_media_samples.py plugins/picturebook-screenwriter/tests/fixtures docs/CHANGELOG.md
git commit -m "test: add cross-media quality samples"
```

### Task 10: Add a fail-closed exporter contract

**Files:**
- Create: `plugins/picturebook-screenwriter/scripts/exporter_contract.py`
- Create: `plugins/picturebook-screenwriter/config/exporters.json`
- Create: `plugins/picturebook-screenwriter/tests/test_exporter_contract.py`
- Modify: `plugins/picturebook-screenwriter/skills/illustration-export/scripts/build_html.py`

**Interfaces:**
- `ExporterContract(exporter_id, supported_types, required_inputs, output_format, required_user_params, confirmation_policy, validation_policy)`
- `validate_export_request(contract, inputs, user_params) -> ExportRequest`
- `check_export_destination(destination, overwrite_allowed=False) -> ExportDestination`
- `build_export_manifest(contract, request) -> dict`

Supported formats in v1: `markdown`, `json`, `screenplay_text`, `page_script`, `html_preview`, `asset_registry`, `production_checklist`.

- [ ] **Step 1: Write failing exporter tests**

Cover:

```python
def test_missing_output_directory_is_rejected():
    with self.assertRaises(ExporterContractError):
        validate_export_request(html_contract, inputs, {"size": "A4", "quality": "high"})

def test_existing_file_is_not_overwritten_by_default():
    with self.assertRaises(ExporterContractError):
        check_export_destination(existing_path, overwrite_allowed=False)
```

Also cover unsupported media, missing inputs, model-call prohibition, half-finished export cleanup, explicit overwrite opt-in, and required user params.

- [ ] **Step 2: Run exporter tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_exporter_contract.py -v`

Expected: FAIL because the contract module is absent.

- [ ] **Step 3: Implement contract validation and destination policy**

Validate inputs, parameters, destination, overwrite policy, format support, and confirmation policy. The contract layer must not write files itself.

- [ ] **Step 4: Adapt the existing illustration exporter**

Reuse `check_export_destination` and `validate_export_request` in the HTML path while preserving current successful CLI behavior.

- [ ] **Step 5: Run exporter and illustration regression**

Run: `python plugins/picturebook-screenwriter/tests/test_exporter_contract.py -v; python plugins/picturebook-screenwriter/skills/illustration-export/scripts/test_build_html.py -v; python plugins/picturebook-screenwriter/skills/illustration-export/scripts/test_asset_registry.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/exporter_contract.py plugins/picturebook-screenwriter/config/exporters.json plugins/picturebook-screenwriter/tests/test_exporter_contract.py plugins/picturebook-screenwriter/skills/illustration-export/scripts/build_html.py
git commit -m "feat: add fail-closed exporter contract"
```

### Task 11: Add migration reporting and the unified release gate

**Files:**
- Create: `plugins/picturebook-screenwriter/scripts/migration_report.py`
- Create: `plugins/picturebook-screenwriter/tests/test_migration_report.py`
- Create: `scripts/release_gate.py`
- Create: `scripts/test_release_gate.py`
- Modify: `plugins/picturebook-screenwriter/config/plugin-contract.json`
- Modify: `docs/RELEASE.md`
- Modify: `docs/CHANGELOG.md`

**Interfaces:**
- `build_migration_report(source_kind, source_version, target_version, inventory) -> MigrationReport`
- `report_to_dict(report) -> dict`
- `run_release_gate(paths=(), verbose=False) -> int`
- Release gate steps: registry contract, knowledge adapter, skill registry, DAG scheduler, quality gate, exporter contract, offline regression, governance check, packaging check.

- [ ] **Step 1: Write failing migration and release tests**

Migration must report old run manifests, old artifact IDs, old knowledge keys, old skill references, old illustration flow, and old export paths as matched, missing, ambiguous, or requiring manual action.

```python
def test_old_knowledge_key_is_reported_v1_compatible_not_rewritten():
    report = build_migration_report("knowledge_key", 1, 2, inventory)
    assert report.items[0].status == "v1_compatible"

def test_release_gate_fails_when_offline_regression_fails():
    assert run_release_gate(paths=[bad_command]) == 1
```

- [ ] **Step 2: Run migration and release-gate tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_migration_report.py -v; python scripts/test_release_gate.py -v`

Expected: FAIL because both modules are absent.

- [ ] **Step 3: Implement read-only migration report**

Produce deterministic JSON-compatible reports with rollback hints. No rewriting, no remote writes, no user-artifact edits.

- [ ] **Step 4: Implement the release gate**

Run the listed checks in order, stop on the first failure, and print a compact result summary. The gate must not hide failures or continue after an unsafe error.

- [ ] **Step 5: Run release checks**

Run: `python plugins/picturebook-screenwriter/tests/test_migration_report.py -v; python scripts/test_release_gate.py -v; python .\scripts\run_plugin_tests.py; python .\scripts\governance_check.py; python .\scripts\package_check.py`

Expected: all PASS / exit 0.

- [ ] **Step 6: Update release documentation and commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/migration_report.py plugins/picturebook-screenwriter/tests/test_migration_report.py scripts/release_gate.py scripts/test_release_gate.py plugins/picturebook-screenwriter/config/plugin-contract.json docs/RELEASE.md docs/CHANGELOG.md
git commit -m "feat: add migration report and release gate"
```

## Completion Checklist

- [ ] Knowledge v2 scope resolution, conflicts, dependency snapshots, and store metadata compatibility are covered by tests.
- [ ] User skills are registered, scoped, prioritized, conflict-audited, snapshotted, and dispatched without bypassing system authority.
- [ ] Picturebook legacy entry, old manifests, old artifacts, old knowledge keys, old illustration flow, and confirmation semantics remain compatible.
- [ ] Shortdrama and tv_longform are executable through their own type packs, not hard-coded scheduler branches.
- [ ] Every activated media has passing and failing representative samples.
- [ ] Export requests are explicit, validated, fail-closed, and cannot overwrite existing files by default.
- [ ] Migration produces read-only reports with rollback hints and explicit manual actions.
- [ ] Full offline regression, governance check, packaging check, and release gate all pass.

## Plan Self-Review

- **Spec coverage:** The remaining phases from the outline map to knowledge v2 (Tasks 1-2), user skills (Tasks 3-5), picturebook migration (Task 6), shortdrama/tv_longform (Tasks 7-8), quality samples (Task 9), output ecosystem (Task 10), and migration/release (Task 11).
- **Step scan:** Each task starts with a failing behavioral test, defines exact interfaces, and ends with focused verification and a scoped commit.
- **Type consistency:** `CreativeContext`, `TypePackDescriptor`, `QualityRuleDescriptor`, `QualityGateReport`, `SkillSnapshot`, `KnowledgeResolution`, `DependencyRecord`, `ExporterContract`, and `MigrationReport` are reused consistently.
- **Review Focus:** Legacy compatibility, skill authority, knowledge conflicts, cross-media coupling, snapshot isolation, and export failure behavior each have an owning test.
- **Proportion:** The plan stays at contracts, adapters, type packs, and regression gates; it does not script content generation or replace existing picturebook workflows.
