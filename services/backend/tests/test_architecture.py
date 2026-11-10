"""Module boundaries (docs/01 §4): a module never imports another module's ORM models.

Cross-module work goes through the other module's ``service`` (or ``access``/``catalogue``)
interface. ``mixt.core`` never depends on ``mixt.modules``.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "mixt"
PRIVATE = {"models", "repository"}


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
    return names


def test_modules_do_not_import_each_others_models() -> None:
    violations = []
    for path in (PACKAGE / "modules").rglob("*.py"):
        own = path.relative_to(PACKAGE / "modules").parts[0]
        for name in _imports(path):
            parts = name.split(".")
            if len(parts) >= 4 and parts[:2] == ["mixt", "modules"] and parts[2] != own and parts[3] in PRIVATE:
                violations.append(f"{path.relative_to(PACKAGE)} imports {name}")
    assert violations == []


def test_core_does_not_depend_on_modules() -> None:
    violations = [
        f"{path.relative_to(PACKAGE)} imports {name}"
        for path in (PACKAGE / "core").rglob("*.py")
        for name in _imports(path)
        if name.startswith(("mixt.modules", "mixt.api"))
    ]
    assert violations == []
