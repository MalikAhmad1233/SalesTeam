"""ASGI entry point: ``uvicorn mixt.main:app``."""

from mixt.api.app import create_app

app = create_app()
