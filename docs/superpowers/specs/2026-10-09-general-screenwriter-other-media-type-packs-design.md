# 通用编剧创作插件：短剧与长篇连续剧类型包设计

**状态：** 设计草案  
**日期：** 2026-10-09  
**关联大纲：** `docs/superpowers/plans/2026-10-09-general-screenwriter-upgrade-outline.md`  
**前置设计：**

- `2026-10-09-general-screenwriter-domain-model-design.md`
- `2026-10-09-general-screenwriter-type-pack-contract-design.md`
- `2026-10-09-general-screenwriter-dag-quality-gate-design.md`

## 1. 目标

为短剧和长篇连续剧定义可执行的类型包边界、核心产物、阶段结构、质量规则和交付形态，使它们最终通过统一入口进入创作。

当前两个媒介仍为 `planned`，本设计只描述目标契约和最小可用版本，不承诺立即可用。

## 2. 通用原则

1. **类型包先行。** 只有类型包声明产物、阶段和质量规则后，媒介才可执行。
2. **最小可用优先。** 每种类型先完成一条可完整确认的最小创作链。
3. **格式分离。** 结构方法、剧本格式和导出格式分别建模。
4. **质量同交付。** 新类型启用时必须同时交付产物 schema、质量规则和代表性样例。
5. **复用通用 DAG。** 只添加类型专属阶段，不复制一套运行内核。

## 3. 短剧类型包

### 3.1 目标 medium

```text
medium_id: shortdrama
version: shortdrama-v1
status: planned
delivery_forms:
  - episode_script
```

最小可用范围建议从单集结构开始。

### 3.2 核心产物

| artifact | 说明 |
| --- | --- |
| `positioning` | 题材、受众、平台与风格 |
| `episode_outline` | 单集大纲 |
| `hook_sheet` | 关键钩子 |
| `beat_sheet` | 节奏节拍 |
| `scene_table` | 场次表 |
| `episode_script` | 集稿 |

### 3.3 核心阶段

```text
session_init
brief_gate
knowledge_load
episode_design
hook_design
beat_design
scene_design
episode_script_delegate
hook_check
pacing_check
dialogue_check
quality_gate
confirmation_gate
persistence
```

### 3.4 质量检查

| 检查 | 说明 |
| --- | --- |
| 开场钩子 | 前几秒/前几行具备吸引力 |
| 关键转折 | 单集内至少有明确转折 |
| 结尾钩子 | 结尾有继续观看动力或闭环 |
| 节奏密度 | 信息密度与冲突推进平衡 |
| 冲突闭环 | 单集目标清楚，冲突可被理解 |
| 人物状态 | 人物目标与变化一致 |
| 格式 | 集稿格式统一 |
| 时长适配 | 符合短剧平台时长预期 |

## 4. 长篇连续剧类型包

### 4.1 目标 medium

```text
medium_id: tv_longform
version: tv_longform-v1
status: planned
delivery_forms:
  - season_episode_script
```

最小可用范围建议先支持单季单集，再扩展到跨季连续性。

### 4.2 层级模型

```text
series
└── season
    └── episode
        └── scene
```

必须支持：

- 系列圣经；
- 季弧线；
- 集列表；
- 单集大纲；
- 场次表；
- 集稿；
- 跨集连续性台账。

### 4.3 核心产物

| artifact | 作用域 |
| --- | --- |
| `series_bible` | series |
| `character_arc_map` | series |
| `timeline_ledger` | series |
| `season_arc` | season |
| `episode_list` | season |
| `episode_outline` | episode |
| `scene_table` | episode |
| `episode_script` | episode |
| `continuity_ledger` | episode / season |

### 4.4 核心阶段

```text
session_init
brief_gate
series_load
season_design
episode_design
scene_design
episode_script_delegate
continuity_check
foreshadow_check
character_state_check
quality_gate
confirmation_gate
persistence
```

最小可用路径：

1. `series_bible`；
2. `season_arc`；
3. `episode_outline`；
4. `episode_script`；
5. `continuity_check`；
6. `confirmation_gate`。

### 4.5 质量检查

| 检查 | 说明 |
| --- | --- |
| 季弧线 | 主目标、阻力、转变清晰 |
| 集功能 | 每集有明确目的 |
| 角色状态 | 与上一集状态一致 |
| 时间线 | 时间推进不矛盾 |
| 伏笔 | 有来源、有目的、有回收点 |
| 回收 | 已回收事件与旧设定一致 |
| 场次连接 | 场景之间过渡合理 |
| 系列约束 | 符合系列圣经 |
| 跨集连续性 | 人物、地点、物件、知识状态一致 |

## 5. 类型包结构

每个类型包都应包含：

```text
TypePackDescriptor
├── medium_id
├── version
├── delivery_forms
├── artifact_types
├── stages
├── optional_workflows
├── workflow_policy
├── validators
├── exporters
├── capabilities
└── status
```

启用条件：

1. 至少一个 `workflow_output` artifact；
2. 至少一个完整核心阶段链；
3. 至少一个 confirmation gate；
4. 至少一个 quality gate；
5. 至少一个代表性样例；
6. 旧 run 不受影响。

## 6. 通用与类型专属阶段

通用阶段：

```text
session_init
brief_gate
knowledge_load
quality_gate
confirmation_gate
persistence
```

类型专属阶段：

| 媒介 | 专属阶段示例 |
| --- | --- |
| 短剧 | hook_design, pacing_check |
| 长篇连续剧 | season_design, episode_design, continuity_check |

阶段 ID 在同一类型包内唯一；不同类型包可以重名，但快照必须记录所属类型包。

## 7. 跨类型知识

知识查询必须区分：

1. 通用创作方法；
2. 媒介类型规范；
3. 题材/风格约束；
4. 系列事实；
5. 项目事实；
6. 季/集/场事实。

短剧和长篇连续剧不得默认读取绘本专属知识页。

## 8. 迁移与启用

建议顺序：

1. **契约建模。** 补全 artifact/stage/quality rule 声明。
2. **样例验证。** 为每种类型准备一份代表性最小样例。
3. **只读执行门。** 仍为 planned，不允许派发。
4. **核心链路。** 激活一条最小创作链。
5. **质量扩展。** 加入格式、节奏、连续性等检查。
6. **跨类型回归。** 确认旧绘本和其他类型互不干扰。

## 9. 验收标准

阶段通过条件：

- 两种类型各自能声明核心产物与阶段；
- planned 状态继续阻止派发；
- 任一类型激活后不会影响绘本；
- 类型包内不存在阶段环或 artifact 引用错误；
- confirmation gate、revision、persistence 行为一致；
- 每种类型都有最小质量检查集。
