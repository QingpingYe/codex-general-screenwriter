"""Build the deterministic skill index used for medium routing."""

from __future__ import annotations

import json
from pathlib import Path


SCHEMA_VERSION = 1
SUPPORT_FIELDS = (
    "medium_ids", "genre_ids", "series_ids", "project_ids", "stage_ids",
    "artifact_ids",
)


def _entry(skill_id: str, layer: str, supports: dict) -> dict:
    return {
        "skill_id": skill_id,
        "layer": layer,
        "supports": {field: list(supports[field]) for field in SUPPORT_FIELDS},
    }


def build_index(plugin_root: Path) -> dict:
    root = Path(plugin_root).resolve()
    skills_root = root / "skills"
    entries = []
    if skills_root.is_dir():
        for directory in sorted(skills_root.iterdir(), key=lambda path: path.name):
            if not directory.is_dir() or directory.name == "user-skills":
                continue
            meta_path = directory / "skill-meta.json"
            if not meta_path.is_file():
                continue
            metadata = json.loads(meta_path.read_text(encoding="utf-8-sig"))
            entries.append(
                _entry(metadata["skill_id"], "system", metadata["supports"])
            )
    user_root = skills_root / "user-skills"
    if user_root.is_dir():
        for directory in sorted(user_root.iterdir(), key=lambda path: path.name):
            if not directory.is_dir():
                continue
            manifest_path = directory / "manifest.json"
            if not manifest_path.is_file():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            entries.append(
                _entry(manifest["skill_id"], "user", manifest["supports"])
            )
    entries.sort(key=lambda entry: entry["skill_id"])
    return {"schema_version": SCHEMA_VERSION, "entries": entries}


def render_index(index: dict) -> str:
    return json.dumps(index, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    root = Path(__file__).resolve().parents[1] / "plugins" / "general-screenwriter"
    target = root / "config" / "skill-index.json"
    target.write_text(render_index(build_index(root)), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
