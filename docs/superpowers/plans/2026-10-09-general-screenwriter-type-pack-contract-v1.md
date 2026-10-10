# 通用编剧类型能力包与产物契约 v1 实施计划（修订）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 建立类型明确、阶段语义可验证的绘本核心契约和独立可选插画 workflow，保持旧绘本行为兼容，并阻止空 active 包或 planned 媒介被错误执行。

**Architecture:** 在已有类型 registry 基础上，将 artifact 的来源/生产/校验语义与 stage 的消费/产出/校验语义显式分开；把现有绘本 creation/revision DAG 作为核心 workflow，把已有 illustration DAG 作为 `required=false` 且 `blocks_core_completion=false` 的独立 workflow。类型解析和 run snapshot 只读，不替换现有阶段状态机与确认门。

**Tech Stack:** Python 3.10+ 标准库、冻结 dataclasses、JSON、`unittest`、既有 stage DAG 和 Codex dispatch adapter。

**Spec:** `docs/superpowers/specs/2026-10-09-general-screenwriter-type-pack-contract-design.md`

## 已发生的实现基线

此前 Native 执行已在当前 `main` 分支生成两个提交：

- `0f2faa9 feat: add type pack contract models`
- `b2b5cf1 feat: validate type pack artifacts and stages`

两者已被追踪，不做 reset/rebase；它们的产物/阶段映射正在本修订中被校正。后续更改使用新的、范围清晰的提交；不纳入 `.sdd-temp-screenwriter-foundation/` 或其他无关文件。

## Global Constraints

- 保留 `picturebook-screenwriter` 入口、六个旧核心 artifact ID、`pb-stage-run-v2`、`pb-stage-task-v1` 和旧无 context manifest 行为。
- `positioning` 是 `brief_gate` 读取的用户简报输入，不是 `brief_gate` 产出。
- artifact 的 `depends_on` 是产物来源/前置引用；stage 的 `depends_on` 才是调度依赖。两者不得混用。
- 现有资料未定义六类核心 artifact 的强制先后依赖；v1 不按列表顺序虚构依赖。未有权威依据时，配置中的 artifact `depends_on` 保持空。
- 本次创建/revision 每个 run 的 `creation_delegate` 只产出 `manifest.artifact_type` 选定的一个核心 artifact；preflight、collision check、QA 是消费/校验，不是产出。
- 插画四类 deliverables 和其八阶段只属于独立 optional illustration workflow，不进入文本 core stages，不阻塞文本 run completion。
- `active` v1 类型包必须有非空 core artifacts 和 core stages；planned 类型可读但不可派发。非空旧字符串格式配置仍兼容读取。
- 配置中的 validator/exporter 只作为标识，不动态导入；不新增第三方运行时依赖，不修改远端知识库。
- 必须先写失败测试再实现；每项测试观察到预期失败后才继续。

## Review Focus

- **阶段字段语义混用**：分别校验 consumes/produces/validates，`brief_gate` 不会生产 positioning。
- **空 active 包**：带版本和策略但无 core artifact/stage 的新 active 包必须拒绝加载；旧非空字符串包仍兼容。
- **可选插画阻塞文本完成**：未启动插画时 core manifest 可独立完成，插画 stages 不进入 creation/revision template。
- **artifact 与 stage 依赖混淆**：artifact 来源引用不要求 stage ID 先后；stage graph 必须无环且 workflow 内引用完整。
- **已有提交和工作区隔离**：不改写前述提交；不触碰 `.sdd-temp-screenwriter-foundation/`。

---

### Task 1: 校正不可变契约模型的 artifact/stage/workflow 语义

**Files:**
- Modify: `plugins/picturebook-screenwriter/scripts/type_registry.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_type_contract_models.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_type_registry.py`

**Interfaces:**
- `ArtifactDescriptor(artifact_id, aliases, delivery_forms, depends_on, origin, input_stage, production_stage, validation_stages, validator, exporter, status)`。
- `StageContract(stage_id, aliases, depends_on, consumes_artifact_ids, produces_artifact_ids, validates_artifact_ids, confirmation_required, status)`。
- `WorkflowInputRequirement(artifact_id, required_status)`：冻结输入要求对象。
- `WorkflowContract(workflow_id, trigger_intent, inputs, artifact_types, stages, required, blocks_core_completion)`：冻结 workflow 对象。
- `TypePackDescriptor` 保留 `artifact_ids` legacy projection，新增 `optional_workflows`；`stages` 始终只表示核心 workflow 阶段。
- `resolve_workflow(type_pack, workflow_id_or_intent) -> WorkflowContract`；`resolve_workflow_artifact(workflow, identifier) -> ArtifactDescriptor`。
- [x] **Step 1: Add failing model tests**

  覆盖：ArtifactDescriptor、StageContract、WorkflowInputRequirement、WorkflowContract 均不可变；阶段的 consumes/produces/validates 是独立 tuple；`positioning` 可表示为 user input 且无 producer；输入要求能绑定 artifact 与 `approved` 状态；workflow 有独立 stages；旧 `artifact_ids` 投影仍返回六个旧 ID。

- [x] **Step 2: Run model tests and observe expected missing-field/API failures**

  Run: `python plugins/picturebook-screenwriter/tests/test_type_contract_models.py`

  Expected: FAIL because explicit workflow/origin/stage-direction fields are absent.

- [x] **Step 3: Implement the minimal frozen model changes**

  在 `type_registry.py` 增加/扩展上述 frozen dataclasses 和错误类型，声明 workflow resolver；保留已有 `TypePackDescriptor.artifact_ids` 行为。此步骤不改配置解析，也不实现 target eligibility 检查。

- [x] **Step 4: Run model plus legacy registry tests**

  Run: `python plugins/picturebook-screenwriter/tests/test_type_contract_models.py; python plugins/picturebook-screenwriter/tests/test_type_registry.py`

  Expected: model tests pass; 旧字符串 registry tests 继续通过。

- [x] **Step 5: Commit model semantics**

  ```powershell
  git add plugins/picturebook-screenwriter/scripts/type_registry.py plugins/picturebook-screenwriter/tests/test_type_contract_models.py plugins/picturebook-screenwriter/tests/test_type_registry.py
  git commit -m "refactor: separate artifact and workflow contract semantics"
  ```

### Task 2: 校正绘本参考配置、拒绝空 active 包并隔离可选插画 workflow

**Files:**
- Modify: `plugins/picturebook-screenwriter/config/type-packs.json`
- Modify: `plugins/picturebook-screenwriter/scripts/type_registry.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_type_registry.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_stage_dag.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_screenwriter_foundation.py`

**Interfaces:**
- `parse_type_registry(payload) -> TypeRegistry`：兼容旧字符串 artifact 配置；严格解析 v1 core artifacts/stages/optional_workflows。
- `validate_type_contract(type_pack) -> TypePackDescriptor`：检查 active v1 非空、引用完整、阶段图区分明确、optional workflow 不阻塞 core。
- `resolve_workflow(type_pack, workflow_id_or_intent) -> WorkflowContract`；`resolve_workflow_artifact(workflow, identifier) -> ArtifactDescriptor`。
- `assert_core_artifact_target(type_pack, artifact_id) -> ArtifactDescriptor`：只接受 active 的 `workflow_output` 核心目标；拒绝 input-only `positioning` 和 optional-workflow artifacts。

- [x] **Step 1: Add failing contract and runtime regression tests**

  覆盖：
  - 空的 active v1 类型包（有版本/策略，但 core artifact 和 stage 都为空）加载失败；
  - optional workflow 的 `required=false` 且 `blocks_core_completion=false` 时不进入 core graph；若 `required=false` 却声明 `blocks_core_completion=true` 则加载失败；
  - 旧非空字符串 artifact 配置仍可解析；
  - `positioning` 的 origin 为 user input、input stage 是 `brief_gate`、production stage 为 null；
  - `creation_delegate.produces_artifact_ids` 是五个可创作目标；`assert_core_artifact_target` 只允许单个 run 选择其中一个，拒绝 input-only `positioning` 和 optional artifacts；`preflight`/`qa` 对目标做 validate；
  - optional illustration workflow 有独立八阶段（`illustration_init` 至 `illustration_delivery`），四个插画 artifact 只在其下；`blocks_core_completion=false`；
  - core stage 不引用插画 stages；文本 creation template 在没有插画 workflow 时仍可走 approved persistence 并完成，证明 required=false optional workflow 不阻塞 core completion；
  - 插画 workflow 的 input requirement 要求 `script` status=`approved`，保留 `asset_confirmation` 与 `asset_final_confirmation`。

- [x] **Step 2: Run focused tests and observe the contract failures**

  Run: `python plugins/picturebook-screenwriter/tests/test_type_registry.py; python plugins/picturebook-screenwriter/tests/test_stage_dag.py; python plugins/picturebook-screenwriter/tests/test_screenwriter_foundation.py`

  Expected: FAIL on bad current artifact/stage mappings, missing empty-active rejection and missing optional-workflow isolation.

- [x] **Step 3: Correct `type-packs.json` as the reference contract**

  将 `positioning` 映射为 `brief_gate` 的 user input；将 topic_plan/worldview/characters/outline/script 声明为 `creation_delegate` 可按 run 目标选择的输出、由 preflight/collision_check/qa 消费或校验；不依据列表顺序添加未证实的 artifact dependencies。把 `asset_registry`、`illustration_prompt_payload`、`image_asset`、`html_preview` 和现有八个 illustration stage 单独放入 optional illustration workflow，明确不可阻塞 core completion。

- [x] **Step 4: Implement schema normalization and semantic validation**

  解析 core 与 optional workflow descriptor；验证 user-input/output producer 规则、所有 stage/artifact 引用、stage DAG 无环、alias 不冲突；实现 `assert_core_artifact_target` 以拒绝 input-only 和 optional target；拒绝空 active v1 包和 `required=false` 且 `blocks_core_completion=true` 的 optional workflow。旧格式识别为 legacy descriptor 并保留读取语义。

- [x] **Step 5: Verify the focused contract and text-only completion regressions**

  Run: `python plugins/picturebook-screenwriter/tests/test_type_registry.py; python plugins/picturebook-screenwriter/tests/test_stage_dag.py; python plugins/picturebook-screenwriter/tests/test_screenwriter_foundation.py`

  Expected: all pass；text-only approved flow 不要求构造 illustration run。

- [x] **Step 6: Commit only the Task 2 correction**

  ```powershell
  git add plugins/picturebook-screenwriter/config/type-packs.json plugins/picturebook-screenwriter/scripts/type_registry.py plugins/picturebook-screenwriter/tests/test_type_registry.py plugins/picturebook-screenwriter/tests/test_stage_dag.py plugins/picturebook-screenwriter/tests/test_screenwriter_foundation.py
  git commit -m "fix: isolate optional illustration workflow contract"
  ```

### Task 3: 接入类型、artifact 与 workflow resolution snapshot

**Files:**
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag.py`
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag_codex.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_stage_dag_context.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py`
- Create: `plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py`

**Interfaces:**
- `build_resolution_snapshot(type_pack, artifact=None, workflow=None) -> dict`。
- snapshot `type_pack` 记录 `medium_id/version/workflow_policy`；可选 `artifact` 记录 `artifact_id/delivery_form`；可选 `workflow` 记录 `workflow_id/trigger_intent`。
- 旧 snapshot 形状继续读取；新增类型字段须与 context、artifact、workflow 一致。

- [x] **Step 1: Add failing snapshot, isolation, and revision tests**

  `test_type_pack_snapshot.py` 覆盖：builder 输出精确的 type_pack、artifact、workflow 三块快照；错误 medium/artifact/workflow 被拒绝；旧 snapshot 两字段形状通过；revision 继承 snapshot 且修改子对象不影响 parent；无 snapshot 的旧 manifest revision 不增加 snapshot；dispatch plan、task envelope 和 sequential fallback 都深拷贝 snapshot。

- [x] **Step 2: Run snapshot tests and observe missing builder/validation behavior**

  Run: `python plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py`

  Expected: FAIL because builder and artifact/workflow snapshot validation are absent.

- [x] **Step 3: Implement builder and additive snapshot validation without rewriting old manifests**

  `stage_dag.build_resolution_snapshot(type_pack, artifact=None, workflow=None)` 仅接受属于对应包/工作流的 immutable descriptors；manifest validator 允许旧 `{type_pack, knowledge, skills}` 和新增 optional `artifact`、`workflow`，验证 context medium 与 snapshot medium 一致。不要自动添加缺失字段。

- [x] **Step 4: Verify revision, plan, task-envelope, and sequential-fallback deep copies**

  对每个输出 snapshot 的嵌套对象做修改，断言原 manifest、parent run 和兄弟 envelope 均不变；revision lineage 仍更新为新 run。
- [x] **Step 5: Run snapshot and all stage DAG tests**

  Run: `python plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py; python plugins/picturebook-screenwriter/tests/test_stage_dag_context.py; python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py; python plugins/picturebook-screenwriter/tests/test_stage_dag.py`

  Expected: all pass; legacy revisions without snapshot do not gain one.

- [x] **Step 6: Commit**

  ```powershell
  git add plugins/picturebook-screenwriter/scripts/stage_dag.py plugins/picturebook-screenwriter/scripts/stage_dag_codex.py plugins/picturebook-screenwriter/tests/test_stage_dag_context.py plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py plugins/picturebook-screenwriter/tests/test_type_pack_snapshot.py
  git commit -m "feat: persist type pack resolution snapshots"
  ```

### Task 4: 加入 planned 类型执行门并验证 optional workflow 路由隔离

**Files:**
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag.py`
- Modify: `plugins/picturebook-screenwriter/scripts/stage_dag_codex.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py`
- Create: `plugins/picturebook-screenwriter/tests/test_type_pack_execution_gate.py`

- [x] **Step 1: Add failing tests for planned dispatch rejection and legacy picturebook fallback**

  `test_type_pack_execution_gate.py` 为 shortdrama、tv_longform 创建合法 project context manifest，断言 `build_dispatch_plan` 和 `format_task_envelope` 均在生成输出前抛出 `TypePackNotExecutableError`；同时覆盖无 context 的旧绘本模板和显式 picturebook manifest 可派发。

- [x] **Step 2: Run the gate tests and observe planned packs are currently dispatched**

  Run: `python plugins/picturebook-screenwriter/tests/test_type_pack_execution_gate.py`

  Expected: FAIL because dispatch/task-envelope boundaries do not yet gate type status.

- [x] **Step 3: Add a shared executable-pack assertion at dispatch and task-envelope boundaries**

  在 `stage_dag.assert_manifest_type_executable(manifest)` 中只对显式 context 解析 registry 并调用 executable assertion；Codex plan 和 envelope 构造在创建输出前调用它。未知 medium 或 registry 错误不得回退成 picturebook；无 context 旧 manifest 保持兼容。

- [x] **Step 4: Verify illustration intent resolves only to its separate workflow and never appends stages to text creation DAG**

  断言 illustration workflow 的 stage IDs 与 creation-template stage IDs 分离；workflow `required=false` 且 `blocks_core_completion=false`，input requirement 要求 `script` status=`approved`；未启动 illustration workflow 的 core creation run 可独立完成。
- [x] **Step 5: Run planned gate, existing dispatch, and foundation regression tests**

  Run: `python plugins/picturebook-screenwriter/tests/test_type_pack_execution_gate.py; python plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py; python plugins/picturebook-screenwriter/tests/test_screenwriter_foundation.py`

  Expected: all pass。

- [x] **Step 6: Commit**

  ```powershell
  git add plugins/picturebook-screenwriter/scripts/stage_dag.py plugins/picturebook-screenwriter/scripts/stage_dag_codex.py plugins/picturebook-screenwriter/tests/test_stage_dag_codex.py plugins/picturebook-screenwriter/tests/test_type_pack_execution_gate.py
  git commit -m "feat: gate planned type pack execution"
  ```

### Task 5: 更新契约说明并完成全量验收

**Files:**
- Modify: `plugins/picturebook-screenwriter/config/plugin-contract.json`
- Modify: `plugins/picturebook-screenwriter/README.md`
- Modify: `plugins/picturebook-screenwriter/skills/picturebook-screenwriter/SKILL.md`
- Modify: `plugins/picturebook-screenwriter/tests/test_plugin_contract.py`
- Modify: `plugins/picturebook-screenwriter/tests/test_skill_contract.py`
- Modify: `docs/CHANGELOG.md`

- [x] **Step 1: Add failing contract/doc assertions for core vs optional workflows and planned media**

  在 `test_plugin_contract.py` 断言契约版本和唯一 active medium；在 `test_skill_contract.py` 断言 approved script 是 illustration workflow 输入，四个插画 artifact 不在 core 输出列表，shortdrama/tv_longform 标记 planned。
- [x] **Step 2: Update metadata and Chinese operator guidance without claiming planned packs are executable**
- [x] **Step 3: Run focused plugin contract tests**

  Run: `python plugins/picturebook-screenwriter/tests/test_plugin_contract.py; python plugins/picturebook-screenwriter/tests/test_skill_contract.py`

  Expected: all pass。

- [x] **Step 4: Run complete offline regression**

  Run: `python .\\scripts\\run_plugin_tests.py`

  Expected: exit 0; all registered offline Python/Node/regression checks pass。

- [x] **Step 5: Run governance and packaging checks**

  Run: `python .\\scripts\\test_governance_check.py; python .\\scripts\\test_package_check.py`

  Expected: both exit 0。

- [x] **Step 6: Review changed files and commit documentation**

  确认 diff 不包含 `.sdd-temp-screenwriter-foundation/`、远端知识库写入或用户创作产物；确认旧 aliases、DAG confirmation/revision 语义保持兼容。记录后续专项为知识库 schema v2。

  ```powershell
  git add plugins/picturebook-screenwriter/config/plugin-contract.json plugins/picturebook-screenwriter/README.md plugins/picturebook-screenwriter/skills/picturebook-screenwriter/SKILL.md plugins/picturebook-screenwriter/tests/test_plugin_contract.py plugins/picturebook-screenwriter/tests/test_skill_contract.py docs/CHANGELOG.md
  git commit -m "docs: document type pack contract foundation"
  ```

## Completion Checklist

- [x] 新 active v1 type pack 为空时加载失败；legacy 非空配置仍读取。
- [x] positioning 是简报输入；core stages 的 consumed/produced/validated 语义正确。
- [x] artifact dependency 不被解释成 stage ordering；没有权威规则的边保持空。
- [x] 插画 artifacts 和 stages 隔离在 optional workflow，不阻塞文本 run。
- [x] 只有 run 目标 artifact 被 creation delegate 产出。
- [x] planned media 不会派发；legacy 绘本 context/manifest/revision 兼容。
- [x] snapshot、测试、治理与打包检查通过。
- [x] Git diff 不含 `.sdd-temp-screenwriter-foundation/`。

## Plan Self-Review

- **Spec coverage:** model semantics in Task 1; configuration/reference validation and empty-active/optional-workflow regressions in Task 2; snapshots in Task 3; executable gate in Task 4; public contract and full validation in Task 5.
- **Test coverage:** Review Focus items map to Tasks 1-4; text-only approval/completion explicitly proves optional work is non-blocking.
- **Type consistency:** ArtifactDescriptor/StageContract/WorkflowContract names and resolver signatures are stable across tasks.
- **Compatibility:** old string registries and old run manifests remain explicit test cases; prior commits are preserved.
- **Scope:** no unrelated files, remote writes, other media workflows, or feature work beyond this contract.

## 整分支复核修复轮（2026-10-09）

独立审查发现五项 Important：公开 DAG 调度绕过 planned gate；历史快照仍可执行；显式 context 可派发输入-only 或错误 workflow；插画未声明脚本来源也可派发；artifact 与 stage alias 跨类别冲突。统一增加先失败后通过的回归测试 `test_type_pack_review_regression.py`，将执行门扩展到公开调度/状态迁移，并在独立插画快照中要求 `workflow_inputs` 来源声明。旧 manifest 仍保持只读兼容；当前版本重新解析后方可执行。详情见本计划的执行 ledger；这次修复未改动其他媒介工作流和远端知识库。
