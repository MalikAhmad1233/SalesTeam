"""Time-zone helpers. All timestamps are stored in UTC; IANA zone names are used for display."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones


class InvalidTimezone(ValueError):
    pass


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(available_timezones())


def validate_timezone(name: str) -> str:
    if name not in _zones():
        raise InvalidTimezone(f"{name!r} is not an IANA time-zone name (e.g. 'Asia/Dubai')")
    return name


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_local(moment: datetime, zone: str) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("naive datetimes are not allowed; store and pass UTC-aware values")
    return moment.astimezone(ZoneInfo(validate_timezone(zone)))
