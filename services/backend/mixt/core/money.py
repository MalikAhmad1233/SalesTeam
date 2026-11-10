"""Money as integer minor units plus an ISO 4217 currency code (ADR-09).

Rules enforced here:
- amounts are integers in minor units; floats are rejected;
- arithmetic is only allowed between amounts of the same currency;
- there is deliberately no currency conversion anywhere in this module (BD-019).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class MoneyError(ValueError):
    pass


class CurrencyMismatch(MoneyError):
    pass


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise MoneyError("amount_minor must be an integer number of minor units")
        if not _CURRENCY_RE.match(self.currency):
            raise MoneyError("currency must be an ISO 4217 code such as 'GBP'")

    def _check(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise MoneyError("can only combine Money with Money")
        if other.currency != self.currency:
            raise CurrencyMismatch(f"cannot combine {self.currency} with {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor < other.amount_minor

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.amount_minor <= other.amount_minor


def parse_major(value: str, currency: str, minor_units: int) -> Money:
    """Parse a decimal string in major units ("1050.00") exactly; extra precision is an error."""
    try:
        amount = Decimal(value.strip().replace(",", ""))
    except InvalidOperation as exc:
        raise MoneyError(f"not a decimal amount: {value!r}") from exc
    if not amount.is_finite():
        raise MoneyError("amount must be finite")
    scaled = amount.scaleb(minor_units)
    if scaled != scaled.to_integral_value():
        raise MoneyError(f"{value!r} has more decimal places than {currency} allows ({minor_units})")
    return Money(int(scaled), currency)


def format_money(money: Money, minor_units: int, display_prefix: str | None = None) -> str:
    """Format for display, always showing the currency explicitly (e.g. 'AED 1,050', 'USD 260')."""
    sign = "-" if money.amount_minor < 0 else ""
    quantum = 10**minor_units if minor_units else 1
    major, minor = divmod(abs(money.amount_minor), quantum)
    body = f"{major:,}"
    if minor_units and minor:
        body += f".{minor:0{minor_units}d}"
    prefix = display_prefix if display_prefix is not None else f"{money.currency} "
    return f"{sign}{prefix}{body}"
