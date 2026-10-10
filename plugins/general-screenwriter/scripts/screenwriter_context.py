"""Validated creative context shared by screenplay media workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from type_registry import (
    TypeRegistryError,
    canonical_medium_id,
    default_type_registry,
    resolve_type_pack,
)


class ContextError(ValueError):
    """Raised when a creative context cannot be normalized."""


@dataclass(frozen=True)
class CreativeContext:
    medium_id: str
    genre_ids: tuple[str, ...] = ()
    series_id: str | None = None
    project_id: str | None = None
    season_id: str | None = None
    episode_id: str | None = None
    scene_id: str | None = None
    delivery_form: str | None = None


_CONTEXT_FIELDS = {
    "medium_id", "genre_ids", "series_id", "project_id", "season_id",
    "episode_id", "scene_id", "delivery_form",
}
_OPTIONAL_IDS = ("series_id", "project_id", "season_id", "episode_id", "scene_id")


def _optional_identifier(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContextError(f"{label} must be null or a non-empty string")
    return value.strip()


def validate_context(
    context: CreativeContext,
    require_project: bool = False,
) -> CreativeContext:
    """Validate and return a canonical immutable context."""
    if not isinstance(context, CreativeContext):
        raise ContextError("context must be a CreativeContext")
    try:
        medium_id = canonical_medium_id(context.medium_id)
    except TypeRegistryError as error:
        raise ContextError(str(error)) from error

    if not isinstance(context.genre_ids, (tuple, list)):
        raise ContextError("genre_ids must be an array of non-empty strings")
    genres: list[str] = []
    seen_genres: set[str] = set()
    for genre in context.genre_ids:
        if not isinstance(genre, str) or not genre.strip():
            raise ContextError("genre_ids entries must be non-empty strings")
        genre = genre.strip()
        key = genre.casefold()
        if key not in seen_genres:
            seen_genres.add(key)
            genres.append(genre)

    optional = {
        name: _optional_identifier(getattr(context, name), name)
        for name in _OPTIONAL_IDS
    }
    if require_project and optional["project_id"] is None:
        raise ContextError("project_id is required for a new project context")

    delivery_form = _optional_identifier(context.delivery_form, "delivery_form")
    if delivery_form is not None:
        pack = resolve_type_pack(default_type_registry(), medium_id)
        allowed_forms = {form.casefold() for form in pack.delivery_forms}
        if delivery_form.casefold() not in allowed_forms:
            raise ContextError(
                f"delivery_form {delivery_form!r} is not supported by {medium_id}"
            )
        delivery_form = next(
            form for form in pack.delivery_forms
            if form.casefold() == delivery_form.casefold()
        )

    return CreativeContext(
        medium_id=medium_id,
        genre_ids=tuple(genres),
        series_id=optional["series_id"],
        project_id=optional["project_id"],
        season_id=optional["season_id"],
        episode_id=optional["episode_id"],
        scene_id=optional["scene_id"],
        delivery_form=delivery_form,
    )


def context_to_dict(context: CreativeContext) -> dict[str, Any]:
    """Serialize a validated context as a JSON-compatible dictionary."""
    context = validate_context(context)
    return {
        "medium_id": context.medium_id,
        "genre_ids": list(context.genre_ids),
        "series_id": context.series_id,
        "project_id": context.project_id,
        "season_id": context.season_id,
        "episode_id": context.episode_id,
        "scene_id": context.scene_id,
        "delivery_form": context.delivery_form,
    }


def context_from_dict(
    payload: dict[str, Any],
    require_project: bool = False,
) -> CreativeContext:
    """Parse, validate, and normalize a JSON creative context."""
    if not isinstance(payload, dict):
        raise ContextError("context must be an object")
    unknown = set(payload) - _CONTEXT_FIELDS
    if unknown:
        raise ContextError(f"unknown context fields: {', '.join(sorted(unknown))}")
    if "medium_id" not in payload:
        raise ContextError("medium_id is required")
    context = CreativeContext(
        medium_id=payload["medium_id"],
        genre_ids=payload.get("genre_ids", ()),
        series_id=payload.get("series_id"),
        project_id=payload.get("project_id"),
        season_id=payload.get("season_id"),
        episode_id=payload.get("episode_id"),
        scene_id=payload.get("scene_id"),
        delivery_form=payload.get("delivery_form"),
    )
    return validate_context(context, require_project=require_project)
