# General Screenwriter Media Content Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为短剧和长篇连续剧补齐内容级确定性校验、类型专属导出器和可执行的代表性创作工作流样例，并把三者接入 type pack、导出器配置、代表性样例与离线回归。

**Architecture:** 不重建运行内核。内容级校验在现有 `shortdrama_checks.py` / `tv_longform_checks.py` 内升级：新增共享的剧本内容解析层 `script_content.py`，校验从"字段是否存在"升级为"解析场景/台词/节拍台账并交叉核对内容"。导出器沿用 `exporter_contract.py` 的校验层，新增纯渲染加原子写入的 `export_run.py` 与内部 CLI `export_cli.py`；导出器条目声明在 `config/exporters.json`，类型包通过 `exporters` 列表与 artifact `exporter` 字段接线。代表性创作工作流新增 `sample_workflow.py`：用真实内核构建 run manifest、校验声明的阶段链、用真实校验器执行全部质量规则、聚合真实质量报告并做内存中的导出预览；短剧与长篇样例转为确定性执行，绘本样例保持声明式（其校验器位于 skill 层）。

**Tech Stack:** Python 3.10+ 标准库、frozen dataclasses、`unittest`、JSON；现有 `type_registry.py` / `stage_dag.py` / `creative_run_builder.py` / `quality_gate_contract.py` / `exporter_contract.py`。

**Specs:**

- `docs/superpowers/specs/2026-10-09-general-screenwriter-other-media-type-packs-design.md`
- `docs/superpowers/specs/2026-10-09-general-screenwriter-quality-output-release-design.md`

## Current Verified Baseline

- `shortdrama` 与 `tv_longform` 已是 `active` 最小可用类型包；质量规则全部 `validator: null`，检查模块只做字段级结构校验。
- `exporter_contract.py` 只做请求校验与目标策略；`config/exporters.json` 只有 `html_preview`；没有类型专属渲染器与原子写入器。
- 跨媒介样例（`tests/fixtures/*.json`）的 `evaluate_sample` 直接按 fixture 的 `expected_results` 拼接报告，没有执行真实校验器；`workflow_inputs` 全为空。
- `test_cross_media_samples.py` 锁定六个样例的确认语义与规则漂移；`run_plugin_tests.py` 自动发现新增测试文件。

## Global Constraints

- 不新增第三方运行时依赖；内容级校验与导出渲染全部确定性，不调用模型、不访问网络、不读远端知识库。
- 默认写盘策略仍是 `dialog_only`。只有导出器收到显式 `output_directory` 与 `filename` 参数时才写文件；目标已存在时默认失败关闭，覆盖必须显式 `overwrite_allowed=True`；失败不得留下临时文件或半成品。
- 内容级校验只从脚本内容（场景、台词、节拍、台账）与显式引用产物推导结论；引用产物缺失时失败关闭，不得静默通过。
- 旧绘本入口、旧 run/manifest、旧插画流程与绘本声明式样例语义保持不变；`picturebook` type pack 本阶段不改动质量规则与校验器。
- 类型包规则改动必须与代表性样例的规则快照同步（`test_cross_media_samples` 的规则漂移检查会强制这一点）。
- 每个任务先写失败测试并观察失败，再写最小实现；每任务收尾运行 `python .\scripts\run_plugin_tests.py` 全绿；每个任务单独提交。
- 命令均在仓库根 `E:\codex-picturebook-agent` 执行；执行方式 inline（用户已指定开始）。

## Review Focus

1. **空洞内容不得通过**：字段齐全但开头钩子空行、全程动作无台词、结尾无钩子的剧本必须失败——Task 1/2 的"空洞内容"用例覆盖。
2. **跨集引用缺失失败关闭**：没有 `series_bible` / `character_arc_map` 引用时 `series_constraint`、`character_state` 必须失败而不是跳过或通过——Task 2 用例覆盖。
3. **导出失败零残留**：目标已存在、渲染失败、非法文件名（路径穿越）时不得写文件、不得留 `.tmp`；写入必须原子——Task 3 用例覆盖。
4. **样例不得再伪造结果**：确定性样例的每条结果必须来自真实校验器（evidence 标记来源），fixture 不得携带 `expected_results` 兜底——Task 5 用例覆盖。
5. **阶段链必须真实可达**：代表性工作流声明的阶段序列必须在当前类型包中拓扑有序、目标产物由链中阶段产出——Task 5 用例覆盖。
6. **中文内容与编码**：中文台词、中文文件名与 UTF-8 输出在所有导出格式中正确——Task 1/3/5 用例覆盖。

---

### Task 1: 共享剧本解析层与短剧内容级校验

**Files:**
- Create: `plugins/general-screenwriter/scripts/script_content.py`
- Modify: `plugins/general-screenwriter/scripts/shortdrama_checks.py`
- Create: `plugins/general-screenwriter/tests/test_script_content.py`
- Modify: `plugins/general-screenwriter/tests/test_shortdrama_type_pack.py`
- Modify: `plugins/general-screenwriter/config/type-packs.json`
- Modify: `plugins/general-screenwriter/tests/fixtures/shortdrama-pass.json`
- Modify: `plugins/general-screenwriter/tests/fixtures/shortdrama-fail.json`

**Interfaces:**
- Produces:
  - `ScriptContentError(ValueError)`（`errors: tuple[str, ...]`）
  - `ScriptScene(scene_id, heading, location, time_of_day, lines, transition)`
  - `ScriptLine(kind, text, speaker)`（`kind` 取值 `action` / `dialogue`）
  - `ParsedScript(scenes, beats, line_count, action_count, dialogue_count, speakers, scene_index)`
  - `parse_episode_script(payload) -> ParsedScript`
  - `scene_dialogue_lines(parsed, scene_id) -> tuple[ScriptLine, ...]`
  - `validate_shortdrama_rules(check_id, artifact, context, references=None) -> QualityCheckResult`
- Consumes: `quality_gate_contract.QualityCheckResult`。

规范 episode_script 载荷（短剧与长篇共用）：

```json
{
  "artifact_id": "episode_script",
  "format": "episode_script",
  "duration_seconds": 120,
  "scenes": [
    {
      "scene_id": "S1", "heading": "场1 天台 夜",
      "location": "天台", "time_of_day": "夜",
      "lines": [
        {"kind": "action", "text": "她推开门，风卷走手里的证物袋。"},
        {"kind": "dialogue", "speaker": "林一", "text": "谁动了我的证据？"}
      ],
      "transition": "切至走廊"
    }
  ],
  "beats": [
    {"beat_id": "b1", "function": "hook", "scene_id": "S1"}
  ],
  "conflict": {"goal": "夺回证据", "escalation_beat_ids": ["b2"],
               "closure_beat_id": "b4", "closed": true},
  "characters": [
    {"name": "林一", "states": [
      {"beat_id": "b1", "state": "calm"},
      {"beat_id": "b4", "state": "determined"}
    ]}
  ]
}
```

解析规则：`scenes` 非空数组；`scene_id` 唯一且非空；`heading`、`location`、`time_of_day` 非空；`lines` 为数组，`kind` 只能是 `action`/`dialogue`，`text` 非空，`dialogue` 必须有 `speaker`；`beats` 为数组，条目含 `beat_id`/`function`/`scene_id` 且 `scene_id` 可解析。解析失败抛 `ScriptContentError`，由检查函数转为 `fail` 并带 `evidence["errors"]`。

检查语义（`CHECK_STAGES` 与阻断策略保持现状不变；全部 8 条规则的 `validator` 在配置中改为 `"shortdrama-checks"`，pack `validators` 列表加 `"shortdrama-checks"`）：

- `opening_hook`：第一个 beat 的 `function == "hook"` 且其 `scene_id` 是第一个场景；该场景至少一行文本长度不小于 6 的台词或动作。
- `turning_point`：存在 `function in {"turn", "reversal"}` 的 beat；其索引（0 起）位于 `[n//4, (3*n)//4]`；该 beat 场景至少一行台词。
- `closing_hook`：最后一个 beat 的 `function in {"closing_hook", "cliffhanger"}`；其 `scene_id` 是最后一个场景；该场景至少一行非空文本。
- `pacing_density`：场景数至少 3；每个场景至少 2 行；台词占比至少 0.25；`duration_seconds / 场景数` 在 `[10, 80]` 秒内（`duration_seconds` 无效时该项失败）。
- `conflict_closure`：`conflict.goal` 非空；`closed is True`；`closure_beat_id` 解析到 beat；闭包索引大于全部 `escalation_beat_ids` 索引且其后无 escalation；闭包场景至少一行台词。
- `character_state`：`characters` 非空；每个角色的状态节拍严格递增；状态发生变化的 beat 场景必须包含该角色的台词；剧本中出现的全部台词角色都必须登记在 `characters`。
- `duration`：`duration_seconds` 为正数且在 `[30, 900]` 秒内；估算时长 `= 台词行数*4.0 + 动作行数*2.5 + 场景数*3.0`，声明值与估算偏差不超过 35%。
- `format`：`format == "episode_script"`；`scene_id` 从 `S1` 连续编号；台词行全部带 speaker；无空文本。

阈值以模块级常量声明（`HOOK_MIN_CHARS = 6`、`SCENE_SECONDS_RANGE = (10, 80)`、`DIALOGUE_SHARE_MIN = 0.25`、`MIN_SCENES = 3`、`DIALOGUE_SECONDS = 4.0`、`ACTION_SECONDS = 2.5`、`SCENE_SETUP_SECONDS = 3.0`、`DURATION_TOLERANCE = 0.35`、`DURATION_RANGE_SECONDS = (30, 900)`）。

- [x] **Step 1: 写失败测试**

`test_script_content.py` 覆盖：合法载荷解析成功（场景数/台词占比/speakers 正确）；`scene_id` 重复、`kind` 未知、台词缺 speaker、`lines` 空数组分别抛 `ScriptContentError` 且 `errors` 非空。

`test_shortdrama_type_pack.py` 把 `episode()` 帮助函数升级为上述规范载荷（5 个场景、5 个 beat：hook/escalation/turn/escalation/closing_hook、两条角色状态线、120 秒），并新增：

```python
def test_hollow_script_content_fails_even_with_all_fields(self):
    result = validate_shortdrama_rules("opening_hook", hollow_episode(), context)
    self.assertEqual(result.status, "fail")

def test_turn_must_sit_in_middle_band(self):
    result = validate_shortdrama_rules("turning_point", episode_moved_turn_to_last(), context)
    self.assertEqual(result.status, "fail")

def test_duration_mismatch_with_content_is_reported(self):
    result = validate_shortdrama_rules("duration", episode(duration_seconds=600), context)
    self.assertEqual(result.status, "fail")
    self.assertIn("estimated_seconds", result.evidence)

def test_unregistered_speaker_fails_character_state(self):
    result = validate_shortdrama_rules("character_state", episode_with_guest_speaker(), context)
    self.assertEqual(result.status, "fail")
```

同时保留既有语义用例（缺失/空字段失败、未知 check_id 抛 `ValueError`、`closing_hook` 失败进入 `require_user_confirmation` 不阻断 `passed`）。合法性样例断言 `result.evidence["source"] == "content"`。

- [x] **Step 2: 运行并确认失败**

Run: `python plugins\general-screenwriter\tests\test_script_content.py; python plugins\general-screenwriter\tests\test_shortdrama_type_pack.py`
Expected: 前者 import 失败；后者多项失败（新载荷下旧实现无法通过内容级断言）。

- [x] **Step 3: 实现解析层与内容级检查（GREEN）**

新建 `script_content.py`（纯函数、无 IO）；重写 `shortdrama_checks.py` 的 `_CHECKS` 为内容级实现，全部结果带 `evidence["source"] = "content"` 与关键度量（`scene_id`、`estimated_seconds`、`dialogue_share` 等）；异常路径统一返回 `fail` 而不是抛出（`ValueError` 仅保留给未知 check_id）。

- [x] **Step 4: 接线 type pack 与样例规则**

`config/type-packs.json`：`shortdrama.validators == ["shortdrama-checks"]`，全部质量规则 `validator` 改为 `"shortdrama-checks"`；同步更新两个 `shortdrama-*.json` 样例的规则条目（保持声明式评估不动）。

Run: `python scripts\release_gate.py`
Expected: `registry_contract`、`quality_gate`、`exporter_contract` 步骤通过（类型契约与样例漂移不回归）。

- [x] **Step 5: 全量回归**

Run: `python .\scripts\run_plugin_tests.py`
Expected: `OK: N offline commands passed`（命令数随新测试文件增加）。

- [x] **Step 6: 提交**

```powershell
git add plugins/general-screenwriter/scripts/script_content.py plugins/general-screenwriter/scripts/shortdrama_checks.py plugins/general-screenwriter/tests/test_script_content.py plugins/general-screenwriter/tests/test_shortdrama_type_pack.py plugins/general-screenwriter/config/type-packs.json plugins/general-screenwriter/tests/fixtures/shortdrama-pass.json plugins/general-screenwriter/tests/fixtures/shortdrama-fail.json
git commit -m "feat: add content-level shortdrama validation"
```

### Task 2: 长篇连续剧内容级校验（跨集连续性）

**Files:**
- Modify: `plugins/general-screenwriter/scripts/tv_longform_checks.py`
- Modify: `plugins/general-screenwriter/tests/test_tv_longform_type_pack.py`
- Modify: `plugins/general-screenwriter/config/type-packs.json`
- Modify: `plugins/general-screenwriter/tests/fixtures/tv-longform-pass.json`
- Modify: `plugins/general-screenwriter/tests/fixtures/tv-longform-fail.json`

**Interfaces:**
- Consumes: Task 1 的 `parse_episode_script` / `scene_dialogue_lines` / `ScriptContentError`。
- Produces: `validate_tv_longform_rules(check_id, artifact, context, references=None) -> QualityCheckResult`；`references` 为 artifact_id 到载荷的映射，可含 `season_arc`、`series_bible`、`character_arc_map`、`timeline_ledger`、`episode_list`、`continuity_ledger`。

规范长剧 episode_script 载荷（在 Task 1 载荷基础上增加）：

```json
{
  "series_id": "s1", "season_id": "season-1", "episode_id": "e2",
  "episode_function": "推进主线：揭露内鬼线索。",
  "arc_beat_ref": "arc-b2",
  "timeline": [{"order": 11, "event": "夜谈", "scene_id": "S1", "flashback": false}],
  "foreshadows": [{"id": "f2", "source": "旧怀表", "purpose": "指向密室", "scene_id": "S1"}],
  "payoffs": [{"foreshadow_id": "f1", "resolution": "怀表指向密室", "scene_id": "S2"}],
  "character_states": [
    {"name": "林一", "prior_state": "calm", "state": "shaken", "transition_scene_id": "S2"}
  ],
  "continuity_ledger_ref": "series/s1/continuity/e2",
  "continuity_ledger": {
    "linked_artifacts": ["episode_script", "season_arc"],
    "entries": [{"field": "character_states", "value": "林一: calm -> shaken"}],
    "conflicts": []
  }
}
```

检查语义（全部 9 条规则 `validator` 改为 `"tv-longform-checks"`，pack `validators` 加 `"tv-longform-checks"`；阻断策略保持现状）：

- `season_arc`：`references["season_arc"].beats` 非空；`arc_beat_ref` 解析到 beat；evidence 记 `beat_id`/`goal`。
- `episode_function`：`episode_function` 至少 6 字；若有 `references["episode_list"]` 且含当前 `episode_id`，功能描述必须一致。
- `timeline`：`timeline` 非空；`order` 严格递增且为整数；每条事件 `scene_id` 可解析；有 `references["timeline_ledger"].last_order` 时，非闪回事件 `order` 必须大于它；闪回条目不参与但记录在 evidence。
- `foreshadow`：伏笔 id 唯一；`source` 场景可解析；`purpose` 非空；本集未回收的伏笔必须有非空 `planned_payoff`。
- `payoff`：每条回收必须指向本集伏笔或 `references["continuity_ledger"].open_foreshadows` 中已登记的 id；场景可解析；同集回收场景索引不得早于伏笔场景；同一伏笔不得重复回收。
- `scene_transition`：相邻场景地点或时段变化时，前一场景 `transition` 必须非空；违反对的 scene_id 进 evidence。
- `character_state`：条目字段非空、`transition_scene_id` 可解析；状态变化场景必须含该角色台词；有 `references["character_arc_map"].latest.states` 时 `prior_state` 必须与上一集记录一致，否则以 `{series_id}:{episode_id}:character-state` 记入 `evidence["conflicts"]` 并失败；台词角色必须全部登记。
- `series_constraint`：必须有 `references["series_bible"]`；台词角色必须是圣经角色；`banned_terms` 出现在任何文本中即失败并列出命中；`series_id` 与圣经的 `series_id` 一致。
- `continuity`：`continuity_ledger_ref` 非空；`continuity_ledger.linked_artifacts` 非空且全部存在于 references；`entries` 非空且值非空；`conflicts` 必须为空，非空则失败并列出。

- [x] **Step 1: 写失败测试**

升级 `episode()` 为规范载荷并新增：

```python
def test_missing_series_bible_fails_closed(self):
    result = validate_tv_longform_rules("series_constraint", episode(), context)
    self.assertEqual(result.status, "fail")

def test_timeline_regression_against_previous_ledger_is_reported(self):
    references = longform_references(timeline_last_order=99)
    result = validate_tv_longform_rules("timeline", episode(), context, references)
    self.assertEqual(result.status, "fail")
    self.assertEqual(result.evidence["regressions"], ["e2:order-11"])

def test_prior_state_mismatch_reports_character_conflict(self):
    references = longform_references(prior_states={"林一": "asleep"})
    result = validate_tv_longform_rules("character_state", episode(), context, references)
    self.assertEqual(result.status, "fail")
    self.assertEqual(result.evidence["conflicts"], ["s1:e2:character-state"])

def test_well_formed_episode_passes_every_check_with_references(self):
    for check_id in TV_LONGFORM_CHECK_IDS:
        result = validate_tv_longform_rules(check_id, episode(), context, longform_references())
        self.assertEqual(result.status, "pass")
```

既有冲突报告格式用例（更新为当前 episode_id）与缺失字段失败用例保留。合法性样例断言 `result.evidence["source"] == "content"`。

- [x] **Step 2: 运行并确认失败**

Run: `python plugins\general-screenwriter\tests\test_tv_longform_type_pack.py`
Expected: 多项失败（无 references 语义与内容级断言）。

- [x] **Step 3: 实现内容级检查（GREEN）**

重写 `tv_longform_checks.py`；所有检查无 `references` 需要时按"依赖缺失失败关闭"处理；evidence 统一带 `source` 与度量。

- [x] **Step 4: 接线 type pack 与样例规则**

同 Task 1：pack `validators` 与规则 `validator` 更新；两个 `tv-longform-*.json` 样例规则同步。

- [x] **Step 5: 全量回归**

Run: `python .\scripts\run_plugin_tests.py`
Expected: 全绿。

- [x] **Step 6: 提交**

```powershell
git add plugins/general-screenwriter/scripts/tv_longform_checks.py plugins/general-screenwriter/tests/test_tv_longform_type_pack.py plugins/general-screenwriter/config/type-packs.json plugins/general-screenwriter/tests/fixtures/tv-longform-pass.json plugins/general-screenwriter/tests/fixtures/tv-longform-fail.json
git commit -m "feat: add content-level tv longform validation"
```

### Task 3: 类型专属导出器渲染与原子写入

**Files:**
- Create: `plugins/general-screenwriter/scripts/export_run.py`
- Create: `plugins/general-screenwriter/scripts/export_cli.py`
- Create: `plugins/general-screenwriter/tests/test_export_run.py`
- Modify: `plugins/general-screenwriter/config/exporters.json`

**Interfaces:**
- Produces:
  - `ExportRunnerError(ValueError)`
  - `ExportResult(exporter_id, output_format, destination, bytes_written, manifest)`
  - `render_export(exporter_id, payloads, user_params=None) -> str`（纯函数，无 IO）
  - `write_export(destination, content, overwrite_allowed=False) -> Path`（同目录临时文件加 `os.replace`；失败清理临时文件）
  - `run_export(exporter_id, artifact_refs, payloads, user_params, *, overwrite_allowed=False, contract_path=None) -> ExportResult`
- Consumes: `exporter_contract.load_exporter_contract` / `validate_export_request` / `check_export_destination` / `build_export_manifest`。

`config/exporters.json` 新增条目（`model_calls` 均为 `forbidden`）：

| exporter_id | supported_types | output_format | required_user_params |
| --- | --- | --- | --- |
| `shortdrama_episode_script` | episode_script | screenplay_text | output_directory, filename |
| `shortdrama_production_checklist` | scene_table | production_checklist | output_directory, filename |
| `tv_episode_script` | episode_script | screenplay_text | output_directory, filename |
| `tv_season_package` | episode_script, continuity_ledger, season_arc | markdown | output_directory, filename |
| `structured_json` | episode_script, continuity_ledger, season_arc, scene_table | json | output_directory, filename |

渲染规则：
- `screenplay_text`：逐场景输出 `heading`，动作行原样，台词行 `speaker：text`，非空 `transition` 以 `【转场】…` 结尾；场景间空行分隔。
- `production_checklist`：输出 Markdown 表格 `场次 | 地点 | 时段 | 出场 | 道具 | 转场 | 备注`，缺省列显示 `-`。
- `tv_season_package`：头部 `《series_id》S{season}E{episode}` 与 `集功能`、`季弧线目标`（取自 season_arc 载荷中匹配 `arc_beat_ref` 的 beat），随后嵌入 `screenplay_text`，最后输出连续性条目表格。
- `structured_json`：`json.dumps(payloads[current_artifact], ensure_ascii=False, indent=2, sort_keys=True)`；多输入时输出 `{"artifacts": {...}}`。
- `render_export` 必须校验载荷必需字段；渲染失败抛 `ExportRunnerError`，且不得产生任何文件。

`run_export` 顺序：加载契约、`validate_export_request`、校验 `filename` 是纯文件名（`Path(filename).name == filename`，否则失败）、解析 `output_directory / filename`、`check_export_destination`、`render_export`、`write_export`。`output_directory` 不存在时按显式参数创建。

`export_cli.py`：`--exporter-id`、`--artifact-refs`（JSON 文件）、`--payloads`（JSON 文件）、`--params`（JSON 文件）、`--overwrite`；成功打印 `ExportResult` JSON 并返回 0，`ExporterContractError`/`ExportRunnerError` 打印 stderr 返回 1，用法错误返回 2。

- [x] **Step 1: 写失败测试**

`test_export_run.py` 覆盖（临时目录，不触碰仓库文件）：

```python
def test_script_render_is_deterministic_and_keeps_chinese_text(self): ...
def test_season_package_embeds_arc_and_continuity(self): ...
def test_existing_destination_is_not_overwritten_without_opt_in(self): ...
def test_failed_render_leaves_no_files_and_no_temp(self): ...
def test_filename_with_path_separator_is_rejected(self): ...
def test_write_failure_removes_partial_temp_file(self): ...
def test_cli_roundtrip_writes_file(self): ...
```

- [x] **Step 2: 运行并确认失败**

Run: `python plugins\general-screenwriter\tests\test_export_run.py`
Expected: import 失败（模块不存在）。

- [x] **Step 3: 实现渲染器、写入器与 CLI（GREEN）**

- [x] **Step 4: 配置与既有导出器回归**

新增 `config/exporters.json` 条目；`html_preview` 条目保持不变。

Run: `python plugins\general-screenwriter\tests\test_exporter_contract.py; python plugins\general-screenwriter\tests\test_export_run.py`
Expected: PASS。

- [x] **Step 5: 全量回归**

Run: `python .\scripts\run_plugin_tests.py`
Expected: 全绿。

- [x] **Step 6: 提交**

```powershell
git add plugins/general-screenwriter/scripts/export_run.py plugins/general-screenwriter/scripts/export_cli.py plugins/general-screenwriter/tests/test_export_run.py plugins/general-screenwriter/config/exporters.json
git commit -m "feat: add media exporter renderer and atomic writer"
```

### Task 4: 导出器接线到类型包与契约

**Files:**
- Modify: `plugins/general-screenwriter/config/type-packs.json`
- Create: `plugins/general-screenwriter/tests/test_media_exporter_wiring.py`

**Interfaces:**
- Consumes: Task 3 的 `config/exporters.json` 条目；`type_registry.validate_type_contract`。
- Produces: `shortdrama.exporters = ["shortdrama_episode_script", "shortdrama_production_checklist", "structured_json"]`、`tv_longform.exporters = ["tv_episode_script", "tv_season_package", "structured_json"]`；`episode_script.exporter` 分别指向两个剧本导出器，短剧 `scene_table.exporter = "shortdrama_production_checklist"`；`picturebook` 条目不变。

- [x] **Step 1: 写失败测试**

`test_media_exporter_wiring.py`：

```python
def test_every_registered_media_exporter_has_config_entry(self): ...
def test_episode_script_artifact_declares_its_exporter(self): ...
def test_contract_validation_accepts_wired_packs(self): ...
def test_pack_exporter_lists_stay_scoped(self): ...
```

- [x] **Step 2: 运行并确认失败**

Run: `python plugins\general-screenwriter\tests\test_media_exporter_wiring.py`
Expected: FAIL（pack `exporters` 为空、artifact `exporter` 为 null）。

- [x] **Step 3: 接线 type pack（GREEN）**

更新 `config/type-packs.json`；不改阶段与质量规则。

- [x] **Step 4: 全量回归**

Run: `python .\scripts\run_plugin_tests.py; python scripts\release_gate.py`
Expected: 全绿。

- [x] **Step 5: 提交**

```powershell
git add plugins/general-screenwriter/config/type-packs.json plugins/general-screenwriter/tests/test_media_exporter_wiring.py
git commit -m "feat: wire media exporters into type packs"
```

### Task 5: 代表性创作工作流（真实校验器执行）

**Files:**
- Create: `plugins/general-screenwriter/scripts/sample_workflow.py`
- Create: `plugins/general-screenwriter/tests/test_representative_workflows.py`
- Modify: `plugins/general-screenwriter/tests/test_cross_media_samples.py`
- Modify: `plugins/general-screenwriter/tests/fixtures/shortdrama-pass.json`
- Modify: `plugins/general-screenwriter/tests/fixtures/shortdrama-fail.json`
- Modify: `plugins/general-screenwriter/tests/fixtures/tv-longform-pass.json`
- Modify: `plugins/general-screenwriter/tests/fixtures/tv-longform-fail.json`
- Modify: `plugins/general-screenwriter/tests/fixtures/picturebook-pass.json`
- Modify: `plugins/general-screenwriter/tests/fixtures/picturebook-fail.json`

**Interfaces:**
- Produces:
  - `SampleWorkflowError(ValueError)`
  - `SampleWorkflowResult(medium, execution, pipeline_stages, report, confirmation_ready, failure_reason, export_previews)`
  - `run_sample_workflow(sample: SampleContract, sample_path: Path | None = None) -> SampleWorkflowResult`
  - `load_sample(path) -> SampleContract`（新字段：`execution`、`pipeline_stages`、`exports`；`deterministic` 样例的 `workflow_inputs` 为完整 artifact 载荷，不再携带 `expected_results`；`declarative` 样例保持 `expected_results`）
- Consumes: Task 1/2 校验器、Task 3 `render_export`、`creative_run_builder.build_creative_run`、`screenwriter_context.context_from_dict`、`quality_gate_contract.build_quality_gate_report`。

`run_sample_workflow` 行为：
1. `resolve_type_pack` 并做规则漂移检查（与 `evaluate_sample` 相同口径）；
2. 校验 `pipeline_stages`：全部存在于 pack、序列内满足 `depends_on` 拓扑序、目标产物由链中阶段产出、链以 `confirmation_gate` 结束；用 `build_creative_run` 验证该 context 可构建 run manifest（manifest 只读使用）；
3. `deterministic` 样例：每条规则必须声明已注册的 validator 执行器（`shortdrama-checks` / `tv-longform-checks`），用目标 artifact 与其余 `workflow_inputs` 作为 references 真实执行，聚合 `QualityGateReport`；任何规则缺执行器即 `SampleWorkflowError`；
4. `declarative` 样例（绘本）：保持现有 `evaluate_sample` 路径，报告 evidence 标记 `source="fixture"`；
5. 导出预览：`exports` 条目用 `render_export` 生成内存预览文本，不写盘；
6. 返回结果，`confirmation_ready` 必须与 fixture `expected.confirmation_ready` 一致（不一致即测试失败）。

样例 fixture v2 结构（短剧示例；长篇同构，`workflow_inputs` 含七个载荷）：

```json
{
  "medium": "shortdrama",
  "execution": "deterministic",
  "context": {"medium_id": "shortdrama", "project_id": "p1", "delivery_form": "episode_script"},
  "target_artifact": "episode_script",
  "pipeline_stages": ["session_init", "brief_gate", "knowledge_load", "episode_design",
                      "hook_design", "beat_design", "scene_design", "episode_script_delegate",
                      "hook_check", "pacing_check", "dialogue_check", "quality_gate",
                      "confirmation_gate"],
  "workflow_inputs": [{"artifact_id": "episode_script", "content": "内容级载荷"}],
  "knowledge_scope": {"scope_type": "project", "scope_id": "p1"},
  "quality_rules": ["与 pack 完全一致，validator 非空"],
  "expected": {"confirmation_ready": true, "blocker_ids": [],
               "user_confirmation_ids": []},
  "exports": [{"exporter_id": "shortdrama_episode_script",
               "user_params": {"output_directory": "out", "filename": "e1.txt"}}],
  "failure_reason": null
}
```

短剧失败样例：最后一个 beat 为 `closure` 且结尾场景无钩子文本，使 `closing_hook` 真实失败并进入 `user_confirmation_ids`。长篇失败样例：`character_arc_map.latest` 中林一状态为 `calm`，本集 `prior_state` 为 `determined`，使 `character_state` 真实硬阻断，`blocker_ids == ["character_state"]`。

- [x] **Step 1: 写失败测试**

`test_representative_workflows.py`：

```python
def test_shortdrama_samples_execute_real_validators(self):
    result = run_sample_workflow(load_sample(SHORTDRAMA_PASS))
    self.assertEqual(result.execution, "deterministic")
    self.assertTrue(result.confirmation_ready)
    for item in result.report.checks:
        self.assertEqual(item.evidence["source"], "validator")

def test_shortdrama_fail_sample_is_blocked_by_real_content(self): ...
def test_longform_fail_sample_blocks_exactly_character_state(self): ...
def test_pipeline_stage_chain_must_be_topologically_valid(self): ...
def test_export_preview_renders_without_writing_files(self): ...
def test_declarative_samples_keep_skill_layer_evaluation(self): ...
```

`test_cross_media_samples.py`：绘本用例继续走 `evaluate_sample`；短剧/长剧用例改为 `run_sample_workflow`；`MediaActivationTests` 不变。

- [x] **Step 2: 运行并确认失败**

Run: `python plugins\general-screenwriter\tests\test_representative_workflows.py; python plugins\general-screenwriter\tests\test_cross_media_samples.py`
Expected: 前者 import 失败；后者因 fixture 结构升级与 fixture-only 评估路径失败。

- [x] **Step 3: 实现 sample_workflow 与样例升级（GREEN）**

- [x] **Step 4: 全量回归**

Run: `python .\scripts\run_plugin_tests.py`
Expected: 全绿（含更新后的六个样例）。

- [x] **Step 5: 提交**

```powershell
git add plugins/general-screenwriter/scripts/sample_workflow.py plugins/general-screenwriter/tests/test_representative_workflows.py plugins/general-screenwriter/tests/test_cross_media_samples.py plugins/general-screenwriter/tests/fixtures
git commit -m "feat: run representative creation workflows with real validators"
```

### Task 6: 契约、文档与发布收尾

**Files:**
- Modify: `plugins/general-screenwriter/config/plugin-contract.json`
- Modify: `plugins/general-screenwriter/tests/test_plugin_contract.py`
- Modify: `plugins/general-screenwriter/README.md`
- Modify: `README.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `plugins/general-screenwriter/.codex-plugin/plugin.json`

**Interfaces:**
- `plugin-contract.json` 新增 `media_content_completion` 块：`schema_version="media-content-completion-v1"`、`content_validators`（shortdrama-checks / tv-longform-checks）、`exporter_ids`、`deterministic_sample_paths`（短剧/长剧四个样例）、`declarative_sample_paths`（绘本两个样例）；`creative_workflow.schema_version` 不变。
- 插件版本升到 `0.7.0`；CHANGELOG 新增 `[0.7.0]` 条目（Added/Changed）。

- [x] **Step 1: 写失败契约测试**

`test_plugin_contract.py` 新增：契约块字段与 fixture 路径真实存在；pack `validators`/`exporters` 与契约块一致；README 不再把"短剧和长篇连续剧的内容级 validators、类型专属导出器"列为暂不支持，且保留既有锚点语句（"均可通过类型包派发"、"知识库 schema v2"、"独立可选插画工作流"）。

Run: `python plugins\general-screenwriter\tests\test_plugin_contract.py`
Expected: FAIL（契约块缺失）。

- [x] **Step 2: 更新契约与 README（GREEN）**

插件 README"已支持"加入内容级校验、导出器与代表性工作流条目；"暂不支持"移除本阶段已完成项（用户技能可视化管理界面保留并改写为"仅支持自然语言管理"）。仓库根 README 同步能力一句话。

- [x] **Step 3: 版本与 CHANGELOG**

`plugin.json` 版本 `0.7.0`；CHANGELOG 记录本阶段三项能力与兼容说明（对外兼容承诺为旧 run/manifest/绘本路径不变；短剧/长剧样例为仓库内测试资产，随包升级）。

- [x] **Step 4: 全量验证**

Run: `python .\scripts\run_plugin_tests.py; python scripts\release_gate.py`
Expected: 全部 PASS / exit 0。

- [x] **Step 5: 提交**

```powershell
git add plugins/general-screenwriter/config/plugin-contract.json plugins/general-screenwriter/tests/test_plugin_contract.py plugins/general-screenwriter/README.md README.md docs/CHANGELOG.md plugins/general-screenwriter/.codex-plugin/plugin.json
git commit -m "docs: announce media content completion"
```

## Completion Checklist

- [x] 短剧 8 条规则与长篇 9 条规则全部由内容级确定性校验器执行，规则 `validator` 非空且进入 pack `validators`。
- [x] 空洞内容、缺失跨集引用、状态冲突、时长与内容不符都会真实失败；失败关闭，不静默通过。
- [x] 五个新导出器声明在 `config/exporters.json`，渲染确定、中文可用、写入原子、失败零残留，短剧/长剧 type pack 完成接线。
- [x] 短剧与长剧各有 pass/fail 两个真实执行样例；报告 evidence 标记校验器来源；声明的阶段链在 pack 中拓扑可达。
- [x] 绘本路径与声明式样例语义未变；全量离线回归、发布门与治理检查通过。

## Plan Self-Review

- **Spec coverage:** 内容级 validators 对应 other-media 设计第 3.4/4.5 节；导出器对应 quality-output-release 设计第 4 节；代表性样例对应第 2.3 节与发布门第 6 节。
- **Step scan:** 每个任务先红后绿、给出精确接口与测试断言，收尾有全量回归与提交。
- **Type consistency:** `validate_*_rules` 保持三参兼容并新增可选 `references`；`render_export` / `run_export` / `ExportResult` 与 Task 4/5 消费口径一致；`SampleWorkflowResult` 字段在测试与 fixture 间一致。
- **Review Focus:** 空洞内容、引用缺失、导出残留、样例真实性、阶段链可达、中文编码各有归属用例。
- **Proportion:** 计划停留在契约、确定性检查、渲染与样例执行层，不引入模型评分或内容生成脚本。
