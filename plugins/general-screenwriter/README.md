# General Screenwriter Workshop for Codex and Claude Code

这是原「绘本编剧工坊」升级后的通用编剧创作插件，同时支持 Codex 与 Claude Code 两种宿主，不依赖 WorkBuddy 团队运行时。当前包名和入口 Skill 都是 `general-screenwriter`；旧插件名不再是当前标识。旧配置路径、旧 run manifest 和旧 lead owner 保留兼容读取。当前支持通用创作内核、类型包工作流、飞书权威知识库、量化质量门、文字工艺、分镜规划、结构化插画提示词、显式确认后的图片生成和插画导出预览。

两个宿主共享同一份 `skills/`，各自读取自己的清单：Codex 使用 `.codex-plugin/plugin.json` 与 `.agents/plugins/marketplace.json`，Claude Code 使用 `.claude-plugin/plugin.json` 与本仓库根 `.claude-plugin/marketplace.json`。技能正文只使用中性引用（如 `general-screenwriter:setup`），不包含任何单一宿主的触发语法。

首次使用时直接说“帮我初始化编剧插件”；涉及飞书知识库的请求会先检查 setup 状态，由 AI 在内部补齐运行时、账户、授权、链接配置和写入验收，完成后继续原任务。正常流程不需要用户执行飞书命令、手工准备配置文件或重开会话。

## 已支持

- 通用编剧创作内核：类型解析、阶段编排、确认门、修订轮次、质量门和解析快照
- 绘本主编式入口工作流：意图识别、简报门、角色切换、确认门、版本化落盘
- 可选阶段 DAG：宿主多 Agent 工具可用时派发子 Agent；不可用时顺序降级
- `text-craft`：儿童绘本文本创作方法论（picturebook 类型包使用）
- `craft-benchmark-check`：picturebook 页脚本的十五项文字工艺指标量化自测
- `staging-planner`：picturebook 跨页分镜站位与空间一致性规划
- `image-prompt-architect`：picturebook 结构化插画提示词；只输出 JSON，不生成图片
- `image-generate`：仅在用户明确确认后调用图片 API
- `illustration-export`：资产登记、本地 HTML 预览与显式图片内嵌
- `session-export`：仅在用户明确要求时导出会话证据，且必须使用用户提供的绝对输出目录
- `knowledge-loader`：只读检索多人协作飞书权威知识库
- `feishu-knowledge-store`：正文内容权威、写后回读与远端租约
- setup：首次使用自检、私有运行时、named profile、设备授权、链接配置、共享目标初始化与写验收
- 通用创作上下文基础：注册媒介类型、题材与系列/项目标识，并兼容旧绘本运行记录
- 通用创作 DAG 与质量门 v1：类型包解析核心阶段/负责人/门，快照携带质量规则，结构化报告区分阻断与确认风险
- 类型包创作工作流：`picturebook` 为完整路径，`shortdrama` 与 `tv_longform` 为最小可用结构化路径
- 内容级校验：短剧（开场/转折/结尾钩子、节奏密度、冲突闭环、时长、人物状态、格式）与长篇连续剧（季弧线、集功能、时间线、伏笔与回收、场次连接、人物状态、系列约束、连续性台账）的确定性检查，全部从剧本内容与显式引用产物推导
- 类型专属导出器：短剧集稿、短剧制作清单、长篇集稿、长篇季包与结构化 JSON；显式参数、失败关闭、原子写入
- 代表性创作工作流：短剧与长篇各有真实执行校验器的通过/失败样例，直接聚合成质量报告；绘本样例保持声明式 skill 层评估
- `lexile-check`：仅使用用户提供的实测结果

## 类型契约边界

三个媒介类型包（picturebook、shortdrama、tv_longform）当前均可通过类型包派发。绘本核心产物为 positioning、topic_plan、worldview、characters、outline、script；其中定位信息作为简报输入。短剧与长篇连续剧声明各自的核心产物、阶段链、内容级质量校验器与类型专属导出器，经统一创作内核派发；质量规则失败按 `hard_block` / `require_user_confirmation` / `advisory` 语义进入报告，导出必须在用户显式给出输出目录与文件名后执行。

插画是独立可选插画工作流，输入要求已批准脚本；资产清单、结构化提示、图片与 HTML 预览都不属于文字核心阶段，也不阻塞文字 run 的确认或完成。旧绘本入口、run manifest 和产物标识继续兼容读取。显式上下文派发必须匹配当前类型包版本；历史快照只读。插画派发前需记录获批脚本或用户明确提供脚本的来源声明，不能把声明当作用户确认的替代。知识库 schema v2 的作用域继承与只读权威解析已接入；v2 写入和完整数据迁移仍是后续专项。

绘本迁移状态由可执行回归矩阵锁定：文字核心与插画工作流均为 migrated，知识适配层为 v1_compatible；旧入口、旧 run/任务 schema、旧产物标识与旧三段知识 key 全部可读。

质量门 v1 是声明与报告契约：`hard_block` 失败阻断确认，`require_user_confirmation` 失败必须用户明确接受，`advisory` 只提示，`informational` 仅记录。报告本身不执行验证器、不写文件，也不替代确认门。

## 暂不支持

- WorkBuddy TeamCreate / SendMessage / 持久多 Agent 团队运行时
- 原生 hooks 与平台级硬约束
- 未确认的默认图片 API 调用
- 用户技能的可视化管理界面（当前仅支持自然语言管理）

运行时强制、脚本校验与提示词约束的边界见 [ENFORCEMENT.md](https://github.com/QingpingYe/codex-general-screenwriter/blob/main/docs/ENFORCEMENT.md)。

## 操作指南

安装、使用、配置、同步和验证流程统一维护在仓库根 README。本文件保留插件能力与边界说明；以下链接在独立安装的插件包中同样可用。

Claude Code 安装入口：`/plugin install general-screenwriter@general-screenwriter-git`；Codex 安装入口见下方链接。

- [安装插件](https://github.com/QingpingYe/codex-general-screenwriter/blob/main/README.md#add-the-plugin)
- [使用插件](https://github.com/QingpingYe/codex-general-screenwriter/blob/main/README.md#use-the-plugin)
- [飞书知识库准备](https://github.com/QingpingYe/codex-general-screenwriter/blob/main/README.md#feishu-knowledge-setup)
- [配置发现规则](https://github.com/QingpingYe/codex-general-screenwriter/blob/main/README.md#configuration-discovery)
- [飞书维护与诊断命令](https://github.com/QingpingYe/codex-general-screenwriter/blob/main/README.md#feishu-runtime-commands)
- [本地验证与发布](https://github.com/QingpingYe/codex-general-screenwriter/blob/main/README.md#verify-locally)
