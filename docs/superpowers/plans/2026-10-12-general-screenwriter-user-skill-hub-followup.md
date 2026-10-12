# User Skill Hub Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按复盘整改设计关闭用户技能中心的链接语义、根目录白名单、写入原子性、旧系统退休、字段命名与系统元数据接线六类问题。

**Architecture:** 校验语义统一在一处 `_require_plain_entry`；写入从文案流程升级为 `install_user_skill_pack` 的"暂存、校验、原子换入、回滚"协议；旧注册表契约分三步退出配置与门禁；系统技能元数据经确定性索引获得机械消费者；每个任务独立提交、独立验收。

**Tech Stack:** Python 3.10+ 标准库、`unittest`、`importlib` 动态加载、Windows junction 检测、现有 `type_registry` / `stage_dag` / `creative_run_builder` 约定。

**Spec:** `docs/superpowers/specs/2026-10-12-general-screenwriter-user-skill-hub-followup-design.md`

## Global Constraints

- 本次不做，也不得顺手实现：快照对账/内容锁定、运行时逐包降级隔离、技能体积上限、防注入围栏。
- 用户可见界面仍只有自然语言；CLI 与脚本是内部实现，不得作为用户操作步骤写入文档。
- `resolution_snapshot.skills` 旧字段必须保持可读（旧快照兼容），新 hub 字段优先级不变。
- 每个任务先写失败测试并观察失败，再写最小实现；单一修复，不夹带无关重构。
- Windows junction 用例在 win32 必须真实执行，不得以平台理由跳过（非 win32 才允许 skip）。
- 每任务收尾运行 `python .\scripts\run_plugin_tests.py` 且全绿；涉及门禁的任务同时运行 `python .\scripts\release_gate.py`。
- 每个任务单独提交，提交信息使用仓库现有 conventional commit 风格。
- 命令均在本仓库根目录 `E:\codex-picturebook-agent` 执行；执行方式为 inline（用户已指定从 Task 1 开始）。

## Review Focus

1. Windows junction / symlink 出现在单包路径、系统技能目录、用户树根、包内任意层：必须拒绝且消息可诊断（Task 1 用例）。
2. 系统技能目录含 `skill-meta.json` 但缺 `SKILL.md`：树校验必须报错，不得静默跳过（Task 1 用例）。
3. `skills/user-skills/` 根下散落文件（含 `.exe`）：树校验与发布门禁必须失败（Task 2 用例）。
4. 覆盖安装被中断、暂存包非法、无标志覆盖：旧包内容完整、live 树无半包、临时目录可回收（Task 3 用例）。
5. 旧 manifest 携带 `resolution_snapshot.skills` 且无注册表文件：仍可通过执行前校验（Task 5 用例）。

---

### Task 1: D6 校验语义统一

**Files:**
- Modify: `plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py`
- Test: `plugins/general-screenwriter/tests/test_user_skill_hub.py`

**Interfaces:**
- Consumes: 现有 `UserSkillHubError`、`_CONTENT_FILE`、`_validate_user_skill`、`_validate_system_skill`、`_reject_extra_files`、`validate_user_skill_tree`。
- Produces: 模块内 `_is_link_like(path: Path) -> bool`、`_require_plain_entry(path: Path, label: str) -> None`（命中链接类抛 `UserSkillHubError`，消息同时含"符号链接"与"junction"）。

- [ ] **Step 1: 写入失败测试与用例调整（RED）**

在 `ValidateUserSkillTests` 增加：

```python
    def test_windows_junction_single_user_skill_pack_is_rejected(self):
        if sys.platform != "win32":
            self.skipTest("junctions are Windows-specific")
        import _winapi
        directory = self.make_skill(skill_id="real-skill")
        link = self.temp_path / "junction-skill"
        _winapi.CreateJunction(str(directory), str(link))
        with self.assertRaisesRegex(UserSkillHubError, "符号链接|junction"):
            validate_user_skill(link, ROOT)
```

在 `ValidateSystemSkillTests` 增加：

```python
    def test_windows_junction_system_skill_is_rejected(self):
        if sys.platform != "win32":
            self.skipTest("junctions are Windows-specific")
        import _winapi
        directory = self.make_system_skill(skill_id="real-system")
        link = self.temp_path / "junction-system"
        _winapi.CreateJunction(str(directory), str(link))
        with self.assertRaisesRegex(UserSkillHubError, "符号链接|junction"):
            validate_system_skill(link, ROOT)

    def test_tree_rejects_half_installed_system_skill(self):
        plugin_root = self.make_plugin_root()
        directory = plugin_root / "skills" / "half-installed"
        directory.mkdir(parents=True)
        (directory / "skill-meta.json").write_text(
            json.dumps(system_metadata("half-installed"), ensure_ascii=False),
            encoding="utf-8",
        )
        with self.assertRaises(UserSkillHubError):
            validate_system_skill_tree(plugin_root)
```

同时调整 `test_tree_validates_only_immediate_skill_directories`：`not-a-skill` 目录不再写入 `skill-meta.json`（保持"两者皆无则跳过"的语义），其余断言不变。

- [ ] **Step 2: 运行并确认失败**

Run: `python plugins\general-screenwriter\tests\test_user_skill_hub.py`
Expected: 3 个新用例失败（两个 junction 用例因未抛错而失败；半安装用例因树校验返回空而失败），其余通过。

- [ ] **Step 3: 实现链接语义与半安装检测（GREEN）**

在 `user_skill_hub.py` 顶部增加 `import os`，新增：

```python
_WINDOWS_MOUNT_POINT_TAG = 0xA0000003


def _is_link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        try:
            return bool(is_junction())
        except OSError:
            return False
    if os.name == "nt":
        try:
            return getattr(os.lstat(path), "st_reparse_tag", 0) == _WINDOWS_MOUNT_POINT_TAG
        except OSError:
            return False
    return False


def _require_plain_entry(path: Path, label: str) -> None:
    if _is_link_like(path):
        raise UserSkillHubError(f"{label} 不得是符号链接或 junction：{path}")
```

落点替换：

1. `_validate_user_skill`：`raw_directory.is_symlink()` 分支替换为 `_require_plain_entry(raw_directory, "用户技能目录")`。
2. `validate_user_skill_tree`：根目录的 `is_symlink` 分支与逐目录的 `is_symlink` 分支分别替换为 `_require_plain_entry(..., "用户技能目录")`；保留 `resolve().parent != resolved_user_skills` 兜底。
3. `_validate_system_skill`：在 `resolve()` 之前对原始路径调用 `_require_plain_entry(..., "系统技能目录")`。
4. `_reject_extra_files`：循环体先判 `_is_link_like(path)` 并抛错，再判白名单（原 `not path.is_symlink()` 条件删除）。
5. `validate_system_skill_tree` 候选过滤改为 `(directory / _CONTENT_FILE).is_file() or (directory / "skill-meta.json").is_file()`。

- [ ] **Step 4: 运行并确认通过**

Run: `python plugins\general-screenwriter\tests\test_user_skill_hub.py`
Expected: 全部通过（win32 上无 skip 的 junction 用例）。

- [ ] **Step 5: 全量回归**

Run: `python .\scripts\run_plugin_tests.py`
Expected: `OK: 79 offline commands passed`（后续任务会追加命令数）。

- [ ] **Step 6: 提交**

```bash
git add plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py plugins/general-screenwriter/tests/test_user_skill_hub.py
git commit -m "fix: unify skill tree link and completeness checks"
```

### Task 2: D2 根目录白名单与树门禁

**Files:**
- Modify: `plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py`
- Modify: `plugins/general-screenwriter/tests/test_user_skill_hub.py`
- Create: `scripts/user_skill_gate.py`
- Create: `scripts/test_user_skill_gate.py`
- Modify: `scripts/run_plugin_tests.py`
- Modify: `scripts/release_gate.py`
- Modify: `scripts/test_release_gate.py`

**Interfaces:**
- Consumes: Task 1 的 `_require_plain_entry`；hub 的 `validate_user_skill_tree(plugin_root)`、`validate_system_skill_tree(plugin_root)`。
- Produces: `scripts.user_skill_gate.check_plugin_skill_trees(plugin_root: Path) -> tuple[str, ...]`；CLI `python scripts\user_skill_gate.py` 退出码 0/1。

- [ ] **Step 1: 写入失败测试（RED）**

`test_user_skill_hub.py` 的 `ValidateUserSkillTreeTests` 增加 `test_loose_files_in_user_skills_root_are_rejected`：在合法树根放入 `notes.md` 与 `tool.exe`，断言 `validate_user_skill_tree` 抛 `UserSkillHubError` 且消息含文件名字。

新增 `scripts/test_user_skill_gate.py`：用例一断言 `check_plugin_skill_trees(真实插件根) == ()`；用例二在临时插件根（复制 `config/type-packs.json`，建 `skills/user-skills/` 与一个合法包，再加散落文件）断言返回非空且消息含散落文件名。

- [ ] **Step 2: 运行并确认失败**

Run: `python plugins\general-screenwriter\tests\test_user_skill_hub.py -k loose` 与 `python scripts\test_user_skill_gate.py`（脚本尚不存在时按 import 失败判断）
Expected: 前者失败（散落文件被静默忽略）；后者因模块不存在失败。

- [ ] **Step 3: 实现白名单与门禁（GREEN）**

`validate_user_skill_tree` 改为逐条目分类：先 `_require_plain_entry(entry, "用户技能目录")` 处理链接类；非目录条目抛 `UserSkillHubError(f"用户技能根目录只允许技能目录：{entry.name}")`；目录条目进入原有包校验。

新建 `scripts/user_skill_gate.py`：用 `importlib.util.spec_from_file_location` 加载 `plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py`（临时把 `plugins/general-screenwriter/scripts` 与 `user-skill-hub/scripts` 加入 `sys.path`），实现 `check_plugin_skill_trees` 捕获 `UserSkillHubError` 返回 `(str(error),)`；`main()` 打印错误并返回 0/1。

接线：`run_plugin_tests.build_commands` 追加 `[sys.executable, str(repo_root / "scripts" / "user_skill_gate.py")]`；`release_gate.GATE_STEPS` 在 `knowledge_adapter` 后插入 `("user_skill_trees", "scripts/user_skill_gate.py")`；`test_release_gate.py` 期望列表同步，并把 `test_declares_nine_gate_steps` 更名为 `test_declares_gate_steps`。

- [ ] **Step 4: 运行并确认通过**

Run: `python scripts\test_user_skill_gate.py; python scripts\test_release_gate.py; python .\scripts\run_plugin_tests.py`
Expected: 全部通过，命令数变为 80。

- [ ] **Step 5: 提交**

```bash
git add plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py plugins/general-screenwriter/tests/test_user_skill_hub.py scripts/user_skill_gate.py scripts/test_user_skill_gate.py scripts/run_plugin_tests.py scripts/release_gate.py scripts/test_release_gate.py
git commit -m "feat: guard user skill tree roots in release gates"
```

### Task 3: D1 原子安装与内部 CLI

**Files:**
- Modify: `plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py`
- Modify: `plugins/general-screenwriter/skills/user-skill-hub/SKILL.md`
- Create: `plugins/general-screenwriter/tests/test_user_skill_install.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 1 的链接语义、Task 2 的根白名单、`validate_user_skill`、`validate_user_skill_tree`。
- Produces: `install_user_skill_pack(staged_dir: Path, plugin_root: Path, *, overwrite: bool = False) -> UserSkill`；`main(argv: Sequence[str] | None = None) -> int`（子命令 `validate`、`validate-tree`、`preview`、`install`）。

- [ ] **Step 1: 写入失败测试（RED）**

新增 `test_user_skill_install.py`（沿用 hub 测试的 `sys.path` 与临时插件根辅助模式）：

1. `test_install_new_pack_swaps_in_and_tree_validates`：暂存合法包 → `install_user_skill_pack` → 目标存在、树校验通过、`.tmp` 无残留。
2. `test_install_refuses_overwrite_without_flag`：目标已存在且 `overwrite=False` → 抛 `UserSkillHubError`，目标内容不变。
3. `test_install_overwrite_replaces_content_and_cleans_backup`：`overwrite=True` → 正文替换、备份目录不存在。
4. `test_install_rolls_back_when_post_swap_validation_fails`：`unittest.mock.patch("user_skill_hub.validate_user_skill_tree", side_effect=UserSkillHubError("boom"))` → 抛错且目标恢复旧内容。
5. `test_install_leaves_tree_untouched_when_staged_pack_invalid`：暂存包缺 `SKILL.md` → 抛错且目标目录不存在。
6. `test_cli_install_roundtrip`：`subprocess` 调用 `python <hub脚本> install --staging <dir> --plugin-root <root>` 退出码 0；再次无 `--overwrite` 调用退出码 1。

- [ ] **Step 2: 运行并确认失败**

Run: `python plugins\general-screenwriter\tests\test_user_skill_install.py`
Expected: 因 `install_user_skill_pack` 与 CLI 不存在而失败/import error。

- [ ] **Step 3: 实现安装协议与 CLI（GREEN）**

按 spec 第 5 节的六步协议实现：单包校验 → 目标冲突检查 → 同卷 `.tmp` 工作副本（`copytree` + 复核）→ 备份改名 → 换入改名（失败回滚）→ 换入后树校验（失败回滚）→ 清理备份。CLI 用 `argparse` 实现四个子命令，`UserSkillHubError` 打印到 stderr 返回 1，用法错误返回 2。

- [ ] **Step 4: 更新 SKILL.md 与 .gitignore**

`SKILL.md`"校验与写入"一节改写为暂存流程（暂存目录由工作流在仓库外或 `.tmp` 创建、先单包校验、预览、用户确认后 `install`、覆盖需显式标志、最后树校验）；保持"不得把内部命令作为用户界面"的既有句子。`.gitignore` 增加一行 `.tmp/`。

- [ ] **Step 5: 运行并确认通过**

Run: `python plugins\general-screenwriter\tests\test_user_skill_install.py; python plugins\general-screenwriter\tests\test_user_skill_hub.py; python .\scripts\run_plugin_tests.py`
Expected: 全部通过，命令数变为 81。

- [ ] **Step 6: 提交**

```bash
git add .gitignore plugins/general-screenwriter/skills/user-skill-hub/SKILL.md plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py plugins/general-screenwriter/tests/test_user_skill_install.py
git commit -m "feat: install user skill packs atomically"
```

### Task 4: D3a 契约收口与门禁改名

**Files:**
- Modify: `plugins/general-screenwriter/config/plugin-contract.json`
- Modify: `plugins/general-screenwriter/scripts/user_skill_contract.py`
- Modify: `plugins/general-screenwriter/scripts/user_skill_resolver.py`
- Modify: `scripts/release_gate.py`
- Modify: `scripts/test_release_gate.py`

**Interfaces:**
- Consumes: Task 2 的门禁步骤表结构。
- Produces: `GATE_STEPS` 中 `skill_registry` 被 `user_skill_hub` 与 `user_skill_runtime` 替换；`plugin-contract.json` 不再声明 `user_skill_contract`。

- [ ] **Step 1: 先改期望测试（RED）**

`test_release_gate.test_declares_gate_steps` 期望列表改为：`registry_contract`、`knowledge_adapter`、`user_skill_trees`、`user_skill_hub`、`user_skill_runtime`、`dag_scheduler`、`quality_gate`、`exporter_contract`、`offline_regression`、`governance_check`、`packaging_check`。

Run: `python scripts\test_release_gate.py`
Expected: 失败（当前列表仍是 `skill_registry` 单步）。

- [ ] **Step 2: 改实现（GREEN）**

`release_gate.py` 以 `("user_skill_hub", "plugins/general-screenwriter/tests/test_user_skill_hub.py")` 与 `("user_skill_runtime", "plugins/general-screenwriter/tests/test_user_skill_run_integration.py")` 替换 `skill_registry` 行；`plugin-contract.json` 删除 `user_skill_contract` 块（保留 `user_skill_hub`）；两个旧模块文件头加一行弃用说明（将在 Task 6 删除）。

- [ ] **Step 3: 验证**

Run: `python scripts\test_release_gate.py; python .\scripts\run_plugin_tests.py`
Expected: 全部通过。

- [ ] **Step 4: 提交**

```bash
git add plugins/general-screenwriter/config/plugin-contract.json plugins/general-screenwriter/scripts/user_skill_contract.py plugins/general-screenwriter/scripts/user_skill_resolver.py scripts/release_gate.py scripts/test_release_gate.py
git commit -m "chore: retire legacy user skill contract from release gates"
```

### Task 5: D3b stage_dag 解耦旧注册表

**Files:**
- Modify: `plugins/general-screenwriter/scripts/stage_dag.py`
- Test: `plugins/general-screenwriter/tests/test_stage_dag_context.py`

**Interfaces:**
- Consumes: `SkillsSnapshotTests._skills_snapshot()` 与 `assert_manifest_type_executable`。
- Produces: 执行路径不再访问 `_load_skill_registry`（该函数随后由 Task 6 删除）。

- [ ] **Step 1: 写入失败测试（RED）**

在 `SkillsSnapshotTests` 增加（并补 `from unittest import mock`）：

```python
    def test_execution_does_not_consult_legacy_user_skill_registry(self):
        manifest = stage_dag.attach_context(
            stage_dag._creation_template_manifest(),
            CreativeContext("picturebook", project_id="p1"),
            _skills_snapshot(),
        )
        manifest["project_root"] = str(REPO_ROOT)
        with mock.patch.object(
            stage_dag,
            "_load_skill_registry",
            side_effect=AssertionError("legacy registry consulted"),
            create=True,
        ):
            stage_dag.assert_manifest_type_executable(manifest)
```

Run: `python plugins\general-screenwriter\tests\test_stage_dag_context.py -k registry`
Expected: 失败（`AssertionError: legacy registry consulted`）。

- [ ] **Step 2: 删除旧路径（GREEN）**

删除 `stage_dag.py` 中 `_load_skill_registry`、`_validate_skills_against_registry` 两函数及 `assert_manifest_type_executable` 内的调用块（`skills = snapshot.get("skills")` 起的三行）；保留 `_validate_compact_skills` 与旧快照字段校验。

- [ ] **Step 3: 验证**

Run: `python plugins\general-screenwriter\tests\test_stage_dag_context.py; python .\scripts\run_plugin_tests.py`
Expected: 全部通过（含 `test_revision_manifest_inherits_skills_snapshot`）。

- [ ] **Step 4: 提交**

```bash
git add plugins/general-screenwriter/scripts/stage_dag.py plugins/general-screenwriter/tests/test_stage_dag_context.py
git commit -m "refactor: decouple stage dag from legacy user skill registry"
```

### Task 6: D3c 删除旧契约与解析器

**Files:**
- Delete: `plugins/general-screenwriter/scripts/user_skill_contract.py`
- Delete: `plugins/general-screenwriter/scripts/user_skill_resolver.py`
- Delete: `plugins/general-screenwriter/config/user-skills.example.json`
- Delete: `plugins/general-screenwriter/tests/test_user_skill_contract.py`
- Delete: `plugins/general-screenwriter/tests/test_user_skill_resolver.py`
- Modify: `docs/CHANGELOG.md`

**Interfaces:**
- Consumes: Task 4/5 已切断全部生产引用。
- Produces: 仓库内仅剩轻量用户技能一套契约。

- [ ] **Step 1: 确认零引用**

Run: `rg -n "user_skill_contract|user_skill_resolver|user-skills.example" --glob "!.git" .`
Expected: 仅命中文档归档与即将删除的文件本身。

- [ ] **Step 2: 删除并更新 CHANGELOG**

删除五个文件；`docs/CHANGELOG.md` 顶部区块新增 Removed 条目：旧版 `user-skill-contract-v1` 注册表与解析器已移除，历史 `resolution_snapshot.skills` 字段仍然可读，`config/user-skills.json` 不再被读取。

- [ ] **Step 3: 验证**

Run: `python .\scripts\run_plugin_tests.py; python .\scripts\release_gate.py`
Expected: 全绿。

- [ ] **Step 4: 提交**

```bash
git add -A plugins/general-screenwriter/scripts/user_skill_contract.py plugins/general-screenwriter/scripts/user_skill_resolver.py plugins/general-screenwriter/config/user-skills.example.json plugins/general-screenwriter/tests/test_user_skill_contract.py plugins/general-screenwriter/tests/test_user_skill_resolver.py docs/CHANGELOG.md
git commit -m "chore: remove legacy user skill registry"
```

### Task 7: D5 wildcard_value 命名与白名单清理

**Files:**
- Modify: `plugins/general-screenwriter/config/plugin-contract.json`
- Modify: `plugins/general-screenwriter/tests/test_user_skill_hub.py`
- Modify: `scripts/package_check.py`
- Modify: `scripts/test_package_check.py`

**Interfaces:**
- Consumes: 现有 `user_skill_hub` 契约块与 `package_check` 密钥扫描。
- Produces: 契约块 `schema_version="user-skill-hub-v2"`、字段 `wildcard_value`（`wildcard_token` 仍以 `token` 结尾，会命中密钥扫描启发式）；`package_check` 无白名单例外。

- [ ] **Step 1: 先改期望测试（RED）**

`test_user_skill_hub.py` 两处断言（契约整字典与 `hub_contract["all_token"]`）改为 `wildcard_value` 与 `user-skill-hub-v2`。

Run: `python plugins\general-screenwriter\tests\test_user_skill_hub.py -k contract`
Expected: 失败。

- [ ] **Step 2: 改契约实现（GREEN）**

`plugin-contract.json` 字段更名并升级 `schema_version`；验证单测通过。

- [ ] **Step 3: 清理 package_check 白名单**

`package_check.py` 删除 `_ALLOWED_JSON_CREDENTIALS` 常量与 `visit()` 中的例外分支；`test_package_check.py` 的 `test_contract_all_token_is_not_treated_as_secret` 改为 `test_contract_wildcard_value_is_not_treated_as_secret`（`wildcard_value` 不误报，`legacy.all_token` 与 `root_token` 均被拦截）。

- [ ] **Step 4: 验证**

Run: `python scripts\test_package_check.py; python .\scripts\run_plugin_tests.py`
Expected: 全绿。

- [ ] **Step 5: 提交**

```bash
git add plugins/general-screenwriter/config/plugin-contract.json plugins/general-screenwriter/tests/test_user_skill_hub.py scripts/package_check.py scripts/test_package_check.py
git commit -m "refactor: rename user skill hub wildcard contract field"
```

### Task 8: D4 系统技能索引与漂移门禁

**Files:**
- Create: `scripts/build_skill_index.py`
- Create: `scripts/test_skill_index.py`
- Create: `plugins/general-screenwriter/config/skill-index.json`
- Modify: `scripts/governance_check.py`
- Modify: `scripts/test_governance_check.py`
- Modify: `plugins/general-screenwriter/skills/general-screenwriter/SKILL.md`

**Interfaces:**
- Consumes: 系统 `skills/*/skill-meta.json`、用户 `skills/user-skills/*/manifest.json`。
- Produces: `build_skill_index.build_index(plugin_root: Path) -> dict`；`config/skill-index.json`。

- [ ] **Step 1: 写入失败测试（RED）**

`scripts/test_skill_index.py`：用例一断言 `build_index(真实插件根)` 序列化结果与已提交 `config/skill-index.json` 一致（文件不存在时先失败）；用例二在临时插件根增删一个技能包后断言索引 entries 集合随之变化；用例三断言重复构建输出逐字节一致。

- [ ] **Step 2: 实现构建器并生成索引（GREEN）**

实现 `build_index`（entries 按 `skill_id` 排序；每条含 `skill_id`、`layer`、`supports`；无时间戳），用 CLI 生成 `config/skill-index.json` 并提交。

- [ ] **Step 3: 治理漂移检查**

`governance_check.py` 增加：重建索引并与 `config/skill-index.json` 逐字节比较，不一致追加快错误"skill-index.json 过期，运行 scripts/build_skill_index.py"；`test_governance_check.py` 增加篡改后报错的用例。

- [ ] **Step 4: 入口路由步骤**

`skills/general-screenwriter/SKILL.md` 增加一句：加载媒介专属系统技能前，先确认 `config/skill-index.json` 中该技能的 `supports` 覆盖当前 `medium_id`。

- [ ] **Step 5: 验证**

Run: `python scripts\test_skill_index.py; python .\scripts\run_plugin_tests.py; python .\scripts\release_gate.py`
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
git add scripts/build_skill_index.py scripts/test_skill_index.py plugins/general-screenwriter/config/skill-index.json scripts/governance_check.py scripts/test_governance_check.py plugins/general-screenwriter/skills/general-screenwriter/SKILL.md
git commit -m "feat: add deterministic skill index and drift gate"
```

## Self-Review

**Spec coverage:** 设计第 3 节 D6 → Task 1；第 4 节 D2 → Task 2；第 5 节 D1 → Task 3；第 6 节 D3 → Tasks 4-6；第 7 节 D5 → Task 7；第 8 节 D4 → Task 8；第 10 节验收标准 1/2/3/4/5/6/7 分别由 Tasks 1/2/3/4-6/7/8 与各任务回归命令覆盖。搁置项（spec 第 2 节）在 Global Constraints 中显式禁止。

**Type consistency:** `_require_plain_entry`（Task 1 产出）被 Task 2 引用；`install_user_skill_pack`、`main`（Task 3）仅被该任务测试与 SKILL.md 引用；`check_plugin_skill_trees`（Task 2）被其测试与 CLI 引用；`build_index`（Task 8）被治理检查引用。门禁步骤名在 Tasks 2/4 中接力更新同一测试。

**Review Focus 对照：** 第 1 条 → Task 1 两个 junction 用例；第 2 条 → Task 1 半安装用例；第 3 条 → Task 2 根白名单与门禁用例；第 4 条 → Task 3 回滚三用例；第 5 条 → Task 5 mock 用例与既有快照用例。

**Proportion:** 每个任务给出接口、落点与测试名，正文不转录实现；Task 1 因立即执行而附完整测试代码，其余任务以断言描述代替。
