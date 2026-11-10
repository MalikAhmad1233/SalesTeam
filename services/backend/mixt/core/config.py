"""Application configuration, read from environment variables prefixed with ``MIXT_``.

Business decisions are NOT configured here: they live in the settings register
(``mixt.modules.settings``). This module only holds technical/deployment configuration.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d*)\s*([smhd])\s*$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


@dataclass(frozen=True)
class Rate:
    """``count`` requests per ``period_seconds``, e.g. ``Rate.parse("10/15m")``."""

    count: int
    period_seconds: int

    @classmethod
    def parse(cls, value: str) -> Rate:
        match = _RATE_RE.match(value)
        if not match:
            raise ValueError(f"rate {value!r} must look like '10/15m' (count / [number] unit s|m|h|d)")
        count, number, unit = int(match.group(1)), int(match.group(2) or 1), match.group(3)
        if count < 1 or number < 1:
            raise ValueError(f"rate {value!r} must be positive")
        return cls(count, number * _UNIT_SECONDS[unit])


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MIXT_", extra="ignore")

    env: Environment = Environment.LOCAL
    database_url: str = Field(description="Application role, e.g. postgresql+psycopg://mixt_app@host/db")

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

    # Proxies whose X-Forwarded-For is believed (the TLS proxy in front of the API). Anything else
    # is ignored, so a client cannot fake its address to dodge rate limits or pollute the audit log.
    trusted_proxies: list[str] = Field(default_factory=lambda: ["127.0.0.1/32", "::1/128"])

    # Rate limiting (IN-21). Redis is required in staging/production so limits hold across processes.
    redis_url: SecretStr | None = None
    rate_limits_enabled: bool = True
    rate_api_per_ip: str = "1200/1m"
    rate_api_per_user: str = "600/1m"
    rate_login_per_ip: str = "30/15m"
    rate_login_per_account: str = "10/15m"
    rate_mfa_per_session: str = "10/5m"
    rate_password_per_user: str = "5/15m"  # noqa: S105 (a rate, not a password)
    rate_sso_per_ip: str = "30/15m"
    rate_import_per_user: str = "20/1h"
    rate_enquiry_per_ip: str = "5/10m"
    rate_webhook_per_connection: str = "6000/1m"

    # Single sign-on (IN-23). Which provider is used is a business setting (`auth.sso`, Q-TECH-01);
    # these are only the client credentials. The public URL builds the redirect address.
    public_base_url: str | None = None
    sso_google_client_id: str | None = None
    sso_google_client_secret: SecretStr | None = None
    sso_microsoft_client_id: str | None = None
    sso_microsoft_client_secret: SecretStr | None = None
    sso_microsoft_tenant_id: str | None = None
    sso_allowed_domains: list[str] = Field(default_factory=list)
    # Local and test only: point a provider at a test identity provider.
    sso_issuer_overrides: dict[str, str] = Field(default_factory=dict)
    # Local and test only: send WhatsApp Graph API calls to a fake server (end-to-end tests).
    whatsapp_graph_base_url: str | None = None

    @field_validator("trusted_proxies")
    @classmethod
    def _networks(cls, value: list[str]) -> list[str]:
        for item in value:
            ipaddress.ip_network(item, strict=False)
        return value

    @field_validator(
        "rate_api_per_ip",
        "rate_api_per_user",
        "rate_login_per_ip",
        "rate_login_per_account",
        "rate_mfa_per_session",
        "rate_password_per_user",
        "rate_sso_per_ip",
        "rate_import_per_user",
        "rate_enquiry_per_ip",
        "rate_webhook_per_connection",
    )
    @classmethod
    def _rate(cls, value: str) -> str:
        Rate.parse(value)
        return value

    @field_validator("sso_allowed_domains")
    @classmethod
    def _domains(cls, value: list[str]) -> list[str]:
        return [d.strip().lower().lstrip("@") for d in value if d.strip()]

    @field_validator("public_base_url")
    @classmethod
    def _base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.match(r"^https?://[^/\s]+$", value.rstrip("/")):
            raise ValueError("MIXT_PUBLIC_BASE_URL must be an origin such as https://app.example.com")
        return value.rstrip("/")

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
        deployed = self.env in (Environment.STAGING, Environment.PRODUCTION)
        if deployed and not self.cookie_secure:
            raise ValueError("MIXT_COOKIE_SECURE must be true outside local/test environments")
        if deployed and self.redis_url is None:
            raise ValueError("MIXT_REDIS_URL is required in staging and production (shared rate limits)")
        if deployed and not self.rate_limits_enabled:
            raise ValueError("rate limits cannot be switched off in staging or production")
        if deployed and self.sso_issuer_overrides:
            raise ValueError("MIXT_SSO_ISSUER_OVERRIDES is for local and test environments only")
        if deployed and self.whatsapp_graph_base_url:
            raise ValueError("MIXT_WHATSAPP_GRAPH_BASE_URL is for local and test environments only")
        if deployed and self.public_base_url and not self.public_base_url.startswith("https://"):
            raise ValueError("MIXT_PUBLIC_BASE_URL must use https in staging and production")
        return self

    def rate(self, name: str) -> Rate:
        return Rate.parse(getattr(self, f"rate_{name}"))


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return AppConfig()  # values come from the environment
