# Knowledge Scope Inheritance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add read-only knowledge scope-chain resolution and schema v2 metadata compatibility without changing v1 writes.

**Architecture:** Introduce a small `scope_model.py` for `ScopeRef` and scope-chain expansion. Add `scope_pages.py` to parse optional `## knowledge-scope` JSON envelopes embedded in page bodies. Extend `KnowledgeQuery`, `KnowledgeEvidence`, `KnowledgeLoader`, and dependency locking to carry scope metadata while preserving legacy v1 behavior. No remote writes or migration.

**Tech Stack:** Python 3.10+, stdlib only, unittest, existing knowledge-loader/store code.

**Spec:** `docs/superpowers/specs/2026-10-09-general-screenwriter-knowledge-scope-design.md`

## Global Constraints

- Read-only implementation; no remote writes, no migration, no file output.
- Existing v1 pages and v1 key behavior must continue to work unchanged.
- Schema v2 metadata is optional and read-only; absence does not cause failure.
- Scope chain order is `task → scene → episode → season → project → series → genre → medium → global`.
- Conflict pages are never silently merged.
- Dependencies must retain v1 records and add scope information only as new optional fields.
- No new third-party dependencies.

## Review Focus

- A page without scope metadata must remain readable as v1.
- A malformed scope envelope must be rejected without making the whole bundle fail.
- A scope envelope claiming a scope outside the query chain must not load.
- Conflict pages must be reported, not silently merged.
- Dependency records must remain readable for old artifacts.

---

### Task 1: ScopeRef and Scope Chain

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/scope_model.py`
- Test: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_scope_model.py`

**Interfaces:**
- Produces:
  - `ScopeRef`
  - `ScopeChainNode`
  - `expand_scope_chain(scope_ref: ScopeRef) -> tuple[ScopeChainNode, ...]`
  - `scope_matches(chain, node) -> bool`

- [x] **Step 1: Add failing model tests**

Cover:
  - task-to-global expansion order;
  - skipping absent levels;
  - medium/genre/project/series matching;
  - rejecting empty or invalid scope types.

- [x] **Step 2: Run tests to verify failure**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_scope_model.py`

Expected: FAIL because `scope_model` does not exist.

- [x] **Step 3: Implement minimal scope model**

Implement immutable dataclasses and deterministic expansion.

- [x] **Step 4: Run tests**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_scope_model.py`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/scope_model.py plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_scope_model.py
git commit -m "feat: add knowledge scope chain model"
```

### Task 2: Read-Only Scope Metadata

**Files:**
- Create: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/scope_pages.py`
- Test: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_scope_pages.py`

**Interfaces:**
- Produces:
  - `ScopeEnvelope`
  - `parse_scope_envelope(body: str) -> ScopeEnvelope | None`

- [x] **Step 1: Add failing parser tests**

Cover:
  - valid `## knowledge-scope` JSON envelope;
  - missing envelope returns `None`;
  - malformed JSON raises `ScopeEnvelopeError`;
  - unknown or invalid fields raise `ScopeEnvelopeError`;
  - authority and scope_type are validated.

- [x] **Step 2: Run tests to verify failure**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_scope_pages.py`

Expected: FAIL because `scope_pages` does not exist.

- [x] **Step 3: Implement minimal parser**

Parse exactly one optional `## knowledge-scope` JSON block. Do not modify the page body.

- [x] **Step 4: Run tests**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_scope_pages.py`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/scope_pages.py plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_scope_pages.py
git commit -m "feat: add knowledge scope metadata parser"
```

### Task 3: Loader Compatibility

**Files:**
- Modify: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/load_knowledge.py`
- Test: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_load_knowledge.py`

**Interfaces:**
- Consumes: `ScopeRef`, `expand_scope_chain`, `parse_scope_envelope`
- Produces:
  - `KnowledgeQuery.scope_ref: ScopeRef | None`
  - `KnowledgeEvidence.scope: ScopeEnvelope | None`
  - `KnowledgeEvidence.scope_chain: tuple[ScopeChainNode, ...]`
  - `KnowledgeEvidenceBundle.conflicts: tuple[ConflictReport, ...]`

- [x] **Step 1: Add failing loader tests**

Cover:
  - legacy v1 behavior unchanged when `scope_ref=None`;
  - v1 page with no scope metadata remains readable;
  - v2 page outside scope chain is excluded;
  - conflict pages produce conflict reports instead of merging;
  - malformed scope page yields warning and is skipped.

- [x] **Step 2: Run tests to verify failure**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_load_knowledge.py`

Expected: FAIL on missing fields and behavior.

- [x] **Step 3: Implement optional scope-aware loading**

Keep existing key filtering as the base path. Apply scope filtering only when `scope_ref` is present. Treat pages without scope metadata as v1-compatible.

- [x] **Step 4: Run loader tests**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_load_knowledge.py`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/load_knowledge.py plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_load_knowledge.py
git commit -m "feat: add scope-aware knowledge loading"
```

### Task 4: Dependency Snapshot

**Files:**
- Modify: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/dependencies.py`
- Test: `plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_dependencies.py`

**Interfaces:**
- Consumes: `ScopeChainNode`
- Produces:
  - `DependencyRecord.scope_chain: tuple[Mapping[str, Any], ...]`
  - `DependencyRecord.knowledge_schema: str`

- [x] **Step 1: Add failing dependency tests**

Cover:
  - old record without scope fields still parses;
  - new record with scope fields parses;
  - dependency record preserves v1 fields.

- [x] **Step 2: Run tests to verify failure**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_dependencies.py`

Expected: FAIL because new fields do not exist.

- [x] **Step 3: Implement additive dependency fields**

Keep `built_against` shape backward-compatible by making the two new fields optional.

- [x] **Step 4: Run dependency tests**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_dependencies.py`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/dependencies.py plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_dependencies.py
git commit -m "feat: record knowledge scope dependencies"
```

### Task 5: Regression Check

**Files:**
- No source changes.

- [x] **Step 1: Run knowledge-loader tests**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_load_knowledge.py`

Expected: PASS

- [x] **Step 2: Run dependency tests**

Run: `python plugins/picturebook-screenwriter/skills/knowledge-loader/scripts/test_dependencies.py`

Expected: PASS

- [x] **Step 3: Run full offline regression**

Run: `python scripts/run_plugin_tests.py`

Expected: exit 0

- [x] **Step 4: Commit any test or doc fixes**

```bash
git add docs/CHANGELOG.md
git commit -m "docs: note knowledge scope inheritance"
```

## Self-Review

- **Spec coverage:** Scope chain, read-only v2 metadata, loader compatibility, conflicts, dependency snapshot.
- **Step scan:** Each step is one action with a checkable result.
- **Type consistency:** Scope names and signatures are stable across tasks.
- **Review Focus:** Covered by Tasks 1-4.
- **Proportion:** Plan remains smaller than the implementation surface.
