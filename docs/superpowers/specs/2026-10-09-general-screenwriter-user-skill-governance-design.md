# 通用编剧创作插件：用户技能注册、解析与治理设计

**状态：** 设计草案  
**日期：** 2026-10-09  
**关联大纲：** `docs/superpowers/plans/2026-10-09-general-screenwriter-upgrade-outline.md`  
**前置设计：**

- `2026-10-09-general-screenwriter-domain-model-design.md`
- `2026-10-09-general-screenwriter-knowledge-scope-design.md`

## 1. 目标

设计用户技能的注册、匹配、解析、执行边界、冲突治理和版本审计，使用户可以为指定媒介类型、题材、系列、项目、阶段或任务注入定制创作能力。

用户技能不是知识页，也不是任意可执行插件代码；它是一份结构化声明加受控执行资源。

## 2. 设计边界

用户技能必须满足：

1. **可声明。** 技能来源、适用范围、输入输出和依赖必须显式声明。
2. **可审计。** 使用、覆盖、停用、回滚都应留下记录。
3. **可隔离。** 用户技能不得静默替换系统技能、系统权威知识或类型包规则。
4. **可追踪。** 产物依赖记录中必须包含实际生效的技能标识和版本。
5. **可回滚。** 任何技能更新都必须保留可回退的版本。

## 3. 技能形态

用户技能可分四类：

| 类型 | 用途 | 执行方式 |
| --- | --- | --- |
| prompt_skill | 指导模型生成或修订文本 | 以提示词、检查清单或方法论进入对应阶段 |
| checklist_skill | 补充审查项 | 产生检查项或质量观察 |
| validator_skill | 校验产物约束 | 输出结构化判定，不直接阻断，除非声明为硬约束 |
| exporter_skill | 扩展输出形态 | 仅在用户明确请求导出时执行 |

禁止将用户技能设计为：

- 直接修改系统配置；
- 直接覆盖类型包契约；
- 隐式调用外部网络；
- 隐式写入文件；
- 绕过确认门。

## 4. 技能清单

每个用户技能至少包含：

```text
schema_version
skill_id
version
title
description
author
owner
status
created_at
updated_at
skill_type
scopes
allowed_stages
input_contract
output_contract
depends_on
conflicts_with
precedence
execution_policy
content_refs
audit
```

字段含义：

| 字段 | 规则 |
| --- | --- |
| `skill_id` | 全局唯一，稳定标识 |
| `version` | 语义化版本或单调序号 |
| `status` | `draft`, `active`, `disabled`, `retired` |
| `skill_type` | `prompt_skill`, `checklist_skill`, `validator_skill`, `exporter_skill` |
| `scopes` | 一个或多个 `ScopeRef` |
| `allowed_stages` | 允许介入的通用阶段或类型包阶段 |
| `input_contract` | 需要的上下文、知识、产物和用户输入 |
| `output_contract` | 输出类型、格式、是否可修改产物 |
| `depends_on` | 依赖的知识、技能、类型包或产物 |
| `conflicts_with` | 显式声明冲突对象 |
| `precedence` | 只允许在同 authority 内排序 |
| `execution_policy` | 对话、只读、需要确认、禁止写入等边界 |
| `content_refs` | 指向技能文本、模板或检查表 |
| `audit` | 创建、变更、发布、停用和回滚记录 |

## 5. 作用域匹配

用户技能使用与知识库相同的 `ScopeRef`：

```text
global
medium
genre
series
project
season
episode
scene
task
```

匹配规则：

1. 技能只有在其声明的每个作用域维度都满足时才进入候选集。
2. 题材/风格采用交集匹配，不要求完全相同。
3. 项目级技能只能在当前项目上下文中生效。
4. 季/集/场技能必须同时能定位到所属项目和媒介。
5. 无有效作用域的技能不得默认全局生效。

示例：

```text
skill_id: fast-episode-hook-checklist
version: 1.2.0
scopes:
  - scope_type: medium
    scope_id: shortdrama
  - scope_type: project
    project_id: project-abc
allowed_stages:
  - post_creation_check
  - pre_confirmation_gate
```

该技能只在 `shortdrama` 与 `project-abc` 同时匹配时可用。

## 6. 优先级

优先级只在同 authority 内比较：

```text
system_skill
type_pack_skill
series_skill
project_skill
user_experiment
```

推荐顺序：

1. **system_skill** 最稳定，不可被用户技能覆盖；
2. **type_pack_skill** 决定媒介类型基础规则；
3. **series_skill** 承载长期系列约定；
4. **project_skill** 承载项目专属约定；
5. **user_experiment** 只在用户显式确认后介入。

用户实验技能：

- 默认只影响当前任务；
- 不进入后续 run 的默认解析；
- 不得改变 confirmation gate 语义；
- 不得修改产物版本历史；
- 不得隐藏系统规则的失败结果。

## 7. 解析模型

目标接口：

```text
SkillQuery
├── scope_ref
├── stage_id
├── intent
├── artifact_targets
├── include_experimental
└── exclude_skill_ids

SkillResolution
├── matches: SkillMatch[]
├── conflicts: SkillConflict[]
├── rejected: SkillRejection[]
├── snapshot: SkillResolutionSnapshot
└── execution_plan: SkillExecutionPlan
```

解析流程：

1. **加载注册表。** 只读加载系统与用户技能声明。
2. **筛状态。** 只使用 `active` 技能；`draft`、`disabled`、`retired` 不进入执行。
3. **匹配作用域。** 展开 scope chain 并判断技能是否适用。
4. **匹配阶段。** 只保留 `allowed_stages` 包含当前阶段的技能。
5. **检查依赖。** 缺少知识、类型包或前置产物时进入 `rejected`。
6. **检测冲突。** 同一输出目标、同一约束对象但规则互斥时进入 `conflicts`。
7. **构建快照。** 记录所有实际生效技能、版本、来源和执行顺序。

## 8. 执行边界

技能执行前必须确认：

1. 当前阶段允许该技能介入；
2. 输入契约满足；
3. 输出目标清楚；
4. 用户确认策略满足；
5. 不违反当前 type pack 的 workflow policy；
6. 不与更高 authority 的硬约束冲突。

执行策略：

| execution_policy | 允许行为 |
| --- | --- |
| `dialog_only` | 只生成建议，不修改状态 |
| `advisory` | 输出检查项或建议，不阻断确认门 |
| `blocking_validator` | 在声明的硬约束失败时阻断确认 |
| `export_only` | 仅在用户明确要求导出时执行 |
| `interactive` | 允许请求用户输入，但不得自动写入 |

默认用户技能应为 `dialog_only` 或 `advisory`。

## 9. 冲突治理

冲突判定维度：

1. 同一作用域；
2. 同一阶段；
3. 同一输出目标；
4. 同一约束对象；
5. 规则语义互斥。

处理规则：

| 情况 | 结果 |
| --- | --- |
| 两个用户技能建议不同 | 产生 conflict，由用户选择 |
| 用户技能与 system 硬约束冲突 | 用户技能失败 |
| 用户技能与 type pack 输出契约冲突 | 用户技能失败 |
| 项目技能与系列技能冲突 | 项目技能优先，报告覆盖关系 |
| 实验技能与稳定技能冲突 | 默认不使用实验技能 |

冲突不得静默合并，也不得只依赖名称顺序。

## 10. 生命周期

```text
draft
→ active
→ disabled
→ active
→ retired
```

变更要求：

- 新版本必须保留旧版本记录；
- `skill_id` 不变，`version` 递增；
- 更新后旧 run 不自动切换到新版本；
- 停用后新 run 不再解析该技能；
- 回滚必须生成新的 `active` 版本记录，不删除历史；
- `retired` 状态只读，不能重新启用，只能基于其派生新技能。

## 11. 快照与依赖记录

每次实际使用技能时，产物或 run 至少记录：

```text
skills_resolution
├── skill_id
├── version
├── authority
├── scopes
├── stage_id
├── execution_policy
├── status
└── content_hash
```

快照必须满足：

- revision 复制时不得与父 run 共享可变对象；
- dispatch plan 与 task envelope 中的快照是隔离副本；
- 历史快照只读；
- 旧 manifest 没有 skills 快照时保持原样，不自动补写。

## 12. 存储与注册

建议两个层：

1. **系统技能目录。** 与插件一起发布，只读，受版本控制。
2. **用户技能目录。** 位于工作区或用户配置目录，按项目隔离。

用户技能目录不放入插件缓存目录；否则无法保证项目隔离与用户治理。目录结构可后续在实施计划中定稿。

## 13. 校验规则

技能清单加载时必须拒绝：

- 缺少 `skill_id`、`version`、`skill_type` 或 `status`；
- `scopes` 为空但试图声明全局生效；
- `allowed_stages` 为空或引用未知阶段；
- `input_contract` 或 `output_contract` 不是对象；
- `execution_policy` 非法；
- `precedence` 试图高于 system；
- `depends_on` 指向不存在的技能、知识或类型包；
- `conflicts_with` 指向不存在的对象；
- `audit` 缺少创建或发布记录。

## 14. 验收标准

阶段通过条件：

- 用户可以注册一个项目级 checklist 技能；
- 技能只在声明的作用域和阶段生效；
- 冲突技能不会被静默覆盖；
- 实验技能不改变确认门语义；
- 产物依赖记录包含实际技能版本；
- 旧 run 和旧技能继续可读；
- 停用、回滚和变更历史可追踪。
