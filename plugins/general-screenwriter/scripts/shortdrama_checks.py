"""Deterministic content-level checks for the shortdrama minimal type pack."""

from quality_gate_contract import QualityCheckResult
from script_content import (
    ParsedScript,
    ScriptContentError,
    parse_episode_script,
    scene_dialogue_lines,
)


CHECK_STAGES = {
    "opening_hook": ("hook_check", "require_user_confirmation"),
    "turning_point": ("hook_check", "require_user_confirmation"),
    "closing_hook": ("hook_check", "require_user_confirmation"),
    "pacing_density": ("pacing_check", "require_user_confirmation"),
    "conflict_closure": ("pacing_check", "require_user_confirmation"),
    "duration": ("pacing_check", "advisory"),
    "character_state": ("quality_gate", "hard_block"),
    "format": ("quality_gate", "hard_block"),
}

SHORTDRAMA_CHECK_IDS = tuple(CHECK_STAGES)

HOOK_MIN_CHARS = 6
SCENE_SECONDS_RANGE = (10, 80)
DIALOGUE_SHARE_MIN = 0.25
MIN_SCENES = 3
DIALOGUE_SECONDS = 4.0
ACTION_SECONDS = 2.5
SCENE_SETUP_SECONDS = 3.0
DURATION_TOLERANCE = 0.35
DURATION_RANGE_SECONDS = (30, 900)
TURN_FUNCTIONS = frozenset({"turn", "reversal"})
CLOSING_FUNCTIONS = frozenset({"closing_hook", "cliffhanger"})


def validate_shortdrama_rules(check_id, artifact, context, references=None) -> QualityCheckResult:
    if check_id not in CHECK_STAGES:
        raise ValueError(f"unknown shortdrama check: {check_id!r}")
    stage_id, blocking_policy = CHECK_STAGES[check_id]
    artifact_id = artifact.get("artifact_id") if isinstance(artifact, dict) else None
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        artifact_id = "episode_script"
    try:
        parsed = parse_episode_script(artifact)
    except ScriptContentError as error:
        status = "fail"
        message = "剧本内容无法解析"
        evidence = {"errors": list(error.errors)}
    else:
        status, message, evidence = _CHECKS[check_id](artifact, parsed)
    evidence = {**evidence, "source": "content"}
    return QualityCheckResult(
        check_id=check_id,
        artifact_id=artifact_id,
        stage_id=stage_id,
        blocking_policy=blocking_policy,
        status=status,
        message=message,
        evidence=evidence,
    )


def _nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _beat_positions(parsed: ParsedScript):
    return {beat.beat_id: index for index, beat in enumerate(parsed.beats)}


def _opening_hook(artifact, parsed: ParsedScript):
    if not parsed.beats:
        return "fail", "节拍台账缺失，无法确认开场钩子", {"beats": 0}
    first = parsed.beats[0]
    if first.function != "hook":
        return "fail", f"首个节拍不是 hook：{first.function}", {
            "first_function": first.function,
        }
    first_scene = parsed.scenes[0]
    if first.scene_id != first_scene.scene_id:
        return "fail", "开场钩子不在第一个场景", {
            "hook_scene": first.scene_id,
            "first_scene": first_scene.scene_id,
        }
    hook_text = next(
        (line.text for line in first_scene.lines
         if len(line.text.strip()) >= HOOK_MIN_CHARS),
        None,
    )
    if hook_text is None:
        return "fail", f"开场场景缺少不少于 {HOOK_MIN_CHARS} 字的钩子内容", {
            "scene_id": first_scene.scene_id,
        }
    return "pass", "", {
        "beat_id": first.beat_id,
        "scene_id": first_scene.scene_id,
        "hook_text": hook_text,
        "min_chars": HOOK_MIN_CHARS,
    }


def _turning_point(artifact, parsed: ParsedScript):
    total = len(parsed.beats)
    if total == 0:
        return "fail", "节拍台账缺失，无法确认关键转折", {"beats": 0}
    low, high = total // 4, (3 * total) // 4
    positions = [
        (index, beat) for index, beat in enumerate(parsed.beats)
        if beat.function in TURN_FUNCTIONS
    ]
    if not positions:
        return "fail", "缺少转折节拍", {
            "functions": [beat.function for beat in parsed.beats],
        }
    in_band = [(index, beat) for index, beat in positions if low <= index <= high]
    if not in_band:
        return "fail", "转折节拍不在中段", {
            "positions": [index for index, _ in positions],
            "band": [low, high],
            "total_beats": total,
        }
    for index, beat in in_band:
        if scene_dialogue_lines(parsed, beat.scene_id):
            return "pass", "", {
                "beat_id": beat.beat_id,
                "position": index,
                "band": [low, high],
                "total_beats": total,
            }
    return "fail", "转折节拍缺少台词支撑", {
        "beat_ids": [beat.beat_id for _, beat in in_band],
    }


def _closing_hook(artifact, parsed: ParsedScript):
    if not parsed.beats:
        return "fail", "节拍台账缺失，无法确认结尾钩子", {"beats": 0}
    last_beat = parsed.beats[-1]
    if last_beat.function not in CLOSING_FUNCTIONS:
        return "fail", f"结尾节拍不是钩子：{last_beat.function}", {
            "last_function": last_beat.function,
        }
    last_scene = parsed.scenes[-1]
    if last_beat.scene_id != last_scene.scene_id:
        return "fail", "结尾钩子不在最后一个场景", {
            "hook_scene": last_beat.scene_id,
            "last_scene": last_scene.scene_id,
        }
    if not any(line.text.strip() for line in last_scene.lines):
        return "fail", "结尾场景缺少钩子文本", {"scene_id": last_scene.scene_id}
    return "pass", "", {
        "beat_id": last_beat.beat_id,
        "function": last_beat.function,
        "scene_id": last_scene.scene_id,
    }


def _pacing_density(artifact, parsed: ParsedScript):
    violations = []
    scene_count = len(parsed.scenes)
    if scene_count < MIN_SCENES:
        violations.append(f"场景数少于 {MIN_SCENES}")
    for scene in parsed.scenes:
        if len(scene.lines) < 2:
            violations.append(f"{scene.scene_id} 行数不足 2")
    share = parsed.dialogue_count / parsed.line_count if parsed.line_count else 0.0
    if share < DIALOGUE_SHARE_MIN:
        violations.append(f"台词占比低于 {DIALOGUE_SHARE_MIN}")
    duration = artifact.get("duration_seconds")
    seconds_per_scene = None
    if _number(duration) and duration > 0:
        seconds_per_scene = duration / scene_count
        if not (SCENE_SECONDS_RANGE[0] <= seconds_per_scene <= SCENE_SECONDS_RANGE[1]):
            violations.append(f"单场景时长超出 {SCENE_SECONDS_RANGE} 秒区间")
    else:
        violations.append("声明时长无效")
    evidence = {
        "scene_count": scene_count,
        "line_count": parsed.line_count,
        "dialogue_share": round(share, 4),
        "seconds_per_scene": (
            round(seconds_per_scene, 2) if seconds_per_scene is not None else None
        ),
        "violations": violations,
    }
    if violations:
        return "fail", "节奏密度不达标：" + "；".join(violations), evidence
    return "pass", "", evidence


def _conflict_closure(artifact, parsed: ParsedScript):
    conflict = artifact.get("conflict")
    if not isinstance(conflict, dict):
        return "fail", "冲突台账缺失", {"conflict": None}
    violations = []
    if not _nonempty_text(conflict.get("goal")):
        violations.append("冲突目标缺失")
    if conflict.get("closed") is not True:
        violations.append("冲突未闭环")
    positions = _beat_positions(parsed)
    closure_beat_id = conflict.get("closure_beat_id")
    closure_index = (
        positions.get(closure_beat_id)
        if isinstance(closure_beat_id, str) else None
    )
    if closure_index is None:
        violations.append("闭包节拍引用无效")
    escalation_ids = conflict.get("escalation_beat_ids", [])
    escalation_positions = []
    if not isinstance(escalation_ids, list):
        violations.append("escalation_beat_ids 必须是数组")
    else:
        for beat_id in escalation_ids:
            index = positions.get(beat_id) if isinstance(beat_id, str) else None
            if index is None:
                violations.append(f"升级节拍引用无效：{beat_id!r}")
            else:
                escalation_positions.append(index)
    if closure_index is not None:
        if escalation_positions and max(escalation_positions) >= closure_index:
            violations.append("闭包节拍必须晚于全部升级节拍")
        closure_scene = parsed.beats[closure_index].scene_id
        if not scene_dialogue_lines(parsed, closure_scene):
            violations.append("闭包场景缺少台词支撑")
    evidence = {
        "goal": conflict.get("goal"),
        "closure_beat_id": closure_beat_id,
        "violations": violations,
    }
    if violations:
        return "fail", "冲突闭环不达标：" + "；".join(violations), evidence
    return "pass", "", {**evidence, "closure_position": closure_index}


def _character_state(artifact, parsed: ParsedScript):
    raw_characters = artifact.get("characters")
    if not isinstance(raw_characters, list) or not raw_characters:
        return "fail", "人物状态台账缺失或为空", {"characters": 0}
    positions = _beat_positions(parsed)
    violations = []
    transitions = 0
    registered = []
    for index, raw in enumerate(raw_characters):
        label = f"characters[{index}]"
        if not isinstance(raw, dict) or not _nonempty_text(raw.get("name")):
            violations.append(f"{label} 缺少角色名")
            continue
        name = raw["name"].strip()
        registered.append(name)
        states = raw.get("states")
        if not isinstance(states, list) or not states:
            violations.append(f"{name} 缺少状态记录")
            continue
        ordered = []
        for entry in states:
            if not isinstance(entry, dict) or not _nonempty_text(entry.get("state")):
                violations.append(f"{name} 状态记录不完整")
                continue
            beat_id = entry.get("beat_id")
            position = positions.get(beat_id) if isinstance(beat_id, str) else None
            if position is None:
                violations.append(f"{name} 状态节拍引用无效：{beat_id!r}")
                continue
            ordered.append((position, str(entry["state"]).strip(), beat_id))
        if not ordered:
            continue
        order_values = [item[0] for item in ordered]
        if order_values != sorted(order_values) or len(set(order_values)) != len(order_values):
            violations.append(f"{name} 状态节拍必须严格递增")
        for previous, current in zip(ordered, ordered[1:]):
            if previous[1] == current[1]:
                continue
            transitions += 1
            beat = parsed.beats[current[0]]
            speakers = {
                line.speaker
                for line in scene_dialogue_lines(parsed, beat.scene_id)
            }
            if name not in speakers:
                violations.append(f"{name} 在状态变化场景缺少台词支撑")
    unknown = sorted(parsed.speakers - set(registered))
    if unknown:
        violations.append(f"未登记角色出现在台词中：{', '.join(unknown)}")
    evidence = {
        "characters": len(registered),
        "transitions": transitions,
        "unknown_speakers": unknown,
        "violations": violations,
    }
    if violations:
        return "fail", "人物状态不达标：" + "；".join(violations), evidence
    return "pass", "", evidence


def _duration(artifact, parsed: ParsedScript):
    declared = artifact.get("duration_seconds")
    estimate = (
        parsed.dialogue_count * DIALOGUE_SECONDS
        + parsed.action_count * ACTION_SECONDS
        + len(parsed.scenes) * SCENE_SETUP_SECONDS
    )
    evidence = {
        "estimated_seconds": round(estimate, 1),
        "declared_seconds": declared if _number(declared) else None,
    }
    if (not _number(declared) or declared <= 0
            or not (DURATION_RANGE_SECONDS[0] <= declared <= DURATION_RANGE_SECONDS[1])):
        return "fail", (
            f"声明时长必须是 {DURATION_RANGE_SECONDS[0]}-{DURATION_RANGE_SECONDS[1]} 秒内的正数"
        ), evidence
    deviation = abs(declared - estimate) / declared
    evidence["deviation"] = round(deviation, 4)
    if deviation > DURATION_TOLERANCE:
        return "fail", (
            f"声明时长与内容估算偏差超过 {int(DURATION_TOLERANCE * 100)}%"
        ), evidence
    return "pass", "", evidence


def _format(artifact, parsed: ParsedScript):
    violations = []
    if artifact.get("format") != "episode_script":
        violations.append("format 必须是 episode_script")
    expected_ids = [f"S{index}" for index in range(1, len(parsed.scenes) + 1)]
    actual_ids = [scene.scene_id for scene in parsed.scenes]
    if actual_ids != expected_ids:
        violations.append("scene_id 必须从 S1 起连续编号")
    evidence = {
        "scene_count": len(parsed.scenes),
        "dialogue_count": parsed.dialogue_count,
        "action_count": parsed.action_count,
        "violations": violations,
    }
    if violations:
        return "fail", "格式不达标：" + "；".join(violations), evidence
    return "pass", "", evidence


_CHECKS = {
    "opening_hook": _opening_hook,
    "turning_point": _turning_point,
    "closing_hook": _closing_hook,
    "pacing_density": _pacing_density,
    "conflict_closure": _conflict_closure,
    "duration": _duration,
    "character_state": _character_state,
    "format": _format,
}
