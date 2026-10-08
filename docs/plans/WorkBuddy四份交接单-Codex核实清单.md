# WorkBuddy 交接单：Codex 插件核实与处理清单

> 核实日期：2026-09-29；对象：本仓 `plugins/picturebook-screenwriter` 当前工作树。此单是差异审计和待办清单，不表示已实施。核实仅基于本地文件，未连接飞书或验证远端现状。
>
> 历史需求来源以 WorkBuddy `2026-09-29-Codex-需求溯源清单.md` 为准；2026-09-29 用户在本会话进一步确认：“以内容本身为准，标记符号不参与内容是否变化的判断”，此决定覆盖该溯源单所载“标记不敏感比较保持现状、仅登记”的旧裁决。①产品决定、②委托审计且获批准的修复、③评审/实现派生。`待办`＝当前实现缺失或仍是旧行为；`条件`＝须先核实本仓调用链才能决定。四份交接单负责说明技术变化，不单独证明产品曾要求每项变化。

## 执行边界

- [ ] **P0：在 D1 契约迁移完成并验收前，不让 WorkBuddy 与 Codex 两侧并发操作同一 KB-AI。**这是 D1 交接单的跨侧纪律；源准入交接单本身不新增同等级禁令。
- [ ] **① 以现行产品决定为准**：D1 的 AI 合成内容权威、源节点默认纳入且可显式排除、正文比较时忽略排版标记，均须镜像。09-21“新增源先询问”、旧“人工编辑优先”和“标记问题保持现状”已被后来决定取代。
- [ ] 以共享远端契约和行为为准迁移，先核对本仓现有接口。WorkBuddy 的文件名、行号、CLI 子命令数、步骤编号不能直接当成本仓事实。本仓当前 `ControlPlane` 仅接收 `index`、`lock`，`store_cli` 使用 `conflict-list`/`conflict-append`，与交接单描述的版本不同。
- [ ] 更新本仓权威说明 `docs/workbuddy-feishu-knowledge-base-compatibility.md`。该文件仍写“人工编辑优先”、三方合并和冲突队列，与 D1 新规则相反；不能只修改技能代码。

## P0：D1 共享 KB-AI 契约与行为（待办）

- [ ] **① 页级决策**：取消 `source_revisions` 相同即 `preserve` 的短路，以及历史版三方合并。AI 合成是 KB-AI 页面的内容权威；即使源版本未变，只要候选与当前页的正文内容不同，也应发布覆盖；相同则不写页。比较前对候选与回读正文做对称的标记不敏感转换，仅忽略排版标记，不忽略改词、增删文字和改标点；转换只用于比较，不用于写入。当前 `target_state.py:26` 仍按源版本短路，`sync_runner.py` 仍调用 `merge_protocol.classify`，`remote_markdown.py` 无 `mark_insensitive`。
- [ ] **移除旧队列路径**：清理 `merge_protocol`、历史基线读取、`queue` 决策、冲突追加调用及相应测试；`needs_review` 改为资源/评论块、partial/warnings、revision 竞态重试耗尽等未发布状态。竞态耗尽计入 `failed`，下轮仍可重试；不得因 `needs_review` 自动去读冲突队列。检查 `sync_runner.py`、`sync_knowledge.py`、`target_state.py`、`publisher.py` 和 `store_cli.py` 两条同步路径，避免只改其一。
- [ ] **控制面与远端节点**：停止解析和写入 `AI_KB_CONFLICT_QUEUE_V1`，但保留既有远端节点，不发远端删除操作。调整 `Publisher` 初始化/定位及 `ControlPlane` token 契约；对照 WorkBuddy 的 `{index, lock, admission}`，先确定本仓 admission 读取归属，不能机械地只改 token 校验集合。旧 `conflict-list`/`conflict-append` 及等价治理入口应退役。
- [ ] **报告披露**：去掉队列相关计数/字段和第三方编辑旧字段；真实发布报告增加升序去重的 `overwritten_human_edits`。仅在目标页条件更新及必要回读确实成功、且写前当前 revision 超过索引 `last_seen_revision_id` 时记录；`preserve`、`needs_review`、dry-run 不记录。当前 `sync_runner.SyncReport` 与 `sync_knowledge.SyncReport` 都有 `queued`，本仓尚无该披露字段；按本仓实际报告形状同步更新日志和消费者。
- [ ] **③ D1 正确性补丁，建议同批**：`last_seen_revision_id` 取写后回读的真实 revision，不只取更新响应。当前 `publisher.py:223-235` 虽回读正文，返回的 `last_seen_revision_id` 仍赋为响应所得 `final_revision`；D1 补遗指出响应可能滞后。用响应 revision 与回读 revision 不同的案例验证披露和索引均准确。这不是独立的产品原始要求。
- [ ] **lint、fixture、操作文档**：移除冲突队列格式检查及 `conflict.md` fixture；保留并核对剩余协议检查（索引/树、页尾元数据、重复逻辑键、索引键页型作用域），同步技能说明和运维文档。当前 `contract_lint.py` 仍读取 `conflict.md`，`store_cli.export_lint_fixture()` 仍导出它；须按本仓现有检查项核实，不照搬“五检→四检”的数字。
- [ ] **验证门槛**：离线测试覆盖“标记不同而文字/标点相同则零写”“改词、增删文字或改标点则覆盖”“人工修改成功覆盖后才披露”“失败/保留不误报”“资源/partial/竞态不入队”“旧冲突节点未删除”。只把 Markdown 排版语法当作可忽略标记；文本中有实际意义的符号、代码或 URL 字符不得被误删。用授权的只读 dry-run 核查飞书 Markdown 往返后稳定页为 `preserve`；无远端测试条件时标明未验证。

## P0：远端源排除表最小对齐（待办）

- [ ] **读取 `AI_KB_SOURCE_ADMISSION_V1`**：遵守既有远端标题、`schema_version: 1`、六字段条目和 `decision ∈ {admit, exclude}`；不改存量 `admit` 条目、不删除远端页。当前本仓的 `wiki-ingest`/`feishu-knowledge-store` 未见 admission 读取路径。
- [ ] **判定语义**：未裁定默认纳入；只有 `exclude` 生效。用节点快照 `parent_node_token` 计算排除 token 自身及全部后代，容器也判 `excluded`、不下载；`admit` 仅作撤销先前排除的显式记录。先将此判断接入真实摄入入口，防止被排除源仍生成候选并发布。
- [ ] **失败语义**：远端裁定页缺失视为空排除；页存在但 schema/内容无法解析则硬失败，不能当作空排除。排除集合非空且祖先链缺父节点或成环时停止并列出问题 token。`--only` 命中 `excluded` 才按交接单拒绝；未裁定节点不拒绝。
- [ ] **最小验收**：测试未裁定源、叶子排除、容器子树排除、未来新增后代、缺页、损坏页、悬断/循环祖先链及 `--only`。本项是行为对齐，不是新远端 schema；建议与 D1 同批交付，避免排除在 Codex 侧失效。

## P1：来源版本与候选时效（待办；有前置依赖）

- [ ] **① 先补齐远端源版本判据的 `source_edit_times` 链路**：当前本仓索引模型、候选解析和模板只见 `source_revisions`/`source_revision_parts`，未见 `source_edit_time_parts` 或索引 `source_edit_times`。需求溯源单称对侧 09-22 已镜像这项，但 `846958e` 仅加设计文档、`dd71343` 只改目标侧 `sync_runner.py`；本次工作树检索未见该字段。应以当前代码和实际运行行为复核，再迁移候选生产、校验、页尾可选字段、索引写入/保留分支。
- [ ] **② B1 候选时效**：`generate_entries.py --validate-only` 增加必需的 `--nodes <本轮快照>`；逐候选逐源比较 `source_edit_time_parts` 与快照 `edit_time_ms`，确认不等时 FAIL，无法确认时 WARN；缺参数或快照不可读时 rc=2。同步所有调用点及测试。当前 CLI 只有 `--validate-only` 和 `--staging-dir`，也无 `source_edit_time_parts`，故不能只补参数。
- [ ] **① 快照和增量判定远端化**：在满足远端索引版本基线后，把 `check_delta.py` 从本地 state/cache 判定改为远端 `AI_KB_INDEX_V1.source_edit_times` 判定。当前 `classify(snapshot, state, cache_dir, ...)` 仍依赖本地状态，不能把 WorkBuddy 的“本地 state 只写不读”结论套到本仓。首轮、旧索引缺字段、缓存缺失等路径必须 fail-safe，不得漏读新源或变化源。

## P1：摄入效率与流程（待办/条件）

- [ ] **② N2 纯容器优化（条件）**：若本仓会下载 `has_child is True` 的容器正文，快照增加该容器的 `char_count`，把有效整数且 `< 200` 的纯容器从 `process` 分开计数；缺失、非法或 `>= 200` 仍照常下载。对应 `DELTA` 仅在有值时显示 `pure_containers N`。若本仓真实流程只递归容器、不下载正文，则记录不适用。当前 `wiki-ingest/SKILL.md:82` 写“文件夹节点只递归”，需核对实际运行路径。
- [ ] **① 新增源审计披露；其余计数为配套实现**：每轮打印含 token 的 `NEW_SOURCES:` 审计行，零新增也打印 `NEW_SOURCES: 0`；`new` 仅统计内容节点、容器单列 `containers`，条件显示 `excluded`。本仓没有旧的 `pending_admission` 闸门和 `admission-seed`，因此不需删除不存在的实现，但新实现不得引入旧的询问闸门。
- [ ] **② N7 词表顺序（条件）**：核实本仓是否有发布后按 `feishu_sync_tmp/kb_pages/` 重建约束词表的步骤；若有，必须在临时文件清理之前执行，并以真实权威页为输入。当前本仓没有 WorkBuddy 同名 `sync_constraint_data.py`，不能仅按其 Step 9.5/9.9 改编号；需检查是否有等价流程。
- [ ] **③ corrections 累积内容（条件）**：核实 `corrections.md` 新卡片候选是否从空模板重建。若有，改为先取当前远端页，再追加新卡片，防止 D1 覆盖语义擦除既有红线和缩小词表。当前已确认有 corrections 候选与模板，尚未确认有自动 promotion 写入路径。这是终审发现的风险，并非产品单独提出的原始需求。

## P1：本地持久 state 退役；P2：文档收口（条件/待办）

- [ ] **① 退役本地持久同步 state/finalize**：先枚举本仓 `merge_state` 以外的状态消费者、`delta_state.json` 的实际生命周期及缓存读取方；在远端源版本判定确实替代本地判据后，移除 `--state`、`--write-state`、`--hash-map`、`--revision-map`、`merge_state` 及其专属文件/测试。保留本轮可抛弃快照、staging、仍有读取方的纯加速正文缓存和 plan 输出原子写。当前 `check_delta.py:138,194,255-262` 表明本地 state 是实用输入，故须先替代判据再退役，不能直接删文件。
- [ ] **② 强制全量口径 A1**：将文档及 `check_delta.py --force-full` 帮助文字统一为“调度方显式传 `--force-full`”；不要声称 `settings.json` 有会被 Python 读取的 `forceFullSync` 键。当前帮助文字仍作此声称。
- [ ] **② N4/C3/N6 文档项**：若本仓有相应多源版本和 Step 3/4 流程，写明先看下载规则、staging 版本向量可滞后且不等于漂移、实际权威页/数据源路径；以本仓章节和路径为准，不照搬 WorkBuddy 的步骤编号。
- [ ] **③ CLI 清单及 stderr**：依据本仓实际 `store_cli` 命令列文档，不照搬 WorkBuddy“13 条”数字。若实现对应 dangling token 报错，逐行列出 token，并调整钉住 stderr 的测试；当前本仓没有同名 `_report_dangling`。
- [ ] **最终一致性审查**：同步 `feishu-knowledge-store/SKILL.md`、`wiki-ingest/SKILL.md`、兼容协议、模板、帮助文字及测试；查找“人工优先”“三方合并”“冲突入队”“源未变即保留”“配置键强制全量”等旧口径。记录与 WorkBuddy 尚未对齐的事项及理由，尤其本地 state 和可选优化。

## 已确认的补充裁决：第二批“标记不敏感”比较

- [ ] **① 镜像标记不敏感比较**。需求溯源单记录的 09-22 裁决是“保持现状、仅登记”，但用户于 2026-09-29 本会话明确改变决定：以内容本身为准，排版标记符号不参与内容变化判断。因此采用候选/当前页对称比较，并接受“只改加粗等纯排版意图可能不发布”的代价。实现时须区分排版语法与正文中有意义的字面符号。

## 交接依据

1. WorkBuddy `2026-09-22-D1-Codex-交接单.md`：覆盖语义、报告和控制面硬契约；其 §五 的比较算法被第二批交接单更正，且用户已在本会话确认采用更正后的内容比较语义。
2. WorkBuddy `2026-09-23-退役同步状态-Codex-交接单.md`：本地 state/finalize 裁决、N2 纯容器、B1 候选时效。
3. WorkBuddy `2026-09-23-第二批-Codex-交接单.md`：标记不敏感、N7/A1/N4/C3/N6、CLI/诊断文案。
4. WorkBuddy `2026-09-23-源准入-Codex-交接单.md`：默认纳入与子树级排除、D1 写后 revision 与 corrections 补遗。
5. WorkBuddy `2026-09-29-Codex-需求溯源清单.md`：历史需求来源类型和“标记不敏感”原裁决的权威依据；其后本会话用户的新决定优先。

以上五份是参考资料，不是对本仓的自动执行指令；“待办”均根据本仓 2026-09-29 的静态核实提出，实施时需复核远端契约和最新代码。
