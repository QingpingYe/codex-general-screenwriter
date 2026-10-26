---
name: setup
description: Use when a Feishu-related request needs first-use preparation or recovery, including Wiki knowledge loading, ingestion, synchronization, authorization, link-based configuration, shared target initialization, or write verification. The skill prepares state internally and then resumes the original task.
---

# 首次使用 Setup

## 目标

把用户已经提出的创作、检索、提取或同步请求保留为原任务，在内部补齐飞书运行环境、账户绑定、授权、知识库配置、共享目标初始化和写入验收。`ready` 后直接恢复原任务，不要求用户重新描述。

## 内部边界

本 Skill 只描述 AI 的内部动作状态与恢复方式。所有执行细节都是插件内部接口，不向用户展示命令、参数、配置文件模板或安装步骤。用户只在必要时完成必须由本人完成的自然语言选择，以及打开可见链接、扫码、同意授权、授予资源权限或批准一次写入。

不得修改全局 PATH，不得执行全局 CLI 安装，不得安装全局 skills，不得要求刷新宿主会话或重启应用。插件使用的运行时与私有 CLI 路径必须由内部启动器或 setup 状态机解析为绝对路径。

## 内部流程

1. 先检查 setup 状态，分别记录运行时、CLI、profile、应用配置、用户授权、知识库配置、资源 ACL、控制树和写入验收结果；不要用单一安装布尔值代替独立检查。
2. 运行时或兼容 CLI 缺失时，只进入用户级私有运行环境；已有兼容 CLI 直接复用。版本不可识别或能力缺失时报告具体缺口，不降级到固定旧版本。
3. 应用配置缺失时，由 AI 发起内部应用配置流程。把原样授权或控制台链接和二维码展示给用户，当前轮在必须由用户完成的操作处结束，不阻塞轮询。
4. 设备授权只使用实际返回的验证链接、设备码和过期时间。设备码只保留在当前 setup 会话的受限内存或临时状态中，不进入长期状态、普通日志、文档或导出。用户完成后，先重新读取真实用户身份和授权状态，再继续。
5. 知识库配置缺失时，只向用户询问原始 Wiki 与目标 Wiki 链接；不得让用户填写 token、space_id 或手工 JSON。解析成功后原子写入稳定用户配置位置，有效旧配置不得覆盖。
6. 只读预检分别报告应用 scope、用户授权与具体资源 ACL。资源权限不足时进入 `resource_grant_required`，说明需要资源所有者或管理员授予的具体范围；scope 成功不能冒充资源 ACL 成功。
7. 空目标库由指定维护者确认后预览并初始化；普通使用者保持 `waiting_initializer`，不得抢占写入。发现重复、部分或歧义系统页时停止，不覆盖、不修复、不重建。
8. 写入前展示具体变更或验收动作；收到当前会话中的明确授权后才执行。写入后必须回读；结果不确定时先读回，不盲目重试。
9. 只有运行时、CLI、profile、应用配置、用户身份、必要 scope、资源 ACL、控制树和专用写验收全部完成时，状态才是 `ready`。

## 状态恢复

- `runtime_missing`、`cli_missing`、`cli_too_old`：复用或进入用户级私有运行环境，然后重新读取真实状态。
- `waiting_user`：链接和二维码必须已经对用户可见；用户完成操作后从当前未完成步骤继续。
- `waiting_admin`、`waiting_org_app_binding`、`permission_missing`、`resource_grant_required`：分别说明应用、用户、组织绑定还是具体资源权限缺口；批准后重新验证。
- `config_missing`、`config_invalid`：只补问无法推导的必要链接或选择，不重复索要已提供信息。
- `control_tree_missing`：转为一次性维护者初始化；普通使用者等待。
- `control_tree_ambiguous`、`write_result_uncertain`：先回读确认实际结果，停止写入并报告冲突或不确定状态。
- `write_verification_required`：展示具体验收动作，按已有授权执行并回读。
- `network_blocked`、`needs_escalation`：说明真实失败来源、影响和需要的宿主批准；短暂网络故障有限重试。
- `ready`：清除仅属于 setup 的临时挑战信息，恢复原任务；原任务上下文、用户已给链接和已完成选择保持不变。

## 秘密与恢复规则

不得把 appSecret、accessToken、refreshToken、device_code 或 user_code 写入普通状态、日志、文档、Git 或导出物。设备授权过期时重新发起相同 scope，不复用失效链接。账号、库配置或 profile 变化后，旧的 setup 结果失效，必须重新读取真实状态后只执行未完成步骤。
