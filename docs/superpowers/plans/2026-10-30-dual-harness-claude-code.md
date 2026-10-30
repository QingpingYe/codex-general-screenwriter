# Dual-Harness Packaging: Codex + Claude Code

- 日期：2026-10-30
- 参考：`E:\codex-script2shot\docs\dual-harness-migration-guide.md`（script2shot 实测改造指南）
- 目标版本：`general-screenwriter` 0.9.0

## 目标

让 `E:\codex-picturebook-agent` 的插件同时安装于 Codex 与 Claude Code：
两种宿主各读各的清单目录，共享同一份 `skills/`；Codex 侧零破坏性改动。

## 形态判断（指南 §0）

本插件是**纯 Skills** 形态：无 MCP server、无构建产物、无 Node 运行时依赖
（运行时代码全部是 Python 脚本 + 设置启动器）。因此改造为指南中的最小工作量：

1. 新增 Claude Code 清单；
2. 技能文本中性化；
3. 版本纪律与一致性测试；
4. 双宿主校验与安装演练。

不需要：`.mcp.json`、Node 运行时探测、构建产物入库、权限预允许片段（无 MCP 工具）。

## 已实施变更

### 清单与 marketplace

- 新增 `plugins/general-screenwriter/.claude-plugin/plugin.json`
  （name `general-screenwriter`、version 0.9.0，与 Codex 清单同源同版本）。
- 新增仓库根 `.claude-plugin/marketplace.json`：marketplace 名
  `general-screenwriter-git`，条目 `source: "./plugins/general-screenwriter"`，
  条目 name 与插件清单完全一致。
- Codex 侧 `.codex-plugin/plugin.json` 与 `.agents/plugins/marketplace.json`
  保持结构不变，仅版本与描述随 0.9.0 同步。

### 技能文本中性化（指南 §6）

- 入口 skill、`stage-orchestration`：把 "Codex 原生 / Codex 会话 / Codex 多
  Agent 工具" 改为宿主中性表述（"宿主多 Agent 工具"），派发流程标题改为
  「多 Agent 派发流程」。
- `staging-planner`、`text-craft`、`craft-benchmark-check` 移除 "Codex 会话 /
  Codex 最小版" 字样。
- `user-skill-hub/SKILL.md` 补 YAML frontmatter（Claude Code 加载技能的必需项）。
- 扫描确认 `skills/**/*.md` 无 `$skill` 与 `/plugin:skill` 任一宿主专属触发语法；
  该约束由新测试守卫。

### 审计与门

- 新增 `plugins/general-screenwriter/tests/test_dual_harness_contract.py`：
  - Claude 清单 name/version/author 与 Codex 清单一致；
  - marketplace 条目绑定正确插件与版本；
  - 四个版本来源（两清单、marketplace 条目、CHANGELOG 最新发布）保持一致；
  - 共享技能正文无宿主专属触发语法；
  - README/RELEASE/ENFORCEMENT 覆盖双宿主说明；
  - release_gate 声明并先于 offline_regression 运行本门；
  - package_check 将 `.claude-plugin/plugin.json` 列为必要文件。
- `scripts/package_check.py` 必要文件清单加入 `.claude-plugin/plugin.json`。
- `scripts/release_gate.py` 新增 `dual_harness_contract` 步骤（位于
  `first_use_contract` 之前）；`plugin-contract.json` 的 `release_gate.steps`
  同步；`scripts/test_release_gate.py` 断言同步。
- `docs/ENFORCEMENT.md` 增补 dual-harness packaging 行（`script_checked`）。
- `docs/RELEASE.md` 增加 `claude plugin validate` 步骤与双清单版本核对说明。

### 版本

- 0.9.0：`plugin.json`（Codex）、`.claude-plugin/plugin.json`、
  `.claude-plugin/marketplace.json`、`docs/CHANGELOG.md`；
  `tests/test_first_use_release_contract.py` 的版本断言同步更新。

### 启动器测试修复（本机/CI 红转绿的一部分）

前置事实：最新 CI（run #21，commit 32af610）在 ubuntu 与 windows 双平台
`Run aggregate verification` 失败；本机复现同一命令，仅 setup 启动器相关
5-6 条测试失败。逐条修复：

1. `test_powershell_launcher_*`：调用 `powershell -File` 时机器策略为
   Restricted（Windows 客户端默认）导致脚本被禁。改为在测试调用中传
   `-ExecutionPolicy Bypass`（仅作用于该次进程调用，不修改机器状态）；
   输出解码固定 UTF-8 + errors=replace，避免 GBK reader thread 崩溃。
2. `preferred='user'` 用例：PATH 上的系统 python 在候选顺序上合法地优先于
   用户级候选，两个启动器测试都在 "user" 分支把 PATH 指向空目录，
   使断言与启动器契约一致。
3. `test_launchers_return_runtime_missing_without_an_interpreter`：
   `PATH=""` 会让 Windows PowerShell 自身无法启动（模块自动加载失败，
   返回 0xFFFF0000）；改为指向"无 Python 的空目录"。`USERPROFILE=""`
   同样破坏 PowerShell 模块自动加载，改为指向临时目录。
4. `_neutral_environment()`：剔除 `CODEX_PYTHON`/`PYTHON`，避免外部环境
   变量注入解释器导致误判。

## 验证记录

- `python scripts/run_plugin_tests.py`：**100/100 通过**（含新增
  test_dual_harness_contract.py 与 package_check 新测试；Node 两个检查通过）。
- Python 3.12 上 `python scripts/release_gate.py`：**全部 14 步通过**，
  packaging_check 报告 `version: 0.9.0`，231 个包内文件。
- `claude plugin validate plugins/general-screenwriter`：Validation passed
  （仅剩 plugin directory 的 LICENSE/icon 分发告警，不影响本地与 git 安装）。
- `claude plugin validate .`（仓库根，marketplace）：Validation passed。
- 隔离配置安装演练（`CLAUDE_CONFIG_DIR` 指向临时目录）：
  `claude plugin marketplace add <repo>` → `plugin install` → `plugin details`：
  Skills (21) 全部列出（user-skills 示例目录不属于系统技能，未计入）、
  无 Agents/Hooks/MCP、无 Errors；演练后已清理临时配置。
- Codex 官方 `validate_plugin.py` 不在本机（`~/.codex/skills/.system` 下没有
  plugin-creator），未运行；Codex 侧清单结构未改动，仅版本与描述文本变化。

## 未覆盖 / 后续

- Claude Code 会话内实际触发技能的行为验收（本机 CLI 2.1.309 仅做了
  validate/install/details 三层演练，未在真实会话内跑创作流程）。
- Codex 侧安装回归（`codex plugin` CLI 不在本机）；清单字段未变，风险低。
- Live first-use 六项验收门（干净 VM、双用户等）状态不变，仍需人工执行。
- LICENSE/icon 为 plugin directory 提交要求；如需提交官方目录再补。
