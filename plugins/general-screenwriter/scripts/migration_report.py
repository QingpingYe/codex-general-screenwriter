"""Read-only migration reporting; never rewrites user or store data."""

from dataclasses import dataclass
from typing import Any, Mapping


KNOWN_STATUSES = {
    "matched", "v1_compatible", "missing", "ambiguous", "manual_action",
}
STANDARD_SOURCE_KINDS = {
    "run_manifest", "artifact_id", "knowledge_key",
    "skill_reference", "illustration_flow", "export_path",
}


@dataclass(frozen=True)
class MigrationItem:
    key: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class MigrationReport:
    source_kind: str
    source_version: int
    target_version: int
    items: tuple[MigrationItem, ...]
    rollback: Mapping[str, Any]

    @property
    def manual_actions(self) -> tuple[str, ...]:
        return tuple(
            f"{item.key}: {item.detail}"
            for item in self.items
            if item.status in {"ambiguous", "manual_action"}
        )


def build_migration_report(
    source_kind: str, source_version: int, target_version: int, inventory
) -> MigrationReport:
    if not isinstance(source_kind, str) or not source_kind.strip():
        raise ValueError("source_kind must be a non-empty string")
    items: list[MigrationItem] = []
    for entry in inventory:
        if (not isinstance(entry, Mapping)
                or not isinstance(entry.get("key"), str) or not entry["key"].strip()):
            items.append(MigrationItem(
                key="<unnamed>", status="missing",
                detail="inventory entry without a stable key",
            ))
            continue
        status = entry.get("status")
        if status not in KNOWN_STATUSES:
            status = "matched"
        items.append(MigrationItem(
            key=entry["key"],
            status=status,
            detail=str(entry.get("detail", "")),
        ))
    return MigrationReport(
        source_kind=source_kind,
        source_version=int(source_version),
        target_version=int(target_version),
        items=tuple(items),
        rollback={
            "mode": "read_only",
            "writes": 0,
            "hint": "restore from source revisions; no data rewritten",
        },
    )


def report_to_dict(report: MigrationReport) -> dict[str, Any]:
    return {
        "source_kind": report.source_kind,
        "source_version": report.source_version,
        "target_version": report.target_version,
        "items": [
            {"key": item.key, "status": item.status, "detail": item.detail}
            for item in report.items
        ],
        "rollback": dict(report.rollback),
    }
