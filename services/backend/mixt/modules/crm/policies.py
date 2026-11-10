"""Record-level access to CRM accounts (docs/08 §3.2).

Visible accounts for a principal:
- everything, with an unscoped ``crm.accounts.read_all``;
- accounts in their markets, with a market-scoped ``read_all`` (an account without a confirmed
  market counts by its country of residence, for visibility only, never for pricing);
- otherwise: accounts they own, accounts owned by members of teams they lead, and the unassigned
  pool (if the setting ``crm.unassigned_pool_visible_to_reps`` is on).
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_, false, or_
from sqlalchemy.orm import Session

from mixt.modules.crm.models import Account
from mixt.modules.identity.access import Access
from mixt.modules.reference import service as reference
from mixt.modules.settings import service as settings


def account_visibility(db: Session, access: Access) -> ColumnElement[bool] | None:
    """SQL condition for visible accounts, or None when everything is visible."""
    if access.has_globally("crm.accounts.read_all"):
        return None
    conditions: list[ColumnElement[bool]] = []
    markets = access.market_scopes("crm.accounts.read_all")
    if markets:
        countries = reference.market_country_codes(db, markets)
        conditions.append(
            or_(
                Account.market_id.in_(markets),
                and_(Account.market_id.is_(None), Account.country_of_residence.in_(countries)),
            )
        )
    if access.has_somewhere("crm.accounts.read"):
        if access.user_id is not None:
            conditions.append(Account.owner_user_id == access.user_id)
        if access.led_team_user_ids:
            conditions.append(Account.owner_user_id.in_(access.led_team_user_ids))
        if settings.get_value(db, "crm.unassigned_pool_visible_to_reps"):
            conditions.append(Account.owner_user_id.is_(None))
    if not conditions:
        return false()
    return or_(*conditions)
