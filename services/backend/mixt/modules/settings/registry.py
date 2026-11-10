"""Setting definitions for outstanding and confirmed business decisions (docs/13, ADR-11, ADR-16).

Each definition carries a JSON schema, a *safe default* (never a guessed business answer), its
status ('safe_default' or 'confirmed' with a decision-log reference), the permission needed to
change it, and the open question it is waiting for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["safe_default", "confirmed"]

OWNER = "settings.change.owner"
PRICING = "settings.change.pricing"
SALES = "settings.change.sales"
ADMIN = "settings.change.admin"
FINANCE = "settings.change.finance"


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    area: str
    description: str
    schema: dict[str, Any]
    default: Any
    change_permission: str
    scopes: tuple[str, ...] = ("global",)
    status: Status = "safe_default"
    decision_ref: str | None = None
    open_question: str | None = None
    requires_dual_approval: bool = False
    # Extra permissions a dual-approval change needs from the second approver.
    second_permission: str | None = None
    notes: str = field(default="")


# Checks a stage can require. Implemented in mixt.modules.pipeline.stages (a test keeps them in sync).
STAGE_CHECKS = ("owner", "market_confirmed", "student_profile", "note", "lost_reason", "nurture_until")

PIPELINE_STAGES_SCHEMA: dict[str, Any] = {
    "type": "array",
    "minItems": 3,
    "items": {
        "type": "object",
        "required": ["key", "name", "type", "requires"],
        "additionalProperties": False,
        "properties": {
            "key": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,40}$"},
            "name": {"type": "string", "minLength": 1, "maxLength": 60},
            "type": {"enum": ["open", "won", "lost"]},
            "sla_hours": {"type": ["integer", "null"], "minimum": 1},
            "requires": {"type": "array", "items": {"enum": list(STAGE_CHECKS)}, "uniqueItems": True},
        },
    },
}

_QUALIFIED = ["owner", "market_confirmed", "student_profile"]
DEFAULT_PIPELINE_STAGES: list[dict[str, Any]] = [
    {"key": "new", "name": "New", "type": "open", "sla_hours": None, "requires": []},
    {"key": "contacted", "name": "Contacted", "type": "open", "sla_hours": None, "requires": ["owner"]},
    {"key": "discovery", "name": "Discovery", "type": "open", "sla_hours": None, "requires": ["owner"]},
    {"key": "qualified", "name": "Qualified", "type": "open", "sla_hours": None, "requires": _QUALIFIED},
    {
        "key": "trial_scheduled",
        "name": "Trial scheduled",
        "type": "open",
        "sla_hours": None,
        "requires": [*_QUALIFIED, "note"],
    },
    {
        "key": "trial_completed",
        "name": "Trial completed",
        "type": "open",
        "sla_hours": None,
        "requires": [*_QUALIFIED, "note"],
    },
    {
        "key": "quotation_sent",
        "name": "Quotation sent",
        "type": "open",
        "sla_hours": None,
        "requires": [*_QUALIFIED, "note"],
    },
    {"key": "negotiation", "name": "Negotiation", "type": "open", "sla_hours": None, "requires": [*_QUALIFIED, "note"]},
    {
        "key": "won_payment_pending",
        "name": "Won: payment pending",
        "type": "open",
        "sla_hours": None,
        "requires": [*_QUALIFIED, "note"],
    },
    {
        "key": "won_paid",
        "name": "Won: paid / onboarded",
        "type": "won",
        "sla_hours": None,
        "requires": [*_QUALIFIED, "note"],
    },
    {"key": "lost", "name": "Lost", "type": "lost", "sla_hours": None, "requires": ["lost_reason"]},
    {"key": "nurture", "name": "Nurture", "type": "open", "sla_hours": None, "requires": ["nurture_until", "note"]},
]


def _enum(*values: Any) -> dict[str, Any]:
    return {"enum": list(values)}


_BOOL: dict[str, Any] = {"type": "boolean"}

DEFINITIONS: tuple[SettingDefinition, ...] = (
    # ---------------------------------------------------------------- pricing and quotations
    SettingDefinition(
        "pricing.catalogue_complete",
        "pricing",
        "Whether the pricing catalogue is complete. While false, Pricing and Quotations show an 'incomplete' banner.",
        _BOOL,
        False,
        OWNER,
        status="confirmed",
        decision_ref="BD-017",
        open_question="Q-PRC-01",
        requires_dual_approval=True,
        second_permission=PRICING,
    ),
    SettingDefinition(
        "pricing.market_basis",
        "pricing",
        "How a customer's pricing market is decided. Currency, phone prefix and curriculum are never used (ADR-13).",
        _enum("staff_confirmed", "rule_based"),
        "staff_confirmed",
        OWNER,
        open_question="Q-MKT-04",
    ),
    SettingDefinition(
        "pricing.tier_selection_mode",
        "pricing",
        "How to choose between several valid tiers/schedules in a market. 'manual' = a person selects per "
        "customer with a reason; the AI never selects (ADR-12).",
        _enum("manual", "market_default", "rule_based"),
        "manual",
        PRICING,
        scopes=("global", "market"),
        open_question="Q-PRC-02, Q-PRC-03",
        requires_dual_approval=True,
        second_permission=PRICING,
    ),
    SettingDefinition(
        "pricing.activation.dual_approval",
        "pricing",
        "Whether activating a price-book version needs two different approvers.",
        _BOOL,
        True,
        OWNER,
        open_question="Q-PRC-20",
    ),
    SettingDefinition(
        "pricing.version.tax_treatment",
        "pricing",
        "Tax treatment of a price-book version. 'unknown' blocks activation.",
        _enum("unknown", "inclusive", "exclusive", "not_applicable"),
        "unknown",
        PRICING,
        scopes=("global", "price_book_version"),
        open_question="Q-PAY-04",
        requires_dual_approval=True,
        second_permission=FINANCE,
    ),
    SettingDefinition(
        "pricing.version.minutes_per_unit",
        "pricing",
        "Minutes per hour/class unit. One class = one hour for the supplied class-based schedules, unless a "
        "package-specific exception is confirmed later (BD-011).",
        {"type": "integer", "minimum": 15, "maximum": 240},
        60,
        PRICING,
        scopes=("global", "price_book_version"),
        status="confirmed",
        decision_ref="BD-011",
    ),
    SettingDefinition(
        "pricing.customer_rate_display",
        "pricing",
        "What customers see: package totals only, or also an hourly rate (derived or official).",
        _enum("totals_only", "totals_and_derived_rate", "totals_and_official_rate"),
        "totals_only",
        PRICING,
        open_question="Q-PRC-08",
    ),
    SettingDefinition(
        "pricing.plan_label_display",
        "pricing",
        "Plan name shown to customers. 'none' until confirmed; Hong Kong Standard/Premium are confirmed (BD-016).",
        _enum("none", "Standard", "Premium"),
        "none",
        PRICING,
        scopes=("global", "price_book"),
        open_question="Q-PRC-06",
    ),
    SettingDefinition(
        "pricing.custom_quantities",
        "pricing",
        "Whether non-listed quantities can be quoted. 'disabled' = only listed packages; anything else becomes a "
        "custom-quote request to a person.",
        _enum("disabled", "approval_required"),
        "disabled",
        PRICING,
        open_question="Q-PRC-18",
    ),
    SettingDefinition(
        "pricing.discounts.mode",
        "pricing",
        "Discount handling. Percentage discounts stay disabled until a rounding rule exists; any discount needs "
        "Sales Manager and Pricing Manager approval.",
        _enum("amount_only_with_approval", "percent_allowed"),
        "amount_only_with_approval",
        OWNER,
        open_question="Q-PRC-11, Q-PRC-12",
    ),
    SettingDefinition(
        "pricing.discount_authority",
        "pricing",
        "Discount limits per role and market. Empty = nobody approves a discount alone.",
        {"type": "object"},
        {},
        OWNER,
        scopes=("global", "role"),
        open_question="Q-PRC-11",
    ),
    SettingDefinition(
        "pricing.minimum_purchase_rules",
        "pricing",
        "Minimum purchase rules per market/plan. None assumed.",
        {"type": "array"},
        [],
        PRICING,
        scopes=("global", "market"),
        open_question="Q-PRC-10",
    ),
    SettingDefinition(
        "pricing.multi_student_quotes",
        "pricing",
        "Who builds quotations for several students. AI drafts single-student options only until decided.",
        _enum("staff_built", "ai_drafts_allowed"),
        "staff_built",
        PRICING,
        open_question="Q-PRC-19",
    ),
    SettingDefinition(
        "pricing.unpriced_market_handling",
        "pricing",
        "Behaviour in markets without approved pricing (Kuwait, Oman, Bahrain, Singapore, Indonesia, South Korea).",
        _enum("escalate_no_figures", "holding_template_auto"),
        "escalate_no_figures",
        SALES,
        open_question="Q-MKT-03",
    ),
    SettingDefinition(
        "quotations.validity",
        "pricing",
        "Quotation validity. 'set_per_quote' = the approver enters an expiry date on every quotation.",
        {"type": "string", "pattern": "^(set_per_quote|fixed_days:[1-9][0-9]{0,2})$"},
        "set_per_quote",
        PRICING,
        open_question="Q-PRC-13",
    ),
    SettingDefinition(
        "quotations.approval",
        "pricing",
        "Who approves a quotation at list price (no discount, no promotion). 'second_person' = always someone other "
        "than the preparer. Discounts always follow pricing.discount_authority.",
        _enum("second_person", "preparer_may_issue_list_price"),
        "second_person",
        OWNER,
        open_question="Q-PRC-22",
    ),
    SettingDefinition(
        "quotations.on_price_change",
        "pricing",
        "What happens to an issued quotation when its price version is superseded. Issued quotes are never altered.",
        _enum("reconfirm_before_acceptance", "honour_until_expiry", "expire_on_change"),
        "reconfirm_before_acceptance",
        PRICING,
        open_question="Q-PRC-13",
    ),
    SettingDefinition(
        "promotions.enabled",
        "pricing",
        "Whether promotions can be activated. Promotions never modify standard pricing (BD-021, ADR-15).",
        _BOOL,
        False,
        OWNER,
        open_question="Q-PRC-05",
        requires_dual_approval=True,
        second_permission=PRICING,
    ),
    SettingDefinition(
        "benefits.claims_mode",
        "pricing",
        "Only benefits/policies attached and approved for the exact price-book version may be shown or said.",
        _enum("approved_only"),
        "approved_only",
        PRICING,
        scopes=("global", "price_book_version"),
        open_question="Q-PKG-01",
    ),
    # ---------------------------------------------------------------- markets and CRM
    SettingDefinition(
        "markets.operating",
        "markets",
        "Markets Mixt operates in (BD-004). The US is never a market (BD-005); the markets table is authoritative.",
        {"type": "array", "items": {"type": "string", "pattern": "^(?!US$)[A-Z]{2}$"}, "uniqueItems": True},
        ["AE", "QA", "KW", "SA", "OM", "BH", "MY", "HK", "SG", "ID", "KR", "GB", "IE"],
        OWNER,
        status="confirmed",
        decision_ref="BD-004",
    ),
    SettingDefinition(
        "markets.mixt_ai_rollout",
        "markets",
        "Which stage of Mixt AI is switched on in a market.",
        _enum("off", "crm_only", "channels", "ai_drafts"),
        "off",
        OWNER,
        scopes=("global", "market"),
        open_question="Q-MKT-06",
    ),
    SettingDefinition(
        "markets.out_of_market_handling",
        "markets",
        "Enquiries from outside the operating markets (including US residents): flagged for a person; no AI sales "
        "reply; no pricing; never added as a market.",
        _enum("human_review", "polite_decline_template"),
        "human_review",
        SALES,
        open_question="Q-MKT-02",
    ),
    SettingDefinition(
        "markets.contact_hours",
        "markets",
        "Acceptable contact hours per market. Unset = scheduled/automated sends disabled.",
        {"type": ["object", "null"]},
        None,
        ADMIN,
        scopes=("global", "market"),
        open_question="Q-MKT-07",
    ),
    SettingDefinition(
        "markets.working_days",
        "markets",
        "Working days (ISO weekday numbers) per market. Unset until confirmed.",
        {"type": ["array", "null"], "items": {"type": "integer", "minimum": 1, "maximum": 7}},
        None,
        ADMIN,
        scopes=("global", "market"),
        open_question="Q-MKT-07",
    ),
    SettingDefinition(
        "crm.curricula",
        "crm",
        "Confirmed curriculum categories (BD-007). IB is not included unless separately approved (BD-008).",
        {"type": "array", "items": {"type": "string"}},
        ["IRISH", "SABIS", "AMERICAN", "BRITISH"],
        OWNER,
        status="confirmed",
        decision_ref="BD-007",
    ),
    SettingDefinition(
        "crm.grade_entry",
        "crm",
        "Grades are free text until per-curriculum grade lists are supplied.",
        _enum("free_text", "controlled_list"),
        "free_text",
        ADMIN,
        scopes=("global", "curriculum"),
        open_question="Q-ACA-03",
    ),
    SettingDefinition(
        "crm.offerings_unconfirmed",
        "crm",
        "Board x qualification and subject combinations not marked as offered must not be claimed; escalate.",
        _enum("do_not_claim_escalate"),
        "do_not_claim_escalate",
        ADMIN,
        open_question="Q-ACA-01, Q-ACA-02",
    ),
    SettingDefinition(
        "crm.student_birth_data",
        "crm",
        "Student birth data collected: year only (data minimisation).",
        _enum("year_only", "full_date"),
        "year_only",
        OWNER,
        open_question="Q-CMP-04",
    ),
    SettingDefinition(
        "crm.lead_assignment",
        "crm",
        "How new accounts get an owner. Manual until routing rules are agreed.",
        _enum("manual", "rules"),
        "manual",
        SALES,
        open_question="Q-TEAM-01",
    ),
    SettingDefinition(
        "crm.pipeline_stages",
        "crm",
        "Stages of the new-business pipeline, in order, with the checks required to enter each one. Proposed "
        "defaults from docs/06; stages for trials, quotations and payments need a note until those modules exist.",
        PIPELINE_STAGES_SCHEMA,
        DEFAULT_PIPELINE_STAGES,
        ADMIN,
        open_question="Q-SAL-01, Q-CRM-01",
    ),
    SettingDefinition(
        "crm.lost_reasons",
        "crm",
        "Reasons a person can choose when an opportunity is lost (generic proposed list).",
        {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["code", "name"],
                "additionalProperties": False,
                "properties": {
                    "code": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,40}$"},
                    "name": {"type": "string", "minLength": 1, "maxLength": 80},
                },
            },
        },
        [
            {"code": "price", "name": "Price"},
            {"code": "timing", "name": "Timing / not now"},
            {"code": "competitor", "name": "Chose another provider"},
            {"code": "no_response", "name": "No response"},
            {"code": "not_a_fit", "name": "Needs not covered"},
            {"code": "other", "name": "Other"},
        ],
        ADMIN,
        open_question="Q-SAL-01",
    ),
    SettingDefinition(
        "crm.unassigned_pool_visible_to_reps",
        "crm",
        "Whether sales reps can see accounts that have no owner yet (the unassigned pool).",
        _BOOL,
        True,
        SALES,
        open_question="Q-TEAM-02",
    ),
    # ---------------------------------------------------------------- channels and AI
    SettingDefinition(
        "channels.email.provider",
        "channels",
        "Email platform. Email channel stays off until chosen.",
        _enum("unset", "gmail", "microsoft_graph"),
        "unset",
        ADMIN,
        open_question="Q-COM-03",
    ),
    SettingDefinition(
        "channels.whatsapp.numbers",
        "channels",
        "WhatsApp Business numbers. None = WhatsApp channel off.",
        {"type": "array", "items": {"type": "string"}},
        [],
        ADMIN,
        scopes=("global", "market"),
        open_question="Q-COM-01, Q-COM-02",
    ),
    SettingDefinition(
        "channels.instagram",
        "channels",
        "Instagram sources in use.",
        _enum("disabled", "lead_ads", "dms", "both"),
        "disabled",
        ADMIN,
        open_question="Q-COM-04",
    ),
    SettingDefinition(
        "messaging.student_direct_contact",
        "channels",
        "Whether students may be messaged directly. Disabled = guardians only.",
        {"type": "string", "pattern": "^(disabled|enabled_from_age:[0-9]{1,2})$"},
        "disabled",
        OWNER,
        open_question="Q-AI-05",
    ),
    SettingDefinition(
        "messaging.sequences_enabled",
        "channels",
        "Automated follow-up sequences.",
        _BOOL,
        False,
        SALES,
        open_question="Q-SAL-06, Q-MKT-07",
    ),
    SettingDefinition(
        "ai.enabled",
        "ai",
        "Master switch for AI agents.",
        _BOOL,
        False,
        OWNER,
        scopes=("global", "agent", "channel", "market"),
    ),
    SettingDefinition(
        "ai.autonomy.customer_facing",
        "ai",
        "Autonomy for customer-facing AI actions. 'approval' = a person approves every one (BD-027).",
        _enum("approval"),
        "approval",
        OWNER,
        scopes=("global", "action", "channel", "market"),
        status="confirmed",
        decision_ref="BD-027",
        open_question="Q-AI-02",
    ),
    SettingDefinition(
        "ai.customer_data_to_llm",
        "ai",
        "Whether customer data may be sent to AI model providers.",
        _enum("blocked", "allowed"),
        "blocked",
        OWNER,
        open_question="Q-CMP-06",
    ),
    SettingDefinition(
        "ai.reply_languages",
        "ai",
        "Languages the AI may reply in; others go to a person.",
        {"type": "array", "items": {"type": "string"}, "minItems": 1},
        ["en"],
        ADMIN,
        open_question="Q-AI-03",
    ),
    SettingDefinition(
        "ai.disclosure",
        "ai",
        "Conversations state that an AI assistant helps the team.",
        _BOOL,
        True,
        OWNER,
        open_question="Q-CMP-05",
    ),
    SettingDefinition(
        "ai.webchat_live",
        "ai",
        "Whether website chat answers live (approved knowledge only).",
        _BOOL,
        False,
        OWNER,
        open_question="Q-AI-02",
    ),
    SettingDefinition(
        "ai.escalate_topics",
        "ai",
        "Topics the AI always passes to a person (proposed list).",
        {"type": "array", "items": {"type": "string"}},
        [
            "pricing_outside_tool",
            "discounts",
            "refunds",
            "complaints",
            "legal",
            "safeguarding",
            "health",
            "out_of_market",
        ],
        OWNER,
        open_question="Q-AI-04",
    ),
    SettingDefinition(
        "ai.monthly_budget",
        "ai",
        "Monthly AI spend limit. Unset = per-run limits only.",
        {"type": ["object", "null"]},
        None,
        OWNER,
        open_question="Q-AI-06",
    ),
    # ---------------------------------------------------------------- delivery, payments, retention
    SettingDefinition(
        "scheduling.trials",
        "delivery",
        "Who proposes trials.",
        _enum("staff_only", "ai_propose"),
        "staff_only",
        SALES,
        open_question="Q-SAL-02, Q-SCH-02",
    ),
    SettingDefinition(
        "scheduling.lesson_lengths",
        "delivery",
        "Lesson lengths offered, in minutes.",
        {"type": "array", "items": {"type": "integer", "minimum": 15, "maximum": 240}, "minItems": 1},
        [60],
        ADMIN,
        open_question="Q-SCH-03",
    ),
    SettingDefinition(
        "tutors.required_checks",
        "delivery",
        "Tutor checks required before assignment. Empty = a coordinator confirms every assignment.",
        {"type": "array", "items": {"type": "string"}},
        [],
        ADMIN,
        scopes=("global", "market"),
        open_question="Q-TUT-03",
    ),
    SettingDefinition(
        "payments.provider",
        "payments",
        "Payment provider. 'none' = payments recorded and confirmed by Finance.",
        {"type": "string"},
        "none",
        FINANCE,
        open_question="Q-PAY-01",
    ),
    SettingDefinition(
        "payments.structure",
        "payments",
        "Invoice structure.",
        _enum("single_invoice_per_quotation", "instalments"),
        "single_invoice_per_quotation",
        FINANCE,
        open_question="Q-PAY-02",
    ),
    SettingDefinition(
        "payments.reminders",
        "payments",
        "Payment reminders.",
        _enum("disabled", "enabled"),
        "disabled",
        FINANCE,
        open_question="Q-PAY-07",
    ),
    SettingDefinition(
        "ledger.cancellation_rules",
        "payments",
        "Cancellation/no-show deductions. Empty = no automatic deductions; staff record adjustments.",
        {"type": "array"},
        [],
        ADMIN,
        scopes=("global", "price_book_version"),
        open_question="Q-PKG-09",
    ),
    SettingDefinition(
        "retention.signals",
        "retention",
        "Retention signals and thresholds.",
        _enum("disabled", "enabled"),
        "disabled",
        SALES,
        open_question="Q-SAL-08",
    ),
    SettingDefinition(
        "referrals.enabled",
        "retention",
        "Referral programme.",
        _BOOL,
        False,
        OWNER,
        open_question="Q-SAL-05",
    ),
    # ---------------------------------------------------------------- platform
    SettingDefinition(
        "auth.sso",
        "platform",
        "Staff single sign-on. 'off' = local accounts with mandatory MFA.",
        _enum("off", "google", "microsoft"),
        "off",
        OWNER,
        open_question="Q-TECH-01",
    ),
    SettingDefinition(
        "auth.sso_satisfies_mfa",
        "platform",
        "Whether a single sign-on that the provider reports as multi-factor ('amr' contains 'mfa') replaces "
        "Mixt's own two-step code. false = staff still enter their authenticator code after single sign-on.",
        _BOOL,
        False,
        OWNER,
        open_question="Q-TECH-01",
    ),
    SettingDefinition(
        "infra.region",
        "platform",
        "Hosting region for real customer data. Unset = production with real data is blocked.",
        {"type": ["string", "null"]},
        None,
        OWNER,
        scopes=("global", "deployment"),
        open_question="Q-CMP-02",
    ),
    SettingDefinition(
        "privacy.retention",
        "platform",
        "Retention periods per data type. Empty = nothing deleted automatically; erasure via requests only.",
        {"type": "object"},
        {},
        OWNER,
        scopes=("global", "data_type"),
        open_question="Q-CMP-07",
    ),
    SettingDefinition(
        "notifications.internal_channel",
        "platform",
        "Where staff alerts go.",
        _enum("dashboard_email", "slack", "teams"),
        "dashboard_email",
        ADMIN,
        open_question="Q-TEAM-04",
    ),
)

BY_KEY: dict[str, SettingDefinition] = {d.key: d for d in DEFINITIONS}
