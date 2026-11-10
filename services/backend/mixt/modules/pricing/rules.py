"""The pricing rule language (docs/04 §8): conditions over a fixed set of customer facts.

    {"all": [{"fact": "account.is_new_customer", "op": "eq", "value": true},
             {"fact": "account.lead_source", "op": "in", "value": ["meta_lead_ads", "website_form"]}]}

Nodes are ``all`` / ``any`` (non-empty lists), ``not`` (one node) or a comparison
``{"fact", "op", "value"}``. Each fact has a type, and only the operators that make sense for that
type are accepted, so a rule that would never work is refused when it is written, not when it runs.
Evaluation returns the result and a readable trace, which the rule tester shows.

Rule kinds:
* ``eligibility``: ``{"condition": <node>}``; a price book (or promotion) is offered only to
  customers for whom it is true.
* ``minimum_purchase``: ``{"condition": <node> | null, "min_quantity": <number>}``; when the
  condition holds (or always, if null), packages below the minimum are not offered.

No rule is confirmed today (Q-PRC-04, Q-PRC-10): every rule needs a decision reference to be approved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

FACT_TYPES: dict[str, str] = {
    "account.market": "string",  # ISO country code of the confirmed pricing market
    "account.country_of_residence": "string",
    "account.is_new_customer": "bool",  # never been a paying customer
    "account.lead_source": "string",  # first-touch lead source code
    "account.tags": "list",
    "students.count": "number",
    "students.curricula": "list",  # curriculum codes, e.g. BRITISH
    "today": "date",
}
OPERATORS: dict[str, frozenset[str]] = {
    "string": frozenset({"eq", "neq", "in", "not_in", "exists"}),
    "bool": frozenset({"eq", "neq", "exists"}),
    "number": frozenset({"eq", "neq", "gte", "lte", "between", "exists"}),
    "list": frozenset({"contains", "not_contains", "exists"}),
    "date": frozenset({"eq", "gte", "lte", "between"}),
}
MAX_NODES = 50
MAX_DEPTH = 6


class RuleInvalid(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("not a number")
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("not a number") from exc


def _date(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("not a date")
    return date.fromisoformat(value)


def _check_value(kind: str, op: str, value: Any, where: str) -> list[str]:
    if op == "exists":
        return [] if isinstance(value, bool) else [f"{where}: 'exists' takes true or false"]
    try:
        if op in ("in", "not_in"):
            if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
                return [f"{where}: '{op}' takes a non-empty list of text values"]
        elif op == "between":
            if not isinstance(value, list) or len(value) != 2:
                return [f"{where}: 'between' takes [low, high]"]
            low, high = (_number(v) for v in value) if kind == "number" else (_date(v) for v in value)
            if low > high:  # type: ignore[operator]
                return [f"{where}: 'between' needs low <= high"]
        elif kind == "string" or op in ("contains", "not_contains"):
            if not isinstance(value, str) or not value:
                return [f"{where}: '{op}' takes a text value"]
        elif kind == "bool":
            if not isinstance(value, bool):
                return [f"{where}: '{op}' takes true or false"]
        elif kind == "number":
            _number(value)
        elif kind == "date":
            _date(value)
    except ValueError:
        return [f"{where}: value {value!r} is not a valid {kind}"]
    return []


def validate_condition(node: Any) -> list[str]:
    problems: list[str] = []
    count = 0

    def walk(n: Any, path: str, depth: int) -> None:
        nonlocal count
        count += 1
        if depth > MAX_DEPTH:
            problems.append(f"{path}: nested too deeply (max {MAX_DEPTH})")
            return
        if not isinstance(n, dict):
            problems.append(f"{path}: must be an object")
            return
        keys = set(n)
        if keys in ({"all"}, {"any"}):
            key = next(iter(keys))
            items = n[key]
            if not isinstance(items, list) or not items:
                problems.append(f"{path}.{key}: must be a non-empty list")
                return
            for i, child in enumerate(items):
                walk(child, f"{path}.{key}[{i}]", depth + 1)
        elif keys == {"not"}:
            walk(n["not"], f"{path}.not", depth + 1)
        elif keys == {"fact", "op", "value"}:
            fact, op = n["fact"], n["op"]
            kind = FACT_TYPES.get(fact) if isinstance(fact, str) else None
            if kind is None:
                problems.append(f"{path}: unknown fact {fact!r} (known: {', '.join(sorted(FACT_TYPES))})")
                return
            if op not in OPERATORS[kind]:
                allowed = ", ".join(sorted(OPERATORS[kind]))
                problems.append(f"{path}: {fact} is a {kind}; use one of {allowed}, not {op!r}")
                return
            problems.extend(_check_value(kind, op, n["value"], path))
        else:
            problems.append(f"{path}: use all / any / not, or fact + op + value")

    walk(node, "condition", 1)
    if count > MAX_NODES:
        problems.append(f"condition: too many parts ({count}; max {MAX_NODES})")
    return problems


def validate_definition(kind: str, definition: Any) -> None:
    problems: list[str] = []
    if not isinstance(definition, dict):
        raise RuleInvalid(["definition must be an object"])
    if kind == "eligibility":
        if set(definition) != {"condition"}:
            problems.append("an eligibility rule is {'condition': ...}")
        else:
            problems += validate_condition(definition["condition"])
    elif kind == "minimum_purchase":
        if set(definition) != {"condition", "min_quantity"}:
            problems.append("a minimum-purchase rule is {'condition': ... or null, 'min_quantity': number}")
        else:
            if definition["condition"] is not None:
                problems += validate_condition(definition["condition"])
            try:
                if _number(definition["min_quantity"]) <= 0:
                    problems.append("min_quantity must be positive")
            except ValueError:
                problems.append("min_quantity must be a number")
    else:
        problems.append(f"unknown rule kind {kind!r}")
    if problems:
        raise RuleInvalid(problems)


@dataclass(frozen=True)
class Evaluation:
    result: bool
    trace: tuple[str, ...]


def _normal(kind: str, value: Any) -> Any:
    if kind == "number":
        return _number(value)
    if kind == "date":
        return value if isinstance(value, date) else _date(value)
    return value


def _compare(kind: str, op: str, actual: Any, expected: Any) -> bool:
    if op == "exists":
        present = actual is not None and actual != []
        return present is expected
    if actual is None:
        return False
    if op in ("in", "not_in"):
        return (actual in expected) is (op == "in")
    if op in ("contains", "not_contains"):
        return (expected in actual) is (op == "contains")
    value = _normal(kind, actual)
    if op == "between":
        low, high = (_normal(kind, v) for v in expected)
        return bool(low <= value <= high)
    other = _normal(kind, expected)
    if op == "eq":
        return bool(value == other)
    if op == "neq":
        return bool(value != other)
    if op == "gte":
        return bool(value >= other)
    return bool(value <= other)  # lte


def evaluate(node: dict[str, Any], facts: dict[str, Any]) -> Evaluation:
    trace: list[str] = []

    def walk(n: dict[str, Any], depth: int) -> bool:
        pad = "  " * depth
        if "all" in n:
            parts = [walk(c, depth + 1) for c in n["all"]]  # evaluate every part, for a full trace
            result = all(parts)
            trace.append(f"{pad}all of the above: {'yes' if result else 'no'}")
            return result
        if "any" in n:
            parts = [walk(c, depth + 1) for c in n["any"]]
            result = any(parts)
            trace.append(f"{pad}any of the above: {'yes' if result else 'no'}")
            return result
        if "not" in n:
            result = not walk(n["not"], depth + 1)
            trace.append(f"{pad}not the above: {'yes' if result else 'no'}")
            return result
        fact, op, expected = n["fact"], n["op"], n["value"]
        actual = facts.get(fact)
        result = _compare(FACT_TYPES[fact], op, actual, expected)
        trace.append(f"{pad}{fact} = {actual!r}; {op} {expected!r}: {'yes' if result else 'no'}")
        return result

    return Evaluation(walk(node, 0), tuple(trace))
