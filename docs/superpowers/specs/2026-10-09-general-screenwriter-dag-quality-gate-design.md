# 通用编剧创作插件：通用创作 DAG 与质量门设计

**状态：** 设计草案  
**日期：** 2026-10-09  
**关联大纲：** `docs/superpowers/plans/2026-10-09-general-screenwriter-upgrade-outline.md`  
**前置设计：**

- `2026-10-09-general-screenwriter-domain-model-design.md`
- `2026-10-09-general-screenwriter-type-pack-contract-design.md`

## 1. 目标

把现有绘本阶段 DAG 抽象为通用创作 DAG，使类型包能声明自己的阶段、产物、质量检查、确认门和修订语义，同时保持旧绘本 run 可读。

本设计只描述运行模型和契约，不实现新媒介工作流。

## 2. 核心概念

```text
CreativeRun
├── run_id
├── root_run_id
├── context
├── intent
├── workflow_id
├── artifact_type
├── type_pack
├── stages
├── resolution_snapshot
├── status
└── outcome
```

`CreativeRun` 不绑定绘本。它只负责：

- 描述一次创作或修订；
- 记录当前上下文；
- 引用类型包、工作流和产物目标；
- 调度类型包声明的阶段；
- 保存状态、确认结果和依赖快照。

## 3. 阶段模型

```text
StageDescriptor
├── stage_id
├── stage_type
├── depends_on
├── consumes_artifact_ids
├── produces_artifact_ids
├── validates_artifact_ids
├── owner
├── gate
├── status
└── outcome
```

`stage_type` 推荐：

| 类型 | 用途 |
| --- | --- |
| `session_init` | 初始化会话 |
| `brief_gate` | 校验创作简报 |
| `knowledge_load` | 加载知识证据 |
| `delegation` | 交给子代理或执行者 |
| `creation` | 生成或修改产物 |
| `validation` | 校验产物 |
| `synthesis` | 汇总检查结果 |
| `confirmation` | 用户确认 |
| `persistence` | 批准后落盘 |
| `export` | 用户明确请求后导出 |
| `delivery` | 交付提醒或报告 |

`owner` 只是一个权限标识，不等于具体 Agent 类型。

## 4. 通用工作流

每个类型包至少声明一个核心 workflow。基础形态可拆为：

```text
session_init
→ brief_gate
→ knowledge_load
→ creation_delegate
→ validation
→ quality_gate
→ confirmation_gate
→ approved_persistence
→ delivery
```

不同类型可以在这些节点之间增加专属阶段，例如：

- 短剧增加 episode hook、episode pacing；
- 长篇连续剧增加 season arc、episode list、continuity ledger。

阶段依赖必须满足：

1. DAG 无环；
2. 消费产物必须存在或可由上游产出；
3. 产出产物必须与 artifact descriptor 一致；
4. 校验产物必须在生产阶段之后；
5. 确认门不被非必要阶段隐藏。

## 5. 确认门

确认门状态：

```text
pending
running
waiting
done
cancelled
```

确认结果：

```text
approved
revision_requested
cancelled
```

规则：

1. 只有 `approved` 才解锁 persistence；
2. `revision_requested` 创建新的 revision run；
3. `cancelled` 终止当前分支；
4. revision run 必须重新执行质量检查；
5. revision run 不得绕过确认门；
6. 确认门必须有负责人和可审计结果。

## 6. 修订

修订 run 结构：

```text
parent_run_id
revision_of_run_id
revision_iteration
revision_feedback
reused_context
updated_snapshot
```

规则：

1. 修订只修改产物版本，不篡改历史；
2. 修订必须重新经过 preflight、collision check 和 quality gate；
3. 修订不能从 pending 或 failed run 派生；
4. 修订必须保留旧 run 的只读引用；
5. 修订产物的新版本必须能追溯到原版本。

## 7. 质量门

质量门由多个检查组成：

```text
QualityGate
├── gate_id
├── scope
├── checks
├── blocking_policy
├── evidence
└── result
```

检查类别：

| 类别 | 示例 |
| --- | --- |
| 结构 | 起承转合、节拍、场次、分集 |
| 角色 | 目标、动机、变化、连续性 |
| 格式 | 页脚本、剧本格式、集稿格式 |
| 知识 | 与权威知识冲突、事实核对 |
| 工艺 | 字数、句长、节奏、钩子 |
| 风险 | 敏感内容、重复、逻辑漏洞 |
| 连续性 | 跨页、跨场、跨集、跨季 |
| 可制作性 | 场景可执行、资源清楚、动作可理解 |

阻断策略：

| 策略 | 含义 |
| --- | --- |
| `hard_block` | 失败即阻断确认 |
| `require_user_confirmation` | 需要用户明确接受风险 |
| `advisory` | 只显示，不阻断 |
| `informational` | 仅记录，不参与判定 |

项目级硬约束使用 `hard_block`；工艺指标通常使用 `require_user_confirmation` 或 `advisory`。

## 8. 快照

每次 run 至少记录：

```text
resolution_snapshot
├── context
├── type_pack
├── workflow
├── artifact
├── knowledge
├── skills
├── quality_rules
└── workflow_inputs
```

规则：

1. 新 run 使用当前解析结果；
2. revision run 继承父 run 快照并可显式更新；
3. dispatch plan 和 task envelope 使用隔离副本；
4. 历史 run 的快照只读；
5. 旧 manifest 没有 snapshot 时不自动补写。

## 9. 调度

调度器职责：

1. 校验 manifest；
2. 检查类型包和目标产物可执行；
3. 解析 ready 阶段；
4. 计算当前批次；
5. 处理失败、跳过和等待；
6. 等待确认门；
7. 在批准后解锁 persistence。

调度器不负责：

- 生成正文；
- 调用外部图片 API；
- 修改用户文件；
- 隐式同步知识库。

## 10. 兼容

现有 `pb-stage-run-v2` 保持可读。迁移策略：

1. 旧 run 继续按绘本解释；
2. 旧 run 不自动补 context 或 snapshot；
3. 新 run 必须显式提供 context 和 type pack；
4. 新 run 的 artifact、workflow、quality rule 都必须由类型包解析；
5. `pb-*` 阶段 ID 保留为绘本兼容别名。

## 11. 错误处理

所有失败应返回结构化错误：

```text
DagError
├── code
├── message
├── field
├── expected
├── actual
└── hint
```

典型错误：

- 未知类型包；
- planned 类型不可执行；
- 阶段依赖成环；
- artifact 目标不属于当前 workflow；
- 确认门缺失或未完成；
- revision run 引用非法父 run；
- snapshot 与 context 不一致。

## 12. 验收标准

阶段通过条件：

- 能从类型包解析出完整 workflow；
- 能调度至少一个非绘本类型的核心 run；
- confirmation gate 与 revision/persistence 语义与现有模型一致；
- quality gate 能输出结构化结果；
- 快照和依赖记录可追溯；
- 旧绘本 run 不需要迁移即可读取。
