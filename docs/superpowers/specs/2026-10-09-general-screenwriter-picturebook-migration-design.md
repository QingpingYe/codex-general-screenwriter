# 通用编剧创作插件：绘本类型包迁移设计

**状态：** 设计草案  
**日期：** 2026-10-09  
**关联大纲：** `docs/superpowers/plans/2026-10-09-general-screenwriter-upgrade-outline.md`  
**前置设计：**

- `2026-10-09-general-screenwriter-domain-model-design.md`
- `2026-10-09-general-screenwriter-type-pack-contract-design.md`

## 1. 目标

把绘本能力从当前插件主流程迁移为可独立注册、可独立校验的绘本类型包，同时保留旧入口、旧产物、旧 run manifest 和旧插画流程兼容。

本设计不新增内容生成功能。

## 2. 当前状态

已有基础：

- `picturebook` 是唯一 active 类型包；
- 已声明六个核心产物；
- 文本创作和修订 DAG 已进入核心契约；
- 插画流程已隔离为 optional workflow；
- planned 媒介不可派发；
- 旧 manifest 和旧产物仍兼容读取。

尚未完成：

- 绘本专用知识仍挂在全局插件能力中；
- 绘本质量规则未完全按类型包隔离；
- 插画能力仍以插件 skill 形式散布；
- 绘本迁移缺少统一的迁移清单和兼容回归矩阵。

## 3. 类型包结构

```text
TypePackDescriptor
├── medium_id: picturebook
├── version
├── aliases
├── legacy_aliases
├── delivery_forms
├── artifact_types
├── stages
├── optional_workflows
├── workflow_policy
├── validators
├── exporters
└── capabilities
```

### 3.1 核心产物

保留现有六个：

| artifact | 语义 |
| --- | --- |
| `positioning` | 用户简报输入 |
| `topic_plan` | 主题方案 |
| `worldview` | 世界观 |
| `characters` | 人物设定 |
| `outline` | 故事结构 |
| `script` | 逐页脚本 |

`positioning` 不作为 `brief_gate` 的产物。

### 3.2 核心阶段

保留现有必需文本阶段：

```text
session_init
brief_gate
knowledge_load
creation_delegate
preflight
collision_check
qa
qa_synthesis
confirmation_gate
persistence
knowledge_reminder
```

这些阶段可以继续保留 `pb-*` 或绘本命名作为兼容别名，但契约来源必须是类型包。

## 4. 能力迁移矩阵

| 现有能力 | 迁移方式 |
| --- | --- |
| 主编入口 | 保留旧入口；新增通用入口按 context 解析绘本包 |
| 六类产物 | 作为 picturebook artifact descriptor |
| 文本工艺 | 作为 picturebook 专属方法论 |
| craft benchmark | 作为 picturebook validator |
| 分镜规划 | 作为 picturebook 可选能力 |
| 插画提示词 | 作为 optional workflow 的 validator |
| 图片生成 | 仅在用户明确确认后使用 |
| 插画导出 | 属于 optional workflow 的 exporter |
| HTML 预览 | 属于 optional workflow 的产物 |
| Feishu 知识 | 通过知识库适配层读取，不直接耦合绘本包 |

## 5. 插画 workflow

保留独立 optional workflow：

```text
illustration
├── trigger_intent: illustration
├── inputs:
│   └── script: approved
├── stages:
│   ├── illustration_init
│   ├── asset_extraction
│   ├── asset_confirmation
│   ├── asset_preproduction
│   ├── asset_final_confirmation
│   ├── illustration_generation
│   ├── html_export
│   └── illustration_delivery
└── artifacts:
    ├── asset_registry
    ├── illustration_prompt_payload
    ├── image_asset
    └── html_preview
```

规则：

1. 插画不阻塞文本 run 完成；
2. 必须有已批准脚本或用户明确提供脚本；
3. 图片生成前必须有人类确认；
4. 不得把输入声明当作用户确认；
5. 导出目录、尺寸和画质必须显式指定。

## 6. 旧兼容

旧对象兼容策略：

| 旧对象 | 目标 |
| --- | --- |
| `picturebook-screenwriter` | 保留入口别名 |
| 旧 six artifact | 保留读取语义 |
| `pb-stage-run-v2` | 只读兼容 |
| `pb-stage-task-v1` | 只读兼容 |
| `pb-screenwriter` | 保留 owner/assignee 别名 |
| `illustration-template` | 继续映射 optional workflow |
| 旧知识 key | 继续按 schema v1 读取 |

## 7. 迁移清单

### 7.1 文本核心

1. 六类产物已在类型包声明；
2. producer / validator / exporter 关系一致；
3. artifact 依赖不冒充阶段依赖；
4. creation/revision 每个 run 只产出一个目标；
5. preflight、collision check、qa 语义清晰。

### 7.2 插画链路

1. 8 个阶段全部在 optional workflow；
2. 4 类插画产物不进入核心产物集合；
3. 确认门和输入来源声明结构完整；
4. 图片生成与 HTML 导出不自动触发。

### 7.3 知识

1. 绘本知识读取通过 KnowledgeQuery；
2. v1 旧 key 可读；
3. v2 页面按 scope chain 解析；
4. 知识来源和 revision 可追溯。

### 7.4 质量

1. craft benchmark 属于 picturebook validator；
2. 硬约束失败阻断确认；
3. 工艺指标偏差显式呈现；
4. Lexile 只接受实测结果。

## 8. 回归矩阵

| 用例 | 期望 |
| --- | --- |
| 旧 creation run 无 context | 按绘本兼容路径可读 |
| 旧 illustration run | 按插画 optional workflow 可读 |
| 新 picturebook creation | 可从类型包解析核心产物 |
| 新 picturebook revision | 可继承快照并重新质检 |
| planned film | 不派发 |
| planned shortdrama | 不派发 |
| planned tv_longform | 不派发 |
| 空 active picturebook | 加载失败 |
| 插画混入核心 DAG | 加载失败 |
| illustration 没有 script 来源声明 | 不派发 |

## 9. 验收标准

阶段通过条件：

- `picturebook` 能在不依赖旧主流程的情况下表达核心契约；
- 文本创作、修订、确认和落盘行为保持兼容；
- 插画可选 workflow 可独立解释；
- 旧入口、旧产物、旧 manifest、旧知识 key 全部可读；
- planned 媒介不被误派发；
- 所有类型包校验失败都有明确错误。
