# User Skill Hub Implementation Plan

**状态：** 已完成（2026-10-12）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a natural-language user-skill hub that validates, matches, overwrites, and shares lightweight skill packs through the plugin repository.

**Architecture:** Add a `user-skill-hub` Codex skill whose scripts own lightweight manifest validation, matching, formatting, and run-record conversion. Store user skills under `skills/user-skills/<skill_id>/` and add `skill-meta.json` to existing system skills so both layers share the same `supports` matching semantics. Extend the creative-run snapshot with `used_user_skills` while preserving the old `skills_resolution` field.

**Tech Stack:** Python 3.10+ standard library, frozen dataclasses, JSON, Markdown, `unittest`, existing `type_registry` / `stage_dag` / `creative_run_builder`, Git for repository publication.

**Spec:** `docs/superpowers/specs/2026-10-10-general-screenwriter-user-skill-hub-design.md`

## Global Constraints

- The user-facing interface is natural language only; internal scripts must not be presented as commands users must run.
- Every `supports.*_ids` array must be non-empty.
- `all` is the only wildcard and must not be mixed with concrete IDs.
- `manifest.json` must contain `user_name`; AI must ask for it when missing.
- Updating a skill overwrites its `manifest.json` and `SKILL.md`; no product version, audit, status, review, or rollback UI.
- User skills may contain only `manifest.json` and `SKILL.md`; executable files are forbidden.
- The shared repository is `https://github.com/QingpingYe/codex-general-screenwriter.git`.
- System rules, type-pack constraints, quality gates, confirmation gates, knowledge authority, and the plugin write policy outrank user skills.
- Each user-skill push mechanically increments the patch component of `plugins/general-screenwriter/.codex-plugin/plugin.json`; this is a release cursor, not skill versioning.

## Review Focus

- Empty or mixed wildcard support fields must fail validation; see Task 1 tests.
- Unknown stage/artifact IDs must fail validation; see Task 1 tests.
- Executable or extra files in a user skill directory must fail validation; see Task 1 tests.
- A missing `user_name` must fail validation, and the hub instructions must require asking the user; see Task 1 and Task 4 tests.
- Picturebook-only system skills must not become `all` merely for coverage; see Task 2 metadata tests.

---

### Task 1: Lightweight User Skill Manifest Validator

**Files:**
- Create: `plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py`
- Test: `plugins/general-screenwriter/tests/test_user_skill_hub.py`

**Interfaces:**
- Consumes: `type_registry.load_type_registry()` and `type_registry.resolve_type_pack(registry, medium_id)`.
- Produces:
  - `UserSkillHubError(ValueError)`
  - `UserSkill` dataclass with `directory: Path`, `manifest: dict[str, Any]`, and `content: str`
  - `validate_user_skill(skill_dir: Path, plugin_root: Path) -> UserSkill`
  - `validate_user_skill_tree(plugin_root: Path) -> tuple[UserSkill, ...]`
  - `SUPPORT_FIELDS: tuple[str, ...] = ("medium_ids", "genre_ids", "series_ids", "project_ids", "stage_ids", "artifact_ids")`

- [x] **Step 1: Write failing validator tests**

Create `test_user_skill_hub.py` with the project's existing `sys.path` pattern and cover:

```python
def valid_manifest(skill_id="test-skill", content="SKILL.md"):
    return {
        "schema_version": 1,
        "skill_id": skill_id,
        "title": "Test Skill",
        "description": "A valid test skill.",
        "user_name": "张三",
        "skill_type": "prompt_skill",
        "supports": {
            "medium_ids": ["shortdrama"],
            "genre_ids": ["all"],
            "series_ids": ["all"],
            "project_ids": ["all"],
            "stage_ids": ["episode_design"],
            "artifact_ids": ["episode_outline"],
        },
        "content": content,
        "updated_at": "2026-10-10T00:00:00+08:00",
    }
```

Tests must assert rejection of: missing fields, empty support arrays, `["all", "shortdrama"]`, `schema_version != 1`, unknown manifest fields, unknown support fields, invalid skill type, invalid ISO timestamp, `skill_id` different from directory name, `content` outside the skill directory, missing `SKILL.md`, empty `SKILL.md`, executable or extra files, duplicate `skill_id` in the tree, and stage/artifact IDs not present in every selected type pack.

Also assert that `medium_ids=["all"]` with `stage_ids=["all"]` and `artifact_ids=["all"]` passes when all other required fields are valid.

- [x] **Step 2: Run the new test file**

Run: `python plugins/general-screenwriter/tests/test_user_skill_hub.py -v`  
Expected: FAIL because `user_skill_hub` does not exist.

- [x] **Step 3: Implement manifest loading and validation**

Implement `UserSkill`, `validate_user_skill`, and `validate_user_skill_tree`. Use standard-library JSON, `datetime.fromisoformat`, `pathlib`, and `hashlib` if needed. Reject unknown fields and executable files. Validate concrete `stage_ids` and `artifact_ids` against the active type packs selected by `medium_ids`; `all` matches every active type pack.

- [x] **Step 4: Run validator tests**

Run: `python plugins/general-screenwriter/tests/test_user_skill_hub.py -v`  
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py plugins/general-screenwriter/tests/test_user_skill_hub.py
git commit -m "feat: validate lightweight user skill packs"
```

### Task 2: System Skill Metadata

**Files:**
- Modify: `plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py`
- Create: `plugins/general-screenwriter/skills/<skill-name>/skill-meta.json` for every existing skill listed below, except the `user-skills` data directory.
- Test: `plugins/general-screenwriter/tests/test_user_skill_hub.py`

**Interfaces:**
- Produces:
  - `SystemSkill` dataclass with `directory: Path` and `metadata: dict[str, Any]`
  - `validate_system_skill(skill_dir: Path, plugin_root: Path) -> SystemSkill`
  - `validate_system_skill_tree(plugin_root: Path) -> tuple[SystemSkill, ...]`

- [x] **Step 1: Add failing system-metadata tests**

Add tests that iterate every immediate child of `plugins/general-screenwriter/skills/` containing `SKILL.md` and assert:

1. `skill-meta.json` exists and validates;
2. `visibility` is `system`;
3. `skill_id` equals the directory name;
4. every `supports.*_ids` array is non-empty;
5. `general-screenwriter` uses `medium_ids=["all"]`;
6. `text-craft`, `craft-benchmark-check`, `staging-planner`, `image-prompt-architect`, `image-generate`, and `illustration-export` use `medium_ids=["picturebook"]`, not `all`;
7. all `skill-meta.json` files use the shared `supports` field names.

- [x] **Step 2: Run tests**

Run: `python plugins/general-screenwriter/tests/test_user_skill_hub.py -v`  
Expected: FAIL because system metadata is missing.

- [x] **Step 3: Implement system metadata validation**

Validate the same schema shape as user skills, but require `visibility == "system"` and omit `user_name` for system metadata. Reuse type-pack validation for concrete stage/artifact IDs.

- [x] **Step 4: Create metadata files**

Create `skill-meta.json` for:

```text
general-screenwriter, stage-orchestration, wiki-ingest, feishu-knowledge-store,
knowledge-loader, lexile-check, story-planning, pre_create-baseline,
in_create-baseline, post_create-baseline, pre_output-baseline,
quality-baseline, session-export, user-skill-hub
```

with:

```json
{
  "schema_version": 1,
  "skill_id": "<directory-name>",
  "visibility": "system",
  "supports": {
    "medium_ids": ["all"],
    "genre_ids": ["all"],
    "series_ids": ["all"],
    "project_ids": ["all"],
    "stage_ids": ["all"],
    "artifact_ids": ["all"]
  }
}
```

Create `picturebook`-scoped metadata for:

```text
text-craft, craft-benchmark-check, staging-planner,
image-prompt-architect, image-generate, illustration-export
```

using the same shape, except `medium_ids: ["picturebook"]`. Before marking `lexile-check` or another skill `all`, verify its method truly applies across media; if uncertain, leave it scoped and record the reason in the PR description.

- [x] **Step 5: Defer plugin contract registration**

Do not add `user-skill-hub` to `config/plugin-contract.json` in this task; its `SKILL.md` is created in Task 4, and adding the contract entry now would fail governance with a contract-only skill. Do not add ignored, repository-local skills such as `jev-decision-runtime`. Task 4 will add the contract entry and object:

```json
{
  "schema_version": "user-skill-hub-v1",
  "all_token": "all",
  "required_user_field": "user_name",
  "skill_types": ["prompt_skill", "checklist_skill", "reference_skill", "exporter_skill"],
  "allow_executable_files": false
}
```

- [x] **Step 6: Run tests and governance**

Run: `python plugins/general-screenwriter/tests/test_user_skill_hub.py -v; python scripts/governance_check.py; python scripts/package_check.py`  
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add plugins/general-screenwriter/skills plugins/general-screenwriter/tests/test_user_skill_hub.py
git commit -m "feat: add system skill scope metadata"
```

### Task 3: Matching and Natural-Language Injection

**Files:**
- Modify: `plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py`
- Test: `plugins/general-screenwriter/tests/test_user_skill_hub.py`

**Interfaces:**
- Consumes: `validate_user_skill_tree(plugin_root)`.
- Produces:
  - `load_matching_user_skills(plugin_root: Path, *, medium_id: str, genre_ids: Sequence[str] = (), series_id: str | None = None, project_id: str | None = None, stage_id: str | None = None, artifact_id: str | None = None) -> tuple[UserSkill, ...]`
  - `format_user_skills(skills: Sequence[UserSkill]) -> str`
  - `used_user_skill_record(skill: UserSkill) -> dict[str, str]`

- [x] **Step 1: Write failing matcher tests**

Using temporary skill packs, assert:

1. `all` matches every valid context;
2. a concrete medium only matches that medium;
3. concrete series/project only match the same ID or `None`-agnostic matching only when the manifest uses `all`;
4. stage and artifact mismatches reject the skill;
5. ordering is project match, series match, genre match, medium match, then `all`, with `title` as the final tie-breaker;
6. `format_user_skills` includes title, `user_name`, description, and content;
7. `used_user_skill_record` returns exactly `skill_id`, `title`, `user_name`, `updated_at`, and `content_hash`, with `content_hash` prefixed by `sha256:`.

- [x] **Step 2: Run matcher tests**

Run: `python plugins/general-screenwriter/tests/test_user_skill_hub.py -v`  
Expected: FAIL because the three functions are absent.

- [x] **Step 3: Implement matching, formatting, and run-record conversion**

Compute specificity as project, series, genre, medium, then zero for `all`; sort descending and tie-break by `title`. `format_user_skills` must be plain text suitable for injection. Hash the exact bytes of `SKILL.md`.

- [x] **Step 4: Run matcher tests**

Run: `python plugins/general-screenwriter/tests/test_user_skill_hub.py -v`  
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add plugins/general-screenwriter/skills/user-skill-hub/scripts/user_skill_hub.py plugins/general-screenwriter/tests/test_user_skill_hub.py
git commit -m "feat: match user skills by creative context"
```

### Task 4: Hub Skill and First Shared Skill

**Files:**
- Create: `plugins/general-screenwriter/skills/user-skill-hub/SKILL.md`
- Create: `plugins/general-screenwriter/skills/user-skills/novel-to-shortdrama-adaptation/manifest.json`
- Create: `plugins/general-screenwriter/skills/user-skills/novel-to-shortdrama-adaptation/SKILL.md`
- Modify: `plugins/general-screenwriter/config/plugin-contract.json`
- Modify: `plugins/general-screenwriter/.codex-plugin/plugin.json`
- Test: `plugins/general-screenwriter/tests/test_user_skill_hub.py`

**Interfaces:**
- Consumes: `validate_user_skill_tree`, `validate_system_skill_tree`, and `load_matching_user_skills`.
- Produces: a real shared skill with `skill_id="novel-to-shortdrama-adaptation"`, `user_name="QingpingYe"`, `medium_ids=["shortdrama"]`, `series_ids=["all"]`, `project_ids=["all"]`, and a hub skill instructing the natural-language workflow.

- [x] **Step 1: Write failing hub and sample tests**

Add tests asserting:

1. the real user-skill tree validates;
2. the sample manifest has `user_name="QingpingYe"` and every support array non-empty;
3. `user-skill-hub/SKILL.md` explicitly requires asking for `user_name` before creating/importing;
4. it explicitly requires overwrite and push confirmation;
5. it forbids exposing internal commands as the user interface;
6. it describes the GitHub repository and mechanical plugin patch bump;
7. `plugin-contract.json.skills` contains `user-skill-hub` and its `user_skill_hub` object declares `schema_version="user-skill-hub-v1"`, `all_token="all"`, `required_user_field="user_name"`, `skill_types=["prompt_skill","checklist_skill","reference_skill","exporter_skill"]`, and `allow_executable_files=false`.

- [x] **Step 2: Run tests**

Run: `python plugins/general-screenwriter/tests/test_user_skill_hub.py -v`  
Expected: FAIL because the hub skill and sample pack are absent.

- [x] **Step 3: Implement the hub workflow document**

Write `SKILL.md` with three modes: create, import/adapt, and update/overwrite. Define the required questions, preview format, overwrite warning, validation step, patch-bump step, Git pull/rebase behavior, push confirmation, and failure handling. Do not require the screenwriter to run commands.

- [x] **Step 4: Create the sample skill**

Write the manifest using `skill_type="prompt_skill"` and canonical shortdrama stages `brief_gate`, `knowledge_load`, `episode_design`, `hook_design`, `beat_design`, `scene_design`, `episode_script_delegate`, `hook_check`, `pacing_check`, `dialogue_check`, and `quality_gate`. Declare artifacts `episode_outline`, `hook_sheet`, `beat_sheet`, `scene_table`, and `episode_script`. Write `SKILL.md` as a practical novel-to-shortdrama adaptation methodology with input, method, episode/hook structure, output format, and checkpoints.

- [x] **Step 5: Register the hub contract and bump the plugin release cursor**

Add `user-skill-hub` to `config/plugin-contract.json.skills` and add the contract object declared above. Do not add ignored, repository-local skills such as `jev-decision-runtime`.

Increment the patch component of `version` in `.codex-plugin/plugin.json`.

- [x] **Step 6: Run validation**

Run: `python plugins/general-screenwriter/tests/test_user_skill_hub.py -v; python scripts/governance_check.py; python scripts/package_check.py`  
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add plugins/general-screenwriter/skills/user-skill-hub/SKILL.md plugins/general-screenwriter/skills/user-skills plugins/general-screenwriter/config/plugin-contract.json plugins/general-screenwriter/.codex-plugin/plugin.json plugins/general-screenwriter/tests/test_user_skill_hub.py
git commit -m "feat: add user skill hub and shortdrama sample"
```

### Task 5: Run Snapshot Integration

**Files:**
- Modify: `plugins/general-screenwriter/scripts/stage_dag.py:127-189`
- Modify: `plugins/general-screenwriter/scripts/stage_dag.py:195-230`
- Modify: `plugins/general-screenwriter/scripts/stage_dag.py:1530-1565`
- Modify: `plugins/general-screenwriter/scripts/creative_run_builder.py`
- Test: `plugins/general-screenwriter/tests/test_user_skill_run_integration.py`

**Interfaces:**
- Consumes: `used_user_skill_record(skill: UserSkill) -> dict[str, str]`.
- Produces:
  - `CreativeRunRequest.used_user_skills: list[dict[str, str]] | None = None`
  - `build_resolution_snapshot(..., used_user_skills: list[dict[str, str]] | None = None)`
  - snapshot field `used_user_skills` with entries containing exactly `skill_id`, `title`, `user_name`, `updated_at`, and `content_hash`

- [x] **Step 1: Write failing integration tests**

Create `test_user_skill_run_integration.py`. Assert that a new typed run with one valid record contains the record under `resolution_snapshot.used_user_skills`, dispatch-plan and task-envelope copies are isolated deep copies, a legacy manifest without the field remains valid and is not modified, and an invalid record (missing `user_name`, unknown extra field, or non-SHA-256 `content_hash`) fails validation.

- [x] **Step 2: Run integration tests**

Run: `python plugins/general-screenwriter/tests/test_user_skill_run_integration.py -v`  
Expected: FAIL because the field is not accepted.

- [x] **Step 3: Extend snapshot validation and builder**

Add `used_user_skills` to the allowed snapshot fields, validate exact entry fields, and carry deep copies through `CreativeRunRequest`, `_snapshot`, and revision construction. Preserve `skills_resolution` unchanged for old manifests.

- [x] **Step 4: Run related tests**

Run: `python plugins/general-screenwriter/tests/test_user_skill_run_integration.py -v; python plugins/general-screenwriter/tests/test_creative_run_builder.py -v; python plugins/general-screenwriter/tests/test_picturebook_migration_matrix.py -v`  
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add plugins/general-screenwriter/scripts/stage_dag.py plugins/general-screenwriter/scripts/creative_run_builder.py plugins/general-screenwriter/tests/test_user_skill_run_integration.py
git commit -m "feat: record used user skills in run snapshots"
```

### Task 6: Documentation and Release Gate

**Files:**
- Modify: `README.md`
- Modify: `docs/CHANGELOG.md`
- Test: whole offline suite

**Interfaces:**
- Consumes: all implemented hub behavior.
- Produces: user-facing documentation and a passing release gate.

- [x] **Step 1: Add failing contract/doc assertions**

Extend `test_user_skill_hub.py` to assert `plugin-contract.json` declares `user-skill-hub` and `README.md` contains a short Chinese explanation that users can add skills through natural conversation and that applicable dimensions use `all` instead of empty arrays.

- [x] **Step 2: Run tests**

Run: `python plugins/general-screenwriter/tests/test_user_skill_hub.py -v`  
Expected: FAIL until README is updated.

- [x] **Step 3: Update user-facing docs**

Document the natural-language flow, required user name, `all` rule, overwrite confirmation, plugin-market update behavior, and system-vs-user skill boundary. Update `docs/CHANGELOG.md`.

- [x] **Step 4: Run the full offline regression**

Run: `python .\scripts\run_plugin_tests.py`  
Expected: PASS with no failed commands.

- [x] **Step 5: Run release checks**

Run: `python .\scripts\governance_check.py; python .\scripts\package_check.py; python .\scripts\release_gate.py`  
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add README.md docs/CHANGELOG.md plugins/general-screenwriter/tests/test_user_skill_hub.py
git commit -m "docs: document natural language user skill hub"
```

## Self-Review

**Spec coverage:** Tasks 1-4 cover manifest schema, `all`, user name, validation, system metadata, matching, hub workflow, overwrite, sample skill, and release cursor. Task 5 covers run traceability. Task 6 covers documentation and release checks. Push behavior is specified as a skill workflow in Task 4 because it is user-authored through Codex rather than a standalone executable product feature.

**Type consistency:** `UserSkill`, `SystemSkill`, `load_matching_user_skills`, `format_user_skills`, `used_user_skill_record`, and `used_user_skills` are used consistently across tasks.

**Proportion:** The plan defines exact interfaces and tests without transcribing implementation bodies.

