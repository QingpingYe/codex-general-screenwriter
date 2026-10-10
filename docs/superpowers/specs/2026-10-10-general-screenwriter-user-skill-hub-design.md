# 通用编剧插件：自然语言用户技能中心设计

**状态：** 设计草案  
**日期：** 2026-10-10  
**取代：** `2026-10-09-general-screenwriter-user-skill-governance-design.md` 中与用户技能版本、审计、生命周期和冲突治理相关的方案。  
**关联仓库：** `https://github.com/QingpingYe/codex-general-screenwriter.git`

## 1. 目标

为没有计算机背景的编剧提供一个自然语言技能中心。用户可以通过 Codex 对话完成以下事情：

1. 从零新建一个技能；
2. 导入本地已有技能或方法论文档，并改造成插件可调用的技能；
3. 更新已有技能，每次更新直接覆盖上一个版本；
4. 把技能推送到通用编剧插件仓库；
5. 让其他用户通过插件市场更新插件后直接使用该技能。

技能必须声明支持的媒介类型、题材、系列、项目、创作阶段和目标产物，AI 才能在绘本、短剧、长篇连续剧的不同创作上下文中选择正确的技能。

本设计刻意不做复杂的技能治理。用户技能没有版本号、评分、审核队列、生命周期状态、回滚界面或冲突矩阵。技能包只保留让 AI 正确路由和使用所需的最小元数据。

## 2. 非目标

第一版不做以下内容：

1. 用户技能版本历史和回滚；
2. 技能评分、评论或使用统计；
3. 人工审核或发布审批流；
4. 生命周期状态机，例如 `draft`、`active`、`disabled`、`retired`；
5. 技能优先级治理或复杂冲突合并；
6. 用户编写或上传任意可执行脚本；
7. 用户直接编辑 JSON 元数据。

Git 提交历史会自然存在，因为推送到 GitHub 需要 commit，但产品层不提供版本选择、diff 对比或历史恢复。

## 3. 核心原则

### 3.1 自然语言是唯一用户入口

用户不需要学习命令。插件提供一个 Codex 技能入口 `user-skill-hub`，由 Codex 负责读取、追问、生成、校验、写入和推送。

内部仍然可以有校验脚本和 Git 操作，但这些对用户不可见。用户只需要表达：

```text
帮我新建一个小说改编短剧技能。
```

或者：

```text
把我本地这个改编方法改造成插件技能。
```

### 3.2 技能是结构化文本包

用户技能由两部分组成：

1. `manifest.json`：机器可读的适用范围和调用信息；
2. `SKILL.md`：给人和 AI 看的方法论正文。

用户技能不是任意插件代码。第一版只支持提示词、方法论、检查清单和输出格式说明，不支持上传可执行程序。

### 3.3 更新即覆盖

同一个 `skill_id` 的技能目录只有一份当前内容。用户确认更新后，新的 `manifest.json` 和 `SKILL.md` 直接覆盖旧文件。

不保留产品层版本号，不生成历史副本，不要求用户理解回滚。Git 历史是否保留由 Git 本身决定，不构成产品功能。

### 3.4 `all` 是唯一通配值

所有适用范围字段都不得为空。如果一个技能适用于全部类型、系列或项目，对应字段必须显式填写：

```json
{
  "medium_ids": ["all"],
  "series_ids": ["all"],
  "project_ids": ["all"]
}
```

禁止使用：

```json
{
  "medium_ids": [],
  "series_ids": null,
  "project_ids": []
}
```

`all` 表示该维度匹配任何当前合法值。新增媒介类型、系列或项目时，`all` 技能自动继续适用。

### 3.5 用户姓名必填

每个技能元数据必须包含贡献者姓名：

```json
{
  "user_name": "张三"
}
```

AI 在创建或导入技能前如果不知道用户姓名，必须先询问，不能使用系统用户名、Git 用户名、占位符或猜测值代替。

## 4. 用户旅程

### 4.1 从想法新建技能

用户可以说：

```text
我要添加一个小说改编短剧的技能。
```

AI 执行：

1. 询问用户姓名，如果当前会话没有确认过；
2. 询问技能来源：口述、粘贴文本，还是导入本地文件；
3. 确认适用媒介类型；
4. 确认题材、系列、项目范围；
5. 确认适用的创作阶段和目标产物；
6. 整理方法论；
7. 展示技能摘要；
8. 用户确认后写入并推送。

### 4.2 导入并改造本地技能

用户可以说：

```text
把我本地 D:\skills\小说改编短剧.md 改造成这个插件能用的技能。
```

AI 执行：

1. 读取本地 Markdown、文本或其他可读文档；
2. 判断哪些内容是方法论、检查项、输入说明、输出格式和示例；
3. 补充缺失的适用范围信息；
4. 生成标准 `SKILL.md`；
5. 生成 `manifest.json`；
6. 校验 `all` 和具体 ID 引用；
7. 展示将要创建或覆盖的内容；
8. 用户确认后推送。

导入不要求用户理解插件格式。AI 负责把普通文档转换成标准结构。

### 4.3 更新技能

用户可以说：

```text
更新小说改编短剧技能，加入付费卡点设计。
```

AI 读取现有 `skills/user-skills/novel-to-shortdrama-adaptation/`，合并用户要求，覆盖原文件。更新前必须展示新摘要，并明确提示会覆盖当前版本。

如果用户要求一个新技能而不是更新，AI 应生成新的 `skill_id`，避免误覆盖他人技能。

### 4.4 其他编剧使用

技能作者推送后，其他用户通过插件市场更新 `general-screenwriter` 插件。插件更新后，新技能进入运行时技能目录。

创作流程解析当前上下文后，只注入匹配的用户技能内容。

## 5. 技能包结构

用户技能保存在插件仓库内：

```text
plugins/general-screenwriter/
  skills/
    user-skill-hub/
      SKILL.md
      scripts/
        validate_user_skills.py
    user-skills/
      novel-to-shortdrama-adaptation/
        manifest.json
        SKILL.md
      dialogue-punch-up-checklist/
        manifest.json
        SKILL.md
```

目录规则：

1. `skill_id` 与目录名一致；
2. `skill_id` 使用小写英文、数字和连字符；
3. 每个技能目录必须包含 `manifest.json` 和 `SKILL.md`；
4. 不允许在用户技能目录中放置可执行脚本；
5. 同名目录更新时整体覆盖，不允许目录内出现多个版本副本。

## 6. Manifest Schema

第一版使用以下字段：

```json
{
  "schema_version": 1,
  "skill_id": "novel-to-shortdrama-adaptation",
  "title": "小说改编短剧",
  "description": "根据小说改编强钩子短剧，处理分集结构、反转、卡点、人物动机和对白压缩。",
  "user_name": "张三",
  "skill_type": "prompt_skill",
  "supports": {
    "medium_ids": ["shortdrama"],
    "genre_ids": ["all"],
    "series_ids": ["all"],
    "project_ids": ["all"],
    "stage_ids": ["brief_gate", "knowledge_load", "creation_delegate", "qa"],
    "artifact_ids": ["outline", "script"]
  },
  "content": "SKILL.md",
  "updated_at": "2026-10-10T00:00:00+08:00"
}
```

### 6.1 字段说明

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `schema_version` | 是 | 当前固定为 `1` |
| `skill_id` | 是 | 全局唯一稳定标识，和目录名一致 |
| `title` | 是 | 用户可读技能名 |
| `description` | 是 | 一到三句话说明技能用途 |
| `user_name` | 是 | 技能贡献者姓名 |
| `skill_type` | 是 | 技能形态 |
| `supports` | 是 | 适用范围对象 |
| `supports.medium_ids` | 是 | 支持的媒介类型；全部填 `["all"]` |
| `supports.genre_ids` | 是 | 支持的题材；全部填 `["all"]` |
| `supports.series_ids` | 是 | 支持的系列；全部填 `["all"]` |
| `supports.project_ids` | 是 | 支持的项目；全部填 `["all"]` |
| `supports.stage_ids` | 是 | 支持的创作阶段 |
| `supports.artifact_ids` | 是 | 支持的目标产物 |
| `content` | 是 | 技能正文文件，第一版固定为 `SKILL.md` |
| `updated_at` | 是 | 最近一次覆盖更新的 ISO 8601 时间 |

### 6.2 技能类型

第一版允许：

| 类型 | 用途 |
| --- | --- |
| `prompt_skill` | 指导生成或修订创作内容 |
| `checklist_skill` | 提供检查项、审查角度或质量清单 |
| `reference_skill` | 提供背景方法论、风格指南或参考资料 |
| `exporter_skill` | 说明导出形态或输出格式，不执行导出代码 |

默认选择 `prompt_skill`。如果 AI 不确定，应向用户确认。

### 6.3 `all` 语义

以下字段接受 `all`：

```text
medium_ids
genre_ids
series_ids
project_ids
stage_ids
artifact_ids
```

规则：

1. 每个数组必须非空；
2. 元素必须是非空字符串；
3. `all` 不能和具体值混用，例如 `["all", "shortdrama"]` 非法；
4. `medium_ids: ["all"]` 表示匹配插件当前全部活跃媒介类型；
5. `series_ids: ["all"]` 表示匹配任何系列；
6. `project_ids: ["all"]` 表示匹配任何项目；
7. `stage_ids: ["all"]` 和 `artifact_ids: ["all"]` 表示跨阶段和跨产物使用，AI 应在用户明确表达“通用”“全流程适用”后才能填写。

## 7. 校验规则

校验由 `user-skill-hub` 内部触发。用户不需要知道校验命令。

### 7.1 必须通过

1. `manifest.json` 是合法 JSON；
2. `SKILL.md` 存在且非空；
3. `schema_version` 等于 `1`；
4. 必填字段全部存在且非空；
5. `user_name` 是真实用户确认过的姓名；
6. `skill_id` 和目录名一致；
7. `skill_id` 在用户技能目录中唯一；
8. `supports` 中没有任何空数组；
9. `all` 不与具体值混用；
10. `medium_ids` 只包含 `all`、`picturebook`、`shortdrama`、`tv_longform`；
11. `stage_ids` 和 `artifact_ids` 要么是 `all`，要么能解析到当前 type pack 合法值；
12. `content` 只指向当前目录内的 `SKILL.md`；
13. 技能目录内没有 `.py`、`.js`、`.exe`、`.bat`、`.ps1` 或其他可执行文件。

### 7.2 应当提醒

1. 一个技能声明了 `stage_ids: ["all"]`，但正文只适合单一阶段；
2. 一个技能声明了 `artifact_ids: ["all"]`，但正文只适合一种产物；
3. 技能正文缺少输入、方法、输出或检查点；
4. 技能标题过于笼统，可能让 AI 在不相关场景调用；
5. `skill_id` 与已有技能相似，可能导致误覆盖。

校验失败时，AI 必须用自然语言解释问题，并给出修改建议，不暴露原始错误堆栈。

## 8. 自然语言交互契约

### 8.1 必问信息

AI 创建或导入技能前，如果以下信息缺失或明显歧义，必须先询问：

1. 用户姓名；
2. 是新建技能还是覆盖已有技能；
3. 支持的媒介类型；
4. 支持的题材；
5. 是否限定系列或项目；
6. 适用的创作阶段；
7. 目标产物；
8. 是否真的需要推送到共享插件仓库。

可以合并成一次简短追问，但不能跳过用户姓名和覆盖确认。

### 8.2 覆盖确认

当目标 `skill_id` 已存在时，AI 必须显示：

```text
已存在技能：小说改编短剧
贡献者：张三
最后更新：2026-10-10

你即将覆盖它的 manifest 和正文。确认覆盖吗？
```

用户明确确认后才能覆盖。

### 8.3 推送确认

写入本地仓库前，AI 展示：

```text
准备创建用户技能：

名称：小说改编短剧
贡献者：张三
支持类型：shortdrama
支持系列：all
支持项目：all
适用阶段：brief_gate、knowledge_load、creation_delegate、qa
目标产物：outline、script

确认后我会更新插件仓库并推送到 GitHub。
```

用户确认后才执行写入、校验、commit 和 push。

## 9. 推送到插件仓库

插件仓库是共享发布源：

```text
https://github.com/QingpingYe/codex-general-screenwriter.git
```

推送流程：

1. 确认当前工作区是该插件仓库，或定位用户授权的本地插件仓库克隆；
2. 拉取远端最新 `main`；
3. 写入或覆盖用户技能目录；
4. 运行轻量校验；
5. 只暂存本次技能相关文件和插件发布游标；
6. 生成人类可读 commit 信息；
7. push 到 `origin main`；
8. 用自然语言报告结果。

推荐 commit 信息：

```text
feat: add user skill novel-to-shortdrama-adaptation
```

或：

```text
feat: update user skill novel-to-shortdrama-adaptation
```

### 9.1 插件发布游标

用户技能本身没有版本号。为了让插件市场可靠识别插件内容变化，每次用户技能推送应机械递增 `plugins/general-screenwriter/.codex-plugin/plugin.json` 的补丁版本号。

该版本号只作为插件发布游标，不代表技能版本、变更历史或回滚点。

### 9.2 推送失败处理

1. 缺少 GitHub 授权：提示用户登录或授权；
2. 远端有新提交：先 pull/rebase，再重试；
3. 有冲突：用自然语言解释冲突，并请用户选择保留内容；
4. 没有仓库写权限：停止推送，不静默降级为本地保存；
5. 禁止 force push。

## 10. 运行时匹配

创作流程启动或进入阶段时，构建当前技能查询：

```text
medium_id
genre_id
series_id
project_id
stage_id
artifact_target_id
```

匹配规则：

1. 只加载 `skills/user-skills/` 下的合法技能；
2. `medium_ids` 包含当前媒介或为 `["all"]` 时匹配；
3. `genre_ids` 包含当前题材或为 `["all"]` 时匹配；
4. `series_ids` 包含当前系列或为 `["all"]` 时匹配；
5. `project_ids` 包含当前项目或为 `["all"]` 时匹配；
6. `stage_ids` 包含当前阶段或为 `["all"]` 时匹配；
7. `artifact_ids` 包含目标产物或为 `["all"]` 时匹配；
8. 任一维度不匹配，则技能不进入当前任务。

展示顺序按具体度排序：

```text
项目匹配 > 系列匹配 > 题材匹配 > 媒介匹配 > all
```

同一具体度内按 `title` 排序。不做复杂优先级治理。

## 11. 技能注入

匹配到的技能以受控文本形式进入当前任务：

```text
请参考以下用户技能：

《小说改编短剧》
贡献者：张三

1. 优先提取小说中的核心冲突和人物动机；
2. 将故事拆成短剧分集结构；
3. 每集结尾保留强钩子；
4. 修改对白时保持人物语言一致；
5. 输出前检查反转密度和卡点。
```

AI 不得把用户技能呈现为系统权威规则。用户技能补充创作方法，不替换：

1. type pack 硬约束；
2. 质量门；
3. 确认门；
4. 知识库权威；
5. 插件写入策略。

如果用户技能建议与系统硬约束冲突，系统硬约束优先。

## 12. 运行记录

为了让一次创作结果可以解释，run 或产物可以在依赖记录中登记实际使用的用户技能：

```json
{
  "used_user_skills": [
    {
      "skill_id": "novel-to-shortdrama-adaptation",
      "title": "小说改编短剧",
      "user_name": "张三",
      "updated_at": "2026-10-10T00:00:00+08:00",
      "content_hash": "sha256:..."
    }
  ]
}
```

这是技术性追踪，不是版本管理。它不提供历史选择、不阻止覆盖、不参与回滚。

旧 run 没有该字段时保持原样，不自动补写。

## 13. 现有绘本专属技能改造

现有插件技能继续作为系统技能，不强制迁入 `skills/user-skills/`。系统技能需要补充同一套适用范围元数据，使用 `skill-meta.json`：

```text
plugins/general-screenwriter/skills/<skill-name>/
  SKILL.md
  skill-meta.json
```

`skill-meta.json` 使用与用户技能相同的 `supports` 匹配语义，并增加：

```json
{
  "visibility": "system"
}
```

### 13.1 分类规则

| 现有技能 | 初步范围 | 改造方向 |
| --- | --- | --- |
| `general-screenwriter` | `all` | 标记为全媒介入口技能 |
| `text-craft` | `picturebook` | 保留绘本文字工艺；如后续抽取通用叙事/对白工艺，再拆出 `all` 通用层 |
| `craft-benchmark-check` | `picturebook` | 保留绘本逐页脚本量化检查；不误标为全类型 |
| `staging-planner` | `picturebook` | 保留绘本分镜站位；后续可抽象成通用视觉场景规划，但第一版不改算法语义 |
| `image-prompt-architect` | `picturebook` | 保留绘本生图提示词；如未来支持短剧视觉物料，再增加媒介适配层 |
| `image-generate` | `picturebook` | 保留绘本插画生成路径 |
| `illustration-export` | `picturebook` | 保留绘本插画导出路径 |
| `pre_create-baseline` | `all` | 标记为通用创作前置流程 |
| `in_create-baseline` | `all` | 标记为通用创作执行流程 |
| `post_create-baseline` | `all` | 标记为通用创作后处理流程 |
| `quality-baseline` | `all` | 标记为通用质量检查流程 |
| `story-planning` | `all` | 标记为通用轻量构思技能 |
| `knowledge-loader` | `all` | 标记为通用知识检索技能 |
| `wiki-ingest` | `all` | 标记为通用资料归纳技能 |
| `feishu-knowledge-store` | `all` | 标记为通用知识发布技能 |
| `session-export` | `all` | 标记为通用会话导出技能 |
| `stage-orchestration` | `all` | 标记为通用阶段调度技能 |

最终表以实施时逐个核对为准；没有把握的技能不得为了覆盖面而改成 `all`。

### 13.2 改造边界

1. 先加元数据，不急于改技能行为；
2. 只有方法论确实跨媒介时才标 `all`；
3. 绘本专属量化指标、分镜算法和插画流程继续限定 `picturebook`；
4. 如果要把绘本技能泛化，必须拆分通用层和绘本层，不能直接把绘本术语强行应用到短剧或长剧；
5. 不把用户技能提升为系统技能；
6. 系统技能不因用户技能存在而失去调用优先级。

## 14. 与现有设计的过渡

现有 `user_skill_contract.py`、`user_skill_resolver.py` 和 `user-skills.example.json` 使用了版本、生命周期、依赖和审计字段。新设计发布后：

1. 用户技能格式以本 spec 为准；
2. 旧契约代码可以在过渡期保留，但不再是新用户技能中心的权威；
3. 不再要求用户技能提供 `version`、`status`、`audit`、`depends_on`、`conflicts_with` 和 `precedence`；
4. `stage_dag` 中涉及用户技能快照的逻辑应改为兼容旧快照、优先读取新轻量格式；
5. 后续实施计划中决定是否删除旧注册表解析器。

## 15. 验收标准

第一版完成时，应满足：

1. 用户通过自然语言创建一个“小说改编短剧”技能；
2. AI 缺少用户姓名时会主动询问；
3. `manifest.json` 的所有适用范围字段非空；
4. 全类型、全系列、全项目技能使用 `all`，不使用空数组；
5. 技能可以被推送到插件仓库；
6. 其他用户更新插件后能看到该技能；
7. 短剧创作上下文能自动匹配到该技能；
8. 绘本创作上下文不会误调用短剧专属技能；
9. 更新技能会覆盖旧内容，并要求用户确认；
10. 用户技能不能携带或触发任意可执行代码；
11. 现有系统技能有适用范围元数据；
12. 现有绘本专属技能没有被错误扩展到短剧或长篇连续剧；
13. 全量插件测试、治理检查和打包检查通过。

