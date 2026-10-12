"""Deterministic media exporters: render in memory, write atomically.

Rendering never touches the filesystem. Only write_export/run_export write,
and only after contract validation and destination checks; failures never
leave partial files behind.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from exporter_contract import (
    build_export_manifest,
    check_export_destination,
    load_exporter_contract,
    validate_export_request,
)
from script_content import ScriptContentError, parse_episode_script


DEFAULT_CONTRACT_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "exporters.json"
)


class ExportRunnerError(ValueError):
    """Raised when an export cannot be rendered or written safely."""


@dataclass(frozen=True)
class ExportResult:
    exporter_id: str
    output_format: str
    destination: Path
    bytes_written: int
    manifest: Mapping[str, Any]


def render_export(exporter_id, payloads, user_params=None) -> str:
    """Render one exporter's output as text without touching the filesystem."""
    if not isinstance(payloads, Mapping):
        raise ExportRunnerError("payloads 必须是 artifact_id 到载荷的对象")
    renderer = _RENDERERS.get(exporter_id)
    if renderer is None:
        raise ExportRunnerError(f"未知或未实现渲染的导出器：{exporter_id!r}")
    try:
        return renderer(payloads, dict(user_params or {}))
    except ExportRunnerError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ExportRunnerError(f"渲染失败：{error}") from error


def write_export(destination, content, overwrite_allowed=False) -> Path:
    """Atomically write text to a concrete file path, cleaning up on failure."""
    path = Path(destination)
    check_export_destination(path, overwrite_allowed=overwrite_allowed)
    if not isinstance(content, str):
        raise ExportRunnerError("导出内容必须是文本")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        descriptor, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent),
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(tmp_path, path)
        tmp_path = None
    except OSError as error:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise ExportRunnerError(f"写入导出文件失败：{error}") from error
    return path


def run_export(
    exporter_id,
    artifact_refs,
    payloads,
    user_params,
    *,
    overwrite_allowed=False,
    contract_path=None,
) -> ExportResult:
    """Validate, render, and atomically write one explicit export request."""
    contract = load_exporter_contract(
        exporter_id, contract_path or DEFAULT_CONTRACT_PATH,
    )
    request = validate_export_request(contract, artifact_refs, user_params)
    if "filename" not in request.user_params:
        raise ExportRunnerError(
            f"导出器 {exporter_id!r} 未声明 filename 参数，无法直写"
        )
    filename = request.user_params["filename"]
    if Path(filename).name != filename or filename in {".", ".."}:
        raise ExportRunnerError(f"filename 必须是纯文件名：{filename!r}")
    destination = Path(request.user_params["output_directory"]) / filename
    check_export_destination(destination, overwrite_allowed=overwrite_allowed)
    content = render_export(exporter_id, payloads, request.user_params)
    written = write_export(
        destination, content, overwrite_allowed=overwrite_allowed,
    )
    return ExportResult(
        exporter_id=exporter_id,
        output_format=contract.output_format,
        destination=written,
        bytes_written=len(content.encode("utf-8")),
        manifest=build_export_manifest(contract, request),
    )


def _require_payload(payloads: Mapping, artifact_id: str) -> Mapping:
    payload = payloads.get(artifact_id)
    if not isinstance(payload, Mapping):
        raise ExportRunnerError(f"缺少输入载荷：{artifact_id}")
    return payload


def _require_text(payload: Mapping, key: str, artifact_id: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExportRunnerError(f"{artifact_id}.{key} 必须是非空字符串")
    return value.strip()


def _require_scenes(payload: Mapping, artifact_id: str):
    scenes = payload.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise ExportRunnerError(f"{artifact_id}.scenes 必须是非空数组")
    for index, scene in enumerate(scenes):
        if not isinstance(scene, Mapping):
            raise ExportRunnerError(f"{artifact_id}.scenes[{index}] 必须是对象")
    return scenes


def _validated_episode_script(payload: Mapping, artifact_id: str):
    try:
        return parse_episode_script(payload)
    except ScriptContentError as error:
        raise ExportRunnerError(
            f"{artifact_id} 载荷不合法：{'；'.join(error.errors)}"
        ) from error


def _screenplay_text(payload: Mapping) -> str:
    parsed = _validated_episode_script(payload, "episode_script")
    blocks = []
    for scene in parsed.scenes:
        lines = [scene.heading]
        for line in scene.lines:
            if line.kind == "dialogue":
                lines.append(f"{line.speaker}：{line.text}")
            else:
                lines.append(line.text)
        if scene.transition:
            lines.append(f"【转场】{scene.transition}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _render_episode_script(payloads: Mapping, user_params: Mapping) -> str:
    return _screenplay_text(_require_payload(payloads, "episode_script"))


def _render_production_checklist(payloads: Mapping, user_params: Mapping) -> str:
    payload = _require_payload(payloads, "scene_table")
    rows = [
        "| 场次 | 地点 | 时段 | 出场 | 道具 | 转场 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for scene in _require_scenes(payload, "scene_table"):
        def cell(key):
            value = scene.get(key)
            if isinstance(value, list):
                value = "、".join(str(item) for item in value)
            if value is None or (isinstance(value, str) and not value.strip()):
                return "-"
            return str(value).strip().replace("|", "\\|")

        rows.append(
            "| " + " | ".join(
                [cell("scene_id")] + [
                    cell(key) for key in
                    ("location", "time_of_day", "cast", "props",
                     "transition", "notes")
                ]
            ) + " |"
        )
    return "\n".join(rows) + "\n"


def _render_season_package(payloads: Mapping, user_params: Mapping) -> str:
    episode = _require_payload(payloads, "episode_script")
    season_arc = _require_payload(payloads, "season_arc")
    ledger = _require_payload(payloads, "continuity_ledger")
    series_id = _require_text(episode, "series_id", "episode_script")
    season_id = _require_text(episode, "season_id", "episode_script")
    episode_id = _require_text(episode, "episode_id", "episode_script")
    function = _require_text(episode, "episode_function", "episode_script")
    beat_ref = episode.get("arc_beat_ref")
    arc_goal = None
    beats = season_arc.get("beats")
    if isinstance(beats, list):
        for beat in beats:
            if isinstance(beat, Mapping) and beat.get("beat_id") == beat_ref:
                goal = beat.get("goal")
                if isinstance(goal, str) and goal.strip():
                    arc_goal = goal.strip()
    if arc_goal is None:
        raise ExportRunnerError(f"季节弧线中缺少 beat：{beat_ref!r}")
    entries = ledger.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ExportRunnerError("continuity_ledger.entries 必须是非空数组")
    document = [
        f"《{series_id}》{season_id} / {episode_id}",
        f"集功能：{function}",
        f"季弧线目标：{arc_goal}",
        "",
        "## 剧本",
        "",
        _screenplay_text(episode).rstrip("\n"),
        "",
        "## 连续性",
        "",
        "| 字段 | 记录 |",
        "| --- | --- |",
    ]
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ExportRunnerError(f"continuity_ledger.entries[{index}] 必须是对象")
        field = entry.get("field")
        value = entry.get("value")
        if (not isinstance(field, str) or not field.strip()
                or not isinstance(value, str) or not value.strip()):
            raise ExportRunnerError(
                f"continuity_ledger.entries[{index}] 字段或值缺失"
            )
        document.append(f"| {field.strip()} | {value.strip()} |")
    return "\n".join(document) + "\n"


def _render_structured_json(payloads: Mapping, user_params: Mapping) -> str:
    if not payloads:
        raise ExportRunnerError("JSON 导出至少需要一个输入载荷")
    for artifact_id, payload in payloads.items():
        if not isinstance(payload, Mapping):
            raise ExportRunnerError(f"JSON 导出载荷必须是对象：{artifact_id}")
    if len(payloads) == 1:
        document: Any = next(iter(payloads.values()))
    else:
        document = {"artifacts": dict(payloads)}
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


_RENDERERS = {
    "shortdrama_episode_script": _render_episode_script,
    "tv_episode_script": _render_episode_script,
    "shortdrama_production_checklist": _render_production_checklist,
    "tv_season_package": _render_season_package,
    "structured_json": _render_structured_json,
}
