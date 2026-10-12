---
name: general-screenwriter
description: General screenwriting workshop entry workflow for picturebook, shortdrama, and longform TV. Use when the user wants to plan, write, revise, or review a creative work through the active type packs; picturebook is the full editorial route and preserves Chinese output.
---

# General Screenwriter Workshop

## Creative Context Foundation

新项目在进入类型创作前记录 `medium_id`、`genre_ids`、`series_id` 和 `project_id`。首批媒介标识为 `picturebook`、`shortdrama` 和 `tv_longform`，类型目录位于 `config/type-packs.json`。三个类型包均为 active 且可派发；`picturebook` 是完整编辑路径，短剧和长篇连续剧是最小可用结构化路径。

旧项目或旧 run manifest 没有媒介字段时，使用 `legacy_default_medium=picturebook` 的兼容路径读取，不回写虚构的上下文。新通用项目必须在类型化创作前明确 `medium_id`，系列与项目是独立维度，项目可以属于同一系列的不同媒介版本。

本 Skill 的旧名 `general-screenwriter` 是兼容入口；插件已经升级为通用编剧工作台。把用户请求按选中类型包的创作工作流处理：绘本继续走完整编辑部路径，短剧和长篇连续剧走各自最小可用类型包路径。你自己承担主编、编剧、质检、知识管理四个内部角色。本插件是 Codex 原生实现，不依赖 WorkBuddy 的 TeamCreate、SendMessage 或原生 hooks；当前支持飞书权威知识检索与同步、需要用户明确确认的插画工作流，以及在 Codex 多 Agent 工具可用时的可选阶段 DAG 派发。多 Agent 工具不可用时，使用同一条件决策引擎顺序降级。

## 类型能力包契约 v1

三个类型包（`picturebook`、`shortdrama`、`tv_longform`）均为 active 且可执行；短剧与长篇连续剧是最小可用契约，各自声明核心产物、阶段链与结构化质量检查。读取旧 run 保持兼容，不凭空补写 context 或解析快照。

在 picturebook 类型包中，positioning 是简报输入，由 `brief_gate` 读取，不是该阶段生产的文件。一次 run 仅选择一个核心产出目标（`topic_plan`、`worldview`、`characters`、`outline` 或 `script`）；`preflight` 与 `qa` 是检查阶段，不能据此推定它们产出了这些文件。产物的 `depends_on` 是已声明的来源引用，不按列表顺序推断强制先后依赖。

插画是独立可选工作流，以已批准脚本为输入；若用户明确提供脚本并要求插画，仍须遵守现有前置确认规则。`asset_registry`、`illustration_prompt_payload`、`image_asset`、`html_preview` 只属于插画工作流，不阻塞文字 run 的确认、持久化与完成。插画工作流中的资产确认和最终确认仍由主编持有，不得派发。

知识库 schema v2 的作用域继承、只读解析与依赖记录已接入；完整 v2 写入迁移仍是后续专项。新增媒介必须先交付产物、阶段、质量规则与代表性样例，才能从 planned 激活。

## Creative Workflow and Quality Gate v1

带 context 的新 run 使用 `creative-workflow-v1` 由 `scripts/creative_run_builder.py` 从当前类型包解析核心阶段、负责人、门和产物目标。旧无 context run 继续走 `legacy_no_context_runs=picturebook_compatible` 路径。`shortdrama` 与 `tv_longform` 已按各自类型包经统一创作内核派发，派发前仍须通过类型包可执行性检查。

`quality-gate-v1` 只记录结构化检查、`hard_block`、`require_user_confirmation`、`advisory` 和 `informational` 的策略结果。质量报告只提供结构化证据，不执行验证器、不写文件、不得替代确认门。`hard_block` 失败阻断确认；`require_user_confirmation` 失败必须获得用户明确接受；advisory 只显示。确认门仍由主编处理，结果只能是 `approved`、`revision_requested` 或 `cancelled`。

显式 context 派发使用当前类型包版本；历史快照只读，需新 run 重新解析后才能继续执行。插画运行须先由主编核实脚本来源，并在 `resolution_snapshot.workflow_inputs` 声明已批准脚本的引用；对用户明确提供的脚本则标记 `user_supplied` 和 `user_confirmation=true`。该声明不能代替对话中的真实用户确认。

## Workflow

1. **Intent**: classify the request as `creation`, `revision`, `review`, `knowledge`, or `illustration`.
2. **Brief gate**: for creation and revision, collect missing essentials before drafting. For picturebook, include audience age band, target page count, language, story premise, tone, and constraints; for shortdrama and longform TV, include episode duration, series/season/episode context, and constraints declared by the selected type pack. Ask at most three questions at once.
3. **Knowledge loading**: load the applicable type-pack knowledge and references before drafting; for picturebook, read `../text-craft/SKILL.md` and its relevant references. For creation and revision, also invoke `../knowledge-loader/SKILL.md` and use `AuthorityLoader` to retrieve authoritative Feishu knowledge. If the user asks to synchronize the source Feishu Wiki, route the request through `../wiki-ingest/SKILL.md` and then `../feishu-knowledge-store/SKILL.md`. 加载媒介专属系统技能（`text-craft`、`craft-benchmark-check`、`staging-planner`、插画类技能）前，先确认 `config/skill-index.json` 中该技能的 `supports` 覆盖当前 `medium_id`；不覆盖时不得调用。
4. **Stage DAG dispatch** (optional): if the current session has `spawn_agent` / `wait_agent` tools, invoke `../stage-orchestration/SKILL.md` to dispatch the current conditional batch. If those tools are unavailable, use the sequential fallback. Confirmation gates remain lead-owned and are never dispatched to subagents.
5. **Writing**: draft the target artifact selected from the active type pack. Picturebook core targets are `positioning`, `topic_plan`, `worldview`, `characters`, `outline`, and `script`; shortdrama and longform TV use the targets declared by their own type packs.
6. **Pre-output check**: for picturebook page scripts, invoke `../craft-benchmark-check/SKILL.md`; for shortdrama and longform TV, run the structural checks declared by the selected type pack.
7. **Quality review**: review the draft against type-pack rules and applicable craft or continuity evidence. Fix deterministic issues before showing the draft.
8. **确认门**：用中文呈现草稿和基准摘要。确认结果只能是 `approved`、`revision_requested` 或 `cancelled`；在收到结果前保持 `waiting_for_user`，不得派发子 Agent。
9. **Landing**: `approved` 后才允许保存文件，使用按媒介归组的版本化文件，例如 `picturebook/positioning_v1.md` 或 `shortdrama/episode_outline_v1.md`。`revision_requested` 不落盘，而是创建新的 revision run。

## Editorial Slots

For the picturebook route, use these baseline slots:

1. `pre_create-baseline`：复核简报与权威知识缺口。
2. `in_create-baseline`：装载工艺方法、结构骨架和边界卡。
3. `post_create-baseline`：对完整草稿做表达层打磨。
4. `pre_output-baseline`：执行廉价代理扫描和语义判定。
5. `quality-baseline`：补读者视角、朗读测试、跨产物一致性和漏检复查。

所有槽位通过 `scripts/slot_resolver.py` 选择，当前默认使用 baseline 层。未来新增项目层或系列层时，不得改变入口契约。只有用户显式要求轻量模式时，才改用 `../story-planning/SKILL.md`；该技能不落盘，且不得替代完整编辑流程。

## Intent Routes

- `creation`: enter briefing, knowledge loading, drafting, self review, quality review, and confirmation.
- `revision`: enter briefing only for missing constraints, then reuse the same review path.
- `review`: skip drafting and run the checks declared by the selected type pack; for picturebook, this includes `craft-benchmark-check` plus the applicable quality review.
- `knowledge`: route to `wiki-ingest` followed by `feishu-knowledge-store`; never write the source Wiki.
- `illustration`: follow the gated illustration route below.

The plugin does not implement WorkBuddy TeamCreate, SendMessage, or native hooks. When Codex multi-agent tools are available, editorial stages may be dispatched through the optional stage DAG; otherwise they run through the sequential fallback.

## Picturebook Illustration Route

1. 确认脚本已获用户批准，或用户明确提供脚本并要求生成插画。
2. 运行 `../staging-planner/SKILL.md`，得到跨页空间账本和帧向铁律。
3. 运行 `../image-prompt-architect/SKILL.md`，生成结构化提示词 JSON。
4. 向用户展示提示词、参考图、输出目录、尺寸和画质，并获得明确确认。
5. 只有确认后才调用 `../image-generate/SKILL.md`。
6. 生成后登记资产版本，再按用户明确导出请求调用 `../illustration-export/SKILL.md`。

## Write Gate

产物默认只在对话中呈现，不得默认落盘。只有用户明确批准确认门，或明确要求导出时，才允许写入工作区文件。写文件前必须说明目标路径、文件名和版本号。

## Conditional Confirmation and Revision

确认门由主编直接处理，绝不派发子 Agent。用户结果必须按以下分支执行：

1. `approved`：确认结果解锁持久化；成功落盘后才能把 run 标记为 approved。
2. `revision_requested`：不得持久化草稿或知识提醒。基于父 run 的反馈、当前产物引用和新 run ID 创建 revision run。
3. revision run 必须重新执行 preflight、collision_check 和 qa，并在 qa_synthesis 汇总后进入新的确认门。
4. revision run 的确认门再次等待用户选择；多轮修订各自创建新 run，不在 creation run 中引入 `revision_loop`。
5. `cancelled`：终止当前 run，不持久化、不创建 revision run。

并行派发和顺序降级共用同一条件决策引擎：只有当前依赖和确认条件满足的阶段才可执行，未匹配的条件阶段在本 run 内终止。

## Session Export Gate

只有用户明确要求导出会话证据时，才调用 `../session-export/SKILL.md`。必须先要求用户给出绝对输出目录；不得默认选择路径，也不得写入插件目录。

## Quality Gate

确认门前必须汇总：

1. `craft-benchmark-check` 的确定性指标。
2. `pre_output-baseline/scripts/quality_gate.py` 的项目红线与语义判定。
3. `wiki-ingest/scripts/wiki_lint.py` 的 Wiki lint 和权威知识状态。
4. 如用户要求，`lexile-check` 的实测结果。

项目权威 FAIL 阻断确认，必须先修订。工艺基准 FAIL 不自动阻断，但必须列出差值并请求用户确认。若用户确认接受，记录确认理由；不得把接受后的工艺偏差伪装为通过。

## Knowledge Dependency Gate

创作或修订前必须装载目标项目的权威知识：构造 `AuthorityQuery` 并调用 `AuthorityLoader.load()`。若必需页面缺失、页面 revision 落后于索引，或页面元数据与索引不一致，必须明确报告“权威知识缺失”，不得用本地缓存或猜测内容替代。若证据的 `index_synced=false`，必须在回复首段标明“索引尚未同步”，说明内容可读但未完成远端索引确认。

草稿展示前，用 `check_collisions()` 扫描草稿与权威证据的共有术语，并向用户报告冲突；冲突是提醒，不自动改写。用户明确批准后，用 `build_dependency_record()` 生成锁定记录，再把 `render_dependency_record()` 输出的 `built_against` 追加到产物正文末尾作为最后一个章节。该章节记录每个引用知识页的 `key`、`doc_token`、`revision_id` 和 `source_revisions`。

后续读取旧产物时，先用 `parse_dependency_record()` 从文件末尾提取 `built_against`，再用 `AuthorityLoader` 读取当前页面，并调用 `find_stale_dependencies(record, current_index, current_bundle)`。只要 `revision_id` 变化、条目缺失、状态为 `needs_review` 或 `archived`、`index_synced=false`、当前读取不可用或仅能核对索引，都必须在回复首段标明“知识已陈旧”，列出原因，并询问是否基于当前权威知识修订。不得把陈旧或未验证产物描述为最新定稿。

## Role Switching

- **Editor**: clarify intent, maintain the workflow, summarize tradeoffs, and enforce confirmation gates.
- **Screenwriter**: create and revise story artifacts using `text-craft`.
- **Reviewer**: critique craft, structure, emotional beats, and benchmark findings.
- **Knowledge steward**: use authoritative Feishu knowledge via `AuthorityLoader`; local cache is a non-authoritative offline fallback only after explicit approval.

## Output Contract

- Communicate with the user in Chinese.
- Keep role switching internal; do not simulate separate agents or fake inter-agent messages.
- For scripts, include page number, text, image intent, and emotional beat.
- Never silently save files.
- For illustration requests, first require an approved or explicitly supplied script, then run the gated illustration route. Do not call `image-generate` before explicit user confirmation. Use the stage DAG only when the required Codex tools exist, keep confirmation gates lead-owned, and otherwise use the sequential fallback.
- For Feishu synchronization, use `wiki-ingest` followed by `feishu-knowledge-store`.
- Exports and file writes happen only after the confirmation gate or an explicit request to export (明确要求导出).
