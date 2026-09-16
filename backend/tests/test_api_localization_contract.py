from __future__ import annotations

import ast
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1] / "app" / "api"


def test_api_routes_do_not_embed_user_facing_message_fields() -> None:
    """Frontend owns locale; API route literals must remain locale-neutral."""
    violations: list[str] = []
    for path in sorted(API_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == "message":
                    violations.append(f"{path.name}:{key.lineno}")
    assert not violations, (
        "API responses must use error_code + params; translate in the frontend: "
        + ", ".join(violations)
    )
