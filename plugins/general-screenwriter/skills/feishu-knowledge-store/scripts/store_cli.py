"""Operator boundary for the Feishu knowledge store."""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import ConfigError, load_config
from config_paths import ConfigResolutionError, resolve_config_path
from control_plane import ControlPlane
from lark_cli import LarkCli
from lark_cli_context import CliContextError, resolve_cli_context
from publisher import Publisher
from resource_access import check_resource_access
from setup_doctor import init_target, run_doctor, verify_write_access
from source_admission import empty_admission_policy
from source_baseline import build_source_baseline, read_source_admission, write_source_baseline
from sync_runner import SyncRunner


@dataclass(frozen=True)
class ReadComponents:
    config: Any
    config_path: Path
    cli_context: Any
    cli: Any
    publisher: Publisher


@dataclass(frozen=True)
class Components(ReadComponents):
    control_plane: ControlPlane


def build_read_components(config_path=None, environ=None, workspace=None, profile=None) -> ReadComponents:
    """Resolve config, one CLI context, and Publisher without touching the control plane."""
    resolved = resolve_config_path(config_path, workspace, environ)
    config = load_config(resolved.path, resolved.path.parent, environ)
    cli_context = resolve_cli_context(profile=profile, environ=environ)
    cli = LarkCli(
        cli_context.binary,
        identity=config.identity,
        profile=cli_context.profile,
    )
    publisher = Publisher(
        cli, config.target.root_token, config.target.space_id,
        root_mode=config.target.root_mode,
    )
    return ReadComponents(config, resolved.path, cli_context, cli, publisher)


def build_components(config_path=None, environ=None, workspace=None, profile=None) -> Components:
    """Build the full runtime for legacy commands that require the control plane."""
    read_components = build_read_components(
        config_path=config_path,
        environ=environ,
        workspace=workspace,
        profile=profile,
    )
    tokens = read_components.publisher.resolve_control_plane()
    control_plane = ControlPlane(
        read_components.cli,
        {"index": tokens["index"], "lock": tokens["lock"]},
        lock_ttl_minutes=read_components.config.lock_ttl_minutes,
    )
    return Components(
        read_components.config,
        read_components.config_path,
        read_components.cli_context,
        read_components.cli,
        read_components.publisher,
        control_plane,
    )


def preflight_payload(components: ReadComponents) -> dict[str, Any]:
    """Run only read-only identity, resource, and control-tree diagnostics."""
    access = check_resource_access(components.config, components.cli)
    tree = components.publisher.inspect_control_tree()
    if not access.ok:
        status = access.status
    elif tree.get("status") == "control_tree_complete":
        status = "read_ready"
    elif tree.get("status") == "control_tree_ambiguous":
        status = "control_tree_ambiguous"
    else:
        status = "control_tree_missing"
    return {
        "status": status,
        "identity": components.config.identity,
        "root": components.config.target.root_token,
        "target_space_id": components.config.target.space_id,
        "resource_access": access.to_dict(),
        "control_tree": tree,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate the Feishu knowledge store")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "resolve", "lock-status"):
        command = commands.add_parser(name)
        command.add_argument("--config")
        command.add_argument("--workspace")
    for name in ("prepare", "publish", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--config")
        command.add_argument("--workspace")
        command.add_argument("--run-dir", required=True)
    source_baseline = commands.add_parser("source-baseline")
    source_baseline.add_argument("--config")
    source_baseline.add_argument("--workspace")
    source_baseline.add_argument("--out", required=True)
    fixture = commands.add_parser("lint-fixture")
    fixture.add_argument("--config")
    fixture.add_argument("--workspace")
    fixture.add_argument("--out", required=True)
    status = commands.add_parser("config-status")
    status.add_argument("--config")
    status.add_argument("--workspace")
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--config")
    doctor.add_argument("--workspace")
    doctor.add_argument("--initializer", action="store_true")
    init = commands.add_parser("init-target")
    init.add_argument("--config")
    init.add_argument("--workspace")
    init.add_argument("--initializer", action="store_true")
    init.add_argument("--authorized", action="store_true")
    write_verify = commands.add_parser("write-verify")
    write_verify.add_argument("--config")
    write_verify.add_argument("--workspace")
    write_verify.add_argument("--authorized", action="store_true")
    return parser


def config_status(args, stdout, environ=None, context_resolver=None) -> int:
    context_resolver = context_resolver or resolve_cli_context
    resolved = None
    try:
        resolved = resolve_config_path(args.config, args.workspace, environ)
        load_config(resolved.path, resolved.path.parent, environ)
        status = "configured"
        origin = resolved.origin
        path = str(resolved.path)
        searched = [str(item) for item in resolved.searched]
    except ConfigResolutionError as error:
        status = error.status
        origin = error.origin
        path = None
        searched = [str(item) for item in error.searched]
    except ConfigError as error:
        status = getattr(error, "status", "invalid_config")
        origin = resolved.origin if resolved is not None else None
        path = str(resolved.path) if resolved is not None else (
            str(args.config) if args.config else None
        )
        searched = [str(item) for item in resolved.searched] if resolved is not None else []

    try:
        context = context_resolver(environ=environ)
        cli_status = {
            "status": "available",
            "path": str(context.binary),
            "version": context.version,
            "profile": context.profile,
            "capabilities": sorted(context.capabilities),
            "installed": False,
        }
    except CliContextError as error:
        cli_status = {**error.to_dict(), "available": False}
    except Exception as error:
        cli_status = {
            "status": "error",
            "available": False,
            "message": str(error),
        }

    payload = {
        "configured": status == "configured",
        "status": status,
        "origin": origin,
        "path": path,
        "searched": searched,
        "cli_status": cli_status,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stdout)
    return 0


def export_lint_fixture(components: Components, out: str | Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    config = components.config
    root = config.target.root_token
    nodes = [{"node_token": root, "title": "<root>", "parent_node_token": None}]

    def walk(parent_node_token: str) -> None:
        for node in components.cli.list_nodes(config.target.space_id, parent_node_token=parent_node_token):
            node_token = next(
                value for key in ("node_token", "obj_token", "token")
                if (value := node.get(key))
            )
            nodes.append({
                "node_token": node_token,
                "title": node.get("title", ""),
                "parent_node_token": parent_node_token,
            })
            walk(node_token)

    walk(root)
    (out / "tree.json").write_text(
        json.dumps(nodes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )

    def content(token: str) -> str:
        return components.cli.fetch_doc(token)["data"]["document"]["content"]

    tokens = components.publisher.resolve_control_plane()
    index_document = content(tokens["index"])
    (out / "index.md").write_text(index_document, encoding="utf-8")

    pages = out / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    index = components.control_plane.read_index()
    for entry in index.values():
        (pages / f"{entry.key.replace('/', '__')}.md").write_text(
            content(entry.doc_token), encoding="utf-8",
        )
    return out


def main(argv=None, stdout=None, components_factory=None) -> int:
    args = build_parser().parse_args(argv)
    stdout = stdout if stdout is not None else sys.stdout
    if args.command == "config-status":
        return config_status(args, stdout, environ=None)

    factory = components_factory if components_factory is not None else build_components
    workspace = Path(args.workspace) if getattr(args, "workspace", None) else None
    try:
        if args.command == "preflight":
            read_factory = (
                build_read_components
                if components_factory is None or components_factory is build_components
                else components_factory
            )
            components = read_factory(args.config, environ=None, workspace=workspace)
            payload = preflight_payload(components)
        elif args.command == "doctor":
            payload = run_doctor(
                config_path=args.config,
                workspace=workspace,
                initializer=bool(getattr(args, "initializer", False)),
            )
        elif args.command == "init-target":
            payload = init_target(
                config_path=args.config,
                workspace=workspace,
                authorized=bool(getattr(args, "authorized", False)),
                initializer_confirmed=bool(getattr(args, "initializer", False)),
            )
        elif args.command == "write-verify":
            payload = verify_write_access(
                config_path=args.config,
                workspace=workspace,
                authorized=bool(getattr(args, "authorized", False)),
            )
        elif args.command in {
            "resolve", "lock-status", "prepare", "publish", "verify",
            "source-baseline", "lint-fixture",
        }:
            components = factory(
                args.config, environ=None, workspace=workspace,
            )
            if args.command == "resolve":
                payload = components.publisher.resolve_control_plane()
            elif args.command == "lock-status":
                revision_id, payload = components.control_plane.read_lock()
                payload = {"revision_id": revision_id, **payload}
            elif args.command == "prepare":
                runner = SyncRunner(
                    components.config_path, components.cli, components.publisher,
                    components.control_plane, config=components.config,
                )
                payload = str(runner.prepare(args.run_dir))
            elif args.command == "publish":
                runner = SyncRunner(
                    components.config_path, components.cli, components.publisher,
                    components.control_plane, config=components.config,
                )
                payload = runner.publish(args.run_dir)
            elif args.command == "verify":
                runner = SyncRunner(
                    components.config_path, components.cli, components.publisher,
                    components.control_plane, config=components.config,
                )
                payload = runner.verify(args.run_dir)
            elif args.command == "source-baseline":
                tokens = components.publisher.resolve_control_plane()
                revision, index = components.control_plane.read_index_with_revision()
                if tokens.get("admission"):
                    admission = read_source_admission(components.cli, tokens["admission"])
                else:
                    admission = empty_admission_policy(page_present=False)
                payload = build_source_baseline(revision, index, admission)
                write_source_baseline(args.out, payload)
                payload = {
                    "out": str(args.out),
                    "index_revision_id": revision,
                    "admission_page_present": admission.page_present,
                }
            else:
                payload = {"out": str(export_lint_fixture(components, args.out))}
        else:
            print(json.dumps({
                "status": "unsupported_command", "command": args.command,
            }, ensure_ascii=False, sort_keys=True), file=stdout)
            return 2
    except Exception as error:
        payload = error.to_dict() if hasattr(error, "to_dict") else {
            "status": "runtime_error", "error": str(error),
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stdout)
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
