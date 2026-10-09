# 通用编剧类型能力包与产物契约 v1 设计

**状态：** 修订草案（2026-10-09）
**前置设计：** `docs/superpowers/specs/2026-10-09-general-screenwriter-domain-model-design.md`
**修订原因：** 首轮实施暴露出产物与阶段关系混用、绘本可选插画流程可能被误纳入文本主流程的问题。

## 1. 目标与范围

定义可加载、可验证的媒介类型包契约，使入口能够解析核心产物、可执行工作流、阶段依赖、可选能力和旧别名。首期把现有绘本编剧流程作为核心工作流，把已有独立插画 DAG 作为显式选择的可选工作流。短剧和长篇连续剧仍只注册为 `planned`，不实现其流程。

本修订只处理类型能力包与产物契约，不实现知识库 schema v2、用户技能中心、其他媒介工作流、质量基准迁移或 UI。

## 2. 依据与兼容边界

已有权威材料确定：

- 六个绘本 artifact type 是 `positioning`、`topic_plan`、`worldview`、`characters`、`outline`、`script`；入口按单个目标产物进入创作，不表示一次 run 必须依次产出全部六项。
- `positioning` 对应创作简报/brief 输入；它不应被声明为 `brief_gate` 阶段的产出。
- creation/revision DAG 有自己的必需阶段、confirmation gate 和批准后 persistence。
- 插画使用单独的 `illustration-template` 和 `illustration` 意图，有独立的 `asset_confirmation`、`asset_final_confirmation`；它只能在已有批准脚本或用户明确提供脚本后启动。
- 旧入口、六类产物名、`pb-stage-run-v2`、`pb-stage-task-v1`、确认结果和 revision 行为继续可读。

现有资料**没有定义六类产物之间必须存在的全局先后依赖图**。因此 v1 不根据列举顺序推断强制依赖；`depends_on` 表示显式的产物来源/前置引用，未被权威规则确认时保持空数组。它不是阶段调度边。阶段调度边只由 workflow 内 `StageContract.depends_on` 表示。

## 3. 契约模型

### 3.1 核心产物 `ArtifactDescriptor`

```text
ArtifactDescriptor
├── artifact_id: string
├── aliases: string[]
├── delivery_forms: string[]
├── depends_on: string[]              # 产物来源/前置引用，不是阶段 DAG 边
├── origin: user_input | workflow_output
├── input_stage: string | null        # 用户输入被哪个阶段读取
├── production_stage: string | null   # 由哪个阶段产生；user_input 必须为 null
├── validation_stages: string[]
├── validator: string | null
├── exporter: string | null
└── status: active | planned
```

`positioning` 声明为 `origin=user_input`、`input_stage=brief_gate`、`production_stage=null`。其余五类是可选的单 run 目标类型，由 `creation_delegate` 根据 manifest 的 `artifact_type` 产出；`preflight` 和 `qa` 验证本次选中的目标，而不是声称每个阶段都生产所有产物。`collision_check` 可声明读取选中产物用于与权威知识核对，不因此成为产物 producer。

第一版不硬编码六类 artifact 之间的递进边。后续只有在权威规则或具体项目输入明确要求时，才把对应前置 artifact 写入 `depends_on`/run 输入引用。

### 3.2 核心阶段 `StageContract`

```text
StageContract
├── stage_id: string
├── aliases: string[]
├── depends_on: string[]
├── consumes_artifact_ids: string[]
├── produces_artifact_ids: string[]
├── validates_artifact_ids: string[]
├── confirmation_required: boolean
└── status: active | planned
```

三个 artifact 字段的语义严格分开：

- `consumes_artifact_ids`：阶段读取的既有输入。
- `produces_artifact_ids`：阶段新建或更新的输出。
- `validates_artifact_ids`：阶段检查的输入，不表示生产。

`creation_delegate.produces_artifact_ids` 是允许作为单 run 目标的集合；实际每次 run 只允许由 `manifest.artifact_type` 选定其中一个目标。阶段依赖必须引用同一 workflow 声明的阶段，并且 DAG 无环。产物的 `production_stage` 与各 `validation_stages` 必须引用对应 workflow 中的阶段。

绘本核心流程只声明当前 creation/revision DAG 的必需执行阶段。确认门的 `approved` 才解锁 persistence；`revision_requested` 不持久化，创建新的 revision run；`cancelled` 终止。阶段模型不新增“optional stage”以免误改现有 completion 语义。

### 3.3 可选工作流 `WorkflowContract`

```text
WorkflowInputRequirement
├── artifact_id: string
└── required_status: string  # illustration 输入固定为 approved

WorkflowContract
├── workflow_id: string
├── trigger_intent: string
├── inputs: WorkflowInputRequirement[]  # artifact_id + required_status
├── artifact_types: ArtifactDescriptor[]
├── stages: StageContract[]
├── required: boolean
└── blocks_core_completion: boolean
```

绘本 `illustration` 是独立 optional workflow：`trigger_intent=illustration`、输入要求为 `approved` 状态的 `script`、`required=false`、`blocks_core_completion=false`。它映射现有独立八阶段 `illustration-template`：`illustration_init`、`asset_extraction`、`asset_confirmation`、`asset_preproduction`、`asset_final_confirmation`、`illustration_generation`、`html_export`、`illustration_delivery`，包括两道人类确认门。四类插画/导出交付物只在该 workflow 声明：

- `asset_registry`：`asset_extraction` 产出的资产清单；
- `illustration_prompt_payload`：`asset_preproduction` 产出的结构化提示；
- `image_asset`：`illustration_generation` 产出的图片；
- `html_preview`：`html_export` 产出的预览。

这些产物和阶段不会加入文本 creation/revision 的核心 DAG。用户未显式启动插画工作流时，它不参与文本 run 的 ready、completion、approved persistence 或 revision 判断。工作流一旦启动，其内部确认与阶段依赖仍严格执行；“可选”指整个工作流相对文本创作可选，不表示内部步骤可跳过。

## 4. 类型包模型与状态

```text
TypePackDescriptor
├── medium_id, version, aliases, legacy_aliases
├── delivery_forms
├── artifact_types: ArtifactDescriptor[]  # 核心产物
├── stages: StageContract[]                # 核心 workflow 阶段
├── optional_workflows: WorkflowContract[]
├── workflow_policy
├── validators, exporters, capabilities
└── status: active | planned
```

`active` 表示契约本身可以用于执行，必须具备版本、workflow policy、至少一个核心阶段和至少一个核心产物。只含类型 ID、无产物和阶段的空 active 包必须在加载期拒绝。为旧配置兼容，旧版“字符串 artifact_types + 无 stages”的非空配置可读取为 legacy descriptor，但不得把它误认为完整 v1 执行契约。

`planned` 包可以读取和展示，不可生成 dispatch plan 或 task envelope。解析成功不代表可执行。配置中的 validator/exporter 仅是注册标识，不动态导入代码。

## 5. 类型与产物解析

接口：

```python
load_type_registry(path=None) -> TypeRegistry
resolve_type_pack(registry, identifier) -> TypePackDescriptor
resolve_artifact(type_pack, identifier) -> ArtifactDescriptor  # core artifacts only
resolve_workflow_artifact(workflow, identifier) -> ArtifactDescriptor  # scoped to one optional workflow
resolve_stage(workflow, identifier) -> StageContract
resolve_workflow(type_pack, workflow_id_or_intent) -> WorkflowContract
assert_core_artifact_target(type_pack, artifact_id) -> ArtifactDescriptor
assert_type_pack_executable(type_pack) -> None
validate_type_contract(type_pack) -> TypePackDescriptor
```

ID、alias 和 legacy alias 在各自命名空间内唯一；产物、阶段的 alias 不得冲突或遮蔽 type ID/alias。跨引用必须指向已声明对象。解析结果为不可变对象或隔离副本。未知 type、artifact、stage 和 workflow 使用可区分的错误。

## 6. Run snapshot 与 dispatch

新 run 的可选 `resolution_snapshot` 至少记录 `type_pack.medium_id/version/workflow_policy` 和选中的 `artifact_id/delivery_form`；插画 run 另可记录 `workflow_id`。manifest 校验确认 snapshot 与 context、目标类型和目标交付形式一致。

snapshot 由 revision 深拷贝继承；dispatch plan/task envelope 只携带已校验快照副本。旧 manifest 无 context/snapshot 时保持原样，不自动补写。

只有显式 context 的 run 才按类型包状态执行 gate。旧无 context manifest 继续使用现有 `picturebook` 兼容路径。对于插画 workflow，dispatch 使用独立 `illustration` DAG；不将其阶段合并到文本 DAG。

## 7. 加载期校验

拒绝：

- 空 active v1 类型包，或 active v1 包缺版本、策略、核心 stages 或核心 artifacts；
- 重复/空的 type、artifact、stage、workflow ID 或 alias；
- artifact 引用未知的 input/production/validation stage 或未知 artifact dependency；
- stage 引用未知的 stage/artifact；
- unsupported delivery form、无效状态、类型包遮蔽/别名冲突；
- workflow stage 图存在环；
- optional workflow 声明 `blocks_core_completion=true`，或其阶段混入核心 workflow；
- `origin=user_input` 却声明 producer，或 `origin=workflow_output` 缺 producer stage。

错误信息包含对象类别与具体标识。

## 8. 测试设计

1. 旧字符串产物列表仍能兼容读取，完整 v1 契约规范化为不可变对象。
2. 空 active 类型包加载失败；四种首批媒介中仅绘本 active，其余 planned 且不可执行。
3. 六类绘本核心产物均被声明；`positioning` 是 brief 输入，不是 `brief_gate` 输出；creation_delegate 每 run 输出由 manifest 指定的单个目标，preflight/qa 是校验者。
4. 四个插画/导出 artifact 只存在于独立的 optional illustration workflow；该 workflow 不阻塞无插画的文本 run 完成。
5. 插画 workflow input requirement 明确 `script` 必须为 `approved`；仍保留资产确认和最终确认门。
6. stage/artifact 引用、重复 alias、非法 delivery form、DAG 环和 workflow 混入均加载失败。
7. 类型、产物、阶段、workflow 的 ID/alias resolver 错误类型可区分。
8. resolution snapshot、revision 和 dispatch 副本的兼容性与隔离性保持。
9. 无 context 的旧绘本 manifest 和现有 creation/revision/illustration DAG 回归不变。

## 9. 分阶段实施

1. 修正 descriptor 模型：显式区分产物来源/生产/校验，阶段消费/产出/校验，可选 workflow。
2. 修正 `type-packs.json`：以现有 DAG 为参照，仅将必需文本流程放在 core；插画内容迁移到独立 optional workflow；拒绝空 active v1 包。
3. 完成 type/artifact/stage/workflow resolver 和全部加载校验。
4. 将选中的类型、目标产物及可选 workflow ID 写入 run resolution snapshot；保持旧数据语义。
5. 在派发入口拒绝 planned 类型；保证未 optional 的 optional workflow 不会进入 core DAG 或阻塞 core completion。
6. 更新契约元数据和中文操作文档；运行全量回归、治理和打包检查。

## 10. 验收标准

- 绘本是非空、完整、可执行的 active v1 包；空 active v1 包拒绝加载。
- 六类绘本核心 artifact 与其输入/产出/校验语义不混淆。
- 四类插画/导出 artifact 只属于独立 optional workflow；无插画的文本 run 可按既有确认与持久化规则完成。
- planned 类型不派发；resolution snapshot 精确并由 revision/dispatch 隔离继承。
- 旧入口、artifact alias、manifest、确认门和 revision 兼容。
- 全量离线测试通过；文档说明后续专项为知识库 schema v2。

## 11. 实现复核补充（2026-10-09）

实施后独立代码复核确认：旧类型包快照虽然要可读，但显式 context 的执行/派发必须匹配当前 type-pack version；planned 类型不能从任一公开 DAG 调度或状态迁移入口取得可执行批次。`artifact_type` 在核心 run 必须是 active 核心输出，不能是简报输入或插画产物；插画必须使用自己的八阶段 DAG。

对于显式 context 的插画 run，`resolution_snapshot.workflow_inputs` 记录 `script` 的来源证据：`status=approved` 且有非空 `ref`；或用户明确提供时 `status=user_supplied`、非空 `ref`、`user_confirmation=true`。这只是运行时来源声明的结构校验，不替代主编核实用户确认或证明引用文件确实已批准。无该声明不派发插画；旧 manifest 的读取不补写此字段。artifact/stage ID 与 alias 在同一类型包的解析作用域内不能交叉冲突。
