"""Deterministic structural checks for the tv_longform minimal type pack."""

from quality_gate_contract import QualityCheckResult


CHECK_STAGES = {
    "season_arc": ("quality_gate", "require_user_confirmation"),
    "episode_function": ("quality_gate", "require_user_confirmation"),
    "timeline": ("continuity_check", "require_user_confirmation"),
    "foreshadow": ("foreshadow_check", "require_user_confirmation"),
    "payoff": ("foreshadow_check", "require_user_confirmation"),
    "scene_transition": ("continuity_check", "require_user_confirmation"),
    "character_state": ("character_state_check", "hard_block"),
    "series_constraint": ("quality_gate", "hard_block"),
    "continuity": ("continuity_check", "hard_block"),
}

TV_LONGFORM_CHECK_IDS = tuple(CHECK_STAGES)


def validate_tv_longform_rules(check_id, artifact, context) -> QualityCheckResult:
    if check_id not in CHECK_STAGES:
        raise ValueError(f"unknown tv_longform check: {check_id!r}")
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


def _dict_fields_check(field, keys):
    def check(artifact):
        value = artifact.get(field)
        if (isinstance(value, dict)
                and all(_nonempty_text(value.get(key)) for key in keys)):
            return "pass", "", {"field": field}
        return "fail", f"{field} 缺失或不完整", {"field": field, "required": list(keys)}
    return check


def _text_check(field):
    def check(artifact):
        if _nonempty_text(artifact.get(field)):
            return "pass", "", {"field": field}
        return "fail", f"{field} 缺失或为空", {"field": field}
    return check


def _timeline(artifact):
    timeline = artifact.get("timeline")
    if (isinstance(timeline, list) and timeline
            and all(isinstance(item, dict) and _nonempty_text(item.get("event"))
                    for item in timeline)):
        orders = [item.get("order") for item in timeline]
        if all(isinstance(order, int) and not isinstance(order, bool) for order in orders) \
                and orders == sorted(orders):
            return "pass", "", {"events": len(timeline)}
    return "fail", "时间线缺失、不完整或顺序矛盾", {"timeline": timeline}


def _foreshadow(artifact):
    foreshadows = artifact.get("foreshadows")
    if (isinstance(foreshadows, list) and foreshadows
            and all(isinstance(item, dict)
                    and _nonempty_text(item.get("id"))
                    and _nonempty_text(item.get("source"))
                    and _nonempty_text(item.get("purpose"))
                    for item in foreshadows)):
        return "pass", "", {"foreshadows": len(foreshadows)}
    return "fail", "伏笔台账缺失或缺少来源/目的", {"foreshadows": foreshadows}


def _payoff(artifact):
    payoffs = artifact.get("payoffs")
    foreshadow_ids = {
        item.get("id") for item in artifact.get("foreshadows", [])
        if isinstance(item, dict)
    }
    if (isinstance(payoffs, list) and payoffs
            and all(isinstance(item, dict)
                    and item.get("foreshadow_id") in foreshadow_ids
                    and _nonempty_text(item.get("resolution"))
                    for item in payoffs)):
        return "pass", "", {"payoffs": len(payoffs)}
    return "fail", "回收缺失或未指向已登记伏笔", {"payoffs": payoffs}


def _scene_transition(artifact):
    scene_table = artifact.get("scene_table")
    if (isinstance(scene_table, list) and scene_table
            and all(isinstance(item, dict) and _nonempty_text(item.get("transition"))
                    for item in scene_table)):
        return "pass", "", {"scenes": len(scene_table)}
    return "fail", "场次表缺失或缺少转场", {"scene_table": scene_table}


def _character_state(artifact):
    states = artifact.get("character_states")
    if (isinstance(states, list) and states
            and all(isinstance(item, dict)
                    and _nonempty_text(item.get("name"))
                    and _nonempty_text(item.get("state"))
                    for item in states)):
        conflicts = [
            f"{item.get('series_id', 's1')}:{item.get('episode_id', 'e1')}:character-state"
            for item in states
            if item.get("conflicts_with_previous") is True
        ]
        if conflicts:
            return "fail", "人物状态与上一集冲突，已报告不合并", {"conflicts": conflicts}
        return "pass", "", {"characters": len(states)}
    return "fail", "人物状态台账缺失或不完整", {"character_states": states}


def _continuity(artifact):
    if _nonempty_text(artifact.get("continuity_ledger_ref")):
        return "pass", "", {"ledger": artifact["continuity_ledger_ref"]}
    return "fail", "缺少连续性台账引用", {"continuity_ledger_ref": None}


_CHECKS = {
    "season_arc": _dict_fields_check("season_arc", ("goal", "obstacle", "turn")),
    "episode_function": _text_check("episode_function"),
    "timeline": _timeline,
    "foreshadow": _foreshadow,
    "payoff": _payoff,
    "scene_transition": _scene_transition,
    "character_state": _character_state,
    "series_constraint": _text_check("series_id"),
    "continuity": _continuity,
}
