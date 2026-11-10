"""Entry points must register every table, otherwise foreign keys cannot be resolved at flush time.

Found by the live smoke test: `python -m mixt.cli create-owner` failed because only the identity
models were loaded. Each entry point is imported in a fresh interpreter to check this.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from mixt.models import Base

EXPECTED = sorted(Base.metadata.tables)


@pytest.mark.parametrize("module", ["mixt.cli", "mixt.main"])
def test_entry_point_registers_all_tables(module: str) -> None:
    code = f"import {module}\nfrom mixt.core.db import Base\nprint(','.join(sorted(Base.metadata.tables)))\n"
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert result.stdout.strip().split(",") == EXPECTED
