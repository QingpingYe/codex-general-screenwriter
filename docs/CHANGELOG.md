# Changelog

## [Unreleased]

## [0.8.0] - 2026-10-26

### Added

- Natural-language first-use setup for Feishu-related work: the AI checks runtime, CLI, named profile, application, authorization, links, resource ACL, shared target ownership, and write verification internally, then resumes the original task.
- User-level private Lark CLI installation, compatible higher-version reuse, stable minimum-version checks, no PATH mutation, and no global skill installation.
- Split setup states for `resource_grant_required`, `waiting_initializer`, `write_verification_required`, and `write_result_uncertain`, with readback-before-retry recovery behavior.
- Release gates `first_use_contract` and `setup_docs_contract` before offline regression, plus explicit live Windows/Feishu acceptance requirements that remain unexecuted until a maintainer records evidence.

### Changed

- Marketplace activation is `ON_USE`; Feishu authentication and setup begin only when a Feishu-dependent request needs them.
- User-facing README follows natural-language interaction only; maintainer commands remain in maintenance documentation.
- 插件版本升至 0.8.0。

### Compatibility

- Existing compatible CLIs and named profiles are reused without overwriting unrelated profiles or credentials. Normal users do not run Feishu commands, prepare JSON, or restart the session.
- Live Windows VM, two-user, higher-version CLI, interrupted-recovery, and credential-scan gates are documented as requiring execution and are not claimed as passed by offline tests.

## [0.7.0] - 2026-10-12

### Added

- 短剧与长篇连续剧的内容级确定性校验：新增共享剧本解析层，短剧 8 项与长篇 9 项检查全部从剧本内容（场景、台词、节拍、台账）和显式引用产物推导，引用缺失时失败关闭。
- 类型专属导出器：短剧集稿、短剧制作清单、长篇集稿、长篇季包与结构化 JSON；纯内存渲染加原子写入，目标已存在默认拒绝，失败零残留。
- 代表性创作工作流：短剧与长篇样例真实执行校验器并聚合成质量报告，附带内存导出预览；绘本样例保持声明式 skill 层评估。
- `scripts/script_content.py`、`scripts/export_run.py`、`scripts/export_cli.py`、`scripts/sample_workflow.py` 及对应回归测试与契约块 `media-content-completion-v1`。

### Changed

- 短剧/长篇 type pack 质量规则接线到 `shortdrama-checks` / `tv-longform-checks`，并声明类型专属导出器与产物接线。
- 长篇连续性台账改为一等引用产物（`continuity_ledger`，含 `linked_artifacts` / `entries` / `conflicts` / `open_foreshadows`），集稿只保留 `continuity_ledger_ref`。
- 插件版本升至 0.7.0。

### Compatibility

- 旧绘本入口、旧 run manifest、旧插画流程与确认门语义不变；默认写盘策略仍为对话输出，未显式导出不写文件。

## [0.6.3] - 2026-10-12

### Changed

- `user-skill-hub` no longer commits or pushes user skills to the plugin repository and no longer bumps the plugin version for them; user skills live in the local plugin checkout only.

## [0.6.2] - 2026-10-12

### Added

- Atomic `install_user_skill_pack` (staged validation, same-volume swap, rollback) with an internal `user_skill_hub.py` CLI and a staged-write hub workflow.
- `scripts/user_skill_gate.py` tree gate wired into `run_plugin_tests` and the release gate for user and system skill trees.
- Deterministic `config/skill-index.json` built by `scripts/build_skill_index.py`, with a governance drift check and an entry-skill medium routing step.

### Changed

- Unified symlink/junction rejection across single-pack, user-tree, system-tree, and pack-inner validation; system skill trees now reject directories that have `skill-meta.json` but no `SKILL.md`.
- `user_skill_hub` contract schema is now `user-skill-hub-v2` with field `wildcard_value`; the `package_check` credential allowlist was removed.
- Release gate steps are now `user_skill_trees`, `user_skill_hub`, and `user_skill_runtime` instead of the legacy `skill_registry` step.

### Removed

- Legacy `user-skill-contract-v1` registry modules (`scripts/user_skill_contract.py`, `scripts/user_skill_resolver.py`), the `config/user-skills.example.json` template, and their tests. Historical `resolution_snapshot.skills` fields remain readable; `config/user-skills.json` is no longer read by any code path.

## [0.6.1] - 2026-10-10

### Added

- Natural-language `user-skill-hub` workflow for lightweight user skill packs with required `user_name`, mandatory nonempty support arrays, `all` as the sole wildcard, explicit overwrite confirmation, and mechanical patch bump for plugin-market updates.
- System skill scope metadata and user skill run traceability through `used_user_skills`.
- Sample user skill for novel-to-shortdrama adaptation.

## [0.6.0] - 2026-10-10

### Added

- Executable picturebook migration compatibility matrix (legacy entry, run/task schemas, artifacts, knowledge keys, planned-media gates).
- Cross-media representative pass/fail samples with type-pack rule drift checks.
- shortdrama and tv_longform minimal type packs (artifacts, stage chains, structural checks) activated after sample coverage.
- Fail-closed exporter contract with explicit destination and overwrite policy.
- User skill contract, scope/stage resolution, conflict audit, and isolated dispatch snapshots.
- Read-only migration report and unified release gate (nine ordered checks, stop-on-first-failure).
- Codex-native picture-book editorial workflow and baseline slots.
- Feishu authoritative knowledge synchronization and retrieval.
- Craft benchmark, project red lines, Wiki lint, and optional Lexile gates.
- Gated illustration workflow with structured prompt payloads.
- Self-contained HTML preview and illustration asset registry.
- Workspace-first Feishu config discovery, config status, and read-only authority CLI.
- Portable Feishu config discovery for project subdirectories, user directories, and shared plugin distribution.
- Typed creative context and a type-pack registry for picturebook-compatible screenwriting workflows.

- Type-pack contract v1 separates core artifacts/stages from the optional picturebook illustration workflow; planned packs, when present, remain read-only and cannot dispatch.
- New optional run snapshots record type-pack, target artifact, delivery form, and workflow selection while retaining old manifest/revision compatibility.
- Knowledge loading now supports optional scope metadata and a task-to-global scope chain while keeping schema v1 pages readable.
- General creative DAG and quality gate v1: full v1 packs declare runtime stage semantics; explicit-context runs are built from type packs; structured quality reports distinguish hard blockers from user-confirmation risks; dispatch snapshots enforce declared quality rules.

### Changed

- KB-AI 同步改为内容权威：候选正文与当前页正文比较时只忽略纯排版标记，正文变化即条件覆盖目标页；成功覆盖人工编辑时在报告 `overwritten_human_edits` 中披露逻辑键。退役人工优先三方合并、冲突队列读写与 `queued`/`third_party_edits` 报告字段；`source_edit_times` 作为可选兼容字段接入索引与页尾；`needs_review` 改为可重试的安全状态。共享兼容协议 1.4.0 已于 2026-09-30 由 Codex/WorkBuddy 双方确认。
- Split WorkBuddy reference material out of the Codex plugin runtime.
- Stage workflows now represent approval and revision as exclusive outcomes.
- Revision rounds create new runs and rerun preflight, collision, and QA checks.
- v1 run manifests require explicit migration.
- Dispatch plans and task envelopes carry validated creative context snapshots while legacy picturebook runs remain readable.
- Renamed the plugin package and entry skill from picturebook-only `picturebook-screenwriter` to `general-screenwriter`; legacy configuration paths and old run lead-owner IDs remain read-compatible.
- Film is no longer registered as a supported medium; shortdrama and tv_longform are active minimal type packs.

- Type-pack loading rejects empty active v1 packs, invalid artifact/stage links, and workflows that would block core completion.
- Knowledge schema v2 scope resolution, compatible page metadata, and dependency records are implemented; full v2 write migration remains a follow-up.

### Fixed

- Dispatch and public DAG scheduling reject unknown or planned media, stale type-pack snapshots, input-only targets, and core/illustration stage mixing; optional illustration requires explicit script-source evidence.
- Artifact/stage alias collisions are rejected across contract categories.

- Knowledge loading now rejects page revisions behind the remote index, marks page-ahead evidence as `index_synced=false`, and prevents unsynced reads from replacing the last confirmed cache.
- Terminal stage-run validation now evaluates run-level status and outcome without shadowing by stage fields.
