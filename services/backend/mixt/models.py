"""Imports every module's ORM models so ``Base.metadata`` is complete (used by Alembic and tests)."""

from mixt.core.db import Base
from mixt.modules.audit import models as audit_models
from mixt.modules.crm import models as crm_models
from mixt.modules.engagement import models as engagement_models
from mixt.modules.events import models as events_models
from mixt.modules.identity import models as identity_models
from mixt.modules.integrations import models as integrations_models
from mixt.modules.leads import models as leads_models
from mixt.modules.messaging import models as messaging_models
from mixt.modules.pipeline import models as pipeline_models
from mixt.modules.pricing import models as pricing_models
from mixt.modules.quotations import models as quotations_models
from mixt.modules.reference import models as reference_models
from mixt.modules.settings import models as settings_models
from mixt.modules.sso import models as sso_models

__all__ = [
    "Base",
    "audit_models",
    "crm_models",
    "engagement_models",
    "events_models",
    "identity_models",
    "integrations_models",
    "leads_models",
    "messaging_models",
    "pipeline_models",
    "pricing_models",
    "quotations_models",
    "reference_models",
    "settings_models",
    "sso_models",
]
