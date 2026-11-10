"""Permission catalogue and default roles (docs/08 §3.1).

The migration seeds exactly this catalogue; ``tests/test_identity_catalogue.py`` fails if the
database and this file drift apart. Roles are data and can be adjusted later (Q-TEAM-02).
"""

from __future__ import annotations

PERMISSIONS: dict[str, str] = {
    "users.read": "View staff users",
    "users.manage": "Create users, change their status and roles",
    "teams.manage": "Create teams and manage membership",
    "reference.read": "View reference data (markets, currencies, curricula)",
    "reference.markets.manage": "Add or change markets (excluded countries are always blocked)",
    "reference.curricula.manage": "Add curricula, boards or qualifications (requires a decision-log reference)",
    "settings.read": "View settings and outstanding decisions",
    "settings.change.owner": "Change settings reserved for the Owner",
    "settings.change.pricing": "Change pricing settings",
    "settings.change.sales": "Change sales settings",
    "settings.change.admin": "Change operations settings",
    "settings.change.finance": "Change finance settings",
    "audit.read": "View the audit log",
    "audit.verify": "Verify audit-log integrity",
    "crm.accounts.read": "View accounts the user has access to",
    "crm.accounts.read_all": "View all accounts regardless of owner (optionally limited to a market)",
    "crm.accounts.create": "Create accounts",
    "crm.accounts.update": "Update accounts the user has access to",
    "crm.accounts.assign_owner": "Change an account's owner",
    "crm.market.confirm": "Confirm an account's pricing market",
    "crm.consents.record": "Record consent given or withdrawn",
    "crm.students.manage": "Create and update students and their academic profiles",
    "crm.students.learning_needs.read": "Read restricted learning-needs notes",
    "crm.students.learning_needs.write": "Write restricted learning-needs notes",
    # Phase 1b (migration 0002)
    "leads.read": "View leads for households you can see",
    "leads.create": "Enter leads by hand",
    "leads.import": "Import leads from a spreadsheet",
    "leads.review": "Review out-of-market, spam and duplicate leads",
    "leads.campaigns.manage": "Create campaigns for lead attribution",
    "crm.opportunities.manage": "Create and update opportunities and move them through the pipeline",
    "crm.accounts.merge": "Merge duplicate households",
    "crm.tasks.manage": "Create and update tasks",
    "crm.notes.write": "Add notes",
    "crm.tags.manage": "Create tags",
    "events.dead_letters.manage": "View and replay failed background work",
}

_PHASE_1B_ALL = [
    "leads.read",
    "leads.create",
    "leads.import",
    "leads.review",
    "leads.campaigns.manage",
    "crm.opportunities.manage",
    "crm.accounts.merge",
    "crm.tasks.manage",
    "crm.notes.write",
    "crm.tags.manage",
]
_REP_1B = ["leads.read", "leads.create", "crm.opportunities.manage", "crm.tasks.manage", "crm.notes.write"]

_CRM_CORE = [
    "crm.accounts.read",
    "crm.accounts.create",
    "crm.accounts.update",
    "crm.market.confirm",
    "crm.consents.record",
    "crm.students.manage",
]

ROLES: dict[str, tuple[str, str, list[str]]] = {
    "owner": ("Owner / Super Admin", "Everything, including security settings and role management", list(PERMISSIONS)),
    "admin": (
        "Admin (Operations)",
        "Users, reference data, operations settings, all CRM records",
        [
            "users.read",
            "users.manage",
            "teams.manage",
            "reference.read",
            "reference.markets.manage",
            "settings.read",
            "settings.change.admin",
            "audit.read",
            "audit.verify",
            *_CRM_CORE,
            "crm.accounts.read_all",
            "crm.accounts.assign_owner",
            *_PHASE_1B_ALL,
            "events.dead_letters.manage",
        ],
    ),
    "pricing_manager": (
        "Pricing Manager",
        "Pricing configuration and approvals",
        ["reference.read", "settings.read", "settings.change.pricing"],
    ),
    "sales_manager": (
        "Sales Manager",
        "All accounts in their markets/teams, assignments, sales settings",
        [
            "users.read",
            "reference.read",
            "settings.read",
            "settings.change.sales",
            *_CRM_CORE,
            "crm.accounts.read_all",
            "crm.accounts.assign_owner",
            "crm.students.learning_needs.read",
            "crm.students.learning_needs.write",
            *_PHASE_1B_ALL,
        ],
    ),
    "sales_rep": (
        "Sales Representative",
        "Own accounts and the unassigned pool",
        ["reference.read", "settings.read", *_CRM_CORE, *_REP_1B],
    ),
    "finance": (
        "Finance",
        "Invoices and payments (from Phase 6), finance settings",
        [
            "reference.read",
            "settings.read",
            "settings.change.finance",
            "crm.accounts.read",
            "crm.accounts.read_all",
            "crm.tasks.manage",
            "crm.notes.write",
        ],
    ),
    "tutor_coordinator": (
        "Tutor Coordinator",
        "Students, tutors and trials",
        [
            "reference.read",
            "settings.read",
            "crm.accounts.read",
            "crm.accounts.read_all",
            "crm.students.manage",
            "crm.students.learning_needs.read",
            "crm.students.learning_needs.write",
            "crm.tasks.manage",
            "crm.notes.write",
        ],
    ),
    "analyst": (
        "Analyst (read-only)",
        "Reports; no personal-data access by default",
        ["reference.read", "settings.read"],
    ),
}
