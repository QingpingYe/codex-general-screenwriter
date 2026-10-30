# Enforcement Levels

`plugin-contract.json` is a public plugin boundary and validation input. It is
not loaded by the runtime execution path and does not act as a sandbox.

The levels below describe where a guarantee actually lives.

- `runtime_required`: execution rejects or blocks an invalid operation.
- `script_checked`: a script validates required inputs, but cannot prove user
  intent or prevent an authorized caller from supplying valid values.
- `prompt_only`: behavior depends on the model following Skill instructions;
  there is no host-level prevention.

A `runtime_required` level only applies when its owner script is in the execution path.
Whether a Skill chooses to invoke that script remains prompt-driven unless
host policy enforces the call.

## Matrix

| Gate | Level | Enforcement point | Consequence |
|---|---|---|---|
| Stage DAG schema, transitions, and terminal state | `runtime_required` | `plugins/general-screenwriter/scripts/stage_dag.py` | Invalid manifests and transitions fail closed. |
| Type pack execution boundary and snapshots | `runtime_required` | `plugins/general-screenwriter/scripts/stage_dag.py`, `plugins/general-screenwriter/scripts/stage_dag_codex.py` | Unknown or planned media, stale snapshots, invalid targets/workflows, and missing workflow-input evidence fail before dispatch. |
| Lead-owned confirmation gates are not dispatched | `runtime_required` | `plugins/general-screenwriter/scripts/stage_dag_codex.py` | Dispatch planning waits instead of assigning a lead-owned gate. |
| Agent output path scope | `runtime_required` | `plugins/general-screenwriter/scripts/stage_dag.py` | Traversal and paths outside the agent scope are rejected. |
| Feishu revision-protected writes | `runtime_required` | `skills/feishu-knowledge-store/scripts/publisher.py` | Writes use the observed revision and verify readback. |
| Self-contained HTML image embedding and size limit | `runtime_required` | `skills/illustration-export/scripts/embed_images.py` | Missing images or over-limit output fail with a non-zero result. |
| Image output directory, size, quality, and API key source | `script_checked` | `skills/image-generate/generate.js` | Missing arguments or key sources fail before generation. |
| HTML build and session export output arguments | `script_checked` | `skills/illustration-export/scripts/build_html.py`, `skills/session-export/scripts/export_session.py` | Callers must provide the expected inputs before the scripts write files. |
| Export request and destination policy | `runtime_required` | `plugins/general-screenwriter/scripts/exporter_contract.py`, `plugins/general-screenwriter/skills/illustration-export/scripts/build_html.py` | Missing inputs/params, unsupported formats, missing destinations, and default overwrite are rejected. |
| Explicit user confirmation before image generation | `prompt_only` | Entry and `image-generate` Skill instructions | A caller that invokes the script directly is not blocked by a consent token. |
| Confirmation gate and default dialog-only write policy | `prompt_only` | Entry Skill instructions | Scripts cannot prove that the user approved a write. |
| Lark CLI minimum stable version and capabilities | `runtime_required` | `skills/feishu-knowledge-store/scripts/lark_cli_contract.py`, `lark_cli_context.py`, `lark_cli.py` | Lower, unstable, unparseable, or capability-incomplete CLIs fail closed; compatible higher versions are not rejected by an allowlist. |
| User-level private Lark CLI installation | `runtime_required` | `skills/feishu-knowledge-store/scripts/lark_runtime.py`, `lark_cli_bootstrap.py` | Automatic installation targets only the user-private runtime and does not mutate PATH or install global skills. |
| Named profile and command binding | `runtime_required` | `skills/feishu-knowledge-store/scripts/lark_cli_context.py`, `lark_profile.py`, `lark_cli.py` | The selected profile is resolved from the explicit flag, the documented environment binding, or the shared setup default, then forwarded to every CLI call on both setup and operational paths; duplicate local entries fail closed as `profile_ambiguous`; profile/app creation remains an explicit two-phase user-consent flow. |
| Split first-use setup state and original-task resume | `runtime_required` | `skills/setup/scripts/setup_cli.py`, `skills/feishu-knowledge-store/scripts/setup_doctor.py` | Runtime, CLI, profile, app, auth, config, ACL, control-tree, and write checks stay independent; the original task resumes only after `ready`. |
| Scope versus resource ACL diagnostics | `runtime_required` | `skills/feishu-knowledge-store/scripts/resource_access.py`, `setup_doctor.py` | Application/user scope success cannot impersonate resource ACL success; denied calls that name a missing scope return `permission_missing`, missing user authorization returns `waiting_admin`, and missing grants return `resource_grant_required`. |
| Owned target initialization, duplicate detection, and write readback | `runtime_required` | `skills/feishu-knowledge-store/scripts/setup_doctor.py`, `publisher.py`, `control_plane.py` | Ordinary users stop at `waiting_initializer`; duplicate or ambiguous trees are not repaired; uncertain writes read back before any retry. |
| Credential redaction and setup-response sanitization | `runtime_required` | `skills/feishu-knowledge-store/scripts/lark_cli.py`, `skills/setup/scripts/setup_cli.py` | CLI diagnostics redact credential-shaped values, and reports, logs, state, and exports carry no appSecret, access token, refresh token, or user code. The `device_code` is the one intentional exception: `auth-start` returns it only as the live handoff channel for the current setup session, it is never written to durable setup state, and the challenge and its QR image are removed once setup reports `ready`. |
| Package JSON credential persistence | `script_checked` | `scripts/package_check.py` | Obvious non-placeholder credential keys, including `device_code` and `user_code`, fail the offline package gate. |
| Natural-language-only first-use routing | `prompt_only` | Entry, setup, and Feishu Skill instructions | The model should invoke setup internally and show the user only natural-language choices, links, QR codes, consent, and write approval; no host hook enforces that route. |
| Dual-harness packaging (Codex `.codex-plugin/` + Claude Code `.claude-plugin/`) | `script_checked` | `plugins/general-screenwriter/tests/test_dual_harness_contract.py`, `scripts/package_check.py` | Missing Claude Code manifest, marketplace/entry drift, version drift across manifests, or harness-specific invocation syntax inside shared skill bodies fail the offline and release gates. The `skills/` tree itself is shared and loaded by both hosts at runtime. |

Use host-level permissions, approval prompts, or hooks when a guarantee must
hold even if a model ignores the Skill instructions.
