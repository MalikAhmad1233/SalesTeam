"""Registers event consumers, scheduled-action handlers and setting validators.

Imported by every entry point (API app, CLI, worker) so behaviour is identical everywhere.
"""

from __future__ import annotations

import mixt.models  # noqa: F401  (registers every table so foreign keys resolve)
from mixt.modules.engagement import consumers as engagement_consumers
from mixt.modules.integrations import service as integrations
from mixt.modules.messaging import service as messaging
from mixt.modules.pipeline import stages as pipeline_stages
from mixt.modules.quotations import service as quotations

_DONE = False


def wire() -> None:
    global _DONE  # noqa: PLW0603
    if _DONE:
        return
    engagement_consumers.register()
    pipeline_stages.register()
    quotations.register()
    integrations.register()
    messaging.register()
    _DONE = True


wire()
