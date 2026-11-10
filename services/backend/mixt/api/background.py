"""Work started right after a request commits, so customers don't wait for the next worker poll.

The worker remains the safety net: anything not finished here is picked up on its next run.
"""

from __future__ import annotations

import uuid

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from mixt.core.config import get_config
from mixt.core.db import _sessionmaker_for
from mixt.core.logging import get_logger
from mixt.modules.events import service as events

log = get_logger("mixt.background")


def run_action_soon(action_id: uuid.UUID) -> None:
    session = _sessionmaker_for(get_config().database_url)()
    try:
        events.run_action_now(session, action_id)
        session.commit()
    except Exception:  # the worker retries it
        session.rollback()
        log.warning("background_action_failed", action_id=str(action_id))
    finally:
        session.close()


def run_after_commit(db: Session, background: BackgroundTasks, action_id: uuid.UUID) -> None:
    """Commit the request's work now, then run the action once the response is sent.

    The request session normally commits after the response, which is after background tasks
    run, so without this commit the background run would not see the action yet.
    """
    db.commit()
    background.add_task(run_action_soon, action_id)
