"""M0′ smoke tests: the package imports, the entry point resolves,
and nothing under tidemark/ imports the legacy tree or Flask."""

from __future__ import annotations

import importlib
import pkgutil
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Matches `import flask`, `from flask import ...`, `import legacy`, `from legacy.x import ...`,
# `import app`, `from app import ...` — as import statements, not as substrings.
_FORBIDDEN_IMPORT = re.compile(
    r"(?m)^\s*(?:"
    r"import\s+(?:flask|legacy|app)\b"
    r"|from\s+(?:flask|legacy|app)(?:\.|\s)"
    r")"
)


def test_version_string() -> None:
    import tidemark

    assert tidemark.__version__ == "0.1.0"


def test_cli_main_importable() -> None:
    from tidemark.cli.main import main

    assert callable(main)


def test_cli_version_runs() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "tidemark.cli.main", "--version"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == "tidemark 0.1.0"


@pytest.mark.parametrize(
    "module_name",
    [
        "tidemark",
        "tidemark.core",
        "tidemark.store",
        "tidemark.daemon",
        "tidemark.cli",
        "tidemark.cli.main",
        "tidemark.gui",
        "tidemark.profiles",
    ],
)
def test_no_legacy_or_flask_imports(module_name: str) -> None:
    module = importlib.import_module(module_name)
    source = Path(module.__file__).read_text(encoding="utf-8")
    match = _FORBIDDEN_IMPORT.search(source)
    assert match is None, (
        f"{module_name} has a forbidden import at {match.group(0)!r}"
    )


def test_packages_have_no_unexpected_modules() -> None:
    """Walk tidemark/ and assert every discovered module imports cleanly."""
    import tidemark

    failures: list[str] = []
    for info in pkgutil.walk_packages(tidemark.__path__, prefix="tidemark."):
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{info.name}: {exc}")
    assert not failures, failures
