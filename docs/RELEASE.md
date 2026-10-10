# Release Checklist

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

3. Confirm the version in `plugins/general-screenwriter/.codex-plugin/plugin.json`, `docs/CHANGELOG.md`, and the release tag describe the same release. Run the release-version gate with the tag value:

   ```powershell
   $env:GENERAL_SCREENWRITER_EXPECTED_VERSION = "<release-version>"
   python .\plugins\general-screenwriter\tests\test_release_contract.py
   Remove-Item Env:GENERAL_SCREENWRITER_EXPECTED_VERSION
   ```

4. Confirm no credentials, run directories, or `.general-screenwriter` files are committed.

## Explicit live gates

1. Run the documented multi-user live Feishu acceptance only after both users approve.
2. Run live image generation only with explicit user confirmation, an explicit output directory, explicit size and quality, and a supplied API key.
3. Confirm no key appears in command history, logs, metadata, or exports.
4. Install from the published Git ref in a clean Codex profile.
5. Record acceptance results and blockers before publishing to the marketplace.

## Unified release gate

Run `python scripts/release_gate.py` before any release. The gate runs the nine
ordered checks (registry contract, knowledge adapter, skill registry, DAG
scheduler, quality gate, exporter contract, offline regression, governance
check, packaging check), stops on the first failure, and exits nonzero. A
failed run must not be released. Migration status is reported with
`plugins/general-screenwriter/scripts/migration_report.py`, which is
read-only: it never rewrites run manifests, knowledge keys, or user artifacts.
