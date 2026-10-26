"""Stable, independent setup checks and their JSON report envelope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


SETUP_REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SetupCheck:
    check_id: str
    status: str
    reason_code: str | None
    message: str
    ai_next_actions: tuple[str, ...]
    human_action: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "message": self.message,
            "ai_next_actions": list(self.ai_next_actions),
            "human_action": self.human_action,
        }


def render_setup_report(checks: Sequence[SetupCheck]) -> dict[str, Any]:
    """Render independent checks without collapsing them into one install flag."""
    normalized = tuple(checks)
    blocking = [check for check in normalized if check.status != "ready"]
    ready = bool(normalized) and not blocking
    status = "ready" if ready else (blocking[0].status if blocking else "needs_context")
    return {
        "schema_version": SETUP_REPORT_SCHEMA_VERSION,
        "status": status,
        "ready": ready,
        "blocking_checks": [check.check_id for check in blocking],
        "checks": [check.to_dict() for check in normalized],
        "ai_next_actions": list(dict.fromkeys(
            action for check in blocking for action in check.ai_next_actions
        )),
        "human_action": next(
            (check.human_action for check in blocking if check.human_action),
            None,
        ),
    }
