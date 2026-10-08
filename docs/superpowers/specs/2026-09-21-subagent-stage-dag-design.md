# 阶段化子 Agent 协作调度设计

日期：2026-09-21  
状态：待评审（方案 A：受控阶段 DAG + 主编星型中转）

## 1. 背景与问题

当前插件已经具备五人专家团与 9 步创作管线：主编负责意图识别、简报、调度、确认门、状态管理与落盘；编剧、质检、知识管理、美术通过 `SendMessage` 回传结果。但这套结构仍是“角色级团队”，不是“阶段级可调度工作流”：

| 环节 | 当前状态 |
|---|---|
| 文字创作、质检、知识消费、插画与 HTML 导出 | 已可派发专职成员 |
| Phase 0 初始化、简报框架、产出前自检、确认门、落盘、进度管理 | 主要由主编执行 |
| 轻量/脑暴模式 | 显式跳过 TeamCreate 与子 Agent |
| 子 Agent 协作 | 只能通过主编中转，不允许直连 |
| Codex 运行时 | 当前会话未暴露多 Agent 工具；插件现有协议主要面向 WorkBuddy |

结果是可以完成业务流程，但主编上下文过重、阶段边界不显式、并行机会不稳定、Codex 侧缺少可复用的运行时适配。

## 2. 目标与非目标

### 目标

1. 把创作、质检、知识、插画、HTML 导出、初始化、自检、落盘等主要工作环节纳入显式阶段 DAG。
2. 每个阶段都有明确负责人、输入、输出、状态、依赖和门禁，可被主编派发给 subagent。
3. 保留主编作为用户交互、用户确认、冲突裁决、任务编排的唯一入口。
4. 允许多个 subagent 在无共享写路径冲突时并行执行。
5. 子 Agent 之间的协作仍通过结构化请求和主编中转实现，不开放任意点对点直连。
6. 为 WorkBuddy 与 Codex 提供可适配的任务信封与结果信封。
7. 不破坏既有全局硬性约束，包括飞书源库只读、AI 库唯一写通道、生图仅归美术、产物默认不落盘、权威版本锁定和确认门机制。

### 非目标

1. 不做子 Agent 之间的自由直连协作。
2. 不把最终确认门、最终裁决、外链确认、知识库地址变更、生图授权、权威冲突裁决下放给子 Agent。
3. 不在本 spec 内实现具体代码。
4. 不重写现有五人专家团角色；先在既有角色上扩展工作型 Agent 与任务协议。
5. 不引入新的知识库权威；KB-AI 仍是结构化知识的共享权威。

## 3. 设计原则

1. **阶段优先**：把每个工作步骤建模为可独立调度的 stage，而不是继续把多个职责塞进主编单回合。
2. **专职 Agent 优先**：专业产出由对应专职成员完成，主编只做编排、校验与用户呈现。
3. **受控协作**：协作表现为结构化消息，不表现为共享上下文或互相改文件。
4. **文件写权隔离**：每个 Agent 只能写自己的输出目录；跨 Agent 状态合并由主编或专门的持久化 Agent 执行。
5. **门禁不可绕过**：简报门、确认门、质检门、外链门禁、飞书写锁、生图授权继续按 SYSTEM.md 的全局硬性约束执行。
6. **降级必须显式**：运行时不具备多 Agent 能力时，只能先向用户声明降级为顺序执行，不能中途静默切换。

## 4. 总体架构

### 4.1 三层结构

```text
用户
  ↓
主编 / 调度层 picturebook-screenwriter-team-lead
  - 意图确认
  - 阶段 DAG 调度
  - 用户确认门
  - 冲突裁决
  - 结果汇总
  ↓
阶段 Agent / 专职 Agent
  - pb-intake-agent
  - pb-preflight-agent
  - pb-persistence-agent
  - pb-screenwriter
  - pb-quality-reviewer
  - pb-knowledge-steward
  - picturebook-art-agent
  ↓
运行时适配层
  - WorkBuddy: TeamCreate / Agent / SendMessage / TaskOutput
  - Codex: spawn_agent / followup_task / wait_agent / list_agents（若启用）
```

主编仍然面向用户；阶段 Agent 不直接面向用户。需要用户决策时，阶段 Agent 发送 `[CONFIRMATION_REQUIRED]`，由主编呈现给用户并回传决策。

### 4.2 通信拓扑

保留星型拓扑：

```text
stage A ──→ lead ──→ stage B
stage B ──→ lead ──→ stage C
stage A ──→ lead ──→ stage C
```

协作消息中的 `logical_target` 表示业务接收者，但物理发送方仍然是主编。这样可以在不开放直连的前提下表达“编剧请知识管理补检索”或“编剧请质检做阶段内预审”。

### 4.3 并行模型

阶段 DAG 中，只有满足以下条件才可并行：

1. 没有循环依赖。
2. 输入已经就绪。
3. 各 Agent 的输出目录互不重叠。
4. 不存在必须由用户先裁决的 pending 门禁。
5. 不需要共享同一份可变状态。

典型并行点：

| 阶段组 | 并行原因 |
|---|---|
| Phase 0 工作空间勘察 + 知识预检 | 无共享写路径 |
| Step 1 简报缺失项分析 + Step 2 knowledge 预装载 | 简报补全不改变知识页内容 |
| Step 4 确定性检查 + Step 4b 撞车检测 | 输入相同，但输出独立 |
| 多视角质检 | 每个视角产出独立报告 |
| 多页插画 / 多资产素材图 | 每页或每资产输出互不重叠 |

## 5. 阶段 DAG

以下为默认 creation 全流程 DAG。`revision`、`review`、`knowledge`、`illustration` 可以按意图裁剪为子图。

| Stage ID | 名称 | 负责人 | 可派发 | 依赖 | 门禁 |
|---|---|---|---|---|---|
| `session_init` | 会话初始化 | `pb-intake-agent` | 是 | 无 | 无 |
| `brief_gate` | 简报完整性 | `pb-intake-agent` | 是 | `session_init` | 简报门 |
| `knowledge_load` | 权威知识装载 | `pb-knowledge-steward` | 是 | `session_init` | authority 完整性 |
| `creation_delegate` | 创作/修订 | `pb-screenwriter` | 是 | `brief_gate`, `knowledge_load` | 无 |
| `preflight` | 产出前自检 | `pb-preflight-agent` | 是 | `creation_delegate` | fatal 红线阻断 |
| `collision_check` | 撞车检测 | `pb-knowledge-steward` | 是 | `creation_delegate` | fatal 撞车阻断 |
| `qa` | 正式质检 | `pb-quality-reviewer` | 是 | `preflight`, `collision_check` | 质检门 |
| `qa_synthesis` | 质检汇总 | 主编 | 否 | `qa` | 无 |
| `confirmation_gate` | 用户确认 | 主编 | 否 | `qa_synthesis` | 确认门 |
| `revision_loop` | 批注修订 | `pb-screenwriter` | 是 | `confirmation_gate` | 依批注而定 |
| `persistence` | 版本化落盘 | `pb-persistence-agent` | 是 | `confirmation_gate` | approve/export 判定 |
| `knowledge_reminder` | 入库提醒 / 红线固化 | 主编 + `pb-knowledge-steward` | 分层 | `persistence` | 用户显式授权 |

`review` 意图从 `preflight` 或 `qa` 进入；`knowledge` 意图走知识子图；`illustration` 意图走独立插画子图。

插画子图建议为：

| Stage ID | 名称 | 负责人 |
|---|---|---|
| `illustration_init` | 路径解析与脚本校验 | `pb-intake-agent` |
| `asset_extraction` | 资产提取 | `picturebook-art-agent` |
| `asset_confirmation` | 资产清单确认 | 主编 |
| `asset_preproduction` | 素材图生成 | `picturebook-art-agent` |
| `asset_final_confirmation` | 素材定稿确认 | 主编 |
| `illustration_generation` | 插画生成 | `picturebook-art-agent` |
| `html_export` | HTML 预览导出 | `picturebook-art-agent` |
| `illustration_delivery` | 文件展示与交付 | 主编 |

## 6. 数据模型

### 6.1 Run Manifest

每个任务创建一份运行清单，建议放在：

```text
{workspace}/{project_root}/.workflow/runs/{run_id}/manifest.json
```

字段示例：

```json
{
  "schema_version": "pb-stage-run-v1",
  "run_id": "20260921-example-0001",
  "intent": "creation",
  "artifact_type": "script",
  "series_id": "example-series",
  "project_id": "example-project",
  "project_root": "E:/workspace/example-project",
  "mode": "full",
  "stages": [
    {
      "stage_id": "brief_gate",
      "assignee": "pb-intake-agent",
      "depends_on": ["session_init"],
      "status": "pending",
      "gate": "brief",
      "input_refs": [],
      "output_refs": []
    }
  ]
}
```

`status` 枚举：

```text
pending → ready → running → blocked → done | failed | cancelled
```

### 6.2 Task Envelope

主编派发任务时使用结构化信封：

```json
{
  "schema_version": "pb-stage-task-v1",
  "run_id": "20260921-example-0001",
  "task_id": "brief_gate-0001",
  "stage_id": "brief_gate",
  "agent_id": "pb-intake-agent",
  "logical_target": "pb-intake-agent",
  "inputs": {},
  "constraints": {},
  "resume_context": "ab12cd34",
  "output_paths": [],
  "return_channel": "lead"
}
```

约束：

1. `agent_id` 必须与已注册 Agent ID 一致。
2. `resume_context` 必须回传并在恢复时校验。
3. 派发时不得用低 `max_turns` 覆盖成员预算；应省略或给足。
4. `output_paths` 必须限定在该 Agent 的独立输出目录。

### 6.3 Result Envelope

子 Agent 回传时使用结果信封：

```json
{
  "schema_version": "pb-stage-result-v1",
  "run_id": "20260921-example-0001",
  "task_id": "brief_gate-0001",
  "stage_id": "brief_gate",
  "agent_id": "pb-intake-agent",
  "status": "done",
  "result": {},
  "artifact_refs": [],
  "requests": [],
  "risks": [],
  "resume_context": "ab12cd34"
}
```

`status` 枚举：

| 状态 | 含义 |
|---|---|
| `done` | 阶段完成 |
| `needs_input` | 需要用户或其他 Agent 输入 |
| `blocked` | 命中门禁，等待裁决 |
| `failed` | 执行失败，可由主编决定重派或转呈用户 |
| `cancelled` | 用户或主编取消 |

## 7. 协作消息协议

协作消息统一通过主编中转。建议在 Result Envelope 的 `requests[]` 中表达：

| Message Type | 用途 | 逻辑接收方 |
|---|---|---|
| `request_input` | 请求补充知识、设定、路径、上下文 | 其他阶段 Agent |
| `request_review` | 请求阶段内预审 | `pb-quality-reviewer` |
| `report_event` | 回传进度、警告、异常 | 主编 |
| `confirmation_required` | 请求用户裁决 | 主编 |
| `report_done` | 阶段完成 | 主编 |

示例：编剧发现缺少角色约束，不直接请求知识管理员，而是回传：

```json
{
  "requests": [
    {
      "type": "request_input",
      "logical_target": "pb-knowledge-steward",
      "operation": "domain_search",
      "payload": {
        "series_id": "example-series",
        "project_id": "example-project",
        "keywords": ["角色", "配角约束"]
      },
      "blocking": true
    }
  ]
}
```

主编解析后：

1. 若知识结果已经存在于 `knowledge_load` 输出，直接回填给编剧。
2. 若不存在，创建新的 `knowledge_refill` 阶段并派发 `pb-knowledge-steward`。
3. 结果作为新 input 再派发 `pb-screenwriter`。

## 8. 新增工作型 Agent

### 8.1 `pb-intake-agent`

职责：

1. 读取用户输入，输出初步意图分类。
2. 勘察工作空间与项目根目录。
3. 初始化或读取 `progress.json`。
4. 整理简报已知项、缺失项和待确认项。
5. 输出 `session_init` 与 `brief_gate` 阶段结果。

不可做：

1. 不代替用户回答缺失约束。
2. 不修改权威知识。
3. 不创建创作产物。

### 8.2 `pb-preflight-agent`

职责：

1. 运行廉价代理检查。
2. 运行 craft benchmark。
3. 运行红线扫描。
4. 分离项目红线 FAIL 与工艺类 FAIL。
5. 输出结构化 preflight 报告。

不可做：

1. 不直接修改草稿。
2. 不自行判定“本次检查可跳过”。
3. 不把工艺基准升格为项目红线。

### 8.3 `pb-persistence-agent`

职责：

1. 根据确认门结果写入定稿或导出稿。
2. 归档旧版本。
3. 更新 `progress.json`。
4. 锁定 `built_against`。
5. 合并场景台账或资产登记册。
6. 汇报文件路径与落盘摘要。

不可做：

1. 不替代确认门。
2. 不把未 approve 的创作产物静默定稿。
3. 不直接写入插件包根目录。

## 9. 文件与状态权限

### 9.1 Run 内目录建议

```text
{project_root}/.workflow/runs/{run_id}/
├── manifest.json
├── messages/
├── outputs/
│   ├── pb-intake-agent/
│   ├── pb-knowledge-steward/
│   ├── pb-screenwriter/
│   ├── pb-preflight-agent/
│   ├── pb-quality-reviewer/
│   ├── pb-persistence-agent/
│   └── picturebook-art-agent/
└── reports/
```

### 9.2 写权规则

| 对象 | 写权 |
|---|---|
| `outputs/{agent_id}/` | 对应 Agent 可写 |
| `messages/` | 主编可写；子 Agent 不得直接写 |
| `manifest.json` | 主编或调度适配层可写 |
| `progress.json` | 默认主编可写；落地阶段由 `pb-persistence-agent` 受控更新 |
| 创作产物 | 默认不落盘；确认门 approve 或用户显式导出后才写入 |
| 插件包根目录配置 | 子 Agent 不得写入 |
| 飞书 KB-AI | 仅 `pb-knowledge-steward` 经协议写通道执行 |

## 10. 运行时适配

### 10.1 WorkBuddy 主路径

| 抽象能力 | WorkBuddy 实现 |
|---|---|
| 初始化团队 | `TeamCreate` |
| 派发阶段任务 | `Agent` |
| 回传结果 | `SendMessage` |
| 查询进度 | `TaskOutput` |
| 恢复任务 | 携带 `resume_context` 重新 `SendMessage` |

WorkBuddy 是第一实现目标，因为插件现有 Agent 与 hooks 均以 WorkBuddy 语义运行。

### 10.2 Codex 适配路径

| 抽象能力 | Codex 实现 |
|---|---|
| 初始化运行清单 | 主编直接写 `manifest.json` |
| 派发阶段任务 | `spawn_agent` |
| 续跑任务 | `followup_task` |
| 等待结果 | `wait_agent` |
| 查询子 Agent | `list_agents` |

Codex 路径必须在 `multi_agent` 能力可用时才启用。若不可用，主编应在任务开始前明确说明“本回合为顺序降级模式”，并继续记录 manifest 与阶段状态。

## 11. 失败处理

| 情况 | 处理 |
|---|---|
| 子 Agent 超轮 | 不得主编代写；省略或提高 `max_turns` 后改参重派 |
| 输出缺失或 schema 不合法 | 阶段标记 `failed`，要求对应 Agent 重传 |
| fatal 红线 / fatal 撞车 | 回退到 `creation_delegate`，携带具体批注重派 |
| 权威知识缺失 | 按 SYSTEM.md 非阻塞规则继续；必需权威缺失时阻塞对应阶段 |
| 生图失败 | 由主编改参重派 `picturebook-art-agent`，不得主编自跑生图 |
| 用户确认缺失 | 阶段标记 `blocked`，不得继续依赖该确认的下游阶段 |
| 并行结果冲突 | 主编暂停受影响阶段，要求用户或对应专职 Agent 裁决 |

## 12. 安全约束

1. `confirmation_required` 必须优先于普通结果处理。
2. 所有用户确认仍由主编发起、收集和回传。
3. 飞书源库保持只读。
4. 飞书 AI 库写入只走 `pb-knowledge-steward` 与协议客户端。
5. 生图只由 `picturebook-art-agent` 执行；主编不得代跑。
6. 子 Agent 不得直接改插件包内的 Agent/Skill/System 约束文件。
7. 产物默认只对话呈现，不默认落盘。
8. 落盘后的产物仍必须由主编调用平台文件展示能力。
9. 任何读图用途继续按 SYSTEM.md 的授权清单执行。

## 13. 测试与验收

### 13.1 单元测试

1. Manifest schema 校验。
2. Task / Result Envelope 校验。
3. DAG 状态机迁移。
4. 依赖循环检测。
5. 并行可执行性判定。
6. `resume_context` 校验。
7. 权限边界扫描：子 Agent 输出路径不得越界。

### 13.2 集成测试

1. 轻量模式不创建团队。
2. 完整创作流程按 DAG 顺序推进。
3. `preflight` 与 `collision_check` 可并行。
4. fatal 检查能回退到修订循环。
5. 确认门阻塞下游阶段。
6. approve 后 `persistence` 正确写入并更新 `progress.json`。
7. 插画子图能在资产确认后继续。
8. 多页插画可并行并合并结果。

### 13.3 验收标准

1. 每个可派发阶段都有清晰负责人与 I/O 契约。
2. 主编不再代写编剧、质检、知识管理、美术的专业产出。
3. 用户确认门与全局硬性约束全部保留。
4. 子 Agent 不出现点对点直连。
5. 子 Agent 文件写权不冲突。
6. WorkBuddy 主路径可运行，Codex 适配路径在能力可用时可切换。
7. 失败与降级路径均有可观测记录。

## 14. 分期落地建议

| 期 | 内容 | 交付 |
|---|---|---|
| P0 | 本 spec 评审与冻结 | 设计文档 |
| P1 | Manifest / Task / Result schema 与调度协议 | schema 校验器 + 文档 |
| P2 | 主编 SOP 改造为阶段 DAG 调度 | 主编与子 Agent 定义更新 |
| P3 | 新增 `pb-intake-agent`、`pb-preflight-agent`、`pb-persistence-agent` | Agent MD + I/O 契约 |
| P4 | WorkBuddy 集成测试 | 端到端用例 |
| P5 | Codex 适配层 | 多 Agent 工具映射与降级路径 |
| P6 | 插画子图并行化 | 多页插画 / 多素材图并行 |

## 15. 开放问题

1. `pb-intake-agent` 是否与主编在 Phase 0 的现有职责合并为轻量阶段函数，还是保留独立 Agent。
2. 多视角质检是否使用同一个 `pb-quality-reviewer` 多次调用，还是新增不同质检视角 Agent。
3. Codex `multi_agent` 能力的版本下限与模型路由策略。
4. `.workflow/runs/` 的历史清理策略与最小保留数量。
5. 知识库同步任务是否也纳入同一 run manifest，还是保持独立知识子图。
