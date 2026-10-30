---
name: user-skill-hub
description: 以自然语言创建、导入/适配、更新或覆盖轻量用户技能的入口；负责归属确认、契约校验与本地安装，不执行任何 git 操作。
---

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

1. `skill_id`：只使用小写英文、数字和中间连字符的目录名，创建后与目录名保持一致。
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

预览时还必须给出软提醒：范围声明过于宽泛、标题过于笼统、正文缺少输入/方法/输出/检查点，或 `skill_id` 与已有技能相似。提醒不阻塞校验，但必须在用户确认前明确展示。

## 校验与写入

用户确认后，先把技能包写入插件仓库之外的暂存目录 `<暂存根>/<skill_id>/`（只含 `manifest.json` 与 `SKILL.md`），运行单包校验并展示预演提醒；校验失败时不得写入插件目录。

校验通过后调用内部安装入口（`install_user_skill_pack`，或 `user_skill_hub.py install`）完成换入：安装器在插件根同卷暂存区复核技能包，备份被覆盖的旧目录（若存在），换入新目录，再对整个用户技能树复查；任一步失败都会回滚到旧内容，live 树不会出现半写入的技能包。安装完成后确认：

- 字段完整、类型正确、`skill_id` 与目录一致；
- 六个 support 数组非空、无重复、`all` 不混用具体 ID；
- medium、stage、artifact 都是 canonical active ID；
- `content` 是 `SKILL.md` 且非空；
- 目录没有额外文件或可执行文件。

任一环节校验失败时不得写入或覆盖。安装完成后运行 `scripts/build_skill_index.py` 重新生成 `config/skill-index.json`，保持本地索引与技能树一致。

## 本地保存

用户技能只保存在本地插件目录 `skills/user-skills/<skill_id>/`。本流程不执行任何 git 操作：不提交、不推送、不改插件版本号，也不提供共享发布或远端同步；安装完成即为本地生效。需要共享或同步时由用户在流程之外自行处理，本技能不代劳。

## 失败处理

- 缺 `user_name`：停下询问，不得假设归属。
- 缺创作上下文或作用域：询问最小必要信息，或建议用 `all`。
- manifest 或类型引用无效：展示具体错误，不写入。
- 目录已存在：切换到更新/覆盖确认。
- 导入内容不安全：移除执行指令、密钥、私有数据，再让用户复查。
- 用户改变意图：回到 create、import/adapt 或 update/overwrite，重新预览。
