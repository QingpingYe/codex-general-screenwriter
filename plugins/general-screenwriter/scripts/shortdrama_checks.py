"""Deterministic structural checks for the shortdrama minimal type pack."""

from quality_gate_contract import QualityCheckResult


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


def validate_shortdrama_rules(check_id, artifact, context) -> QualityCheckResult:
    if check_id not in CHECK_STAGES:
        raise ValueError(f"unknown shortdrama check: {check_id!r}")
    stage_id, blocking_policy = CHECK_STAGES[check_id]
    artifact_id = artifact.get("artifact_id") if isinstance(artifact, dict) else None
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        artifact_id = "episode_script"
    status, message, evidence = _CHECKS[check_id](artifact)
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


def _text_check(field):
    def check(artifact):
        if _nonempty_text(artifact.get(field)):
            return "pass", "", {"field": field}
        return "fail", f"{field} 缺失或为空", {"field": field}
    return check


def _pacing(artifact):
    beats = artifact.get("beats")
    if isinstance(beats, list) and beats:
        return "pass", "", {"beats": len(beats)}
    return "fail", "beats 缺失或为空", {"beats": 0}


def _conflict_closure(artifact):
    conflict = artifact.get("conflict")
    if (isinstance(conflict, dict)
            and _nonempty_text(conflict.get("goal"))
            and conflict.get("closed") is True):
        return "pass", "", {"goal": conflict["goal"]}
    return "fail", "冲突目标缺失或未闭环", {"conflict": conflict}


def _character_state(artifact):
    characters = artifact.get("characters")
    if (isinstance(characters, list) and characters
            and all(isinstance(item, dict)
                    and _nonempty_text(item.get("name"))
                    and _nonempty_text(item.get("state"))
                    for item in characters)):
        return "pass", "", {"characters": len(characters)}
    return "fail", "人物状态台账缺失或不完整", {"characters": characters}


def _format(artifact):
    if artifact.get("format") == "episode_script":
        return "pass", "", {"format": "episode_script"}
    return "fail", "格式必须是 episode_script", {"format": artifact.get("format")}


def _duration(artifact):
    value = artifact.get("duration_seconds")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return "pass", "", {"duration_seconds": value}
    return "fail", "时长必须是正数", {"duration_seconds": value}


_CHECKS = {
    "opening_hook": _text_check("opening_hook"),
    "turning_point": _text_check("turning_point"),
    "closing_hook": _text_check("closing_hook"),
    "pacing_density": _pacing,
    "conflict_closure": _conflict_closure,
    "character_state": _character_state,
    "format": _format,
    "duration": _duration,
}
