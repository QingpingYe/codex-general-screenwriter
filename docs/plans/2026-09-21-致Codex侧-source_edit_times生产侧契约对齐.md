# 致 Codex 侧：`source_edit_times` 是一处**单边契约**——生产侧规范缺失 + 发布侧 preserve 短路

> 发件方：WorkBuddy 侧 picturebook-screenwriter（绘本编剧工坊）
> 收件方：Codex 侧 picturebook-screenwriter 维护者
> 日期：2026-09-21 | 协议版本：v1.3.0
> 主题：下载层增量判定的版本信号 `source_edit_times` 在真机上**全部为 null** 的根因、本侧修复、以及请贵方同步处置的部分

## 零、一句话结论

`source_edit_times` 在**消费侧早已完整实现**（解析 / 校验 / 写入 / 渲染），但**生产侧的三处规范从未要求摄入环节产出它**，且**发布侧的 `preserve` 分支会把这个字段丢掉**。二者叠加的净效果：该字段从发布之日起就没被写过一次，真机 12 条索引条目**全为 `null`**，下载层增量判定每轮退化为 `unknown`（等同全量重读）。

这不是"忘了补写"，是**两层结构性缺口**。本侧已修复两层；若贵方也有独立的发布实现或摄入规范，需**同一口径**同步，否则会出现新的单边契约。

---

## 一、实证：字段在链路两端"一热一冷"

### 1.1 消费侧：全链路已支持（`skills/feishu-knowledge-store/`）

| 环节 | 位置 | 行为 |
|---|---|---|
| 候选页解析 | `page_codec.py` `parse_candidate` | 读 frontmatter `source_edit_time_parts` → 合成为 `source_edit_times` 映射 |
| 页尾元数据校验 | `page_codec.py` `_validate_metadata` | `required = {…六字段}`，`optional = {"source_edit_times"}` —— **第七字段是显式允许的可选项** |
| 渲染远端页 | `page_codec.py` `render_remote_page` | 有则写入页尾 JSON 块 |
| 索引条目写入 | `publisher.py:90/108/176` | 三处写入/透传 |
| 索引条目模型 | `models.py` `IndexEntry.source_edit_times: dict[str,int] | None = None` | 注释直书"None = 旧条目（协议 v1.3.0 前发布）" |

### 1.2 生产侧：三处规范**全无此字段**（修复前）

| 规范文件 | 修复前状态 |
|---|---|
| `schema/wiki-page-frontmatter.schema.md` | 「来源追踪字段」表只有 `source_node_tokens` + `source_revision_parts`（**两组**）；且「发布页机器可读元数据」节写死"**固定六字段**""字段必须且只能是上述六个"——**与实现直接矛盾** |
| `skills/wiki-ingest/references/structured-output-templates.md` | frontmatter 模板无该字段 |
| `skills/wiki-ingest/SKILL.md` Step 7 | 只要求记录 `source_node_tokens[]` 与 `revision_id` |

`generate_entries.py` 虽有校验分支，但措辞是"**A2 协议字段（可选）**……若存在则校验"——**只保证"写对了不报错"，不保证"会被写"**。

### 1.3 真机实测：12 个 staging 候选页零命中

```
$ grep -rn "source_edit_time_parts" wiki_staging/      # 修复前
（零命中）
# 每页只有 source_node_tokens + source_revision_parts
```

⇒ 索引条目自然无该字段 ⇒ 下载层判据回退 `unknown`。

### 1.4 发布侧第二处缺口：`preserve` 短路丢字段

`sync_runner.py` `_decide()` **只比 `source_revisions`**：

```python
source_changed = dict(candidate.metadata["source_revisions"]) != dict(entry.source_revisions)
if not source_changed:
    return _Decision("preserve", "原始资料无变化，保留当前目标页")
```

于是 `_update()` 的 preserve 分支只刷 `last_seen_revision_id`，**返回旧条目**：

```python
replace(entry, last_seen_revision_id=current_revision)   # 修复前：候选侧的 source_edit_times 被丢弃
```

**后果放大**：源未变的页占绝大多数（真机 12 条里 10 条 preserve），这些条目**永远不会自愈**。即使生产侧以后写对了，只要页面内容没变，索引条目就一直在 `preserve` 里被旧值覆盖。

### 1.5 第三处缺口：零变更快路径

全 `unchanged` 时跳过下载 / 合成 / 写入，**连索引页都不重写**——存量 null 条目在这个路径下没有任何自愈机会。

---

## 二、字段契约的精确规范（请贵方照此对齐）

### 2.1 staging 候选 frontmatter

```yaml
source_node_tokens:              # 必填：string[]，宿主原始资料节点 token
  - "{node_token}"
source_revision_parts:           # 必填：string[]，逐源修订号，与 node_tokens 等长
  - "{revision}"                 #   ⚠ 一律**带引号字符串**
source_edit_time_parts:          # 可选但强烈建议写全：integer[]，逐源编辑时间（毫秒）
  - 1756572300000                #   ⚠ 一律**裸整数，不得加引号**
```

### 2.2 远端页尾块（KB-AI 权威页唯一机器可读元数据）

**必填六字段**：`schema_version` / `key` / `page_type` / `source_node_tokens` / `source_revisions` / `last_ai_revision_id`
**可选一字段**：`source_edit_times`（对象：`{源 token: 毫秒整数}`）

> 注意：修复前本侧 `schema/wiki-page-frontmatter.schema.md` 写的是"**固定六字段**"，与 `page_codec.py` 的 `optional={"source_edit_times"}` **矛盾**。该文档已改为"六必填 + 至多一可选"。**若贵方 schema 文档同样写死六字段，请一并订正**——否则照文档实现的一方会主动拒绝这个字段。

### 2.3 三条硬约束（违反即被发布入口拒绝）

| # | 约束 | 校验点 |
|---|---|---|
| 1 | `source_edit_time_parts` 元素必须是**正整数 int**（`bool` 不算） | `page_codec.py`：`isinstance(v, bool) or not isinstance(v, int) or v <= 0` → 拒 |
| 2 | **键集（长度 + 顺序）必须与 `source_node_tokens` 完全一致** | `page_codec.py`：`len(edit_time_parts) != len(source_node_tokens)` → 拒；`_validate_metadata`：`set(edit_times) != set(tokens)` → 拒 |
| 3 | 某源 `edit_time_ms` 缺失（降级链两路皆失败）时，**该页整页省略此字段** | 不得只写一部分——否则键集与 tokens 不一致，整页发不出去 |

---

## 三、本侧已做的修复

### 3.1 生产侧对齐（三处规范 + 一处保持不收紧）

| 文件 | 改动 |
|---|---|
| `schema/wiki-page-frontmatter.schema.md` | ①「来源追踪字段」表加 `source_edit_time_parts` 行（含类型方向与键集约束）；②「两组字段分工」→「**三组**字段分工」，加入版本信号组；③「发布页机器可读元数据」节由"固定六字段"改为"**六必填 + 至多一可选**"，并订正字段集规则句 |
| `skills/wiki-ingest/references/structured-output-templates.md` | frontmatter 通用字段块加 `source_edit_time_parts`（标注裸整数）；下方说明段补充语义与"不加引号"提醒 |
| `skills/wiki-ingest/SKILL.md` Step 7「候选页准备」 | 新增一条：每页记录 `source_edit_time_parts[]`，取自 Step 2 `_nodes_snapshot.json` 的 `edit_time_ms`，并写明 null 时整页省略 |
| `skills/wiki-ingest/scripts/generate_entries.py` | **有意不收紧为必填**——先让存量对齐一轮，下一轮再按需把"必须写"变成硬校验（见第六节） |

### 3.2 发布侧 `preserve` 补刷新（`skills/feishu-knowledge-store/scripts/sync_runner.py`）

```python
if decision.action == "preserve":
    counts["preserved"] += 1
    # 源未变 ⇒ 目标页零触碰（不覆盖是对的）。但索引条目的**版本信号**
    # source_edit_times 是源侧事实（"本轮读到各源在什么时刻"），与页面内容
    # 是否变更无关，故一并刷新——否则旧条目（协议 v1.3.0 前的 null）永远
    # 不自愈。候选侧无值（老候选页未写 source_edit_time_parts）时保留条目
    # 原值，不抹掉既有基线。
    refreshed = candidate.metadata.get("source_edit_times") or entry.source_edit_times
    return _Outcome(
        ACTION_PRESERVED, decision.reason, entry.key,
        replace(entry, last_seen_revision_id=current_revision,
                source_edit_times=refreshed),
        current_revision, current_revision,
    )
```

**设计要点**：这个字段是**源侧事实**，不是页面内容的函数。页面不动是对的，但索引条目没有理由拒绝吸收它。`or` 回退保证老候选页不会把既有基线抹成 null。

新增两条防回归测试（`test_sync_runner.py`）：

- `test_preserve_refreshes_source_edit_times_on_the_index_entry` —— 条目为 null（旧条目）+ 候选带值 ⇒ 刷新
- `test_preserve_keeps_existing_edit_times_when_candidate_lacks_them` —— 条目有值 + 候选无值 ⇒ 保留原值

---

## 四、请贵方同步处置

### 4.1 若贵方有独立的摄入规范（必须）

`source_edit_time_parts` 的**生产侧要求**需在贵方对应规范中同样声明——字段名、类型方向（裸整数）、键集一致性三条硬约束逐字对齐。否则双方产出的候选页在这一个字段上形状不同，会成为**新的单边契约**。

### 4.2 若贵方有独立的发布实现（必须核查）

请检查贵方的 `preserve` / "源未变即跳过"分支是否有同样问题：**源侧事实字段不应因页面未变更而被丢弃**。判据很简单——问一句：

> "当源版本向量未变、但本轮读到了新的 `source_edit_times`，贵方的索引条目会不会吸收它？"

若答案是"不会"，那么贵方也与本侧修复前一样，存量条目**永远不会自愈**。

### 4.3 若贵方 schema 文档写死"固定六字段"（建议）

与 4.1 同源——文档与实现互相矛盾时，先照文档实现的一方被动拒绝。本侧已改为"六必填 + 至多一可选"。

---

## 五、实现时必踩的三个坑（供贵方规避）

1. **标量类型方向与既有陷阱相反**。`source_revision_parts` 必须**带引号字符串**；`source_edit_time_parts` 必须**裸整数**。实测本侧 YAML 解析：裸 `-?[0-9]+` 全匹配 → `int()`；带引号走引号分支返回 `str`，紧接着 `page_codec.py` 的 `isinstance(v, int)` 直接拒。**写反了整页发不出去**。
2. **键集必须与 `source_node_tokens` 完全一致**。若某页有**任一**源 `edit_time_ms` 为 null（降级链两路都缺），则该页**整页**不能带这个字段——不能只写一部分。
3. **回填值必须取当下快照**。用过期值会让下一轮误判 `changed`（只是多一次重摄，不丢数据，但会白跑一轮）。好消息：它**不参与** `_decide` 的 `source_changed` 判定，回填不会引起页面抖动。

---

## 六、存量 12 条的回填（方案 A）

**依据**：索引条目本身是一张页（`99_系统控制台/同步索引`），"写索引"走发布通道；而 `publish` 只有 `--from-staging` / `--dry-run` / `--holder`，**无 force / 元数据刷新开关**；`preserve` 也不补字段（修复前）。因此存量回填必须**制造一次真实的重处理**。

**采用方案 A**：用 `check_delta.py --only <全部内容节点 token>` 触发一轮**定点重摄**（子集节点一律按真实判定，unchanged 也会因定点语义重摄），走正常发布入口 → 层 2 的 preserve 刷新自动写入 `source_edit_times`。

- **零新代码**，全程走协议入口（锁 / 回读 / 校验全部复用）
- **代价**：9 个源重下载重合成一轮（≈一次全量）
- **顺序有硬依赖**：第三节的生产侧对齐必须先于本次回填（否则无数据源）；层 2 的 preserve 刷新必须先于本次回填（否则 preserve 仍会丢）

**备选（未采用）**：B 新增一次性 `backfill-edit-times --from-snapshot` 命令（动作最小但多一份常驻代码）；C 人工改远端索引页 JSON（不推荐，12 条 × 多 token 手写且 `_index_entry` 校验严格）。

**下一轮建议**：存量对齐后，可把 `generate_entries.py` 的 `source_edit_time_parts` 从"存在时校验"收紧为**必填 FAIL**（凡发布环节必被拒的，就在校验这里失败——与本侧既有口径一致）。本轮先不收紧，避免存量候选页集体判 FAIL。

---

## 七、本侧改动清单与验证

| 文件 | 改动 |
|---|---|
| `schema/wiki-page-frontmatter.schema.md` | 三处（字段表 / 三组分工 / 六必填+一可选） |
| `skills/wiki-ingest/references/structured-output-templates.md` | 两处（模板字段 / 说明段） |
| `skills/wiki-ingest/SKILL.md` | Step 7 候选页准备新增一条 |
| `skills/feishu-knowledge-store/scripts/sync_runner.py` | preserve 分支补刷新 |
| `skills/feishu-knowledge-store/scripts/test_sync_runner.py` | 新增两条防回归测试 |

**验证**：`feishu-knowledge-store` 全量回归 **41 tests OK**（原 39 + 新增 2）；约束门禁全量扫描 **EXIT=0**（源根 + cache 运行副本）。

## 八、存量回填结果（本轮已执行 · 方案 A）

**执行**：`check_delta.py --only <全部 9 个内容节点 token>` 定点重摄一轮 → 正常发布入口（run `d9a3eade6038`，索引 revision **18 → 20**）。

**结果：12/12 条目 `source_edit_times` 全部非 null**（键集与 `source_node_tokens` 完全一致、顺序一一对应）：

| 逻辑键 | source_edit_times（源 token 前缀 → 毫秒） |
|---|---|
| common/creation-standards | `HBT7…→1789350333000`；`XyAI…→1789350190000` |
| common/market-research | `IaC1…→1788948293000` |
| common/quality-rubric | `AaCv…→1789350245000`；`NGpE…→1789350291000` |
| 小狗Barry/{characters,content-spec,creation-standards,references,worldview} | 均 `SLpx…→1789961741000` |
| 小老鼠迈尔斯/characters | `YeBD…→1789990239000` |
| 小老鼠迈尔斯/content-spec | `DDPR…→1789352991000` |
| 小老鼠迈尔斯/creation-standards | `DDPR…→1789352991000` |
| 小老鼠迈尔斯/worldview | `K8EX…→1789980700000` |

**端到端验证（回填后不带 `--only` 重跑增量判定）**：

```
DELTA: 12 nodes → skip 9 / process 3 / new 3 / deleted 0 / unknown 0
```

9 个内容节点由 `unknown` **全部翻转为 `unchanged`（skip）**，legacy 判据回退**消失**（unknown 0，且原先那条 "索引存在缺 source_edit_times 的旧条目" WARN 不再出现）。**根因消除：下载层不再每轮回退为全量重读。** 余 3 = 容器页（正常容器过滤路径）。

**独立复核（本侧另跑，未复用执行方输出）**：

| 检验 | 方法 | 结果 |
|---|---|---|
| 生产侧真的写了吗 | 对 12 个 staging 候选页调发布入口 `parse_candidate` 实解析 | **12/12** 产出 `source_edit_times`，值全为 `int`、键集与 tokens 对齐 |
| 远端真的落库了吗 | `store_cli index` 只读回读 | **12/12 非 null**，与 staging 值完全一致 |

**真实变更披露**：`小老鼠迈尔斯/characters` 的源文档在**上一轮同步之后**被真实编辑（rev 26 → 28），该页经 `source_only_change` 发布（页面 revision 6 → 8）；其余 11 页源未变 → `preserve`（**页面零触碰**）。未生成新页、未改写任何正文。

**⚠ 连带影响（本侧已处置）**：权威值因此推进 —— `authority_lock.characters` 6 → 8，已同步刷新（并新增 `authority_advance_log` 留档）。两个脚本产物的 `built_against.characters` 仍为 6，是否随权威推进待裁断（见第九节）。

## 九、待裁断：`built_against` 是否随权威推进

`小老鼠迈尔斯/characters` 页 revision 由 6 推进到 8（源真实编辑所致，正文实质内容经复核未变），使上一轮「口径纠正」写入的 `built_against.characters = 6` 与当前权威值不再相等。两条路：

- **A 同步推进**（延续上一轮口径纠正精神）：`built_against.characters` → 8，**不标陈旧**。依据：本轮复核确认为来源引用行 + frontmatter 变化，正文实质内容未变。
- **B 保守标注**：保留 6 并标 `stale_due_to_authority_update: true` + `stale_details` 说明，提示人工复核两个脚本。符合协议"权威更新 ⇒ 依赖产物陈旧"的字面语义，但会留下需人工关闭的标记。

本侧**未擅自处置**——这是跨产物的语义裁断。
