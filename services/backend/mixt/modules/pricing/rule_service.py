"""Pricing rules: writing, approving (four-eyes, with a decision reference), testing against a customer,
and attaching approved rules to a price book's market assignment (docs/04 §8, §11)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mixt.core.context import Actor
from mixt.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from mixt.core.timezones import now_utc
from mixt.modules.audit import service as audit
from mixt.modules.crm import service as crm
from mixt.modules.engagement import service as engagement
from mixt.modules.identity.access import Access
from mixt.modules.leads import service as leads
from mixt.modules.pricing import rules
from mixt.modules.pricing.models import PriceBookMarketAssignment, PricingRule
from mixt.modules.pricing.service import DECISION_REF

Rule = PricingRule


def _validated(kind: str, definition: Any) -> dict[str, Any]:
    try:
        rules.validate_definition(kind, definition)
    except rules.RuleInvalid as exc:
        raise ValidationFailed("RULE_INVALID", "The rule is not valid.", missing=exc.problems) from exc
    return dict(definition)


def facts_for(db: Session, account_id: uuid.UUID, today: date | None = None) -> dict[str, Any]:
    f = crm.pricing_facts(db, account_id)
    return {
        "account.market": f.market_country,
        "account.country_of_residence": f.country_of_residence,
        "account.is_new_customer": f.is_new_customer,
        "account.lead_source": leads.source_code(db, f.first_touch_lead_source_id),
        "account.tags": engagement.account_tag_names(db, account_id),
        "students.count": f.student_count,
        "students.curricula": list(f.curriculum_codes),
        "today": today or now_utc().date(),
    }


def list_rules(db: Session, access: Access) -> list[PricingRule]:
    access.require_somewhere("pricing.read")
    return list(db.scalars(select(PricingRule).order_by(PricingRule.code, PricingRule.rule_version.desc())))


def get_rule(db: Session, rule_id: uuid.UUID) -> PricingRule:
    rule = db.get(PricingRule, rule_id)
    if rule is None:
        raise NotFound("RULE_NOT_FOUND", "Pricing rule not found.")
    return rule


def create_rule(
    db: Session,
    actor: Actor,
    access: Access,
    code: str,
    name: str,
    kind: str,
    definition: Any,
    description: str | None,
    decision_ref: str | None,
) -> PricingRule:
    """A new draft rule; an existing code gets its next version (the approved one stays unchanged)."""
    access.require_somewhere("pricing.rules.manage")
    if decision_ref and not DECISION_REF.match(decision_ref):
        raise ValidationFailed("DECISION_REF_INVALID", "A decision reference looks like 'BD-034'.")
    if len(name.strip()) < 3:
        raise ValidationFailed("NAME_REQUIRED", "Give the rule a name.")
    validated = _validated(kind, definition)
    latest = db.scalar(select(func.max(PricingRule.rule_version)).where(PricingRule.code == code))
    rule = PricingRule(
        code=code,
        rule_version=(latest or 0) + 1,
        name=name.strip(),
        kind=kind,
        definition=validated,
        description=(description or "").strip() or None,
        decision_ref=decision_ref or None,
        created_by=actor.principal_id,
    )
    db.add(rule)
    db.flush()
    audit.record(db, actor, "pricing_rule_created", "pricing_rule", rule.id, {"code": code, "kind": kind})
    return rule


def update_draft(
    db: Session,
    actor: Actor,
    access: Access,
    rule_id: uuid.UUID,
    name: str,
    definition: Any,
    description: str | None,
    decision_ref: str | None,
) -> PricingRule:
    access.require_somewhere("pricing.rules.manage")
    rule = get_rule(db, rule_id)
    if rule.status != "draft":
        raise Conflict("RULE_NOT_DRAFT", "Approved rules never change: create a new version instead.")
    if decision_ref and not DECISION_REF.match(decision_ref):
        raise ValidationFailed("DECISION_REF_INVALID", "A decision reference looks like 'BD-034'.")
    rule.name, rule.definition = name.strip(), _validated(rule.kind, definition)
    rule.description, rule.decision_ref = (description or "").strip() or None, decision_ref or None
    db.flush()
    audit.record(db, actor, "pricing_rule_updated", "pricing_rule", rule.id, {"code": rule.code})
    return rule


def approve_rule(db: Session, actor: Actor, access: Access, rule_id: uuid.UUID) -> PricingRule:
    access.require_somewhere("pricing.rules.approve")
    rule = get_rule(db, rule_id)
    if rule.status != "draft":
        raise Conflict("RULE_NOT_DRAFT", f"This rule is already {rule.status}.")
    if rule.created_by == actor.principal_id:
        raise PermissionDenied("FOUR_EYES", "Someone other than the author must approve a pricing rule.")
    if not rule.decision_ref:
        raise ValidationFailed(
            "DECISION_REF_REQUIRED",
            "A pricing rule is Mixt's business decision: add its decision-log reference before approving.",
        )
    _validated(rule.kind, rule.definition)
    rule.status, rule.approved_by, rule.approved_at = "approved", actor.principal_id, now_utc()
    db.flush()
    audit.record(db, actor, "pricing_rule_approved", "pricing_rule", rule.id, {"ref": rule.decision_ref})
    return rule


def retire_rule(db: Session, actor: Actor, access: Access, rule_id: uuid.UUID) -> PricingRule:
    access.require_somewhere("pricing.rules.approve")
    rule = get_rule(db, rule_id)
    if rule.status != "approved":
        raise Conflict("RULE_NOT_APPROVED", "Only an approved rule can be retired.")
    in_use = db.scalar(
        select(func.count()).where(
            (PriceBookMarketAssignment.eligibility_rule_id == rule.id)
            | (PriceBookMarketAssignment.minimum_purchase_rule_id == rule.id)
        )
    )
    if in_use:
        raise Conflict("RULE_IN_USE", "Detach the rule from its price books first.")
    rule.status, rule.retired_at = "retired", now_utc()
    db.flush()
    audit.record(db, actor, "pricing_rule_retired", "pricing_rule", rule.id, {})
    return rule


@dataclass(frozen=True)
class RuleTest:
    rule: PricingRule
    facts: dict[str, Any]
    result: bool
    trace: tuple[str, ...]
    min_quantity: str | None


def evaluate(rule: PricingRule, facts: dict[str, Any]) -> rules.Evaluation:
    condition = rule.definition.get("condition")
    if condition is None:  # minimum purchase that always applies
        return rules.Evaluation(True, ("applies to every customer",))
    return rules.evaluate(condition, facts)


def try_rule(db: Session, access: Access, rule_id: uuid.UUID, account_id: uuid.UUID) -> RuleTest:
    """The rule tester: what this rule decides for this customer, and why."""
    access.require_somewhere("pricing.rules.manage")
    crm.get_account(db, access, account_id)  # visibility
    rule = get_rule(db, rule_id)
    facts = facts_for(db, account_id)
    outcome = evaluate(rule, facts)
    minimum = str(rule.definition["min_quantity"]) if rule.kind == "minimum_purchase" else None
    printable = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in facts.items()}
    return RuleTest(rule, printable, outcome.result, outcome.trace, minimum)


def try_rule_with_facts(db: Session, access: Access, rule_id: uuid.UUID, facts: dict[str, Any]) -> rules.Evaluation:
    """The rule tester with example facts (for people who cannot open customer records)."""
    access.require_somewhere("pricing.rules.manage")
    unknown = sorted(set(facts) - set(rules.FACT_TYPES))
    if unknown:
        raise ValidationFailed("UNKNOWN_FACTS", "Only the listed facts can be used.", missing=unknown)
    sample = dict(facts)
    if isinstance(sample.get("today"), str):
        try:
            sample["today"] = date.fromisoformat(sample["today"])
        except ValueError as exc:
            raise ValidationFailed("INVALID_FACT", "today must be a date such as 2026-11-10.") from exc
    return evaluate(get_rule(db, rule_id), sample)


def attach_rule(
    db: Session,
    actor: Actor,
    access: Access,
    assignment_id: uuid.UUID,
    kind: str,
    rule_id: uuid.UUID | None,
) -> PriceBookMarketAssignment:
    """Make an approved rule apply to a price book in one market (or remove it with ``rule_id=None``)."""
    access.require_somewhere("pricing.rules.manage")
    assignment = db.get(PriceBookMarketAssignment, assignment_id)
    if assignment is None:
        raise NotFound("ASSIGNMENT_NOT_FOUND", "Market assignment not found.")
    if kind not in ("eligibility", "minimum_purchase"):
        raise ValidationFailed("INVALID_KIND", "Kind is eligibility or minimum_purchase.")
    if rule_id is not None:
        rule = get_rule(db, rule_id)
        if rule.status != "approved":
            raise Conflict("RULE_NOT_APPROVED", "Only an approved rule can be used.")
        if rule.kind != kind:
            raise ValidationFailed("WRONG_RULE_KIND", f"That is a {rule.kind} rule.")
    column = "eligibility_rule_id" if kind == "eligibility" else "minimum_purchase_rule_id"
    before = getattr(assignment, column)
    setattr(assignment, column, rule_id)
    db.flush()
    audit.record(
        db,
        actor,
        "pricing_rule_attached",
        "price_book",
        assignment.price_book_id,
        {"kind": kind, "from": str(before) if before else None, "to": str(rule_id) if rule_id else None},
    )
    return assignment
