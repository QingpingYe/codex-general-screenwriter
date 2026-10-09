# Picture Book Screenwriter for Codex

这是「绘本编剧工坊」的 Codex 原生插件，不依赖 WorkBuddy 团队运行时。当前支持编辑式入口、飞书权威知识库、文字工艺、量化自检、分镜规划、结构化插画提示词、显式确认后的图片生成和插画导出预览。

## 已支持

- 主编式入口工作流：意图识别、简报门、角色切换、确认门、版本化落盘
- 可选阶段 DAG：Codex 多 Agent 工具可用时派发子 Agent；不可用时顺序降级
- `text-craft`：儿童绘本文本创作方法论
- `craft-benchmark-check`：十五项文字工艺指标量化自测
- `staging-planner`：跨页分镜站位与空间一致性规划
- `image-prompt-architect`：结构化插画提示词；只输出 JSON，不生成图片
- `image-generate`：仅在用户明确确认后调用图片 API
- `illustration-export`：资产登记、本地 HTML 预览与显式图片内嵌
- `session-export`：仅在用户明确要求时导出会话证据，且必须使用用户提供的绝对输出目录
- `knowledge-loader`：只读检索多人协作飞书权威知识库
- `feishu-knowledge-store`：正文内容权威、写后回读与远端租约
- 通用创作上下文基础：注册媒介类型、题材与系列/项目标识，并兼容旧绘本运行记录
- `lexile-check`：仅使用用户提供的实测结果

## 暂不支持

- WorkBuddy TeamCreate / SendMessage / 持久多 Agent 团队运行时
- 原生 hooks 与平台级硬约束
- 未确认的默认图片 API 调用

运行时强制、脚本校验与提示词约束的边界见 [ENFORCEMENT.md](https://github.com/QingpingYe/codex-picturebook-agent/blob/main/docs/ENFORCEMENT.md)。

## 操作指南

安装、使用、配置、同步和验证流程统一维护在仓库根 README。本文件保留插件能力与边界说明；以下链接在独立安装的插件包中同样可用。

- [安装插件](https://github.com/QingpingYe/codex-picturebook-agent/blob/main/README.md#add-the-plugin)
- [使用插件](https://github.com/QingpingYe/codex-picturebook-agent/blob/main/README.md#use-the-plugin)
- [飞书知识库准备](https://github.com/QingpingYe/codex-picturebook-agent/blob/main/README.md#feishu-knowledge-setup)
- [配置发现规则](https://github.com/QingpingYe/codex-picturebook-agent/blob/main/README.md#configuration-discovery)
- [飞书操作命令](https://github.com/QingpingYe/codex-picturebook-agent/blob/main/README.md#feishu-runtime-commands)
- [本地验证与发布](https://github.com/QingpingYe/codex-picturebook-agent/blob/main/README.md#verify-locally)
