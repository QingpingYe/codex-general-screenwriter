# 通用编剧基础契约与绘本兼容适配实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏现有绘本工作流的前提下，加入通用创作上下文、类型注册和运行记录扩展，为后续知识库、用户技能和多类型能力包提供稳定基础。

**Architecture:** 新增独立的上下文与类型注册模块，使用配置文件声明首批媒介类型。现有 `pb-stage-run-v2`、`pb-stage-task-v1` 和绘本入口继续兼容；通用上下文以可选扩展字段接入运行清单和任务信封，旧清单缺少这些字段时按绘本兼容路径读取。知识库 schema v2、技能注册中心和电影/短剧/长篇类型包留在后续专项计划。

**Tech Stack:** Python 3.10+ 标准库、`unittest`、JSON 配置、现有阶段 DAG 和 Codex dispatch adapter。

**Spec:** `docs/superpowers/specs/2026-10-09-general-screenwriter-domain-model-design.md`

## Global Constraints

- 旧 `picturebook-screenwriter` 入口、旧六类产物、旧三段知识 key 和旧 run manifest 必须继续可读。
- 现有 `pb-stage-run-v2` 和 `pb-stage-task-v1` 保持可解析；新增上下文字段为可选扩展。
- 首期只建立通用契约，不把绘本 benchmark、页数或插画约束放入通用内核。
- 类型、系列、项目和任务作用域只记录上下文；继承、覆盖和冲突解析由后续知识/技能专项实现。
- 默认写入策略、用户确认门、`approved` / `revision_requested` / `cancelled` 语义保持不变。
- 所有新增用户可见 skill 文本使用中文；所有新增解析和校验必须可测试、可复现。
- 不新增第三方运行时依赖，不修改远端知识库，不在本计划中执行迁移写入。

## Review Focus

- **无 context 的旧 manifest**：应按绘本兼容路径读取，并且序列化时不凭空覆盖旧字段。由 Task 2 的 legacy manifest 测试覆盖。
- **未知媒介和别名冲突**：未知 `medium_id`、重复 alias 或空 alias 必须在加载阶段失败。由 Task 1 的 registry 校验测试覆盖。
- **多题材标签顺序**：`genre_ids` 应去重、保持稳定顺序并拒绝空值。由 Task 1 的 context 测试覆盖。
- **revision 上下文继承**：创建 revision run 时必须复制 context 和 resolution snapshot，不能继承错误的父 run 标识。由 Task 2 的 revision 测试覆盖。
- **任务信封隔离**：dispatch plan 和 task envelope 只能携带已校验的上下文快照，不能让下游修改原 manifest。由 Task 3 的 deep-copy 测试覆盖。

---

### Task 1: 建立创作上下文与类型注册契约

**Files:**
- Create: `plugins/picturebook-screenwriter/scripts/screenwriter_context.py`
- Create: `plugins/picturebook-screenwriter/scripts/type_registry.py`
- Create: `plugins/picturebook-screenwriter/config/type-packs.json`
- Create: `plugins/picturebook-screenwriter/tests/test_screenwriter_context.py`
- Create: `plugins/picturebook-screenwriter/tests/test_type_registry.py`

**Interfaces:**
- `CreativeContext(medium_id, genre_ids=(), series_id=None, project_id=None, season_id=None, episode_id=None, scene_id=None, delivery_form=None)`：表示一次创作的媒介与上下文；旧绘本读取允许 `project_id=None`。
- `validate_context(context, require_project=False) -> CreativeContext`：校验媒介、题材、标识和交付形式，返回规范化的不可变上下文。
- `context_to_dict(context) -> dict` 与 `context_from_dict(payload, require_project=False) -> CreativeContext`：负责可持久化的 JSON 形式。
- `TypePackDescriptor(medium_id, aliases, delivery_forms, artifact_types, workflow_policy, status, legacy_aliases=())`：类型包注册描述；`status` 为 `active` 或 `planned`。
- `load_type_registry(path) -> TypeRegistry`、`resolve_type_pack(registry, identifier) -> TypePackDescriptor`：从 JSON 加载并按 ID 或 alias 解析类型。
- `config/type-packs.json` 首期注册 `picturebook`、`film`、`shortdrama`、`tv_longform`；其中只有 `picturebook` 声明现有入口和旧产物 alias，其他三类先声明最小交付形式和 `status: planned`。

- [ ] **Step 1: Write the failing context tests**

```python
def test_normalizes_and_deduplicates_genres():
    context = context_from_dict({
        "medium_id": "picture-book",
        "genre_ids": ["mystery", "comedy", "mystery"],
    })
    assert context.medium_id == "picturebook"
    assert context.genre_ids == ("mystery", "comedy")

def test_rejects_unknown_medium_and_blank_genre():
    with self.assertRaises(ContextError):
        context_from_dict({"medium_id": "unknown"})
    with self.assertRaises(ContextError):
        context_from_dict({"medium_id": "film", "genre_ids": [""]})

def test_legacy_context_can_omit_project_id():
    context = context_from_dict({"medium_id": "picturebook"})
    self.assertIsNone(context.project_id)
```

- [ ] **Step 2: Run the context tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_screenwriter_context.py -v`

Expected: FAIL because the context module and parser do not exist.

- [ ] **Step 3: Implement the context module**

Define the canonical IDs and aliases in one place. Normalize `picture-book` and `picture book` to `picturebook`; preserve the input order of first-seen `genre_ids` while removing duplicates; reject non-string or blank identifiers. `require_project=True` must require a non-empty `project_id` for new generic creation paths.

- [ ] **Step 4: Write the failing registry tests**

```python
def test_loads_four_initial_mediums(self):
    registry = load_type_registry(CONFIG)
    self.assertEqual(
        {pack.medium_id for pack in registry.packs},
        {"picturebook", "film", "shortdrama", "tv_longform"},
    )

def test_resolves_picturebook_alias(self):
    registry = load_type_registry(CONFIG)
    self.assertEqual(
        resolve_type_pack(registry, "picture book").medium_id,
        "picturebook",
    )

def test_rejects_duplicate_aliases(self):
    path = write_json({"schema_version": 1, "packs": [
        {"medium_id": "film", "aliases": ["screen"]},
        {"medium_id": "shortdrama", "aliases": ["screen"]},
    ]})
    with self.assertRaises(TypeRegistryError):
        load_type_registry(path)
```

- [ ] **Step 5: Run registry tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_type_registry.py -v`

Expected: FAIL because the registry loader and configuration do not exist.

- [ ] **Step 6: Implement the registry and initial configuration**

Validate schema version, unique `medium_id`, unique aliases, non-empty delivery forms, a valid `status`, and one workflow policy per pack. Keep planned packs loadable for registration tests; the entry workflow must route only `status=active` packs in this foundation slice, leaving planned pack execution to later type-pack plans.

- [ ] **Step 7: Run both contract test files**

Run: `python plugins/picturebook-screenwriter/tests/test_screenwriter_context.py -v; python plugins/picturebook-screenwriter/tests/test_type_registry.py -v`

Expected: all context and registry tests pass.

- [ ] **Step 8: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/screenwriter_context.py plugins/picturebook-screenwriter/scripts/type_registry.py plugins/picturebook-screenwriter/config/type-packs.json plugins/picturebook-screenwriter/tests/test_screenwriter_context.py plugins/picturebook-screenwriter/tests/test_type_registry.py
git commit -m "feat: add screenwriter context and type registry"
```

### Task 2: 扩展运行清单并保持绘本 manifest 兼容

**Files:**
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_stage_dag.py`
- Create: `plugins/picturebook-screenwriter/tests/test_stage_dag_context.py`

**Interfaces:**
- `attach_context(manifest, context, resolution_snapshot=None) -> dict`：在深拷贝的 manifest 上写入可选 `context` 和 `resolution_snapshot`，不修改输入对象。
- `extract_context(manifest) -> CreativeContext`：有 `context` 时解析并校验；缺失时返回 `medium_id="picturebook"` 的兼容上下文。
- `validate_manifest(manifest)`：继续接受无上下文的 `pb-stage-run-v2`；出现上下文时校验其结构和类型包引用。
- `build_revision_manifest(...)`：复制父 run 的 context 和 resolution snapshot，同时保持新的 `run_id`、`iteration` 和 `revision_of_run_id` 规则。

- [ ] **Step 1: Write failing manifest context tests**

```python
def test_legacy_manifest_infers_picturebook_context(self):
    manifest = stage_dag._creation_template_manifest()
    self.assertEqual(
        stage_dag.extract_context(manifest).medium_id,
        "picturebook",
    )

def test_attach_context_is_deep_copy_and_validates_snapshot(self):
    manifest = stage_dag._creation_template_manifest()
    context = CreativeContext("film", ("mystery",), project_id="p1")
    enriched = stage_dag.attach_context(
        manifest,
        context,
        {"type_pack": {"medium_id": "film", "version": "0.1.0"}},
    )
    self.assertNotIn("context", manifest)
    self.assertEqual(enriched["context"]["medium_id"], "film")
    stage_dag.validate_manifest(enriched)

def test_revision_copies_context_but_changes_lineage(self):
    parent = stage_dag._creation_template_manifest()
    parent = stage_dag.attach_context(
        parent,
        CreativeContext("picturebook", project_id="p1"),
        {"type_pack": {"medium_id": "picturebook", "version": "0.5.1"}},
    )
    # The test class defines _complete_revision_requested_parent(), which
    # creates the source artifact and fast-forwards the fixture through the
    # existing confirmation gate helpers.
    revision = self._complete_revision_requested_parent(parent)
    self.assertEqual(revision["context"], parent["context"])
    self.assertEqual(revision["resolution_snapshot"], parent["resolution_snapshot"])
    self.assertNotEqual(revision["run_id"], parent["run_id"])
    self.assertEqual(revision["revision_of_run_id"], parent["run_id"])
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_stage_dag_context.py -v`

Expected: FAIL because manifest context helpers and validation do not exist.

- [ ] **Step 3: Add optional context validation to `stage_dag.py`**

Keep `RUN_SCHEMA` as `pb-stage-run-v2` for this compatibility slice. Validate `context` only when present; preserve all existing stage, outcome, confirmation, migration, and path checks. Validate `resolution_snapshot` as an object containing `type_pack` and optional `knowledge` and `skills` arrays or objects; do not resolve knowledge or skills in this task.

- [ ] **Step 4: Add `attach_context` and `extract_context`**

Use `copy.deepcopy` before enriching manifests. The legacy fallback must not write a synthetic context back into an old manifest unless the caller explicitly invokes `attach_context`.

- [ ] **Step 5: Propagate optional fields through revision creation**

Update `build_revision_manifest` to copy context and resolution snapshot after constructing the revision template. Keep old manifests without these fields valid and leave their revision behavior unchanged.

- [ ] **Step 6: Run the existing stage DAG suite and focused tests**

Run: `python plugins/picturebook-screenwriter/tests/test_stage_dag_context.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag.py -v`

Expected: focused context tests and all existing stage DAG tests pass.

- [ ] **Step 7: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/stage_dag.py plugins/picturebook-screenwriter/tests/test_stage_dag.py plugins/picturebook-screenwriter/tests/test_stage_dag_context.py
git commit -m "feat: add compatible creative context to stage runs"
```

### Task 3: Carry context through Codex dispatch plans and task envelopes

**Files:**
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag_codex.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py`

**Interfaces:**
- `build_dispatch_plan(manifest)`：在现有 `pb-dispatch-plan-v2` 中增加可选的 validated `context` 和 `resolution_snapshot` 字段。
- `format_task_envelope(manifest, stage)`：在现有 `inputs.run_context` 中加入深拷贝的 `creative_context` 和 `resolution_snapshot`。
- `build_sequential_fallback(manifest)`：复用同一字段和校验逻辑，不创建第二套上下文解析路径。

- [ ] **Step 1: Write failing dispatch tests**

```python
def test_dispatch_plan_exposes_validated_context(self):
    manifest = stage_dag.attach_context(
        stage_dag._creation_template_manifest(),
        CreativeContext("film", ("mystery",), project_id="p1"),
        {"type_pack": {"medium_id": "film", "version": "0.1.0"}},
    )
    plan = stage_dag_codex.build_dispatch_plan(manifest)
    self.assertEqual(plan["context"]["medium_id"], "film")
    self.assertEqual(plan["resolution_snapshot"]["type_pack"]["medium_id"], "film")

def test_task_envelope_deep_copies_context(self):
    manifest = stage_dag.attach_context(
        stage_dag._creation_template_manifest(),
        CreativeContext("picturebook", project_id="p1"),
        {"type_pack": {"medium_id": "picturebook", "version": "0.5.1"}},
    )
    task = stage_dag_codex.format_task_envelope(manifest, manifest["stages"][1])
    task["inputs"]["run_context"]["creative_context"]["medium_id"] = "film"
    self.assertEqual(manifest["context"]["medium_id"], "picturebook")
```

- [ ] **Step 2: Run the adapter tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py -v`

Expected: FAIL because the plan and envelope omit the new fields.

- [ ] **Step 3: Add context propagation to the adapter**

Call `stage_dag.extract_context` only after `validate_manifest`. Use JSON-compatible dictionaries produced by `context_to_dict`; never pass mutable manifest references into task envelopes. Preserve existing lead-owned confirmation behavior and current plan schema.

- [ ] **Step 4: Update the existing envelope assertions**

Keep the current `run_context` fields unchanged and assert the new fields alongside them. Add coverage for legacy manifests: they should produce an inferred picturebook context without changing their source manifest.

- [ ] **Step 5: Run adapter and stage DAG tests**

Run: `python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py -v; python plugins/picturebook-screenwriter/tests/test_stage_dag.py -v`

Expected: all adapter and stage DAG tests pass.

- [ ] **Step 6: Commit**

```powershell
git add plugins/picturebook-screenwriter/scripts/stage_dag_codex.py plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py
git commit -m "feat: propagate creative context through dispatch"
```

### Task 4: Declare the foundation contract and entry behavior

**Files:**
- Modify: `plugins/picturebook-screenwriter/config/plugin-contract.json`
- Modify: `plugins/picturebook-screenwriter/skills/picturebook-screenwriter/SKILL.md`
- Modify: `plugins/picturebook-screenwriter/tests/test_plugin_contract.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_skill_contract.py`
- Modify: `plugins/picturebook-screenwriter/README.md`

**Interfaces:**
- Contract field `creative_context` declares `schema_version: "screenwriter-context-v1"`, the four initial `medium_ids`, scope levels, and `legacy_default_medium: "picturebook"`.
- Contract field `type_registry` points to `config/type-packs.json`.
- Contract field `compatibility` declares `legacy_entry_skill`, `legacy_run_schema`, `legacy_task_schema`, and `legacy_knowledge_key_shape`.
- Entry skill documents collecting medium, genre, series and project context, with legacy picturebook inference when an old project has no medium field.

- [ ] **Step 1: Write failing contract and skill tests**

```python
def test_contract_declares_context_and_registry(self):
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    self.assertEqual(contract["creative_context"]["schema_version"], "screenwriter-context-v1")
    self.assertEqual(
        set(contract["creative_context"]["medium_ids"]),
        {"picturebook", "film", "shortdrama", "tv_longform"},
    )
    self.assertEqual(contract["type_registry"], "config/type-packs.json")

def test_entry_documents_context_resolution(self):
    text = ENTRY_SKILL.read_text(encoding="utf-8")
    self.assertIn("medium_id", text)
    self.assertIn("series_id", text)
    self.assertIn("legacy_default_medium", text)
```

- [ ] **Step 2: Run focused contract tests to verify they fail**

Run: `python plugins/picturebook-screenwriter/tests/test_plugin_contract.py -v; python plugins/picturebook-screenwriter/tests/test_skill_contract.py -v`

Expected: FAIL because the contract fields and entry documentation are absent.

- [ ] **Step 3: Add contract metadata and entry documentation**

Keep the current contract schema version and existing artifact, quality, illustration, and write-policy fields. Add only the foundation metadata. State that legacy projects without a medium use the picturebook compatibility path and that new generic projects must declare a medium before type-specific drafting.

- [ ] **Step 4: Update the plugin README capability summary**

Describe the new context/type foundation as an evolving capability while preserving the existing picturebook behavior description. Do not advertise film, shortdrama, or tv_longform as fully supported until their type packs land.

- [ ] **Step 5: Run plugin contract and package checks**

Run: `python plugins/picturebook-screenwriter/tests/test_plugin_contract.py -v; python plugins/picturebook-screenwriter/tests/test_skill_contract.py -v; python scripts/package_check.py`

Expected: all focused tests pass and package validation reports success.

- [ ] **Step 6: Commit**

```powershell
git add plugins/picturebook-screenwriter/config/plugin-contract.json plugins/picturebook-screenwriter/skills/picturebook-screenwriter/SKILL.md plugins/picturebook-screenwriter/tests/test_plugin_contract.py plugins/picturebook-screenwriter/tests/test_skill_contract.py plugins/picturebook-screenwriter/README.md
git commit -m "docs: declare screenwriter context foundation"
```

### Task 5: Add the foundation integration regression and release handoff

**Files:**
- Create: `plugins/picturebook-screenwriter/tests/test_screenwriter_foundation.py`
- Modify: `docs/CHANGELOG.md`

**Interfaces:**
- The integration test loads the registry, enriches the legacy picturebook creation template, validates the manifest, builds a Codex dispatch plan, formats a task envelope, and creates a revision run from the enriched parent.
- The changelog records the new context/type registry foundation and its compatibility boundary.

- [ ] **Step 1: Write the end-to-end regression test**

Exercise this sequence with a `film` context and a separate legacy picturebook manifest:

1. Resolve `film` from `type-packs.json`.
2. Attach the context and type-pack snapshot to a creation manifest.
3. Validate the manifest and build both normal and sequential dispatch plans.
4. Assert the task envelope contains the same context snapshot.
5. Complete a revision-requested parent and assert the revision retains context and lineage.
6. Validate that an untouched legacy manifest still infers `picturebook`.

- [ ] **Step 2: Run the focused integration test to verify it fails before integration is complete**

Run: `python plugins/picturebook-screenwriter/tests/test_screenwriter_foundation.py -v`

Expected: FAIL until all prior tasks are integrated.

- [ ] **Step 3: Fix only integration mismatches**

Keep changes limited to field names, imports, registry loading, and compatibility behavior required by the test. Do not add knowledge inheritance, skill execution, or new type-specific quality rules in this task.

- [ ] **Step 4: Run the complete plugin regression suite**

Run: `python scripts/run_plugin_tests.py`

Expected: all tracked plugin tests pass.

- [ ] **Step 5: Run release checks**

Run: `python scripts/governance_check.py; python scripts/package_check.py`

Expected: both commands exit 0.

- [ ] **Step 6: Update the changelog**

Record that the foundation adds typed creative context, a type-pack registry, optional run metadata, dispatch propagation, and legacy picturebook compatibility. Record that knowledge schema v2, user skills, and additional type packs remain subsequent work.

- [ ] **Step 7: Commit**

```powershell
git add plugins/picturebook-screenwriter/tests/test_screenwriter_foundation.py docs/CHANGELOG.md
git commit -m "test: verify screenwriter foundation compatibility"
```

## Follow-up Plans Deliberately Excluded

The approved domain design covers several independent subsystems. After this foundation slice is reviewed, create separate plans for:

1. Knowledge schema v2, scope inheritance, and `AuthorityQuery`/`page_codec` migration.
2. User skill registry, resolution precedence, conflict audit, and version locking.
3. Type pack contracts and picturebook migration.
4. Film, shortdrama, and tv_longform type packs.
5. Type-specific quality benchmarks, continuity tracking, and export formats.

## Plan Self-Review

- The plan preserves the existing picturebook entry, manifest schema, task schema, artifact aliases, knowledge keys, and confirmation semantics.
- Each task has a focused test cycle and produces an interface consumed by later tasks.
- Context normalization, registry validation, legacy inference, revision lineage, and dispatch deep-copy behavior are explicitly tested.
- Scope inheritance and knowledge/skill resolution are explicitly deferred to separate plans instead of being partially implemented here.
- No task changes remote Feishu data or writes user creative artifacts.
