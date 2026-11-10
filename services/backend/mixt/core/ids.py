"""Time-ordered UUIDv7 identifiers (RFC 9562)."""

from __future__ import annotations

import os
import time
import uuid

_RAND_B_MASK = (1 << 62) - 1


def uuid7() -> uuid.UUID:
    """Return a UUIDv7: 48-bit Unix milliseconds, version 7, 74 random bits, RFC variant."""
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    rand_a = (rand >> 62) & 0xFFF
    rand_b = rand & _RAND_B_MASK
    value = ((unix_ms & ((1 << 48) - 1)) << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def uuid7_timestamp_ms(value: uuid.UUID) -> int:
    """Return the Unix millisecond timestamp embedded in a UUIDv7."""
    if value.version != 7:
        raise ValueError("not a UUIDv7")
    return value.int >> 80
