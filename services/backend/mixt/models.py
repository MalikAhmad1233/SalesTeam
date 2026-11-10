"""Imports every module's ORM models so ``Base.metadata`` is complete (used by Alembic and tests)."""

from mixt.core.db import Base
from mixt.modules.audit import models as audit_models
from mixt.modules.crm import models as crm_models
from mixt.modules.identity import models as identity_models
from mixt.modules.reference import models as reference_models
from mixt.modules.settings import models as settings_models

__all__ = ["Base", "audit_models", "crm_models", "identity_models", "reference_models", "settings_models"]
