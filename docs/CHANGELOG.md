# Changelog

## [Unreleased]

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
