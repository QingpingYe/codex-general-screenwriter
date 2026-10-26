# Release Checklist

This is maintainer documentation. User-facing first-use behavior is described
in the root and plugin README as natural-language interaction only. Normal
users do not run Feishu setup commands.

## Offline gates

1. Run every offline Python, Node, governance, and package gate:

   ```powershell
   python .\scripts\run_plugin_tests.py
   ```

2. Run plugin structure validation:

   ```powershell
   $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { "$HOME\.codex" }
   python "$codexHome\skills\.system\plugin-creator\scripts\validate_plugin.py" .\plugins\general-screenwriter
   ```

3. Run the unified release gate. It runs `first_use_contract` and
   `setup_docs_contract` before the offline regression:

   ```powershell
   python .\scripts\release_gate.py
   ```

4. Confirm the version in `plugins/general-screenwriter/.codex-plugin/plugin.json`,
   `docs/CHANGELOG.md`, and the release tag describe the same release. Run the
   release-version gate with the tag value:

   ```powershell
   $env:GENERAL_SCREENWRITER_EXPECTED_VERSION = "<release-version>"
   python .\plugins\general-screenwriter\tests\test_release_contract.py
   Remove-Item Env:GENERAL_SCREENWRITER_EXPECTED_VERSION
   ```

5. Confirm no credentials, run directories, or `.general-screenwriter` files
   are committed. The package gate also rejects persisted `device_code` and
   `user_code` values in JSON package files.

## Unified release gate

Run `python scripts/release_gate.py` before any release. The gate runs the
ordered checks (registry contract, knowledge adapter, user-skill gates, DAG
scheduler, quality gate, exporter contract, first-use contract, setup docs
contract, offline regression, governance check, packaging check), stops on the
first failure, and exits nonzero. A failed run must not be released. Migration
status is reported with
`plugins/general-screenwriter/scripts/migration_report.py`, which is
read-only: it never rewrites run manifests, knowledge keys, or user artifacts.

## Live first-use release gate (requires execution)

Status for the current release: **NOT RUN**. These live Feishu and Windows
checks require execution in a clean live environment and must not be marked
passed from this repository's offline tests. Offline tests are not live
acceptance evidence.

For every check, retain de-identified evidence: execution time, platform and
architecture, CLI version and source, profile origin, authorization status,
source/target link resolution, initializer ownership, duplicate-page check,
ACL before/after state, write/readback revision, user terminal-command count,
and secret-scan results.

1. **clean Windows VM / 干净 Windows VM**: install only from the published
   marketplace in a clean Windows account or VM without the author's global
   skills or development checkout. Confirm the current session resolves the
   private user-level runtime and CLI by absolute path. Requires execution.

2. **existing higher-version CLI / 已有更高版本 CLI**: test with a compatible
   higher-version CLI and unrelated plugins/profiles. Confirm the existing CLI
   is reused, the named profile is created or reused correctly, other profiles
   remain unchanged, and no PATH or global configuration is modified. Requires
   execution.

3. **two real users / 两个真实用户**: have two real users complete their own
   authorization, source reads, target writes, revision updates, and readback.
   Confirm each user uses their own identity and profile, the first user owns
   empty-target initialization, the second waits and reuses it, and no shared
   maintainer token is used. Requires execution.

4. **no global install / 无全局安装**: confirm setup performs no global npm
   install, installs no global skills, does not overwrite an existing system CLI,
   does not modify PATH, and does not require a restart or new terminal session.
   Confirm the user executes zero terminal commands. Requires execution.

5. **no credential leakage / 无凭证泄漏**: scan command history, logs, Git
   status and committed files, setup state, generated configurations, and
   exports for `appSecret`, `accessToken`, `refreshToken`, and `device_code`.
   Confirm all are absent and offline tests are not live acceptance evidence.
   Requires execution.

6. **interrupted recovery / 中断恢复**: exercise authorization expiry,
   administrator approval delay, network interruption, process interruption,
   and an uncertain write. Confirm every path rereads real state, resumes only
   unfinished steps, never blindly retries creation or overwrite, and eventually
   resumes the original task. Requires execution.

Live image generation remains a separate explicit-confirmation gate. It is not
part of first-use setup and must not run without an explicit output directory,
size, quality, API-key source, and user confirmation.
