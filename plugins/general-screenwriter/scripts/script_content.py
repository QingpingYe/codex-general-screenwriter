"""Deterministic parsing for episode-script payloads shared by media checks.

This module never reads files or calls models: it parses an in-memory artifact
payload into immutable scene and beat views so content-level validators can
derive verdicts from the script itself instead of declared fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


class ScriptContentError(ValueError):
    """Raised when an episode-script payload cannot be parsed."""

    def __init__(self, errors: Any):
        self.errors = tuple(str(item) for item in errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class ScriptLine:
    kind: str
    text: str
    speaker: str | None = None


@dataclass(frozen=True)
class ScriptScene:
    scene_id: str
    heading: str
    location: str
    time_of_day: str
    lines: tuple[ScriptLine, ...]
    transition: str


@dataclass(frozen=True)
class ScriptBeat:
    beat_id: str
    function: str
    scene_id: str


@dataclass(frozen=True)
class ParsedScript:
    scenes: tuple[ScriptScene, ...]
    beats: tuple[ScriptBeat, ...]
    line_count: int
    action_count: int
    dialogue_count: int
    speakers: frozenset[str]
    scene_index: Mapping[str, int]


def _plain_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def parse_episode_script(payload: Any) -> ParsedScript:
    """Parse a scene/line/beat episode payload into immutable views."""
    if not isinstance(payload, Mapping):
        raise ScriptContentError(["剧本载荷必须是对象"])
    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ScriptContentError(["scenes 必须是非空数组"])

    errors: list[str] = []
    scenes: list[ScriptScene] = []
    seen_scene_ids: set[str] = set()
    for index, raw_scene in enumerate(raw_scenes):
        label = f"scenes[{index}]"
        if not isinstance(raw_scene, Mapping):
            errors.append(f"{label} 必须是对象")
            continue
        scene_id = _plain_text(raw_scene.get("scene_id"))
        if scene_id is None:
            errors.append(f"{label}.scene_id 必须是非空字符串")
            continue
        if scene_id in seen_scene_ids:
            errors.append(f"{label}.scene_id 重复：{scene_id}")
            continue
        seen_scene_ids.add(scene_id)
        heading = _plain_text(raw_scene.get("heading"))
        location = _plain_text(raw_scene.get("location"))
        time_of_day = _plain_text(raw_scene.get("time_of_day"))
        for name, value in (("heading", heading), ("location", location),
                            ("time_of_day", time_of_day)):
            if value is None:
                errors.append(f"{label}.{name} 必须是非空字符串")

        raw_lines = raw_scene.get("lines")
        lines: list[ScriptLine] = []
        if not isinstance(raw_lines, list) or not raw_lines:
            errors.append(f"{label}.lines 必须是非空数组")
        else:
            for line_index, raw_line in enumerate(raw_lines):
                line_label = f"{label}.lines[{line_index}]"
                if not isinstance(raw_line, Mapping):
                    errors.append(f"{line_label} 必须是对象")
                    continue
                kind = raw_line.get("kind")
                if kind not in ("action", "dialogue"):
                    errors.append(f"{line_label}.kind 只能是 action/dialogue")
                    continue
                text = _plain_text(raw_line.get("text"))
                if text is None:
                    errors.append(f"{line_label}.text 必须是非空字符串")
                    continue
                speaker = None
                if kind == "dialogue":
                    speaker = _plain_text(raw_line.get("speaker"))
                    if speaker is None:
                        errors.append(f"{line_label}.speaker 必须是非空字符串")
                        continue
                lines.append(ScriptLine(kind=kind, text=text, speaker=speaker))

        transition = raw_scene.get("transition", "")
        if not isinstance(transition, str):
            errors.append(f"{label}.transition 必须是字符串")
            transition = ""
        if heading is not None and location is not None and time_of_day is not None:
            scenes.append(ScriptScene(
                scene_id=scene_id,
                heading=heading,
                location=location,
                time_of_day=time_of_day,
                lines=tuple(lines),
                transition=transition.strip(),
            ))

    raw_beats = payload.get("beats", [])
    beats: list[ScriptBeat] = []
    if not isinstance(raw_beats, list):
        errors.append("beats 必须是数组")
    else:
        known_scene_ids = {scene.scene_id for scene in scenes}
        seen_beat_ids: set[str] = set()
        for index, raw_beat in enumerate(raw_beats):
            label = f"beats[{index}]"
            if not isinstance(raw_beat, Mapping):
                errors.append(f"{label} 必须是对象")
                continue
            beat_id = _plain_text(raw_beat.get("beat_id"))
            function = _plain_text(raw_beat.get("function"))
            scene_id = _plain_text(raw_beat.get("scene_id"))
            if beat_id is None:
                errors.append(f"{label}.beat_id 必须是非空字符串")
                continue
            if beat_id in seen_beat_ids:
                errors.append(f"{label}.beat_id 重复：{beat_id}")
                continue
            seen_beat_ids.add(beat_id)
            if function is None:
                errors.append(f"{label}.function 必须是非空字符串")
                continue
            if scene_id is None:
                errors.append(f"{label}.scene_id 必须是非空字符串")
                continue
            if scene_id not in known_scene_ids:
                errors.append(f"{label}.scene_id 引用未知场景：{scene_id}")
                continue
            beats.append(ScriptBeat(
                beat_id=beat_id, function=function, scene_id=scene_id,
            ))

    if errors:
        raise ScriptContentError(errors)

    line_count = sum(len(scene.lines) for scene in scenes)
    action_count = sum(
        1 for scene in scenes for line in scene.lines if line.kind == "action"
    )
    dialogue_count = line_count - action_count
    speakers = frozenset(
        line.speaker for scene in scenes for line in scene.lines
        if line.speaker is not None
    )
    scene_index = MappingProxyType({
        scene.scene_id: index for index, scene in enumerate(scenes)
    })
    return ParsedScript(
        scenes=tuple(scenes),
        beats=tuple(beats),
        line_count=line_count,
        action_count=action_count,
        dialogue_count=dialogue_count,
        speakers=speakers,
        scene_index=scene_index,
    )


def scene_dialogue_lines(parsed: ParsedScript, scene_id: str) -> tuple[ScriptLine, ...]:
    """Return the dialogue lines of one scene, or an empty tuple."""
    index = parsed.scene_index.get(scene_id)
    if index is None:
        return ()
    return tuple(
        line for line in parsed.scenes[index].lines if line.kind == "dialogue"
    )
