"""Entry points must register every table and event consumer (foreign keys, timeline, reminders).

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
    code = (
        f"import {module}\n"
        "from mixt.core.db import Base\n"
        "from mixt.modules.events import service as events\n"
        "print(','.join(sorted(Base.metadata.tables)))\n"
        "print(','.join(sorted(c.name for c in events.consumers())))\n"
        "print(','.join(events.action_types()))\n"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    tables, consumers, actions = result.stdout.strip().split("\n")
    assert tables.split(",") == EXPECTED
    assert consumers == "engagement.timeline"
    assert actions == "engagement.create_task"
