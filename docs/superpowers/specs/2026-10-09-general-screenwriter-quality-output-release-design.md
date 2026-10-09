# 通用编剧创作插件：质量评测、输出与发布设计

**状态：** 设计草案  
**日期：** 2026-10-09  
**关联大纲：** `docs/superpowers/plans/2026-10-09-general-screenwriter-upgrade-outline.md`  
**前置设计：**

- `2026-10-09-general-screenwriter-domain-model-design.md`
- `2026-10-09-general-screenwriter-type-pack-contract-design.md`
- `2026-10-09-general-screenwriter-dag-quality-gate-design.md`

## 1. 目标

建立跨类型质量评测、代表性样稿、输出接口、兼容回归和发布门，使通用编剧插件在新增媒介类型时不会破坏已有能力。

本设计只描述评测和发布体系，不改变现有内容生成策略。

## 2. 质量评测体系

### 2.1 三层评测

```text
unit checks
→ type pack checks
→ end-to-end samples
```

| 层 | 目标 | 输入 |
| --- | --- | --- |
| unit checks | 校验 schema、依赖、字段、引用完整性 | 配置或小样本 |
| type pack checks | 校验类型专属产物与规则 | 类型包和样稿 |
| end-to-end samples | 校验从简报到最终产物的完整链路 | 简报、知识、类型包 |

### 2.2 通用质量维度

| 维度 | 说明 |
| --- | --- |
| correctness | 字段、引用、依赖、类型正确 |
| consistency | 人物、时间线、世界观、系列事实一致 |
| completeness | 产物包含必要部分 |
| structure | 结构链路清楚，阶段依赖合理 |
| readability | 阅读节奏、句长、段落密度 |
| actionability | 可拍摄、可执行、可修订 |
| traceability | 知识、技能、类型包版本可追溯 |
| safety | 不引入未授权外部调用或未确认写入 |

### 2.3 类型质量样例

每类媒介至少准备一个代表性样例：

| 类型 | 最小样例 |
| --- | --- |
| picturebook | 简报 → 六类产物中的目标产物 → QA → 确认 |
| film | 简报 → synopsis → beat sheet → screenplay → QA → 确认 |
| shortdrama | 简报 → episode outline → hook sheet → episode script → QA → 确认 |
| tv_longform | series bible → season arc → episode script → continuity check → 确认 |

每个样例至少包含：

- 输入简报；
- 目标产物；
- 知识依赖；
- 质量规则；
- 预期结果；
- 预期失败样例。

## 3. 质量门

质量门输出：

```text
QualityReport
├── gate_id
├── scope
├── checks
├── pass
├── blockers
├── warnings
├── metrics
├── evidence
└── policy_version
```

每条检查：

```text
QualityCheckResult
├── check_id
├── check_type
├── target_artifact
├── blocking_policy
├── status
├── message
└── evidence
```

状态：

```text
pass
warn
fail
skipped
unknown
```

阻断策略：

| 策略 | 结果 |
| --- | --- |
| `hard_block` | fail 阻断确认 |
| `require_user_confirmation` | fail 需用户明确接受 |
| `advisory` | fail 只显示 |
| `informational` | fail 只记录 |

## 4. 输出接口

输出必须分两类：

1. **对话输出。** 默认只生成对话内容，不写文件。
2. **导出输出。** 用户明确指定输出目录、格式和必要参数后执行。

### 4.1 支持格式

| 格式 | 适用类型 |
| --- | --- |
| Markdown | 通用中间产物 |
| JSON | 结构化产物、报告、审计记录 |
| Fountain / screenplay text | 电影、短剧、长篇连续剧 |
| Page script | 绘本 |
| HTML preview | 绘本插画和展示型预览 |
| Asset registry | 插画资产 |
| Production checklist | 场次表、制作需求 |

### 4.2 导出器契约

```text
Exporter
├── exporter_id
├── supported_types
├── required_inputs
├── output_format
├── required_user_params
├── confirmation_policy
└── validation_policy
```

规则：

1. 输出目录必须显式指定；
2. 输出不能覆盖用户已有文件，除非用户明确允许；
3. 输出前必须校验输入产物；
4. 输出过程不调用模型；
5. 输出失败不得留下半成品。

## 5. 兼容回归

每个发布必须验证：

| 用例 | 期望 |
| --- | --- |
| 旧 picturebook run 可读 | 不因新 schema 失败 |
| 旧 illustration run 可读 | 不因新 workflow 分层失败 |
| 旧知识 key 可读 | 三段 key 继续解析 |
| 新 picturebook run 可执行 | 类型包解析成功 |
| planned film 不派发 | 执行门阻断 |
| planned shortdrama 不派发 | 执行门阻断 |
| planned tv_longform 不派发 | 执行门阻断 |
| snapshot 隔离 | revision、plan、task 不共享可变对象 |
| 确认门语义 | approved/revision_requested/cancelled 不变 |
| 默认写盘策略 | 未批准不写入 |

## 6. 发布门

发布前至少检查：

```text
1. schema_version 检查通过
2. type pack contract 检查通过
3. knowledge adapter 检查通过
4. skill registry 检查通过
5. dag scheduler 检查通过
6. quality gate 检查通过
7. output exporter 检查通过
8. offline regression 检查通过
9. governance 检查通过
10. packaging 检查通过
```

发布说明必须包含：

1. 新增能力；
2. 兼容风险；
3. 迁移状态；
4. 已知限制；
5. 不可用能力；
6. 用户确认要求。

## 7. 迁移工具

迁移工具只做映射与报告，不做静默改写：

```text
MigrationReport
├── source_kind
├── source_version
├── target_version
├── matched_items
├── missing_fields
├── ambiguous_items
├── manual_actions
└── rollback_info
```

必须覆盖：

1. 旧 run manifest；
2. 旧产物 ID；
3. 旧知识 key；
4. 旧技能引用；
5. 旧插画流程；
6. 旧导出路径。

## 8. 版本与发布策略

### 8.1 类型包版本

类型包启用后使用独立版本号。变更分为：

| 变更 | 影响 |
| --- | --- |
| patch | 错误修复、文档说明 |
| minor | 新增可选产物、可选阶段、非阻断质量规则 |
| major | 改变核心产物、核心阶段、确认门或持久化语义 |

### 8.2 契约版本

契约版本独立于插件版本：

```text
type-pack-contract-v1
knowledge-scope-v2
user-skill-contract-v1
creative-run-v3
```

同版本内的向后兼容改动不得破坏现有 run。

### 8.3 发布节奏

建议按能力片发布：

1. **契约片。** 只加 schema 和校验。
2. **兼容片。** 只加兼容读取和迁移工具。
3. **执行片。** 激活某个类型包最小链路。
4. **质量片。** 加入类型质量规则和评测。
5. **输出片。** 加入导出器和发布生态。

## 9. 验收标准

阶段通过条件：

- 每个启用类型都有可运行的代表性样例；
- 质量报告结构统一；
- 输出格式和用户参数显式可校验；
- 旧绘本、旧知识、旧 run 均可读；
- planned 媒介不会被误派发；
- 发布包包含治理和打包检查；
- 用户能从发布说明中明确知道哪些能力可用、哪些不可用。
