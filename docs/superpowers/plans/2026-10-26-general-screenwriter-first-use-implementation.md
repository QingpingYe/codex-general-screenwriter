# General Screenwriter First-Use Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现从 GitHub 市场安装后即可用自然语言完成 lark-cli 自举、设备授权、知识库配置、资源权限诊断、目标控制树初始化和写验收的首次使用闭环。

**Architecture:** 先建立不可变的 CLI 版本契约、统一 `CliContext` 和用户级私有安装器，再增加 named profile、设备授权、链接配置、ACL 诊断与 setup 状态机，最后把 preflight 与 `init-target` 从既有控制面解析中解耦，并接入所有飞书入口、文档和发布门。所有真实写入在执行前产生 preview，远端结果必须回读验证，用户不执行命令行操作。

**Tech Stack:** Python 3.10+、`unittest`、JSON sidecar 状态、PowerShell/POSIX 薄启动器、lark-cli JSON 协议、现有 `store_cli.py` / `Publisher` / `AuthorityLoader` 适配器。

**Spec:** `docs/superpowers/specs/2026-10-26-general-screenwriter-first-use-design.md`

## Global Constraints

- CLI 版本只使用一个下限：`MIN_LARK_CLI_VERSION = "1.0.95"`；`1.0.95` 及更高的稳定语义版本通过版本门槛，`1.0.96`、`1.0.98`、`1.0.100`、`1.1.0`、`2.0.0` 都必须通过；不得维护精确版本白名单，`tested_versions` 只能记录兼容验收结果，不能参与准入。
- 预发行版本按稳定发布规则处理：默认不接受 `-alpha`、`-beta`、`-rc`；解析失败、不可执行和能力缺失必须是不同状态。
- 默认不得执行 `npx @larksuite/cli@latest install`；该安装器执行全局 npm 安装和全局 lark skills 安装。默认安装路线是用户级 `npm install --prefix <user-data>/general-screenwriter/runtimes/lark-cli/<version> @larksuite/cli@<resolved-stable>` 或官方发布包加校验值。
- 默认应用策略是每用户独立应用；共享应用只接受组织已经批准的本地绑定或密钥管理配置，不得通过聊天、插件状态、Git 或配置文件传递 appSecret。
- 任何新应用配置都必须使用 `config init --new --name <profile>`；不得省略 `--name`。后续 `auth`、`profile`、`wiki`、`docs`、`drive` 调用必须显式绑定同一个 `--profile`。
- 无本地配置时，源库和目标库 Wiki 链接是必要用户输入；用户不填写 token、space_id 或内部 ID。不得把作者电脑配置当作团队默认值。
- 必需核心 scope：`docx:document:create`、`docx:document:readonly`、`docx:document:write_only`、`wiki:node:retrieve`、`wiki:node:create`、`wiki:node:read`、`wiki:space:read`、`drive:file:download`、`docs:permission.member:auth`。条件 scope：`drive:drive.metadata:readonly`、`docs:document.media:upload`。默认不请求 `wiki:wiki`、`drive:drive` 或 `domain all`。
- setup 状态必须使用独立 check，不得用单一“已安装”布尔值。状态至少覆盖 `runtime_missing`、`cli_missing`、`cli_too_old`、`version_unparseable`、`capability_missing`、`app_unconfigured`、`waiting_user`、`waiting_admin`、`waiting_org_app_binding`、`permission_missing`、`resource_grant_required`、`config_missing`、`config_invalid`、`profile_ambiguous`、`control_tree_missing`、`waiting_initializer`、`control_tree_ambiguous`、`write_result_uncertain`、`write_verification_required`、`network_blocked`、`needs_escalation`、`read_ready`、`ready`。
- 空目标库首次初始化必须由指定维护者执行；其他同事进入 `waiting_initializer`，不得两边同时执行 `Publisher.initialize()`。没有远端原子互斥前，不得宣称跨机器原子初始化能力。
- 首次 setup 不自动执行全量知识同步；演示写入、验收写入和正式初始化必须各自有明确 preview，并遵循已有用户授权。
- 订阅式约定只有在脚本、启动器或测试中强制才算硬约束；没有宿主 hook 时，AI 必须先走 setup 的提示词约定不得宣传成平台级拦截。
- 每个任务先写失败测试并观察失败，再写最小实现；每个任务结束后运行对应测试和 `python .\scripts\run_plugin_tests.py`，单独提交。
- 当前 Windows 是首个完整验收平台；macOS/Linux 的代码路径必须同步实现，但未实际验收的平台/架构在报告中标记为未验证。

## Review Focus

1. 已有兼容 CLI、已有 profile 和其他 app 配置同时存在时，新 CLI 或新 profile 流程不得修改、清理或覆盖它们（Task 1、Task 2、Task 3、Task 4 用例）。
2. 私有安装路径不得出现全局 npm 安装、global lark skills 安装、PATH 修改或系统 CLI 覆盖，且安装后当前会话仍能直接使用绝对路径（Task 3 用例）。
3. 无配置用户只提供源/目标链接时，链接解析、root mode 推导、原子保存和 ACL 授权状态必须分别可诊断；scope 已授权不能冒充目标资源 ACL 已满足（Task 5、Task 6 用例）。
4. 两个使用者同时看到空目标库时，未确认的普通使用者必须进入 `waiting_initializer` 且零写入；指定维护者路径必须可幂等回读，重复或歧义系统页必须停止并报告，不能宣称无锁的跨机器原子性（Task 6、Task 9 用例）。
5. 授权过期、设备码中断、写入结果不确定和原始创作请求被 setup 打断时，必须恢复真实状态并继续原任务，不得重复创建、重复授权或静默丢失请求（Task 4、Task 6、Task 9 用例）。

---

### Task 1: Lark CLI 版本契约与 SemVer 门槛

**Files:**
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli_contract.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli_contract.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli_bootstrap.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli_bootstrap.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli.py`

**Interfaces:**
- Consumes: 现有 `LarkCli._raw()`、`ensure_lark_cli()` 和 `--version` 输出。
- Produces: `MIN_LARK_CLI_VERSION: str`、`parse_version(text: str) -> tuple[int, int, int] | None`、`version_meets_minimum(version: str) -> bool`、`detect_capabilities(binary: Path, runner=subprocess.run) -> frozenset[str]`。

- [ ] **Step 1: 写入失败测试**

在 `test_lark_cli_contract.py` 增加断言：

```python
self.assertFalse(version_meets_minimum("1.0.94"))
self.assertTrue(version_meets_minimum("1.0.95"))
self.assertTrue(version_meets_minimum("1.0.100"))
self.assertTrue(version_meets_minimum("1.1.0"))
self.assertTrue(version_meets_minimum("2.0.0"))
self.assertFalse(version_meets_minimum("1.0.95-rc.1"))
self.assertIsNone(parse_version("unparseable"))
```

在现有 bootstrap/CLI 测试中把 `1.0.96` 的精确白名单断言改成“不低于 `1.0.95` 的稳定版本可用”。

- [ ] **Step 2: 运行并确认失败**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_cli_contract.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_cli_bootstrap.py"`

Expected: 新模块或新符号不存在导致失败；旧测试仍证明白名单行为。

- [ ] **Step 3: 实现单一下限与能力探测**

`lark_cli_contract.py` 只保留数值 SemVer 比较、稳定版判断和 capability 探针；`lark_cli_bootstrap.py` 的 `_inspect_candidates()` 与 `lark_cli.py` 的 `verify_supported_version()` 改为调用该契约。capability 探针至少检查 `help`、`schema`、`auth login --help`、`wiki --help`、`docs --help`、`drive --help`，命令缺失时返回具体 capability 名称，不归入版本错误。

- [ ] **Step 4: 运行并确认通过**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_cli_contract.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_cli_bootstrap.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_cli.py"`

Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli_contract.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli_contract.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli_bootstrap.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli_bootstrap.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli.py
git commit -m "feat: use a single lark cli minimum version"
```

### Task 2: 统一 CliContext、路径解析和 profile 绑定

**Files:**
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli_context.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli_context.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/config.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/store_cli.py`
- Modify: `plugins/general-screenwriter/skills/knowledge-loader/scripts/authority_cli.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_store_cli.py`
- Modify: `plugins/general-screenwriter/skills/knowledge-loader/scripts/test_authority_cli.py`

**Interfaces:**
- Consumes: Task 1 的 `version_meets_minimum()` 和 `detect_capabilities()`。
- Produces: `@dataclass(frozen=True) CliContext(binary: Path, version: str, profile: str | None, capabilities: frozenset[str])`、`resolve_cli_context(candidates=None, profile=None, environ=None, runner=subprocess.run, which=shutil.which) -> CliContext`、`build_cli_command(context: CliContext, *arguments: str) -> list[str]`。

- [ ] **Step 1: 写入失败测试**

在 `test_lark_cli_context.py` 覆盖：显式路径优先、PATH 次之、标准目录再次、私有安装目录存在时被识别、首候选坏但后候选好、显式路径失效时报告路径而不继续命中同一值、带空格/中文路径、无 profile 时不生成 `--profile`、有 profile 时每个命令都带 `--profile <name>`。

- [ ] **Step 2: 运行并确认失败**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_cli_context.py"`

Expected: 模块不存在或路径/profile 断言失败。

- [ ] **Step 3: 实现解析器并接线消费者**

`resolve_cli_context()` 返回真实探测后的绝对可执行路径、版本、profile 和能力集合。`LarkCli` 接受可选 `profile` 并把 `--profile <name>` 插入所有子命令；`store_cli.build_components()` 不再直接取 `config.cli_candidates[0]`，`authority_cli.py` 不再手工探测候选。无效显式路径必须给出失败路径和原因，后续调用不得继续使用该值。

- [ ] **Step 4: 运行并确认通过**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_cli_context.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_store_cli.py"; python "plugins\general-screenwriter\skills\knowledge-loader\scripts\test_authority_cli.py"`

Expected: 全部 PASS，且 profile 参数出现在每一个 fake CLI 调用中。

- [ ] **Step 5: 提交**

```bash
git add plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli_context.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli_context.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/config.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/store_cli.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_store_cli.py plugins/general-screenwriter/skills/knowledge-loader/scripts/authority_cli.py plugins/general-screenwriter/skills/knowledge-loader/scripts/test_authority_cli.py
git commit -m "feat: resolve one cli context with profile binding"
```

### Task 3: 用户级私有 CLI 安装

**Files:**
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_runtime.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_runtime.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli_bootstrap.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli_bootstrap.py`

**Interfaces:**
- Consumes: Task 2 的 `resolve_cli_context()`。
- Produces: `@dataclass(frozen=True) RuntimePaths(root: Path, node_dir: Path, npm_prefix: Path, cli_bin: Path)`、`@dataclass(frozen=True) PrivateCliArtifact(url: str, sha256: str, platform: str, arch: str)`、`resolve_runtime_paths(environ=None, platform=None) -> RuntimePaths`、`install_private_cli(paths: RuntimePaths, version: str, runner=subprocess.run, artifact: PrivateCliArtifact | None = None) -> CliInstallResult`。

- [ ] **Step 1: 写入失败测试**

在 `test_lark_runtime.py` 断言：已有合格 CLI 不调用 npm；npm 缺失返回 `runtime_missing`；安装命令包含 `npm`、`install`、`--prefix`、`@larksuite/cli@<version>`；命令中永远不出现 `-g`、`npx ... install`、`skills add`；安装后返回私有目录中的绝对路径；下载失败、校验失败、平台/架构不支持分别为独立状态；执行前后 `PATH` 对象不变。

- [ ] **Step 2: 运行并确认失败**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_runtime.py"`

Expected: 模块或私有安装行为不存在。

- [ ] **Step 3: 实现私有安装与运行时契约**

`lark_runtime.py` 只使用用户数据目录，调用 `npm install --prefix <npm_prefix> @larksuite/cli@<version>`；如果选择官方二进制路线，则必须接收官方校验值并在复制前验证 SHA-256。运行时不修改全局 PATH、不安装 global skills、不覆盖系统 CLI，并把持久路径和安装结果返回给 setup 状态机。

- [ ] **Step 4: 运行并确认通过**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_runtime.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_cli_bootstrap.py"`

Expected: 全部 PASS；fake runner 的调用记录中没有全局安装或全局技能命令。

- [ ] **Step 5: 提交**

```bash
git add plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_runtime.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_runtime.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli_bootstrap.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli_bootstrap.py
git commit -m "feat: install lark cli only into user runtime"
```

### Task 4: Named Profile、共享应用边界与设备授权

**Files:**
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_profile.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_auth.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_profile.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_auth.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli.py`

**Interfaces:**
- Consumes: Task 2 的 `CliContext`、`build_cli_command()`。
- Produces: `ProfileState(name: str, app_id: str, source: Literal["existing", "created", "bound"])`、`OrgAppBindingRequired`（异常带 `status="waiting_org_app_binding"`）、`ensure_named_profile(context, profile_name, mode="per_user", runner=subprocess.run) -> ProfileState`、`AppConfigChallenge(profile_name: str, verification_url: str, console_url: str | None, output_path: Path)`、`begin_app_config(context, profile_name, runner=subprocess.Popen) -> AppConfigChallenge`、`wait_app_config(challenge, timeout_seconds=600, clock=time.monotonic, sleeper=time.sleep) -> ProfileState`、`DeviceAuthorization(verification_url: str, device_code: str, expires_in: int)`、`begin_device_auth(context, scopes=REQUIRED_SCOPES, runner=subprocess.run) -> DeviceAuthorization`、`complete_device_auth(context, device_code, runner=subprocess.run) -> dict[str, Any]`、`write_qr_png(context, url, destination, runner=subprocess.run) -> Path`。

- [ ] **Step 1: 写入失败测试**

测试新的 app 创建命令必须精确包含 `config init --new --name <profile>`；后台配置输出必须能提取原样 URL/控制台链接并生成二维码；已存在 named profile 时不覆盖；其他 profile、secret、user token 保持不变；共享模式没有本地受控绑定时抛出 `waiting_org_app_binding`；`auth login --no-wait --json` 返回裸对象时读取 `verification_url`、`device_code`、`expires_in`，不要求 `user_code` 或 `ok/data`；过期后重新发起相同 scope；日志和异常中不出 appSecret、access token、refresh token、device code。

- [ ] **Step 2: 运行并确认失败**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_profile.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_auth.py"`

Expected: 模块或 named-profile/设备授权行为不存在。

- [ ] **Step 3: 实现 profile 与授权适配**

`lark_profile.py` 负责发现、创建、复用和绑定 named profile；默认 `mode="per_user"`，共享模式只接受预先存在的受控本地绑定。`begin_app_config()` 使用后台进程启动 `config init --new --name <profile>`，把 stdout/stderr 写入受限临时文件，提取 URL 后结束当前轮；`wait_app_config()` 只轮询真实配置状态。`lark_auth.py` 固定核心 scope，调用 `auth login --no-wait --json` 和 `auth login --profile <profile> --device-code <device_code>`，保留 URL 原样，不重拼 query，不把 user_code 当作 device code，不写长期状态中的授权秘密；`write_qr_png()` 使用官方 CLI 的二维码能力或已验证的本地生成器。

- [ ] **Step 4: 运行并确认通过**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_profile.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_auth.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_lark_cli.py"`

Expected: 全部 PASS，且 fake CLI 调用中所有后续命令都绑定 profile。

- [ ] **Step 5: 提交**

```bash
git add plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_profile.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_auth.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_profile.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_auth.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/lark_cli.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_lark_cli.py
git commit -m "feat: isolate profiles and automate device authorization"
```
### Task 5: 链接驱动的配置生成与资源 ACL 诊断

**Files:**
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/knowledge_config_bootstrap.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/resource_access.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_knowledge_config_bootstrap.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_resource_access.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/config_paths.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_config_paths.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_config.py`

**Interfaces:**
- Consumes: Task 2 的 `CliContext`、现有 `KnowledgeConfig` / `SourceConfig` / `TargetConfig`、`LarkCli.get_node()`、`fetch_doc()`。
- Produces: `WikiReference(url: str, token: str, space_id: str | None, root_mode: Literal["space", "node"])`、`parse_wiki_reference(url: str) -> WikiReference`、`build_config_from_links(source_url: str, target_url: str, cli: LarkCli) -> KnowledgeConfig`、`write_config_atomic(config: KnowledgeConfig, destination: Path) -> Path`、`ResourceAccessReport(status: Literal["ok", "resource_grant_required", "waiting_admin"], missing: tuple[str, ...], details: tuple[str, ...])`、`check_resource_access(config: KnowledgeConfig, cli: LarkCli, sample_node_tokens: Iterable[str] = ()) -> ResourceAccessReport`。

- [ ] **Step 1: 写入失败测试**

覆盖：标准 Wiki space URL、Wiki node URL、带查询参数/分片 URL、非 Wiki URL、source 与 target 指向同一资源、无法判断 root mode；`build_config_from_links()` 不要求用户填写 space_id/token；写入是临时文件加 `os.replace()`；失败时保留旧配置；配置和报告中不出现 appSecret、access token、refresh token；根可读但采样节点不可读时必须返回 `resource_grant_required`，不能返回 `ok`。

- [ ] **Step 2: 运行并确认失败**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_knowledge_config_bootstrap.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_resource_access.py"`

Expected: 模块不存在或 ACL 误判为 `ok`。

- [ ] **Step 3: 实现链接解析、原子配置和 ACL onboarding**

`parse_wiki_reference()` 只解析 Wiki URL 或显式 token，不接受普通网页抓取。`build_config_from_links()` 通过 `wiki +node-get` 获取 `space_id`、节点身份和 root mode；身份不明确时返回 `config_invalid`，不猜测。`check_resource_access()` 分层检查 user 身份、源根和采样文档可读、目标根可读、目标编辑权限与验收页写入前权限；资源 ACL 缺失时必须与 scope 缺失分开报告。`config_paths.py` 保持现有显式和用户目录优先级，只增加首次写入的稳定 destination resolver，不把私有 CLI profile 混入知识库 schema。

- [ ] **Step 4: 运行并确认通过**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_knowledge_config_bootstrap.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_resource_access.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_config_paths.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_config.py"`

Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/knowledge_config_bootstrap.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/resource_access.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_knowledge_config_bootstrap.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_resource_access.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/config_paths.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_config_paths.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_config.py
git commit -m "feat: bootstrap knowledge config from wiki links"
```

### Task 6: Setup 状态机、preflight 解耦与 init-target 所有权

**Files:**
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/setup_state.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/setup_doctor.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_setup_state.py`
- Create: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_setup_doctor.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/store_cli.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/publisher.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_store_cli.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_publisher.py`

**Interfaces:**
- Consumes: Task 2 的 `CliContext`、Task 3 的私有安装结果、Task 4 的 profile/auth 状态、Task 5 的配置与 ACL 报告。
- Produces: `SetupCheck(check_id: str, status: str, reason_code: str | None, message: str, ai_next_actions: tuple[str, ...], human_action: str | None)`、`render_setup_report(checks: Sequence[SetupCheck]) -> dict[str, Any]`、`run_doctor(config_path=None, workspace=None, environ=None, initializer=False, runner=subprocess.run) -> dict[str, Any]`、`init_target(config_path=None, workspace=None, environ=None, authorized=False, initializer_confirmed=False, runner=subprocess.run) -> dict[str, Any]`、`Publisher.inspect_control_tree() -> dict[str, Any]`、`Publisher.preview_initialization() -> dict[str, Any]`。

- [ ] **Step 1: 写入失败测试**

覆盖：空目标库的 `doctor` 在控制树缺失时不调用 `resolve_control_plane()`，也不加载 `ControlPlane`；未确认初始化维护者时返回 `waiting_initializer` 且写入调用为零；确认维护者后可预览、初始化、写后回读、重复运行幂等；普通使用者不会抢占初始化写入；已存在或重复系统页返回 `control_tree_ambiguous` 且不继续覆盖；写入结果不确定返回 `write_result_uncertain`；只有实际写验收成功后才返回 `ready`；普通 init 不触发全量同步。

- [ ] **Step 2: 运行并确认失败**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_setup_state.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_setup_doctor.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_store_cli.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_publisher.py"`

Expected: 新状态模块不存在，或现有 `build_components()` 在空库提前失败。

- [ ] **Step 3: 实现分层构建和初始化状态**

把 `build_components()` 拆成“解析配置与 CLI 上下文”“只读 doctor”“按需构建 Publisher/ControlPlane”三层；`preflight` 只做身份、源库、目标根和控制树只读诊断。新增 `store_cli.py doctor`、`store_cli.py init-target` 和 `store_cli.py write-verify`。`Publisher` 增加无写入的 tree inspection 与 preview；`init_target()` 在空库阶段不获取不存在的锁，维护者确认后才调用 `initialize()`，写后回读并检查重复页。

- [ ] **Step 4: 运行并确认通过**

Run: `python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_setup_state.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_setup_doctor.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_store_cli.py"; python "plugins\general-screenwriter\skills\feishu-knowledge-store\scripts\test_publisher.py"; python .\scripts\run_plugin_tests.py`

Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/setup_state.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/setup_doctor.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_setup_state.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_setup_doctor.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/store_cli.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/publisher.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_store_cli.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/test_publisher.py
git commit -m "feat: add setup doctor and owned target initialization"
```

### Task 7: Setup Skill、入口接线与用户文档

**Files:**
- Create: `plugins/general-screenwriter/skills/setup/SKILL.md`
- Create: `plugins/general-screenwriter/skills/setup/skill-meta.json`
- Create: `plugins/general-screenwriter/skills/setup/scripts/setup_cli.py`
- Create: `plugins/general-screenwriter/skills/setup/scripts/runtime_launcher.ps1`
- Create: `plugins/general-screenwriter/skills/setup/scripts/runtime_launcher.sh`
- Create: `plugins/general-screenwriter/skills/setup/scripts/test_setup_cli.py`
- Create: `plugins/general-screenwriter/tests/test_setup_contract.py`
- Modify: `plugins/general-screenwriter/skills/general-screenwriter/SKILL.md`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/SKILL.md`
- Modify: `plugins/general-screenwriter/skills/wiki-ingest/SKILL.md`
- Modify: `plugins/general-screenwriter/skills/wiki-ingest/references/feishu-wiki-extraction.md`
- Modify: `plugins/general-screenwriter/skills/knowledge-loader/SKILL.md`
- Modify: `plugins/general-screenwriter/config/plugin-contract.json`
- Modify: `plugins/general-screenwriter/config/skill-index.json`
- Modify: `plugins/general-screenwriter/.codex-plugin/plugin.json`
- Modify: `README.md`
- Modify: `plugins/general-screenwriter/README.md`

**Interfaces:**
- Consumes: Task 1-6 的全部内部接口。
- Produces: `setup_cli.py doctor --json`、`setup_cli.py auth-start --json`、`setup_cli.py auth-complete --device-code <code> --json`、`setup_cli.py config-from-links --source-url <url> --target-url <url> --json`、`setup_cli.py target-init --initializer --authorized --json`、`setup_cli.py write-verify --authorized --json`。

- [ ] **Step 1: 写入失败测试**

在 `test_setup_cli.py` 覆盖命令输出 JSON 和退出码、薄启动器选择宿主/系统/用户 Python 的优先级、无解释器时返回 `runtime_missing`、启动器不修改 PATH；在 `test_setup_contract.py` 断言 setup skill 出现在 plugin contract、skill index、manifest 和全部入口技能中；入口技能必须先走 setup，旧文档不得再要求用户运行 `lark-cli auth login`、复制配置模板或重开终端；用户可见步骤中不得出现 `config init`、`auth login`、`npx ... install` 等内部命令。

- [ ] **Step 2: 运行并确认失败**

Run: `python "plugins\general-screenwriter\skills\setup\scripts\test_setup_cli.py"; python "plugins\general-screenwriter\tests\test_setup_contract.py"`

Expected: setup skill 或 CLI 不存在；旧入口文案断言失败。

- [ ] **Step 3: 创建 setup skill 并接线全部飞书入口**

新增 `skills/setup/SKILL.md`、`skill-meta.json`、`runtime_launcher.ps1` 和 `runtime_launcher.sh`；skill 只描述 AI 内部动作、状态解释和恢复，不向用户暴露命令。两个薄启动器只负责寻找宿主 Python、系统 Python 或用户级 Python，并把解释器绝对路径交给包内脚本；它们不得下载 CLI、不得调用全局 lark skills、不得要求重开终端。`setup_cli.py` 组合 Task 1-6 模块，负责 doctor、auth、config、init 和 write verification。修改 `general-screenwriter`、`feishu-knowledge-store`、`wiki-ingest`、`knowledge-loader` 的入口，让飞书相关请求先检查 setup 状态，成功后恢复原任务。更新 `config/plugin-contract.json`、`config/skill-index.json` 和 `.codex-plugin/plugin.json`，再运行索引生成脚本。

- [ ] **Step 4: 运行并确认通过**

Run: `python "plugins\general-screenwriter\skills\setup\scripts\test_setup_cli.py"; python "plugins\general-screenwriter\tests\test_setup_contract.py"; python "plugins\general-screenwriter\tests\test_plugin_contract.py"; python .\scripts\run_plugin_tests.py`

Expected: 全部 PASS；用户可见文档中没有手工飞书命令。

- [ ] **Step 5: 提交**

```bash
git add plugins/general-screenwriter/skills/setup plugins/general-screenwriter/tests/test_setup_contract.py plugins/general-screenwriter/skills/general-screenwriter/SKILL.md plugins/general-screenwriter/skills/feishu-knowledge-store/SKILL.md plugins/general-screenwriter/skills/wiki-ingest/SKILL.md plugins/general-screenwriter/skills/wiki-ingest/references/feishu-wiki-extraction.md plugins/general-screenwriter/skills/knowledge-loader/SKILL.md plugins/general-screenwriter/config/plugin-contract.json plugins/general-screenwriter/config/skill-index.json plugins/general-screenwriter/.codex-plugin/plugin.json README.md plugins/general-screenwriter/README.md
git commit -m "feat: add the first-use setup skill"
```

### Task 8: 首次使用端到端离线仿真

**Files:**
- Create: `plugins/general-screenwriter/tests/test_first_use_e2e.py`
- Modify: `plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/setup_doctor.py`
- Modify: `plugins/general-screenwriter/skills/setup/scripts/setup_cli.py`

**Interfaces:**
- Consumes: Task 1-7 的公开内部接口和 fake runner/fake CLI 测试夹具。
- Produces: 端到端离线场景：私有安装 → named profile → device auth → link config → ACL onboarding → doctor → target init → write verify → 恢复原请求。

- [ ] **Step 1: 写入失败测试**

在 `test_first_use_e2e.py` 建立 fake user-data 目录和 fake CLI runner，覆盖：全局无 CLI 时只进入私有安装；已有全局兼容 CLI 时直接复用；已有其他 profile 时新建 profile 不清理旧配置；设备码过期后可重新发起同 scope；源/目标链接解析成功后 ACL 缺失进入 `resource_grant_required`；授权后进入 `ready`；空目标库只有指定维护者写入，普通使用者等待；重复或歧义系统页停止并报告；写入结果不确定先回读，再恢复原任务。

- [ ] **Step 2: 运行并确认失败**

Run: `python "plugins\general-screenwriter\tests\test_first_use_e2e.py"`

Expected: 端到端状态链尚未连通。

- [ ] **Step 3: 补齐编排胶水**

只增加 setup doctor 和 setup CLI 的状态传递、重试和原任务恢复，不重写 Task 1-7 的模块职责。每次重试必须先读真实状态，只执行未完成步骤；网络错误有限重试，权限、校验、重复资源错误不无限重试。

- [ ] **Step 4: 运行并确认通过**

Run: `python "plugins\general-screenwriter\tests\test_first_use_e2e.py"; python .\scripts\run_plugin_tests.py`

Expected: 全部 PASS，fake runner 中没有全局安装、重复创建、重复授权或静默覆盖记录。

- [ ] **Step 5: 提交**

```bash
git add plugins/general-screenwriter/tests/test_first_use_e2e.py plugins/general-screenwriter/skills/feishu-knowledge-store/scripts/setup_doctor.py plugins/general-screenwriter/skills/setup/scripts/setup_cli.py
git commit -m "test: cover first use end to end"
```

### Task 9: 发布门、维护文档与真实环境验收

**Files:**
- Create: `plugins/general-screenwriter/tests/test_first_use_release_contract.py`
- Modify: `scripts/run_plugin_tests.py`
- Modify: `scripts/release_gate.py`
- Modify: `scripts/test_release_gate.py`
- Modify: `scripts/package_check.py`
- Modify: `docs/RELEASE.md`
- Modify: `docs/ENFORCEMENT.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `.agents/plugins/marketplace.json`
- Modify: `plugins/general-screenwriter/.codex-plugin/plugin.json`

**Interfaces:**
- Consumes: Task 1-8 的全部测试、setup skill 和运行时安装路径。
- Produces: 新增 release gate 步骤 `first_use_contract` 和 `setup_docs_contract`；发布检查覆盖干净 Windows 账号、已有更高版本 CLI、其他插件/profile、两用户权限验收、无凭证泄漏和中断恢复。

- [ ] **Step 1: 写入失败测试**

在 `test_first_use_release_contract.py` 断言 `GATE_STEPS` 包含 `first_use_contract`、`setup_docs_contract`，`run_plugin_tests.py` 能发现所有新增测试，`docs/RELEASE.md` 包含干净 Windows VM、已有更高版本 CLI、两个真实用户、无全局安装、无凭证、中断恢复六类验收，并且 README/用户文档不再要求用户执行飞书命令。

- [ ] **Step 2: 运行并确认失败**

Run: `python "plugins\general-screenwriter\tests\test_first_use_release_contract.py"; python "scripts\test_release_gate.py"`

Expected: 新 gate 步骤或文档声明不存在。

- [ ] **Step 3: 接入发布门和文档**

在 `scripts/run_plugin_tests.py` 中确保新增测试被发现；在 `scripts/release_gate.py` 中把 `first_use_contract` 和 `setup_docs_contract` 放到 offline regression 前。将插件 manifest version 从 `0.7.0` 升到 `0.8.0`，同步 CHANGELOG、RELEASE、ENFORCEMENT、marketplace 和 manifest 的首次使用说明。维护者命令只放维护文档，用户文档只保留自然语言步骤。

- [ ] **Step 4: 运行全部离线验收**

Run:

```powershell
python .\scripts\run_plugin_tests.py
python .\scripts\release_gate.py
python .\scripts\governance_check.py
python .\scripts\package_check.py
```

Expected: 全部 PASS，release gate 输出包含 `first_use_contract` 和 `setup_docs_contract`。

- [ ] **Step 5: 执行真实环境发布门**

在干净 Windows 账号/VM 中只从市场安装插件，不给作者全局技能和开发目录，依次记录：

1. 无 CLI → 用户级私有安装 → 当前会话验证绝对路径。
2. named profile 创建/复用 → 其他 profile 不变。
3. 授权链接和二维码可见 → 用户完成同意 → device code 续跑成功。
4. 源/目标链接生成配置 → 缺失 ACL 显示 `resource_grant_required` → 授权后重验。
5. 空目标库由维护者初始化 → 第二用户等待并复用。
6. 每用户创建、带 revision 更新、回读验收页。
7. 中断、过期、网络失败、写入结果不确定后恢复原任务。
8. 日志、Git、状态、导出中无 appSecret/accessToken/refreshToken/device_code。

- [ ] **Step 6: 提交**

```bash
git add plugins/general-screenwriter/tests/test_first_use_release_contract.py scripts/run_plugin_tests.py scripts/release_gate.py scripts/test_release_gate.py scripts/package_check.py docs/RELEASE.md docs/ENFORCEMENT.md docs/CHANGELOG.md .agents/plugins/marketplace.json plugins/general-screenwriter/.codex-plugin/plugin.json
git commit -m "chore: gate the first use release"
```

## Execution Order

按 Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8 → Task 9 顺序执行。Task 1-2 是后续所有任务的前置；Task 3-4 可并行设计但必须合并后再进入 Task 5；Task 6 必须等待 Task 5 的 ACL 报告接口稳定；Task 7-9 不得绕过任何前序任务的状态机。

## Live Acceptance Evidence

真实环境验收必须保留脱敏证据：执行时间、平台/架构、CLI 版本、profile 来源、授权状态、链接解析结果、初始化所有权、重复页检查、写入/回读 revision、ACL 授权前后状态、用户命令行操作次数和秘密扫描结果。不得把离线 fake runner 结果表述为真实飞书验收。

## Self-Review Checklist

- [ ] Spec 的目标、用户约束、版本规则、私有安装路线、named profile、共享应用边界、链接配置、scope 清单、ACL onboarding、拆分 preflight、初始化所有权、写验收和发布门都有对应任务。
- [ ] 每个任务都有失败测试、失败运行、最小实现、通过运行和独立提交。
- [ ] 后续任务使用的 `CliContext`、`RuntimePaths`、`ProfileState`、`DeviceAuthorization`、`ResourceAccessReport`、`SetupCheck` 名称与前序任务一致。
- [ ] Review Focus 的五类风险分别由 Task 1-4、Task 3、Task 5-6、Task 6/9、Task 4/6/9 的测试覆盖。
- [ ] 计划没有把真实飞书资源操作、全局 npm 写入、global skills 安装或用户命令行操作当作默认步骤。