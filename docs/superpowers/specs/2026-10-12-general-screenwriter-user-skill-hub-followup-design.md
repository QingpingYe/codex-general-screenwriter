# 通用编剧插件：用户技能中心复盘整改设计

**状态：** 设计草案
**日期：** 2026-10-12
**关联设计：** `docs/superpowers/specs/2026-10-10-general-screenwriter-user-skill-hub-design.md`
**关联实施计划：** `docs/superpowers/plans/2026-10-12-general-screenwriter-user-skill-hub-followup.md`
**关联仓库：** `https://github.com/QingpingYe/codex-general-screenwriter.git`

## 1. 背景

2026-10-12 对用户技能中心的设计与实现做了全量复盘（设计、运行时接线、契约配置、门禁、测试），确认为以下问题：

| 编号 | 严重度 | 问题 | 复现状态 |
| --- | --- | --- | --- |
| 1 | P1 | 同一次派发中，运行快照记录的 `content_hash` 与任务信封实际注入内容不一致 | 已复现 |
| 2 | P1 | 单个坏技能包连坐所有媒介的运行；hub 流程为"先落盘后校验" | 已复现 |
| 3 | P2 | `skills/user-skills/` 根目录散落文件绕过全部校验与打包检查 | 已复现 |
| 4 | P2 | 共享技能内容无体积上限、无结构化围栏、无注入扫描 | 设计缺口 |
| 5 | P2 | 新旧两代用户技能系统并行，发布门禁指向旧系统 | 静态确认 |
| 6 | P3 | 系统技能 `skill-meta.json` 只验不用，无运行时或门禁消费者 | 静态确认 |
| 7 | P3 | 死代码（不可达分支）与 `all_token` 命名撞密钥扫描启发式 | 静态确认 |
| 8 | P3 | 校验语义不对称：单包校验不拒 junction；系统树静默跳过半安装目录 | 已确认 |

本设计只处理除搁置项以外的整改目标；实施顺序与验收见后文。

## 2. 搁置项（明确不做）

以下内容属于"有意省略治理后的补偿护栏"，本设计明确不做，不得顺手实现：

1. 运行快照与注入内容的对账（快照锁定内容、dispatch 时 content_hash 复核）。
2. 运行时逐包降级隔离（坏包跳过并告警，而不是整树 fail-closed）。
3. 用户技能正文体积上限。
4. 注入内容的结构化围栏与防注入扫描。

搁置期间，`resolution_snapshot.used_user_skills` 与任务信封 `inputs.user_skills` 的既有行为保持不变，`#1` 与 `#2` 的运行时连坐问题在搁置解除前保持现状，仅通过"坏包不进入 live 树"（D1）降低触发概率。

## 3. D6 校验语义统一

目标：链接类条目（symlink/junction）在单包校验、用户树、系统树、包内遍历四处的判定一致；系统树不再静默跳过半安装技能。

规则：

1. 新增模块内助手 `_is_link_like(path: Path) -> bool`：`Path.is_symlink()` 为真，或在支持 `Path.is_junction` 的 Python（3.12+）上为真，或 Windows 上 `os.lstat` 的 `st_reparse_tag` 等于 `0xA0000003`（mount point）时为真。
2. 新增 `_require_plain_entry(path: Path, label: str) -> None`：命中链接类即抛 `UserSkillHubError`，消息同时包含"符号链接"与"junction"两个词。
3. 落点：`_validate_user_skill`（单包根）、`validate_user_skill_tree`（根与每个直接条目）、`_validate_system_skill`（resolve 之前）、`_reject_extra_files`（包内任何链接类条目）。
4. 系统树候选目录判定从"含 `SKILL.md`"改为"含 `SKILL.md` 或 `skill-meta.json`"；含 `skill-meta.json` 但缺 `SKILL.md` 的目录报错，两者皆无的目录继续跳过。
5. 既有"包必须直接位于 `skills/user-skills`"检查保留，作为解析逃逸的兜底。

测试要求：Windows 上单包 junction、系统技能 junction 必须真实执行并断言拒绝；半安装系统技能目录进树校验必须报错；既有 symlink/junction 树级用例保持通过；`jev-decision-runtime` 这类既无 `SKILL.md` 也无 `skill-meta.json` 的目录不受影响。

## 4. D2 用户技能根目录白名单与门禁

目标：`skills/user-skills/` 根下只允许技能目录，散落文件不再被静默忽略。

规则：

1. `validate_user_skill_tree` 遍历根下全部直接条目：不是目录的条目一律报错，报错消息包含条目名；链接类目录条目走 D6 的链接错误。
2. 新增薄门禁脚本 `scripts/user_skill_gate.py`，接口 `check_plugin_skill_trees(plugin_root: Path) -> tuple[str, ...]`，对插件根分别运行用户树与系统树校验，返回错误消息元组（空表示通过）；CLI 输出错误并返回 0/1。
3. 门禁接线：`scripts/run_plugin_tests.py` 的命令列表新增该脚本；`scripts/release_gate.py` 的 `GATE_STEPS` 新增 `("user_skill_trees", "scripts/user_skill_gate.py")`；`scripts/test_release_gate.py` 的期望步骤列表同步更新，并把 `test_declares_nine_gate_steps` 更名为不绑定数量的 `test_declares_gate_steps`。

测试要求：根下 `.exe`、`.md` 等散落文件被拒；真实插件根通过；门禁脚本对含散落文件的临时插件根返回错误字符串。

## 5. D1 用户技能原子安装

目标：坏包或半写入包不进入 live 树；"校验失败不得写入"从文案承诺变成机械事实。

接口：`user_skill_hub.install_user_skill_pack(staged_dir: Path, plugin_root: Path, *, overwrite: bool = False) -> UserSkill`。

换入协议：

1. 先对暂存包做单包校验，失败即抛错，live 树零改动。
2. 目标目录为 `plugin_root/skills/user-skills/<skill_id>`；已存在且未给 `overwrite` 时拒绝。
3. 同卷暂存根为 `plugin_root.parent/".tmp"/"user-skill-hub"`；把暂存包复制到 `<skill_id>-<uuid8>` 工作目录，再复制校验一次。
4. 目标存在时先改名为 `<skill_id>-backup-<uuid8>`，再把工作目录改名为目标；任一步失败回滚备份。
5. 换入后运行 `validate_user_skill_tree`；失败则移除新目标、恢复备份并抛错；成功则删除备份。
6. 模块增加内部 CLI（`validate`、`validate-tree`、`preview`、`install`），供工作流调用；CLI 与脚本都不是用户界面。

配套修改：`skills/user-skill-hub/SKILL.md` 的"校验与写入"一节改写为"暂存 → 单包校验 → 预览 → 用户确认 → install（覆盖显式标志）→ 树校验"；`.gitignore` 增加 `.tmp/`。

测试要求：新装成功；无标志拒绝覆盖且原包内容不变；覆盖成功后备份清理；换入后树校验失败时回滚到旧内容；暂存包非法时 live 树零改动；CLI install 往返成功、无标志覆盖返回非零。

## 6. D3 旧系统退休

目标：轻量用户技能中心成为唯一权威；旧注册表契约退出配置面与门禁。

分三步，各自独立提交与验证：

1. **收口声明**：从 `config/plugin-contract.json` 删除 `user_skill_contract` 块；`release_gate.py` 的 `skill_registry` 步骤替换为 `user_skill_hub`（`tests/test_user_skill_hub.py`）与 `user_skill_runtime`（`tests/test_user_skill_run_integration.py`）两步；两个旧模块加弃用说明头；`test_release_gate.py` 期望列表同步。
2. **解耦调度器**：删除 `stage_dag._load_skill_registry`、`_validate_skills_against_registry` 及其调用点；`resolution_snapshot.skills` 的 schema 校验与读取保留，旧快照继续可读，只是不再与注册表对照。
3. **删除旧件**：删除 `scripts/user_skill_contract.py`、`scripts/user_skill_resolver.py`、`config/user-skills.example.json`、`tests/test_user_skill_contract.py`、`tests/test_user_skill_resolver.py`；CHANGELOG 记录 breaking 说明（`config/user-skills.json` 从未随插件发布，不提供转换器）。

依据：仓库内不存在 `config/user-skills.json`；解析器无生产调用方；旧契约与新 hub 的 `skill_type` 集合互相矛盾（`validator_skill` 对 `reference_skill`），保留即双权威。

测试要求：解耦前先写一条失败测试，证明执行路径会访问旧注册表加载函数（mock 断言），解耦后该访问消失且既有快照用例全绿；删除后全库无残留导入。

## 7. D5 字段命名与死代码清理

目标：消除密钥扫描启发式与契约字段的命名撞车；死代码随 D3 一并消灭。

规则：

1. `plugin-contract.json` 的 `user_skill_hub.all_token` 更名 `wildcard_token`，`schema_version` 由 `user-skill-hub-v1` 升为 `user-skill-hub-v2`（`v1` 已随 0.6.1 发布，按版本化 schema 处理）。
2. `scripts/package_check.py` 删除 `_ALLOWED_JSON_CREDENTIALS` 白名单机制并简化 `visit()`；`scripts/test_package_check.py` 中原"白名单放行"用例改为验证 `wildcard_token` 不触发误报、`root_token` 仍被拦截。
3. 死代码（`user_skill_contract` 不可达 precedence 分支、resolver 的 `PRECEDENCE_RANK` 兜底）不单独处理，随 D3 第 3 步删除。
4. 历史计划文档中的 `all_token` 字样保持不动，属归档记录。

## 8. D4 系统技能索引

目标：系统技能元数据从"只验不用"变成有机械消费者的数据。

方案（A，采纳）：

1. 新增 `scripts/build_skill_index.py`，接口 `build_index(plugin_root: Path) -> dict`，扫描系统 `skill-meta.json` 与用户 `manifest.json`，输出确定性结构：`schema_version`、按 `skill_id` 排序的 `entries`，每条含 `skill_id`、`layer`（`system`/`user`）、`supports` 六个数组；不含时间戳，保证字节稳定。
2. 生成并提交 `plugins/general-screenwriter/config/skill-index.json`。
3. `scripts/governance_check.py` 增加漂移检查：现场重建索引与已提交文件逐字节比较，不一致报错并提示运行 `scripts/build_skill_index.py`。
4. 入口 `skills/general-screenwriter/SKILL.md` 增加路由步骤：加载媒介专属系统技能前，先确认索引条目的 `supports` 覆盖当前 `medium_id`。

方案（B，不采纳）：将系统元数据声明为纯 CI 不变量并从 spec 移除"共享匹配语义"。不采纳原因：验证项 11 的运行时语义将被放弃，索引方案的机械成本更低。

边界声明：Codex harness 仍会暴露全部插件技能，索引无法阻止调用；本方案提供的是"索引正确、完整、新鲜"的机械保证加 agent 侧路由检查，不宣称更强执行力。

测试要求：`build_index` 对真实插件根的结果与提交文件逐字节一致；篡改任一 `skill-meta.json` 后索引重建结果变化、治理检查报错；新增或删除技能包时缺索引漂移被门禁捕获。

## 9. 实施顺序

`D6 → D2 → D1 → D3（三步）→ D5 → D4`

- D6 是其余任务的基础设施：D2 的根白名单与 D1 的换入校验都复用统一的链接语义。
- D1 依赖 D6 与 D2 的校验结果做换入后复核。
- D5 必须在 D3 之后：先移除旧契约块，再改名字段，避免同一文件两处并发改动。
- 每个任务：失败测试先行、单一修复、任务内不夹带重构；收尾跑全量离线回归。

## 10. 验收标准

1. Windows 上单包 junction 与系统技能 junction 均被拒绝；系统树对半安装目录报错。
2. `skills/user-skills/` 根下散落文件导致树校验与 release gate 失败。
3. 无效或半写入的技能包无法进入 live 树；覆盖安装失败时旧内容完整恢复。
4. `plugin-contract.json` 只保留 `user_skill_hub` 一套用户技能契约；旧注册表模块与示例删除；`resolution_snapshot.skills` 旧快照仍可读。
5. `wildcard_token` 命名不再触发密钥扫描白名单；`package_check` 白名单机制删除。
6. `config/skill-index.json` 与现场重建逐字节一致，漂移被治理检查拦截。
7. `python .\scripts\run_plugin_tests.py` 与 `python .\scripts\release_gate.py` 全绿；Windows junction 用例真实执行（日志中不出现 skip）。

## 11. 影响面清单

| 文件 | 动作 |
| --- | --- |
| `plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py` | 链接语义统一、根白名单、原子安装、内部 CLI |
| `plugins/general-screenwriter/skills/user-skill-hub/SKILL.md` | 写入流程改写为暂存安装 |
| `plugins/general-screenwriter/tests/test_user_skill_hub.py` | D6/D2/D5 用例 |
| `plugins/general-screenwriter/tests/test_user_skill_install.py` | 新增原子安装用例 |
| `plugins/general-screenwriter/tests/test_stage_dag_context.py` | 旧注册表解耦回归用例 |
| `plugins/general-screenwriter/config/plugin-contract.json` | 删除旧契约块；字段更名与 schema 升级 |
| `plugins/general-screenwriter/config/skill-index.json` | 新增确定性索引 |
| `plugins/general-screenwriter/skills/general-screenwriter/SKILL.md` | 索引路由步骤 |
| `scripts/user_skill_gate.py`、`scripts/test_user_skill_gate.py` | 新增树门禁 |
| `scripts/build_skill_index.py`、`scripts/test_skill_index.py` | 新增索引构建 |
| `scripts/governance_check.py`、`scripts/test_governance_check.py` | 索引漂移检查 |
| `scripts/release_gate.py`、`scripts/test_release_gate.py` | 门禁步骤更新 |
| `scripts/package_check.py`、`scripts/test_package_check.py` | 白名单机制删除 |
| `scripts/run_plugin_tests.py` | 新增树门禁命令 |
| `docs/CHANGELOG.md` | 记录 breaking 变更 |
| `.gitignore` | 增加 `.tmp/` |
| 删除：`scripts/user_skill_contract.py`、`scripts/user_skill_resolver.py`、`config/user-skills.example.json`、两个旧测试 | D3 第 3 步 |
