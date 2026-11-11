"""Every endpoint commits its transaction before the response is sent.

With FastAPI's default ("request") scope, the exit code of a ``yield`` dependency runs after the
response has been sent. For the database session that meant: the client got "200 OK" for a change
before it was committed, so a read straight after it (for example the dashboard reloading a list,
served by another API worker) could still see the old data, and a commit that failed would follow
a success response. Seen on staging as a completed task that was still listed as open.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, iter_route_contexts

from mixt.api.app import create_app
from mixt.core.db import get_session


def _session_dependencies(dependant: Dependant) -> Iterator[Dependant]:
    for dependency in dependant.dependencies:
        if dependency.call is get_session:
            yield dependency
        yield from _session_dependencies(dependency)


def test_every_endpoint_commits_before_responding() -> None:
    app = create_app()
    checked = 0
    wrong: list[str] = []
    for context in iter_route_contexts(app.routes):  # includes the routes of included routers
        route = context.route
        if not isinstance(route, APIRoute):
            continue
        for dependency in _session_dependencies(route.dependant):
            checked += 1
            if dependency.scope != "function":
                wrong.append(f"{sorted(route.methods)} {context.path}")
    assert checked > 100  # the walk really finds the session dependencies
    assert not wrong, f'declare Depends(get_session, scope="function") in: {sorted(set(wrong))}'
