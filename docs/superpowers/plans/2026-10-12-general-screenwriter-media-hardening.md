# General Screenwriter Media Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复复查发现的 5 个问题：显式“无前序状态”契约、长篇引用失败关闭收口、导出器必填字段校验、导出目录错误包装、CLI UTF-8 输出。

**Architecture:** 沿用现有确定性校验与导出内核，不新增依赖。`tv_longform_checks.py` 明确 `character_arc_map.latest` 的无前序表示并补齐 `series_bible` 校验；`export_run.py` 复用 `script_content.parse_episode_script` 校验 episode_script 载荷，停止伪造 heading/scene_id；`write_export` 统一包装目录创建失败；`export_cli.py` 将 stdout/stderr 固定为 UTF-8。

**Tech Stack:** Python 3.10+ 标准库、unittest、现有 `script_content.py` / `tv_longform_checks.py` / `export_run.py` / `export_cli.py`。

**Spec:**

- `docs/superpowers/specs/2026-10-09-general-screenwriter-other-media-type-packs-design.md`
- `docs/superpowers/specs/2026-10-09-general-screenwriter-quality-output-release-design.md`
- 前序完成计划 `docs/superpowers/plans/2026-10-12-general-screenwriter-media-content-completion.md`
- 本次复查结论：5 项问题，以及 `latest: {"episode_id": null, "states": []}` 的无前序约定。

## Global Constraints

- 不新增第三方运行时依赖；校验与导出全部确定性，不调用模型、不访问网络。
- 内容级校验只从脚本内容与显式引用产物推导；引用或必需字段缺失、类型错误一律失败关闭。
- 默认写盘策略 `dialog_only`；只有显式 `output_directory` + `filename` 才写；目标已存在默认失败，覆盖必须 `overwrite_allowed=True`；失败不得留下临时文件或半成品。
- 旧绘本入口、旧 run/manifest、插画流程、picturebook 声明式样例语义不变。
- 每个任务先写失败测试并观察失败，再做最小实现；任务收尾跑对应测试与 `python .\scripts\run_plugin_tests.py`；每任务单独提交。
- 执行方式 inline；沿用仓库既有 ruling 在 `main` 工作树内提交，不新建 worktree。
- 最终运行 `python scripts\release_gate.py`，并做一次全分支自审（无可用子代理工具时按 executing-plans 降级路径）。

## Review Focus

1. 首集用 `latest: {"episode_id": null, "states": []}` 必须通过；`latest` 缺失、`episode_id` 非法、null 与 states 非空矛盾、state 条目畸形都必须失败。
2. 导出器不得再为缺失 heading 生成“场N”、为缺失 scene_id 生成“SN”；checklist 缺省列按计划显示 `-`。
3. 中文 filename 下 CLI stdout/stderr 必须是 UTF-8 可解码；输出目录创建失败不得打 traceback。
4. 目录创建失败时不得留下临时文件，原子写入语义不变。
5. 校验收紧后六个代表样例与全部离线回归必须保持通过。

---

### Task 1: 长篇引用失败关闭收口

**Files:**

- Modify: `plugins/general-screenwriter/scripts/tv_longform_checks.py`
- Modify: `plugins/general-screenwriter/tests/test_tv_longform_type_pack.py`
- Modify: `docs/superpowers/plans/2026-10-12-general-screenwriter-media-content-completion.md`

**Interfaces:**

- Consumes: 现有 `_reference`、`_nonempty_text`、`validate_tv_longform_rules`；工作树中已完成的 `timeline_ledger.last_order`、`episode_list`、`continuity.conflicts` 收紧改动。
- Produces:
  - `character_arc_map.latest` 契约：必须存在且为对象；`episode_id` 为 `null`（无前序剧集）或非空字符串；`states` 必须为数组；`episode_id=null` 时 `states` 必须为空数组；有前序剧集时每个条目必须有非空 `name`/`state` 且角色名唯一。
  - `series_bible` 契约：`series_id` 必须是非空字符串且与集稿一致；`characters` 必须是非空数组且条目带非空 `name`；`banned_terms` 若存在必须是数组。

**Ruling:** 采用 `latest.episode_id: null` + `states: []` 作为显式“无前序状态”表示，不新增 `has_prior_episode` — 复用现有 `latest` 容器，改动面最小 — 代价：未来若消费者需要布尔标记，需要迁移或同时接受两种表示。

- [ ] **Step 1: 写失败测试**

在 `test_tv_longform_type_pack.py` 的 `ContentCheckTests` 中加入：

```python
def test_character_state_explicit_no_prior_state_passes(self):
    references = longform_references()
    references["character_arc_map"] = {
        "artifact_id": "character_arc_map",
        "latest": {"episode_id": None, "states": []},
    }
    result = validate_tv_longform_rules(
        "character_state", episode(), context(), references)
    self.assertEqual(result.status, "pass")

def test_character_state_missing_latest_fails_closed(self):
    references = longform_references()
    references["character_arc_map"] = {"artifact_id": "character_arc_map"}
    result = validate_tv_longform_rules(
        "character_state", episode(), context(), references)
    self.assertEqual(result.status, "fail")
    self.assertTrue(result.evidence["violations"])

def test_character_state_no_prior_with_states_fails_closed(self):
    references = longform_references()
    references["character_arc_map"] = {
        "artifact_id": "character_arc_map",
        "latest": {
            "episode_id": None,
            "states": [{"name": "林一", "state": "calm"}],
        },
    }
    result = validate_tv_longform_rules(
        "character_state", episode(), context(), references)
    self.assertEqual(result.status, "fail")

def test_character_state_malformed_prior_entry_fails_closed(self):
    references = longform_references()
    references["character_arc_map"] = {
        "artifact_id": "character_arc_map",
        "latest": {"episode_id": "e1", "states": [{"name": "林一"}]},
    }
    result = validate_tv_longform_rules(
        "character_state", episode(), context(), references)
    self.assertEqual(result.status, "fail")

def test_missing_bible_series_id_fails_closed(self):
    references = longform_references()
    references["series_bible"] = {
        "artifact_id": "series_bible",
        "characters": [{"name": "林一"}, {"name": "陈默"}],
    }
    result = validate_tv_longform_rules(
        "series_constraint", episode(), context(), references)
    self.assertEqual(result.status, "fail")
    self.assertTrue(any(
        "series_id" in item for item in result.evidence["violations"]))

def test_empty_bible_characters_fails_closed(self):
    references = longform_references()
    references["series_bible"] = {
        "artifact_id": "series_bible",
        "series_id": "s1",
        "characters": [],
    }
    items = scenes()
    for item in items:
        item["lines"] = [action("只有动作，没有台词。")]
    result = validate_tv_longform_rules(
        "series_constraint", episode(scenes=items), context(), references)
    self.assertEqual(result.status, "fail")

def test_malformed_banned_terms_fails_closed(self):
    references = longform_references()
    references["series_bible"] = dict(
        references["series_bible"], banned_terms="穿越")
    result = validate_tv_longform_rules(
        "series_constraint", episode(), context(), references)
    self.assertEqual(result.status, "fail")
```

`test_character_state_explicit_no_prior_state_passes` 是契约锁：当前实现已会通过，它防的是后续收紧误杀首集。

- [ ] **Step 2: 运行并确认失败**

Run: `python plugins\general-screenwriter\tests\test_tv_longform_type_pack.py`
Expected: 7 条新增用例中，6 条缺失/畸形用例 FAIL；显式无前序契约锁 PASS。

- [ ] **Step 3: 实现失败关闭校验**

`_character_state`：要求 `arc_map.latest` 为对象；按 `episode_id` 为 `None`、合法非空字符串、非法值三分支处理；`None` 分支要求 `states == []`；合法前序分支要求 `states` 为数组、条目 `name`/`state` 非空且角色名唯一，并据此构造 `previous_states`。

`_series_constraint`：`series_bible.series_id` 必须非空且与集稿一致；`characters` 必须是非空数组且每个条目带非空 `name`；`banned_terms` 若不是数组则记违规；剧本行文本命中逻辑保持不变。

- [ ] **Step 4: 运行任务测试**

Run: `python plugins\general-screenwriter\tests\test_tv_longform_type_pack.py`
Expected: OK。

- [ ] **Step 5: 全量回归**

Run: `python .\scripts\run_plugin_tests.py`
Expected: `OK: 86 offline commands passed`。

- [ ] **Step 6: 同步计划措辞**

把 `2026-10-12-general-screenwriter-media-content-completion.md` 的 `character_state` 与 `series_constraint` 两条检查语义更新为本任务契约。

- [ ] **Step 7: 提交**

```powershell
git add plugins/general-screenwriter/scripts/tv_longform_checks.py plugins/general-screenwriter/tests/test_tv_longform_type_pack.py docs/superpowers/plans/2026-10-12-general-screenwriter-media-content-completion.md
git commit -m "fix: fail closed on malformed tv longform references"
```

### Task 2: 导出器必填字段校验

**Files:**

- Modify: `plugins/general-screenwriter/scripts/export_run.py`
- Modify: `plugins/general-screenwriter/tests/test_export_run.py`

**Interfaces:**

- Consumes: `script_content.parse_episode_script(payload) -> ParsedScript`、`script_content.ScriptContentError`。
- Produces:
  - `_validated_episode_script(payload, artifact_id) -> ParsedScript`，解析失败转 `ExportRunnerError`。
  - `_screenplay_text(payload) -> str` 使用 parsed scenes 渲染，不再伪造 heading。
  - `_render_production_checklist` 缺 `scene_id` 时按计划输出 `-`，不再生成 `SN`。

- [ ] **Step 1: 写失败测试**

在 `RenderTests` / `RunExportTests` 中加入：

```python
def test_script_render_requires_heading(self):
    payloads = {"episode_script": episode_payload()}
    del payloads["episode_script"]["scenes"][0]["heading"]
    with self.assertRaises(ExportRunnerError):
        render_export("shortdrama_episode_script", payloads)

def test_script_render_requires_canonical_scene_fields(self):
    for key in ("scene_id", "location", "time_of_day"):
        payloads = {"episode_script": episode_payload()}
        del payloads["episode_script"]["scenes"][0][key]
        with self.subTest(key=key), self.assertRaises(ExportRunnerError):
            render_export("shortdrama_episode_script", payloads)

def test_script_render_rejects_empty_lines(self):
    payloads = {"episode_script": episode_payload()}
    payloads["episode_script"]["scenes"][0]["lines"] = []
    with self.assertRaises(ExportRunnerError):
        render_export("shortdrama_episode_script", payloads)

def test_production_checklist_missing_scene_id_renders_dash(self):
    text = render_export(
        "shortdrama_production_checklist",
        {"scene_table": {"artifact_id": "scene_table", "scenes": [{}]}},
    )
    self.assertIn("| - | - | - | - | - | - | - |", text)
    self.assertNotIn("| S1 |", text)
```

- [ ] **Step 2: 运行并确认失败**

Run: `python plugins\general-screenwriter\tests\test_export_run.py`
Expected: 新增用例 FAIL（heading/scene 字段缺失仍渲染成功；checklist 伪造 `S1`）。

- [ ] **Step 3: 实现必填校验**

`export_run.py` 引入 `parse_episode_script` 与 `ScriptContentError`；新增 `_validated_episode_script`；`_screenplay_text` 先解析再按 `ParsedScript.scenes` 渲染；checklist 的 `scene_id` 改走统一的 `cell(...)`，缺省输出 `-`。

- [ ] **Step 4: 运行任务测试**

Run: `python plugins\general-screenwriter\tests\test_export_run.py`
Expected: OK。

- [ ] **Step 5: 全量回归**

Run: `python .\scripts\run_plugin_tests.py`
Expected: `OK: 86 offline commands passed`，六个代表样例的导出预览保持通过。

- [ ] **Step 6: 提交**

```powershell
git add plugins/general-screenwriter/scripts/export_run.py plugins/general-screenwriter/tests/test_export_run.py
git commit -m "fix: validate required exporter payload fields"
```

### Task 3: 导出失败面加固

**Files:**

- Modify: `plugins/general-screenwriter/scripts/export_run.py`
- Modify: `plugins/general-screenwriter/scripts/export_cli.py`
- Modify: `plugins/general-screenwriter/tests/test_export_run.py`

**Interfaces:**

- `write_export`：`mkdir`、`mkstemp`、写入、`os.replace` 的所有 `OSError` 统一转 `ExportRunnerError`，临时文件清理语义不变。
- `export_cli.main`：在解析参数前把 `sys.stdout` / `sys.stderr` 重设为 UTF-8（流不支持 `reconfigure` 时跳过）。

- [ ] **Step 1: 写失败测试**

```python
def test_output_directory_creation_failure_raises_runner_error(self):
    with tempfile.TemporaryDirectory() as tmp:
        blocker = Path(tmp) / "blocker"
        blocker.write_text("keep", encoding="utf-8")
        with self.assertRaises(ExportRunnerError):
            write_export(blocker / "sub" / "out.txt", "content")
        self.assertEqual(blocker.read_text(encoding="utf-8"), "keep")
        self.assertEqual(list(Path(tmp).iterdir()), [blocker])

def test_cli_directory_failure_has_no_traceback(self):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        blocker = tmp_path / "blocker"
        blocker.write_text("keep", encoding="utf-8")
        refs_file = tmp_path / "refs.json"
        payloads_file = tmp_path / "payloads.json"
        params_file = tmp_path / "params.json"
        refs_file.write_text(
            json.dumps(artifact_refs(), ensure_ascii=False), encoding="utf-8")
        payloads_file.write_text(
            json.dumps({"episode_script": episode_payload()},
                       ensure_ascii=False), encoding="utf-8")
        params_file.write_text(
            json.dumps({"output_directory": str(blocker / "sub"),
                        "filename": "e2.txt"},
                       ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([
            sys.executable, str(CLI),
            "--exporter-id", "shortdrama_episode_script",
            "--artifact-refs", str(refs_file),
            "--payloads", str(payloads_file),
            "--params", str(params_file),
        ], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"[export_cli]", result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

def test_cli_output_is_utf8_with_chinese_filename(self):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        refs_file = tmp_path / "refs.json"
        payloads_file = tmp_path / "payloads.json"
        params_file = tmp_path / "params.json"
        refs_file.write_text(
            json.dumps(artifact_refs(), ensure_ascii=False), encoding="utf-8")
        payloads_file.write_text(
            json.dumps({"episode_script": episode_payload()},
                       ensure_ascii=False), encoding="utf-8")
        params_file.write_text(
            json.dumps({"output_directory": tmp,
                        "filename": "第一集.txt"},
                       ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([
            sys.executable, str(CLI),
            "--exporter-id", "shortdrama_episode_script",
            "--artifact-refs", str(refs_file),
            "--payloads", str(payloads_file),
            "--params", str(params_file),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("第一集.txt", result.stdout)
        written = tmp_path / "第一集.txt"
        self.assertIn(
            "林一：谁动了我的证据？",
            written.read_text(encoding="utf-8"),
        )
```

- [ ] **Step 2: 运行并确认失败**

Run: `python plugins\general-screenwriter\tests\test_export_run.py`
Expected: 目录创建用例抛 `FileExistsError`；CLI traceback 用例发现 `Traceback`；中文 filename 用例 stdout 匹配不到中文。

- [ ] **Step 3: 实现错误包装与 UTF-8 输出**

`write_export` 把 `path.parent.mkdir(...)` 移入现有 `try`；`export_cli.main` 开头对 stdout/stderr 调用 `reconfigure(encoding="utf-8")`。

- [ ] **Step 4: 运行任务测试**

Run: `python plugins\general-screenwriter\tests\test_export_run.py`
Expected: OK。

- [ ] **Step 5: 全量回归与发布门**

Run: `python .\scripts\run_plugin_tests.py`
Expected: `OK: 86 offline commands passed`。

Run: `python scripts\release_gate.py`
Expected: `all checks passed`。

- [ ] **Step 6: 提交**

```powershell
git add plugins/general-screenwriter/scripts/export_run.py plugins/general-screenwriter/scripts/export_cli.py plugins/general-screenwriter/tests/test_export_run.py
git commit -m "fix: harden export failure surface"
```

## Completion Checklist

- [ ] 5 项复查问题都有对应测试，且测试先失败后通过。
- [ ] `latest: {"episode_id": null, "states": []}` 首集语义与失败关闭语义同时成立。
- [ ] 导出器不再伪造 heading/scene_id，缺字段失败或按计划显示 `-`。
- [ ] 目录创建失败统一为 `ExportRunnerError`，CLI 无 traceback、stdout/stderr 为 UTF-8。
- [ ] `python .\scripts\run_plugin_tests.py` 与 `python scripts\release_gate.py` 全绿。
- [ ] 全分支自审完成；无可用子代理工具时在最终消息说明降级。

## Plan Self-Review

- **Spec coverage:** 5 项复查问题映射到 Task 1（问题 1/3）、Task 2（问题 2）、Task 3（问题 4/5）。
- **Step scan:** 每个任务先红后绿，测试、实现、任务测试、全量回归、提交各为独立步骤。
- **Type consistency:** `_validated_episode_script`、`ExportRunnerError`、`ParsedScript`、`write_export`、`export_cli.main` 的接口与现有模块一致。
- **Review Focus:** 首集表示、导出伪造、UTF-8、零残留、样例回归都有归属测试。
- **Proportion:** 计划只锁定契约、测试与最小实现，不引入新抽象或依赖。
