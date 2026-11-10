"""Application configuration, read from environment variables prefixed with ``MIXT_``.

Business decisions are NOT configured here: they live in the settings register
(``mixt.modules.settings``). This module only holds technical/deployment configuration.
"""

from __future__ import annotations

import base64
import binascii
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MIXT_", extra="ignore")

    env: Environment = Environment.LOCAL
    database_url: str = Field(description="SQLAlchemy URL, e.g. postgresql+psycopg://user@host/db")

    # Field-level encryption key ring: {"key_id": "<base64 32-byte key>"}; supplied as JSON.
    encryption_keys: dict[str, str]
    active_encryption_key_id: str

    cookie_secure: bool = True
    session_idle_minutes: int = Field(default=30, ge=5, le=24 * 60)
    session_absolute_hours: int = Field(default=12, ge=1, le=72)
    login_max_failures: int = Field(default=5, ge=3, le=20)
    login_lockout_minutes: int = Field(default=15, ge=1, le=24 * 60)
    cors_origins: list[str] = Field(default_factory=list)
    log_level: str = "INFO"
    log_json: bool = True

    @model_validator(mode="after")
    def _validate(self) -> AppConfig:
        if self.active_encryption_key_id not in self.encryption_keys:
            raise ValueError("MIXT_ACTIVE_ENCRYPTION_KEY_ID must be one of MIXT_ENCRYPTION_KEYS")
        for key_id, encoded in self.encryption_keys.items():
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError(f"encryption key {key_id!r} is not valid base64") from exc
            if len(raw) != 32:
                raise ValueError(f"encryption key {key_id!r} must decode to 32 bytes")
        if self.env in (Environment.STAGING, Environment.PRODUCTION) and not self.cookie_secure:
            raise ValueError("MIXT_COOKIE_SECURE must be true outside local/test environments")
        return self


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig()  # values come from the environment
