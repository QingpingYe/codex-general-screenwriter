from dataclasses import dataclass


SCOPE_ORDER = (
    "task",
    "scene",
    "episode",
    "season",
    "project",
    "series",
    "genre",
    "medium",
    "global",
)


@dataclass(frozen=True)
class ScopeChainNode:
    scope_type: str
    scope_id: str
    authority: str = "system"

    def __post_init__(self):
        if self.scope_type not in SCOPE_ORDER:
            raise ValueError(f"unknown scope_type: {self.scope_type}")
        if not isinstance(self.scope_id, str) or not self.scope_id.strip():
            raise ValueError("scope_id must be non-empty")


@dataclass(frozen=True)
class ScopeRef:
    task_id: str | None = None
    scene_id: str | None = None
    episode_id: str | None = None
    season_id: str | None = None
    project_id: str | None = None
    series_id: str | None = None
    genre_ids: tuple[str, ...] = ()
    medium_id: str | None = None
    authority: str = "system"


def expand_scope_chain(scope: ScopeRef):
    if not isinstance(scope, ScopeRef):
        raise TypeError("scope must be a ScopeRef")
    chain: list[ScopeChainNode] = []
    for scope_type in SCOPE_ORDER:
        if scope_type == "genre":
            for genre_id in scope.genre_ids:
                chain.append(ScopeChainNode(scope_type, genre_id, scope.authority))
            continue
        value = getattr(scope, f"{scope_type}_id", None)
        if value:
            chain.append(ScopeChainNode(scope_type, value, scope.authority))
    if not chain:
        raise ValueError("scope ref has no scope identifiers")
    chain.append(ScopeChainNode("global", "all", scope.authority))
    return tuple(chain)


def scope_matches(chain, node):
    if not isinstance(node, ScopeChainNode):
        return False
    return any(
        item.scope_type == node.scope_type and item.scope_id == node.scope_id
        for item in chain
    )
