"""Deterministic knowledge scope resolution over loaded evidence bundles."""

from dataclasses import dataclass, replace

from dependencies import build_dependency_record as _build_v1_record
from load_knowledge import ConflictReport
from scope_model import ScopeChainNode, ScopeRef, expand_scope_chain, scope_matches


AUTHORITY_RANK = {
    "system": 0,
    "type_pack": 1,
    "series": 2,
    "project": 3,
    "user_experiment": 4,
}


@dataclass(frozen=True)
class KnowledgeResolution:
    matches: tuple
    conflicts: tuple
    warnings: tuple
    scope_chain: tuple
    knowledge_schema: str
    rejected: tuple = ()


def build_scope_ref(context):
    if context is None:
        raise ValueError("context is required")
    return ScopeRef(
        task_id=None,
        scene_id=getattr(context, "scene_id", None),
        episode_id=getattr(context, "episode_id", None),
        season_id=getattr(context, "season_id", None),
        project_id=getattr(context, "project_id", None),
        series_id=getattr(context, "series_id", None),
        genre_ids=tuple(getattr(context, "genre_ids", ()) or ()),
        medium_id=getattr(context, "medium_id", None),
    )


def resolve_knowledge(bundle, query):
    if bundle is None or query is None:
        raise ValueError("bundle and query are required")
    scope_ref = query.scope_ref
    if scope_ref is None:
        series_id = getattr(query, "series_id", "") or None
        scope_ref = ScopeRef(project_id=query.project_id, series_id=series_id)
    chain = expand_scope_chain(scope_ref)

    candidates = []
    rejected = []
    warnings = []
    for item in bundle.items:
        node = _scope_node(item)
        if node is not None and not scope_matches(chain, node):
            warnings.append(f"{item.key} 不在当前 scope chain 内，已拒绝")
            rejected.append(item)
            continue
        candidates.append(item)

    topics = {}
    for item in candidates:
        topics.setdefault(_topic(item), []).append(item)

    winners = []
    conflicts = []
    for topic in sorted(topics):
        group = sorted(
            topics[topic],
            key=lambda it: (
                _chain_index(it, chain),
                AUTHORITY_RANK.get(_authority(it), 99),
                it.key,
            ),
        )
        winner = group[0]
        if _authority(winner) == "user_experiment" and any(
            _authority(it) != "user_experiment" for it in group
        ):
            warnings.append(f"{winner.key} 是 user_experiment，不能覆盖更高权威知识")
            rejected.append(winner)
            group = [it for it in group if _authority(it) != "user_experiment"]
            winner = group[0]
        losers = group[1:]
        for loser in losers:
            if _authority(loser) == "user_experiment":
                warnings.append(f"{loser.key} 是 user_experiment，不能覆盖更高权威知识")
                rejected.append(loser)
        if losers:
            conflicts.append(ConflictReport(
                scope_type=_winner_scope_type(winner),
                scope_id=_winner_scope_id(winner),
                reason="same topic claimed by multiple scope nodes; nearest scope wins",
                keys=tuple(sorted(it.key for it in (winner, *losers))),
            ))
        winners.append(winner)

    winners.sort(key=lambda it: _chain_index(it, chain))
    knowledge_schema = (
        "knowledge-scope-v2"
        if any(it.scope is not None for it in winners)
        else "v1"
    )
    return KnowledgeResolution(
        matches=tuple(winners),
        conflicts=tuple(conflicts),
        warnings=tuple(warnings),
        scope_chain=chain,
        knowledge_schema=knowledge_schema,
        rejected=tuple(rejected),
    )


def build_dependency_record(bundle, artifact_id, artifact_type, resolution=None):
    if resolution is None:
        return _build_v1_record(bundle, artifact_id, artifact_type)
    filtered = replace(bundle, items=tuple(resolution.matches))
    record = _build_v1_record(filtered, artifact_id, artifact_type)
    chain = tuple(
        {
            "scope_type": node.scope_type,
            "scope_id": node.scope_id,
            "authority": node.authority,
        }
        for node in resolution.scope_chain
    )
    return replace(
        record,
        scope_chain=chain,
        knowledge_schema="knowledge-scope-v2",
    )


def _scope_node(evidence):
    if getattr(evidence, "scope", None) is None:
        return None
    scope = evidence.scope
    return ScopeChainNode(scope.scope_type, scope.scope_id, scope.authority)


def _topic(evidence):
    return evidence.key.rsplit("/", 1)[-1]


def _authority(evidence):
    node = _scope_node(evidence)
    if node is not None:
        return node.authority
    return "project"


def _chain_index(evidence, chain):
    node = _scope_node(evidence)
    if node is None:
        for index, item in enumerate(chain):
            if item.scope_type == "project":
                return index
        return 0
    for index, item in enumerate(chain):
        if item.scope_type == node.scope_type and item.scope_id == node.scope_id:
            return index
    return len(chain)


def _winner_scope_type(evidence):
    node = _scope_node(evidence)
    if node is not None:
        return node.scope_type
    return "project"


def _winner_scope_id(evidence):
    node = _scope_node(evidence)
    if node is not None:
        return node.scope_id
    parts = evidence.key.split("/")
    return parts[1] if len(parts) == 3 else evidence.key
