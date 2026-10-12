#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Internal CLI for the deterministic media exporters."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from exporter_contract import ExporterContractError
from export_run import ExportRunnerError, run_export


def _read_json(path, label):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExportRunnerError(f"无法读取{label}：{path}") from error


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="通用编剧导出器（内部工具）")
    parser.add_argument("--exporter-id", required=True)
    parser.add_argument("--artifact-refs", required=True)
    parser.add_argument("--payloads", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--contract")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        artifact_refs = _read_json(args.artifact_refs, "输入引用")
        payloads = _read_json(args.payloads, "输入载荷")
        params = _read_json(args.params, "用户参数")
        result = run_export(
            args.exporter_id,
            artifact_refs,
            payloads,
            params,
            overwrite_allowed=args.overwrite,
            contract_path=args.contract,
        )
    except (ExporterContractError, ExportRunnerError) as error:
        print(f"[export_cli] {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "exporter_id": result.exporter_id,
        "output_format": result.output_format,
        "destination": str(result.destination),
        "bytes_written": result.bytes_written,
        "manifest": dict(result.manifest),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
