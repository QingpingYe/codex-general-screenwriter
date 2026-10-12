"""Tree-level release gate for user and system skill packs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "general-screenwriter"
_HUB_SCRIPT = (
    PLUGIN_ROOT / "skills" / "user-skill-hub" / "scripts" / "user_skill_hub.py"
)
_HUB = None


def _load_hub():
    global _HUB
    if _HUB is None:
        for path in (PLUGIN_ROOT / "scripts", _HUB_SCRIPT.parent):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
        spec = importlib.util.spec_from_file_location(
            "general_screenwriter_user_skill_hub_gate", _HUB_SCRIPT
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载用户技能模块：{_HUB_SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _HUB = module
    return _HUB


def check_plugin_skill_trees(plugin_root: Path) -> tuple[str, ...]:
    hub = _load_hub()
    root = Path(plugin_root)
    for validate in (hub.validate_user_skill_tree, hub.validate_system_skill_tree):
        try:
            validate(root)
        except hub.UserSkillHubError as error:
            return (str(error),)
    return ()


def main() -> int:
    errors = check_plugin_skill_trees(PLUGIN_ROOT)
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print("用户/系统技能树校验失败", file=sys.stderr)
        return 1
    print("用户/系统技能树校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
