# User Skill Hub

## 用途

以自然语言帮助用户创建、导入/适配、更新或覆盖轻量用户技能。用户技能只承载可注入的方法、检查清单、参考资料或导出说明，不承载可执行文件。

本技能是自然语言入口，不得把内部命令作为用户界面。不要要求 screenwriter 运行命令；必要的目录检查、manifest 校验、类型包校验和文件写入由工作流在内部完成。

## 三种模式

### Create

用于从用户的想法或素材创建新用户技能。

### Import / Adapt

用于从 GitHub 仓库、对话文本或既有文档导入技能，再改造成符合当前用户技能契约的技能包。导入内容只能保留为方法、检查清单、参考资料或导出说明；外部示例中的执行步骤、密钥、真实项目数据和非通用规则必须先清理。

### Update / Overwrite

用于修改现有技能内容、作用域、标题或描述。若目标目录已存在且要替换文件，这是覆盖模式；先完整展示差异或新文件预览，再等待确认。

## 必问与确认

创建或导入用户技能前，必须先询问 user_name。没有明确的归属人，不得创建或导入技能。若用户没有给出，询问归属人是用户名还是组织名，并原样记录到 `user_name`。

还要确认：

1. `skill_id`：小写连字符目录名，创建后与目录名保持一致。
2. `title`、`description`：说明技能用途和适用方法。
3. `skill_type`：`prompt_skill`、`checklist_skill`、`reference_skill` 或 `exporter_skill`。
4. `medium_ids`、`genre_ids`、`series_ids`、`project_ids`、`stage_ids`、`artifact_ids`：全部使用当前类型包的 canonical ID；`all` 不能与具体 ID 混用，也不接受别名。
5. `SKILL.md`：用户可读的方法主体。

覆盖现有技能前必须获得用户明确确认。确认信息必须指明目标 `skill_id`、将要替换的文件和不可恢复风险。未确认前不得删除或替换已有 `manifest.json` 或 `SKILL.md`。

## 预览格式

写入前先给出紧凑预览：

```text
skill_id: <id>
title: <标题>
user_name: <归属>
skill_type: <类型>
medium_ids: <数组>
genre_ids: <数组>
series_ids: <数组>
project_ids: <数组>
stage_ids: <数组>
artifact_ids: <数组>
updated_at: <ISO 8601 时区时间>
changes: 新建 / 修改 / 覆盖
preview:
<SKILL.md 摘要或关键变化>
```

覆盖时逐项列出旧值和新值；无法恢复的删除项单独标出。

## 校验与写入

用户确认后，按用户技能契约生成只包含 `manifest.json` 和 `SKILL.md` 的技能目录。工作流必须先运行用户技能树校验，确认：

- 字段完整、类型正确、`skill_id` 与目录一致；
- 六个 support 数组非空、无重复、`all` 不混用具体 ID；
- medium、stage、artifact 都是 canonical active ID；
- `content` 是 `SKILL.md` 且非空；
- 目录没有额外文件或可执行文件。

校验失败时不得写入、不得覆盖，也不得提交。

## Git 与补丁版本

用户技能属于插件包，源仓库是 `https://github.com/QingpingYe/codex-general-screenwriter.git`。

写入技能包后，若用户要求保存或提交，机械递增 plugin.json 的 patch 版本，例如 `0.6.0` 到 `0.6.1`。不要改 major 或 minor，不要手写日期或描述性版本号。

如果用户要求同步远端，先确认当前分支和未提交工作，再执行 pull/rebase；存在冲突时停止并让用户选择保留方向。推送前必须获得用户明确确认，禁止自动 push。失败或网络不可用时保留本地文件和未提交变更，说明下一步选项。

## 失败处理

- 缺 `user_name`：停下询问，不得假设归属。
- 缺创作上下文或作用域：询问最小必要信息，或建议用 `all`。
- manifest 或类型引用无效：展示具体错误，不写入。
- 目录已存在：切换到更新/覆盖确认。
- 导入内容不安全：移除执行指令、密钥、私有数据，再让用户复查。
- 用户改变意图：回到 create、import/adapt 或 update/overwrite，重新预览。
