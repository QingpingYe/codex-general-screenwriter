"""Deterministic content-level checks for the tv_longform minimal type pack."""

from typing import Mapping

from quality_gate_contract import QualityCheckResult
from script_content import (
    ParsedScript,
    ScriptContentError,
    parse_episode_script,
    scene_dialogue_lines,
)


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

FUNCTION_MIN_CHARS = 6


def validate_tv_longform_rules(check_id, artifact, context, references=None) -> QualityCheckResult:
    if check_id not in CHECK_STAGES:
        raise ValueError(f"unknown tv_longform check: {check_id!r}")
    stage_id, blocking_policy = CHECK_STAGES[check_id]
    artifact_id = artifact.get("artifact_id") if isinstance(artifact, dict) else None
    if not isinstance(artifact_id, str) or not artifact_id.strip():
        artifact_id = "episode_script"
    reference_map = references if isinstance(references, Mapping) else {}
    try:
        parsed = parse_episode_script(artifact)
    except ScriptContentError as error:
        status = "fail"
        message = "剧本内容无法解析"
        evidence = {"errors": list(error.errors)}
    else:
        status, message, evidence = _CHECKS[check_id](artifact, parsed, reference_map)
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


def _reference(references: Mapping, artifact_id: str):
    value = references.get(artifact_id)
    return value if isinstance(value, Mapping) else None


def _season_arc(artifact, parsed: ParsedScript, references: Mapping):
    season_arc = _reference(references, "season_arc")
    if season_arc is None:
        return "fail", "缺少季节弧线引用", {"reference": "season_arc"}
    beats = season_arc.get("beats")
    if not isinstance(beats, list) or not beats:
        return "fail", "季节弧线缺少节拍", {"reference": "season_arc"}
    beat_ref = artifact.get("arc_beat_ref")
    for beat in beats:
        if (isinstance(beat, Mapping)
                and beat.get("beat_id") == beat_ref
                and _nonempty_text(beat.get("goal"))):
            return "pass", "", {
                "arc_beat_ref": beat_ref,
                "goal": beat["goal"],
                "beats": len(beats),
            }
    return "fail", f"arc_beat_ref 无法解析：{beat_ref!r}", {
        "arc_beat_ref": beat_ref,
        "beats": len(beats),
    }


def _episode_function(artifact, parsed: ParsedScript, references: Mapping):
    function = artifact.get("episode_function")
    if not _nonempty_text(function) or len(function.strip()) < FUNCTION_MIN_CHARS:
        return "fail", f"episode_function 至少需要 {FUNCTION_MIN_CHARS} 字", {
            "episode_function": function,
        }
    function = function.strip()
    episode_list = _reference(references, "episode_list")
    episode_id = artifact.get("episode_id")
    if episode_list is not None:
        episodes = episode_list.get("episodes")
        if isinstance(episodes, Mapping):
            entry = episodes.get(episode_id)
            if isinstance(entry, Mapping):
                expected = entry.get("function")
                if expected != function:
                    return "fail", "episode_function 与集列表不一致", {
                        "expected": expected,
                        "actual": function,
                    }
    return "pass", "", {"episode_function": function}


def _timeline(artifact, parsed: ParsedScript, references: Mapping):
    timeline = artifact.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        return "fail", "时间线缺失或为空", {"timeline": timeline}
    ledger = _reference(references, "timeline_ledger")
    last_order = ledger.get("last_order") if ledger is not None else None
    has_last_order = isinstance(last_order, int) and not isinstance(last_order, bool)
    episode_id = artifact.get("episode_id", "e1")
    violations, regressions, flashbacks = [], [], []
    previous_order = None
    for index, event in enumerate(timeline):
        label = f"timeline[{index}]"
        if not isinstance(event, Mapping):
            violations.append(f"{label} 必须是对象")
            continue
        order = event.get("order")
        if not isinstance(order, int) or isinstance(order, bool):
            violations.append(f"{label}.order 必须是整数")
            continue
        if previous_order is not None and order <= previous_order:
            violations.append(f"{label}.order 必须严格递增")
        previous_order = order
        scene_id = event.get("scene_id")
        if not isinstance(scene_id, str) or scene_id not in parsed.scene_index:
            violations.append(f"{label}.scene_id 引用未知场景：{scene_id!r}")
        if event.get("flashback") is True:
            flashbacks.append(f"{episode_id}:order-{order}")
            continue
        if has_last_order and order <= last_order:
            regressions.append(f"{episode_id}:order-{order}")
    evidence = {
        "regressions": regressions,
        "flashbacks": flashbacks,
        "violations": violations,
    }
    if regressions:
        return "fail", "事件顺序与上一集时间线冲突", evidence
    if violations:
        return "fail", "时间线不达标：" + "；".join(violations), evidence
    return "pass", "", evidence


def _foreshadow(artifact, parsed: ParsedScript, references: Mapping):
    foreshadows = artifact.get("foreshadows")
    if not isinstance(foreshadows, list) or not foreshadows:
        return "fail", "伏笔台账缺失或为空", {"foreshadows": foreshadows}
    payoff_ids = {
        item.get("foreshadow_id")
        for item in artifact.get("payoffs", [])
        if isinstance(item, Mapping)
    }
    violations, open_ids, seen = [], [], set()
    for index, item in enumerate(foreshadows):
        label = f"foreshadows[{index}]"
        if not isinstance(item, Mapping):
            violations.append(f"{label} 必须是对象")
            continue
        foreshadow_id = item.get("id")
        if not _nonempty_text(foreshadow_id):
            violations.append(f"{label}.id 必须是非空字符串")
            continue
        foreshadow_id = foreshadow_id.strip()
        if foreshadow_id in seen:
            violations.append(f"{label}.id 重复：{foreshadow_id}")
            continue
        seen.add(foreshadow_id)
        source = item.get("scene_id")
        if not isinstance(source, str) or source not in parsed.scene_index:
            violations.append(f"{label}.scene_id 引用未知场景：{source!r}")
        if not _nonempty_text(item.get("purpose")):
            violations.append(f"{label}.purpose 不能为空")
        if foreshadow_id not in payoff_ids:
            open_ids.append(foreshadow_id)
            if not _nonempty_text(item.get("planned_payoff")):
                violations.append(f"{label} 未回收且缺少 planned_payoff")
    evidence = {"open_foreshadows": sorted(open_ids), "violations": violations}
    if violations:
        return "fail", "伏笔台账不达标：" + "；".join(violations), evidence
    return "pass", "", evidence


def _payoff(artifact, parsed: ParsedScript, references: Mapping):
    payoffs = artifact.get("payoffs")
    if not isinstance(payoffs, list) or not payoffs:
        return "fail", "回收台账缺失或为空", {"payoffs": payoffs}
    local_foreshadows = {}
    for item in artifact.get("foreshadows", []):
        if isinstance(item, Mapping) and _nonempty_text(item.get("id")):
            local_foreshadows[item["id"].strip()] = item
    ledger = _reference(references, "continuity_ledger")
    open_ids = set()
    if ledger is not None and isinstance(ledger.get("open_foreshadows"), list):
        for item in ledger["open_foreshadows"]:
            if isinstance(item, Mapping) and _nonempty_text(item.get("id")):
                open_ids.add(item["id"].strip())
    violations, seen = [], set()
    for index, item in enumerate(payoffs):
        label = f"payoffs[{index}]"
        if not isinstance(item, Mapping):
            violations.append(f"{label} 必须是对象")
            continue
        foreshadow_id = item.get("foreshadow_id")
        if not _nonempty_text(foreshadow_id):
            violations.append(f"{label}.foreshadow_id 不能为空")
            continue
        foreshadow_id = foreshadow_id.strip()
        if foreshadow_id in seen:
            violations.append(f"{label} 重复回收：{foreshadow_id}")
            continue
        seen.add(foreshadow_id)
        if foreshadow_id not in local_foreshadows and foreshadow_id not in open_ids:
            violations.append(f"{label} 指向未登记伏笔：{foreshadow_id}")
        if not _nonempty_text(item.get("resolution")):
            violations.append(f"{label}.resolution 不能为空")
        scene_id = item.get("scene_id")
        payoff_index = parsed.scene_index.get(scene_id) if isinstance(scene_id, str) else None
        if payoff_index is None:
            violations.append(f"{label}.scene_id 引用未知场景：{scene_id!r}")
        elif foreshadow_id in local_foreshadows:
            setup_scene = local_foreshadows[foreshadow_id].get("scene_id")
            setup_index = (
                parsed.scene_index.get(setup_scene)
                if isinstance(setup_scene, str) else None
            )
            if setup_index is not None and payoff_index < setup_index:
                violations.append(f"{label} 回收早于伏笔场景")
    evidence = {"resolved": sorted(seen), "violations": violations}
    if violations:
        return "fail", "回收台账不达标：" + "；".join(violations), evidence
    return "pass", "", evidence


def _scene_transition(artifact, parsed: ParsedScript, references: Mapping):
    violations = []
    checked_pairs = 0
    for current, following in zip(parsed.scenes, parsed.scenes[1:]):
        same_location = current.location == following.location
        same_time = current.time_of_day == following.time_of_day
        if same_location and same_time:
            continue
        checked_pairs += 1
        if not _nonempty_text(current.transition):
            violations.append(f"{current.scene_id}->{following.scene_id}")
    evidence = {"checked_pairs": checked_pairs, "violations": violations}
    if violations:
        return "fail", "场次连接缺少转场说明", evidence
    return "pass", "", evidence


def _character_state(artifact, parsed: ParsedScript, references: Mapping):
    states = artifact.get("character_states")
    if not isinstance(states, list) or not states:
        return "fail", "人物状态台账缺失或为空", {"character_states": states}
    arc_map = _reference(references, "character_arc_map")
    previous_states = {}
    if arc_map is not None:
        latest = arc_map.get("latest")
        if isinstance(latest, Mapping) and isinstance(latest.get("states"), list):
            for entry in latest["states"]:
                if isinstance(entry, Mapping) and _nonempty_text(entry.get("name")):
                    previous_states[entry["name"].strip()] = entry.get("state")
    series_id = artifact.get("series_id", "s1")
    episode_id = artifact.get("episode_id", "e1")
    violations, conflicts, registered = [], [], []
    for index, item in enumerate(states):
        label = f"character_states[{index}]"
        if not isinstance(item, Mapping):
            violations.append(f"{label} 必须是对象")
            continue
        name = item.get("name")
        if not _nonempty_text(name):
            violations.append(f"{label}.name 不能为空")
            continue
        name = name.strip()
        registered.append(name)
        prior = item.get("prior_state")
        current = item.get("state")
        if not _nonempty_text(prior):
            violations.append(f"{name}.prior_state 不能为空")
        if not _nonempty_text(current):
            violations.append(f"{name}.state 不能为空")
        scene_id = item.get("transition_scene_id")
        scene_index = parsed.scene_index.get(scene_id) if isinstance(scene_id, str) else None
        if scene_index is None:
            violations.append(
                f"{label}.transition_scene_id 引用未知场景：{scene_id!r}"
            )
        elif (_nonempty_text(prior) and _nonempty_text(current)
              and prior.strip() != current.strip()):
            speakers = {
                line.speaker for line in scene_dialogue_lines(parsed, scene_id)
            }
            if name not in speakers:
                violations.append(f"{name} 在状态变化场景缺少台词支撑")
        if name in previous_states and _nonempty_text(prior):
            recorded = previous_states[name]
            if _nonempty_text(recorded) and recorded.strip() != prior.strip():
                conflicts.append(f"{series_id}:{episode_id}:character-state")
    if arc_map is None:
        violations.append("缺少上一集角色状态引用")
    unknown = sorted(parsed.speakers - set(registered))
    if unknown:
        violations.append(f"未登记角色出现在台词中：{', '.join(unknown)}")
    evidence = {
        "conflicts": sorted(set(conflicts)),
        "unknown_speakers": unknown,
        "violations": violations,
    }
    if conflicts:
        return "fail", "人物状态与上一集冲突，已报告不合并", evidence
    if violations:
        return "fail", "人物状态不达标：" + "；".join(violations), evidence
    return "pass", "", evidence


def _series_constraint(artifact, parsed: ParsedScript, references: Mapping):
    bible = _reference(references, "series_bible")
    if bible is None:
        return "fail", "缺少系列圣经引用", {"reference": "series_bible"}
    violations = []
    series_id = artifact.get("series_id")
    bible_series_id = bible.get("series_id")
    if not _nonempty_text(series_id):
        violations.append("series_id 不能为空")
    elif _nonempty_text(bible_series_id) and series_id.strip() != bible_series_id.strip():
        violations.append("series_id 与系列圣经不一致")
    bible_characters = set()
    if isinstance(bible.get("characters"), list):
        for item in bible["characters"]:
            if isinstance(item, Mapping) and _nonempty_text(item.get("name")):
                bible_characters.add(item["name"].strip())
    unknown = sorted(parsed.speakers - bible_characters)
    if unknown:
        violations.append(f"台词角色不在系列圣经中：{', '.join(unknown)}")
    banned_hits = []
    banned_terms = bible.get("banned_terms")
    if isinstance(banned_terms, list):
        texts = [line.text for scene in parsed.scenes for line in scene.lines]
        for term in banned_terms:
            if _nonempty_text(term) and any(term.strip() in text for text in texts):
                banned_hits.append(term.strip())
    if banned_hits:
        violations.append(f"命中禁用项：{', '.join(banned_hits)}")
    evidence = {
        "series_id": series_id,
        "unknown_speakers": unknown,
        "banned_hits": banned_hits,
        "violations": violations,
    }
    if violations:
        return "fail", "系列约束不达标：" + "；".join(violations), evidence
    return "pass", "", evidence


def _continuity(artifact, parsed: ParsedScript, references: Mapping):
    ledger_ref = artifact.get("continuity_ledger_ref")
    if not _nonempty_text(ledger_ref):
        return "fail", "缺少连续性台账引用", {"continuity_ledger_ref": ledger_ref}
    ledger = _reference(references, "continuity_ledger")
    if ledger is None:
        return "fail", "缺少连续性台账引用产物", {
            "continuity_ledger_ref": ledger_ref,
        }
    violations = []
    linked = ledger.get("linked_artifacts")
    if not isinstance(linked, list) or not linked:
        violations.append("linked_artifacts 必须是非空数组")
        linked = []
    target_id = artifact.get("artifact_id", "episode_script")
    for artifact_id in linked:
        if artifact_id == target_id:
            continue
        if _reference(references, artifact_id) is None:
            violations.append(f"缺少引用产物：{artifact_id}")
    entries = ledger.get("entries")
    if not isinstance(entries, list) or not entries:
        violations.append("entries 必须是非空数组")
    else:
        for index, entry in enumerate(entries):
            if (not isinstance(entry, Mapping)
                    or not _nonempty_text(entry.get("field"))
                    or not _nonempty_text(entry.get("value"))):
                violations.append(f"entries[{index}] 字段或值缺失")
    conflicts = ledger.get("conflicts")
    if conflicts:
        violations.append(f"台账冲突未解决：{conflicts}")
    evidence = {
        "ledger": ledger_ref,
        "linked_artifacts": linked,
        "violations": violations,
    }
    if violations:
        return "fail", "连续性台账不达标：" + "；".join(violations), evidence
    return "pass", "", evidence


_CHECKS = {
    "season_arc": _season_arc,
    "episode_function": _episode_function,
    "timeline": _timeline,
    "foreshadow": _foreshadow,
    "payoff": _payoff,
    "scene_transition": _scene_transition,
    "character_state": _character_state,
    "series_constraint": _series_constraint,
    "continuity": _continuity,
}
