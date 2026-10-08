#!/usr/bin/env python3
"""Export literal native UI tokens for the dependency-free browser prototype."""

from __future__ import annotations

import ast
import json
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def literal_constants(path: Path) -> dict[str, object]:
    """Read literal assignments without importing AppKit or starting the app."""
    constants = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                with suppress(ValueError, TypeError):
                    constants[target.id] = ast.literal_eval(value)
    return constants


def main() -> None:
    tokens = literal_constants(ROOT / "src/hrm_live/ui/tokens.py")
    popover = literal_constants(ROOT / "src/hrm_live/ui/popover.py")
    tokens.update({key: popover[key] for key in ("POPOVER_WIDTH", "HERO_GAUGE_SIZE")})
    path = ROOT / "prototype/tokens.json"
    path.write_text(json.dumps(tokens, indent=2) + "\n")
    print(f"Updated {path.relative_to(ROOT)} from native UI tokens")


if __name__ == "__main__":
    main()
