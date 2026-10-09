# 通用编剧创作插件：知识库作用域与继承设计

**状态：** 设计草案  
**日期：** 2026-10-09  
**关联大纲：** `docs/superpowers/plans/2026-10-09-general-screenwriter-upgrade-outline.md`  
**前置设计：** `2026-10-09-general-screenwriter-domain-model-design.md`

## 1. 目标

本文设计知识库 schema v2、作用域模型、继承关系、冲突处理和旧 key 兼容策略，使知识页能同时服务绘本、电影、短剧和长篇连续剧。

本设计只描述契约和迁移边界，不改变现有知识库远端内容，也不引入自动内容生成。

## 2. 当前边界

现有知识页使用三段逻辑键：

```text
series_id / project_id / page_type
```

`page_codec.py` 只接受 `schema_version=1`、既有页面类型和三段 key。`knowledge-loader` 也只能按 `series_id + project_id + page_types` 精确匹配。该模型适合当前绘本项目，但无法表达：

- 全局通用创作方法；
- 媒介类型级规范；
- 题材/风格约束；
- 系列与项目之间的事实继承；
- 季、集、场等细粒度事实；
- 任务级临时约束。

## 3. 目标知识页模型

每条知识页除正文外至少声明：

```text
schema_version: 2
page_id
page_type
scope_type
scope_id
medium_id
genre_ids
series_id
project_id
season_id
episode_id
scene_id
title
authority
version
supersedes
depends_on
source_refs
built_against
updated_at
```

字段含义：

| 字段 | 规则 |
| --- | --- |
| `scope_type` | `global`, `medium`, `genre`, `series`, `project`, `season`, `episode`, `scene`, `task` |
| `scope_id` | 与 `scope_type` 匹配的稳定标识；`global` 可用 `all` |
| `authority` | `system`, `type_pack`, `series`, `project`, `user_experiment` |
| `version` | 单调递增或语义化版本，用于陈旧判断 |
| `supersedes` | 明确替代的旧知识页 |
| `depends_on` | 本页依赖的知识或事实来源 |
| `source_refs` | 飞书节点、外部资料、用户输入等来源引用 |
| `built_against` | 读取/写入/创作时绑定的知识版本快照 |

不要求所有字段同时非空。校验按 `scope_type` 与 `page_type` 决定必填项。

## 4. 作用域层级

推荐解析顺序：

```text
global
→ medium
→ genre
→ series
→ project
→ season
→ episode
→ scene
→ task
```

规则：

1. **默认向下继承。** 下层创作可以读取上层适用知识。
2. **显式覆盖。** 只有声明 `authority` 与覆盖规则的页面可以覆盖上层。
3. **不隐式合并。** 多个候选规范冲突时，不得通过文本拼接默默合并；必须产生解析报告。
4. **项目事实优先于系列推测。** `project` 级事实可以覆盖 `series` 级假设。
5. **系统权威不被用户实验覆盖。** `system` 级规则只能被后续系统版本替代，不能被项目级提示词静默绕过。

## 5. ScopeRef

作用域统一用 `ScopeRef` 表达：

```text
ScopeRef
├── scope_type
├── scope_id
├── medium_id
├── genre_ids
├── series_id
├── project_id
├── season_id
├── episode_id
├── scene_id
└── task_id
```

`ScopeRef` 不要求所有字段都填写，但至少必须能判断当前查询处于哪一层。未知层级或空层级按“不可解析”处理，不自动猜测。

## 6. 页面类型

schema v2 的页面类型分为四类：

### 6.1 通用方法

示例：

- 创作方法论；
- 结构方法；
- 人物弧线方法；
- 冲突推进方法；
- 修订流程；
- 质量评价方法。

这些页面通常是 `scope_type=global` 或 `scope_type=medium`。

### 6.2 类型规范

示例：

- 绘本逐页规范；
- 电影标准剧本格式；
- 短剧集级节奏；
- 长篇连续剧跨集结构。

这些页面通常声明 `medium_id`，并由类型包引用。

### 6.3 系列与项目事实

示例：

- 世界观；
- 人物；
- 时间线；
- 系列设定；
- 项目事实；
- 制作约束；
- 已确认事件。

这些页面必须声明明确的 `series_id` 或 `project_id`，必要时补充季、集、场。

### 6.4 评估与历史

示例：

- 质量基准；
- 样稿；
- 修订记录；
- 项目评价。

这些页面通常按项目或系列作用域保存，允许历史版本共存。

## 7. 解析模型

目标查询接口：

```text
KnowledgeQuery
├── scope_ref
├── page_types
├── media_ids
├── genre_ids
├── include_global
├── include_parent_scopes
└── require_conflicts_visible

KnowledgeResolution
├── matches: KnowledgeEvidence[]
├── scope_chain: ScopeChain[]
├── conflicts: ConflictReport[]
├── unreadable: UnreadableReport[]
└── built_against: KnowledgeDependencySnapshot
```

解析流程：

1. **展开 scope chain。** 根据当前 `ScopeRef` 生成合法的父链。
2. **过滤页面类型。** 只保留请求的 `page_types`。
3. **过滤媒介/题材。** 媒介级页面只匹配当前 `medium_id`；题材级页面要求当前 `genre_ids` 有交集。
4. **收集候选页。** 从 `task` 到 `global` 或反向收集均可，但最终按固定优先级解释。
5. **检测冲突。** 同一逻辑主题、同一约束对象但结论不同的页面必须进入 `conflicts`。
6. **构建证据包。** 返回可见页面、优先级、来源、版本和依赖快照。

## 8. 冲突与覆盖

冲突按三个维度判断：

1. **作用域维度：** 是否处于同一 scope chain；
2. **主题维度：** 是否针对同一 `page_type` 或同一逻辑键；
3. **约束维度：** 是否形成互斥决策。

处理规则：

| 情况 | 结果 |
| --- | --- |
| 上层通用规则，下层具体规则 | 可继承；解析结果标注覆盖关系 |
| 同层互斥页面 | 必须产生 `conflict`，不能静默选择 |
| 项目事实与系列设定冲突 | 项目事实可覆盖；报告显示来源与版本 |
| 用户实验知识试图覆盖系统规则 | 不生效；解析结果中标记拒绝原因 |
| 旧 schema 页与新 schema 页同主题 | 旧页兼容读取；新页必须显式 `supersedes` 后才可作为当前权威 |

## 9. 依赖与陈旧检测

每次创作读取知识后，产物的 `built_against` 至少记录：

```text
knowledge_schema
scope_chain
page_id
page_revision
scope_type
scope_id
medium_id
genre_ids
authority
priority
```

后续判断时：

- 页面 revision 变化 → 产物可能陈旧；
- scope chain 中新增页面 → 产物可能受新知识影响；
- 页面 authority 变化 → 需要重新解释优先级；
- 页面进入 `superseded` 状态 → 产物应提示重新校验；
- 页面无法读取 → 阻止以该页作为权威依据。

## 10. 旧数据兼容

旧三段 key 保持可读：

```text
series_id/project_id/page_type
```

迁移规则：

1. 旧页不重写为 schema v2；读取时保留 v1 解释器。
2. 新页不得复用旧三段 key 拼接新语义。
3. 新页若替代旧页，必须写入 `supersedes`。
4. 系列页、项目页、系统页的语义必须从 `scope_type` 推导，不再依赖 `/` 分隔符。
5. v1 页的兼容状态必须在读取结果中显式返回，不能伪装为已迁移的 v2 权威页。

## 11. 校验规则

schema v2 页面加载时必须校验：

- `scope_type` 合法；
- `scope_id` 与 `scope_type` 匹配；
- `authority` 合法；
- `page_type` 已注册；
- `medium_id`、`genre_ids`、`series_id`、`project_id` 与 `scope_type` 一致；
- `depends_on` 指向存在的页面或事实；
- `source_refs` 非空，除非是本地设计文档类型；
- `built_against` 结构完整；
- `supersedes` 不形成环。

## 12. 迁移路径

按四个切片迁移：

1. **只读解析器。** 先实现 v2 页面解析和 scope chain 展开，不改变写入。
2. **读取合并。** knowledge-loader 支持同时返回 v1 与 v2 页，并区分兼容状态。
3. **写入支持。** knowledge-store 支持新增 v2 页面，保留 v1 页面只读。
4. **旧页迁移工具。** 提供映射报告和用户确认后的迁移建议，不做静默改写。

## 13. 验收标准

阶段通过条件：

- 能为任一项目构造合法 `ScopeRef`；
- 能从全局到任务级展开 scope chain；
- 能判断某页适用范围与优先级；
- 能明确显示 v1、v2、兼容态、冲突态；
- 项目事实可以覆盖系列假设，系统规则不被实验知识覆盖；
- 产物能记录所读取知识的完整作用域链与版本；
- 旧三段 key 页继续可读。
