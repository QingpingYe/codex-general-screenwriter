# General Screenwriter for Codex

这是由 `general-screenwriter` 包提供的 Codex 原生通用编剧创作插件，不依赖 WorkBuddy 团队运行时。原绘本编剧工坊已升级为通用工作台；当前包名和入口 Skill 都是 `general-screenwriter`，旧插件名不再是当前标识。当前三类媒介均可派发，绘本是完整创作路径，短剧和长篇连续剧是已激活的最小可用类型包，并具备内容级确定性校验、类型专属导出器和真实执行的代表性创作样例。

This repository is the active home for the Codex plugin. It packages:

- General screenwriter type packs
- Editorial workflow
- Text craft methodology
- Craft benchmark checks
- Staging planner
- Gated illustration workflow
- Self-contained HTML preview
- 多人协作飞书知识库同步与权威检索

本文件是安装、使用、配置、同步和验证流程的唯一维护入口。[插件 README](plugins/general-screenwriter/README.md) 保留包内能力与边界说明，并链接到这里。

## Add the plugin

In the ChatGPT desktop app plugin marketplace, add:

```text
https://github.com/QingpingYe/codex-general-screenwriter.git
```

Use `main` as the Git ref. For a small repository, leave the sparse path empty.

从 Marketplace 安装后，在 Codex 中调用插件即可。以下 CLI 和 Python 示例供本地操作与维护使用；Python 示例均从本仓库根目录执行。仅安装插件的用户如需手动执行脚本，应使用已安装插件的实际路径。

From Codex CLI, you can also run:

```powershell
codex plugin marketplace add https://github.com/QingpingYe/codex-general-screenwriter.git --ref main
codex plugin add general-screenwriter@general-screenwriter-github
```

如果 `general-screenwriter-github` 已注册，安装时只需第二条命令。

## Use the plugin

Start a new Codex chat and try:

```text
帮我从零开始策划一个 32 页、面向 3-6 岁儿童的中文绘本故事，主题是学会分享。
```

也可以直接使用其他 active 类型包：

```text
帮我用短剧类型包规划一集 3 分钟、以结尾钩子收束的悬疑短剧。
帮我用长篇类型包核对第二集的角色状态和伏笔连续性。
```

The plugin supports:

- Typed picturebook, shortdrama, and longform TV workflows
- Intent routing, briefing gate, role switching, confirmation gate
- Picture-book text craft methodology and baselines
- Quantified self-review of page text
- Spatial planning for page-by-page storyboards
- Structured illustration prompts, explicit image-generation confirmation, and asset tracking
- Self-contained HTML preview
- Feishu authoritative knowledge retrieval and synchronized ingestion

## User skill hub

插件提供 `user-skill-hub` 自然对话入口。你可以直接说想添加、导入、适配或更新技能；Codex 会先询问并记录 `user_name`，再生成只包含 `manifest.json` 和 `SKILL.md` 的轻量技能包。

六个适用范围数组必须非空。适用维度用 `all`，不能留空数组；`all` 也不能与具体 ID 混用。已有目标 `skill_id` 会进入覆盖模式：先展示差异或新文件预览，再等待用户明确确认。

用户技能只添加在你本地的插件目录，`user-skill-hub` 不会为它执行 git 提交或推送，也不修改插件版本号；共享发布不在该流程内。

用户技能只承载可注入的方法、检查清单、参考资料或导出说明，不能携带可执行文件。系统技能保持插件内置；用户技能不能替代系统技能、运行时规则或类型包契约。

## Feishu knowledge setup

每位使用者需要自己的 lark-cli 登录身份，以及原始飞书 Wiki 的读取权限；执行同步还需要目标 Wiki 的写入权限。

先检查 lark-cli 兼容性，再由本人登录：

```powershell
python .\plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\lark_cli_bootstrap.py
lark-cli auth login
```

兼容检查当前支持 `1.0.95` / `1.0.96`，检查 `LARK_CLI_PATH`、PATH 和标准安装位置，包括 Windows 的 `%APPDATA%\npm`、`%ProgramFiles%\nodejs`，以及 Unix 的 `~/.local/bin`、`/usr/local/bin`、`/opt/homebrew/bin`。若返回 `missing`，它会给出安装命令；只有用户明确批准后才用 `--install` 执行 `npx @larksuite/cli@latest install`。安装器需要 Node.js 16+ 提供 `npx`，安装后仍需本人登录；`unsupported` 表示当前版本未获支持，不自动替换已有 CLI。

将 [配置模板](plugins/general-screenwriter/config/feishu-knowledge-base.example.json) 复制为 `<workspace>/feishu-knowledge-base.json`，或放入下节列出的用户配置目录。`<workspace>` 是实际项目或系列工作区，不是插件缓存目录。

配置使用 schema v2。使用前替换所有占位值，并确认：

- `source.space_id`：原始 Wiki 空间 ID。
- `source.wiki_url`：原始 Wiki URL；将模板中的 `<tenant>` 和 `<source-wiki-token>` 替换为实际值。
- `source.root_mode`：来源范围模式，模板使用 `space`。
- `target.space_id`：目标 Wiki 空间 ID。
- `target.root_mode`：`space` 表示系统容器位于空间根目录，此时省略 `target.root_token`；`node` 表示容器位于指定节点下，此时填写实际 `target.root_token`。

不要提交真实配置或运行产物到 Git，也不要把持久配置存入插件缓存。

原始资料库只读。目标 Wiki 是共享权威，页面正文以同步候选为准：忽略纯排版标记后正文相同则保留，不同则发布。含资源、评论或未知块的页面标记为 `needs_review`；成功覆盖人工编辑时，在报告 `overwritten_human_edits` 中披露。

## Configuration discovery

配置按以下顺序发现：

1. 显式 `--config`。
2. 环境变量 `GENERAL_SCREENWRITER_KB_CONFIG`。
3. 当前 `<workspace>` 及最近祖先目录中的 `feishu-knowledge-base.json`。
4. 用户配置目录：Windows 为 `%APPDATA%\general-screenwriter\feishu-knowledge-base.json`；macOS 为 `~/Library/Application Support/general-screenwriter/feishu-knowledge-base.json`；Linux 为 `${XDG_CONFIG_HOME:-~/.config}/general-screenwriter/feishu-knowledge-base.json`。
5. deprecated fallback：先读取上一版插件的用户目录（如 `%APPDATA%\picturebook-screenwriter\feishu-knowledge-base.json`），再读取 `~/.picturebook-screenwriter/feishu-knowledge-base.json`。

项目子目录会继承最近祖先目录的配置。配置模板不会被自动发现。若把配置放在 `<workspace>/.general-screenwriter/` 或其他自定义位置，需要显式 `--config` 或环境变量；该位置不是默认发现目录。`config-status` 会报告 `origin`（如 `workspace`、`ancestor`、`user`）、`path` 和 `searched`。

## Feishu runtime commands

以下 PowerShell 示例从仓库根目录运行。将 `<workspace>` 替换为项目工作区的绝对路径，并将 `<project_id>`、`<series_id>` 替换为实际标识；后续命令在同一终端中复用这些变量。

```powershell
$workspace = '<workspace>'
$env:GENERAL_SCREENWRITER_KB_CONFIG = Join-Path $workspace 'feishu-knowledge-base.json'
python .\plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\store_cli.py config-status --workspace $workspace
python .\plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\store_cli.py preflight --config $env:GENERAL_SCREENWRITER_KB_CONFIG
python .\plugins\general-screenwriter\skills\knowledge-loader\scripts\authority_cli.py load --workspace $workspace --project-id '<project_id>' --series-id '<series_id>' --page-types worldview,characters,content-spec
```

`preflight` 读取目标控制树，并检查用户身份与目标根可读性；原始库读取权限和目标库写入权限仍需事先获得。`authority_cli.py` 只读检索；`index_synced=false` 表示页面新于索引，需要说明“索引尚未同步”，不得据此覆盖最后确认缓存。离线缓存是非权威版本，只有用户显式批准后才添加 `--allow-offline-cache`，并持续说明“离线”和“非权威”。

同步先创建任务局部运行目录并读取远端来源基线：

```powershell
$run_dir = Join-Path $workspace ('.general-screenwriter/tmp/' + (Get-Date -Format yyyyMMdd-HHmmss))
python .\plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\store_cli.py source-baseline --config $env:GENERAL_SCREENWRITER_KB_CONFIG --out "$run_dir\source_baseline.json"
```

接着通过 [wiki-ingest](plugins/general-screenwriter/skills/wiki-ingest/SKILL.md) 读取和归纳源资料，在同一个运行目录生成 `wiki_staging/_manifest.json` 及候选 Markdown。候选准备完成后再执行：

```powershell
python .\plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\store_cli.py prepare --config $env:GENERAL_SCREENWRITER_KB_CONFIG --run-dir $run_dir
python .\plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\store_cli.py publish --config $env:GENERAL_SCREENWRITER_KB_CONFIG --run-dir $run_dir
python .\plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\store_cli.py verify --config $env:GENERAL_SCREENWRITER_KB_CONFIG --run-dir $run_dir
```

`prepare` 写任务局部目录；`publish` 持有远端租约，发布后回读页面与索引，并输出 `sync_report.json`。当前 `verify` 只生成本地 `verify_report.json`，不独立核对远端知识页；远端写入结果应查看 `publish` 的回读记录。

## Verify locally

使用 Python 3.10+ 和 Node.js 运行聚合离线检查。Windows 上如果 `python` 指向 Microsoft Store 存根，请先使用可用解释器。

```powershell
python .\scripts\run_plugin_tests.py
```

The aggregate runner executes every Python test, both Node checks, governance
validation, and package validation.

运行时、脚本校验与提示词约束的边界见 [ENFORCEMENT.md](docs/ENFORCEMENT.md)。发布前阅读 [RELEASE.md](docs/RELEASE.md)。
