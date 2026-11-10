"""CRM use cases: households, contacts, contact points, consents, students.

Rules applied here:
- ADR-13: the pricing market is set only by an explicit confirmation from a person; nothing
  infers it from currency, phone prefix, curriculum or country of residence.
- BD-005 / setting ``markets.out_of_market_handling``: an account living outside the 13 operating
  markets (including the US) is flagged ``out_of_market`` for a person to review.
- Records the caller cannot see are reported as "not found" so their existence is not revealed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import Select, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from mixt.core import crypto
from mixt.core.context import Actor
from mixt.core.errors import NotFound, PermissionDenied, PreconditionFailed, ValidationFailed
from mixt.core.ids import uuid7
from mixt.core.normalize import normalize_email, normalize_phone
from mixt.core.timezones import InvalidTimezone, now_utc, validate_timezone
from mixt.modules.audit import service as audit
from mixt.modules.crm.models import (
    Account,
    Consent,
    Contact,
    ContactPoint,
    Student,
    StudentExam,
    StudentSubject,
)
from mixt.modules.crm.policies import account_visibility
from mixt.modules.identity import service as identity
from mixt.modules.identity.access import Access
from mixt.modules.reference import service as reference

MANUAL_LIFECYCLE_STAGES = frozenset({"lead", "prospect", "disqualified", "out_of_market"})
SYSTEM_LIFECYCLE_STAGES = frozenset({"customer", "former_customer"})  # set by enrolment/payments later


# ------------------------------------------------------------------ helpers


def _tz(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return validate_timezone(value)
    except InvalidTimezone as exc:
        raise ValidationFailed("INVALID_TIMEZONE", str(exc)) from exc


def _country(db: Session, code: str | None) -> str | None:
    if code is None:
        return None
    normalized = code.upper()
    if not reference.country_exists(db, normalized):
        raise ValidationFailed("UNKNOWN_COUNTRY", f"'{code}' is not an ISO 3166-1 country code.")
    return normalized


def _language(db: Session, code: str | None) -> str | None:
    if code is None:
        return None
    if not reference.language_exists(db, code):
        raise ValidationFailed("UNKNOWN_LANGUAGE", f"Language '{code}' is not in the reference list.")
    return code


def _residence_lifecycle(db: Session, country: str | None, current: str) -> str:
    """Out-of-market flag from residence. Never sets or implies a pricing market."""
    if country is None:
        return current
    served = reference.active_market_for_country(db, country) is not None
    if not served:
        return "out_of_market"
    return "lead" if current == "out_of_market" else current


def _snapshot(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {f: getattr(obj, f) for f in fields}


def _check_version(obj: Any, expected_version: int | None) -> None:
    if expected_version is None:
        raise PreconditionFailed("VERSION_REQUIRED", "Send the record version you edited (If-Match).")
    if obj.version != expected_version:
        raise PreconditionFailed("VERSION_MISMATCH", "This record was changed by someone else; reload it.")


def mask_contact_value(kind: str, value: str) -> str:
    if kind == "email" and "@" in value:
        local, domain = value.split("@", 1)
        return f"{local[:1]}***@{domain}"
    if len(value) <= 4:
        return "***"
    return f"{value[:4]}***{value[-2:]}"


# ------------------------------------------------------------------ accounts


ACCOUNT_FIELDS = (
    "display_name",
    "kind",
    "country_of_residence",
    "timezone",
    "preferred_language",
    "lifecycle_stage",
    "owner_user_id",
    "is_vip",
    "status",
)


def _visible_accounts(db: Session, access: Access) -> Select[tuple[Account]]:
    access.require_somewhere("crm.accounts.read")
    query = select(Account).where(Account.status != "anonymised")
    condition = account_visibility(db, access)
    return query if condition is None else query.where(condition)


def get_account(db: Session, access: Access, account_id: uuid.UUID) -> Account:
    account = db.scalar(_visible_accounts(db, access).where(Account.id == account_id))
    if account is None:
        raise NotFound("ACCOUNT_NOT_FOUND", "Account not found.")
    return account


def list_accounts(
    db: Session,
    access: Access,
    search: str | None = None,
    lifecycle_stage: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    before_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[Account]:
    query = _visible_accounts(db, access).order_by(Account.id.desc()).limit(min(max(limit, 1), 200))
    if search:
        pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(Account.display_name.ilike(pattern) | (Account.account_number == search.upper()))
    if lifecycle_stage:
        query = query.where(Account.lifecycle_stage == lifecycle_stage)
    if owner_user_id:
        query = query.where(Account.owner_user_id == owner_user_id)
    if before_id:
        query = query.where(Account.id < before_id)
    return list(db.scalars(query))


def _require_update(access: Access) -> None:
    access.require_somewhere("crm.accounts.update")


def _validate_owner(db: Session, owner_user_id: uuid.UUID | None) -> None:
    if owner_user_id is not None and not identity.user_is_active(db, owner_user_id):
        raise ValidationFailed("INVALID_OWNER", "The owner must be an active user.")


def create_account(
    db: Session,
    actor: Actor,
    access: Access,
    display_name: str,
    kind: str = "household",
    country_of_residence: str | None = None,
    timezone: str | None = None,
    preferred_language: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    owner_explicit: bool = False,
    is_vip: bool = False,
) -> Account:
    access.require_somewhere("crm.accounts.create")
    if kind not in ("household", "institution"):
        raise ValidationFailed("INVALID_KIND", "Kind must be household or institution.")
    if not display_name.strip():
        raise ValidationFailed("NAME_REQUIRED", "A display name is required.")
    if access.has_somewhere("crm.accounts.assign_owner") and owner_explicit:
        owner = owner_user_id
    elif owner_explicit and owner_user_id != access.user_id:
        raise PermissionDenied("PERMISSION_DENIED", "You cannot assign accounts to other people or to the pool.")
    else:
        owner = access.user_id  # reps own what they create
    _validate_owner(db, owner)
    country = _country(db, country_of_residence)
    account = Account(
        display_name=display_name.strip(),
        kind=kind,
        country_of_residence=country,
        timezone=_tz(timezone),
        preferred_language=_language(db, preferred_language),
        owner_user_id=owner,
        is_vip=is_vip,
        lifecycle_stage=_residence_lifecycle(db, country, "lead"),
        created_by=actor.principal_id,
    )
    db.add(account)
    db.flush()
    db.refresh(account)
    audit.record(
        db, actor, "account_created", "account", account.id, audit.diff({}, _snapshot(account, ACCOUNT_FIELDS))
    )
    return account


def update_account(
    db: Session,
    actor: Actor,
    access: Access,
    account_id: uuid.UUID,
    expected_version: int | None,
    changes: dict[str, Any],
) -> Account:
    _require_update(access)
    account = get_account(db, access, account_id)
    _check_version(account, expected_version)
    before = _snapshot(account, ACCOUNT_FIELDS)
    allowed = {
        "display_name",
        "country_of_residence",
        "timezone",
        "preferred_language",
        "is_vip",
        "lifecycle_stage",
        "owner_user_id",
        "kind",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationFailed("UNKNOWN_FIELDS", f"These fields cannot be changed here: {', '.join(sorted(unknown))}.")
    if "display_name" in changes:
        if not str(changes["display_name"] or "").strip():
            raise ValidationFailed("NAME_REQUIRED", "A display name is required.")
        account.display_name = str(changes["display_name"]).strip()
    if "kind" in changes:
        if changes["kind"] not in ("household", "institution"):
            raise ValidationFailed("INVALID_KIND", "Kind must be household or institution.")
        account.kind = changes["kind"]
    if "timezone" in changes:
        account.timezone = _tz(changes["timezone"])
    if "preferred_language" in changes:
        account.preferred_language = _language(db, changes["preferred_language"])
    if "is_vip" in changes:
        account.is_vip = bool(changes["is_vip"])
    if "owner_user_id" in changes:
        access.require_somewhere("crm.accounts.assign_owner")
        _validate_owner(db, changes["owner_user_id"])
        account.owner_user_id = changes["owner_user_id"]
    if "lifecycle_stage" in changes:
        stage = changes["lifecycle_stage"]
        if stage in SYSTEM_LIFECYCLE_STAGES:
            raise ValidationFailed("LIFECYCLE_MANAGED_BY_SYSTEM", f"'{stage}' is set by enrolment and payments.")
        if stage not in MANUAL_LIFECYCLE_STAGES:
            raise ValidationFailed("INVALID_LIFECYCLE_STAGE", f"Unknown lifecycle stage '{stage}'.")
        account.lifecycle_stage = stage
    if "country_of_residence" in changes:
        account.country_of_residence = _country(db, changes["country_of_residence"])
        account.lifecycle_stage = _residence_lifecycle(db, account.country_of_residence, account.lifecycle_stage)
    try:
        db.flush()
    except StaleDataError as exc:
        raise PreconditionFailed("VERSION_MISMATCH", "This record was changed by someone else; reload it.") from exc
    db.refresh(account)
    audit.record(
        db, actor, "account_updated", "account", account.id, audit.diff(before, _snapshot(account, ACCOUNT_FIELDS))
    )
    return account


def confirm_market(
    db: Session,
    actor: Actor,
    access: Access,
    account_id: uuid.UUID,
    market_id: uuid.UUID,
    note: str,
    expected_version: int | None,
) -> Account:
    """A person confirms the account's pricing market (ADR-13). Never automatic."""
    account = get_account(db, access, account_id)
    access.require("crm.market.confirm", market_id)
    _check_version(account, expected_version)
    market = reference.require_market(db, market_id)
    if market.status != "active":
        raise ValidationFailed("MARKET_NOT_ACTIVE", f"{market.name} is not an active market.")
    if len(note.strip()) < 5:
        raise ValidationFailed(
            "CONFIRMATION_NOTE_REQUIRED", "Say how the market was confirmed (e.g. 'parent said they live in Dubai')."
        )
    before = {"market_id": account.market_id, "lifecycle_stage": account.lifecycle_stage}
    account.market_id = market.id
    account.market_confirmed_by = actor.principal_id
    account.market_confirmed_at = now_utc()
    account.market_confirmation_note = note.strip()
    if account.lifecycle_stage == "out_of_market":
        account.lifecycle_stage = "lead"
    db.flush()
    db.refresh(account)
    audit.record(
        db,
        actor,
        "account_market_confirmed",
        "account",
        account.id,
        {
            **audit.diff(before, {"market_id": account.market_id, "lifecycle_stage": account.lifecycle_stage}),
            "note": note.strip(),
        },
    )
    return account


# ------------------------------------------------------------------ contacts


CONTACT_FIELDS = (
    "role",
    "first_name",
    "last_name",
    "preferred_name",
    "relationship_to_students",
    "is_primary",
    "is_decision_maker",
    "preferred_language",
    "timezone",
)
CONTACT_ROLES = frozenset({"guardian", "payer", "student", "other"})


def _clear_primary(db: Session, account_id: uuid.UUID, except_id: uuid.UUID | None) -> None:
    """Clear the primary flag on other contacts first, so the one-primary index is never violated."""
    query = update(Contact).where(Contact.account_id == account_id, Contact.is_primary)
    if except_id is not None:
        query = query.where(Contact.id != except_id)
    db.execute(
        query.values(is_primary=False, version=Contact.version + 1), execution_options={"synchronize_session": "fetch"}
    )


def list_contacts(db: Session, access: Access, account_id: uuid.UUID) -> list[Contact]:
    get_account(db, access, account_id)
    return list(
        db.scalars(
            select(Contact)
            .where(Contact.account_id == account_id, Contact.archived_at.is_(None))
            .order_by(Contact.created_at)
        )
    )


def _get_contact(db: Session, access: Access, contact_id: uuid.UUID) -> tuple[Contact, Account]:
    contact = db.get(Contact, contact_id)
    if contact is None or contact.archived_at is not None:
        raise NotFound("CONTACT_NOT_FOUND", "Contact not found.")
    try:
        account = get_account(db, access, contact.account_id)
    except NotFound as exc:
        raise NotFound("CONTACT_NOT_FOUND", "Contact not found.") from exc
    return contact, account


def add_contact(db: Session, actor: Actor, access: Access, account_id: uuid.UUID, data: dict[str, Any]) -> Contact:
    _require_update(access)
    get_account(db, access, account_id)
    role = data.get("role")
    if role not in CONTACT_ROLES:
        raise ValidationFailed("INVALID_ROLE", "Role must be guardian, payer, student or other.")
    if not (data.get("first_name") or data.get("last_name") or data.get("preferred_name")):
        raise ValidationFailed("NAME_REQUIRED", "Give at least one name for the contact.")
    has_primary = db.scalar(
        select(func.count())
        .select_from(Contact)
        .where(Contact.account_id == account_id, Contact.is_primary, Contact.archived_at.is_(None))
    )
    make_primary = bool(data.get("is_primary")) or not has_primary
    if make_primary and has_primary:
        _clear_primary(db, account_id, None)
    contact = Contact(
        account_id=account_id,
        role=role,
        first_name=data.get("first_name"),
        last_name=data.get("last_name"),
        preferred_name=data.get("preferred_name"),
        relationship_to_students=data.get("relationship_to_students"),
        is_primary=make_primary,
        is_decision_maker=data.get("is_decision_maker"),
        preferred_language=_language(db, data.get("preferred_language")),
        timezone=_tz(data.get("timezone")),
        created_by=actor.principal_id,
    )
    db.add(contact)
    db.flush()
    db.refresh(contact)
    audit.record(
        db,
        actor,
        "contact_created",
        "contact",
        contact.id,
        {"account_id": str(account_id), **audit.diff({}, _snapshot(contact, CONTACT_FIELDS))},
    )
    return contact


def update_contact(
    db: Session,
    actor: Actor,
    access: Access,
    contact_id: uuid.UUID,
    expected_version: int | None,
    changes: dict[str, Any],
) -> Contact:
    _require_update(access)
    contact, account = _get_contact(db, access, contact_id)
    _check_version(contact, expected_version)
    allowed = set(CONTACT_FIELDS)
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationFailed("UNKNOWN_FIELDS", f"These fields cannot be changed here: {', '.join(sorted(unknown))}.")
    before = _snapshot(contact, CONTACT_FIELDS)
    if "role" in changes and changes["role"] not in CONTACT_ROLES:
        raise ValidationFailed("INVALID_ROLE", "Role must be guardian, payer, student or other.")
    if changes.get("is_primary") is False and contact.is_primary:
        raise ValidationFailed("PRIMARY_REQUIRED", "Make another contact primary instead of removing the flag.")
    if changes.get("is_primary") and not contact.is_primary:
        _clear_primary(db, account.id, contact.id)
    for key, raw in changes.items():
        if key == "timezone":
            value = _tz(raw)
        elif key == "preferred_language":
            value = _language(db, raw)
        else:
            value = raw
        setattr(contact, key, value)
    try:
        db.flush()
    except StaleDataError as exc:
        raise PreconditionFailed("VERSION_MISMATCH", "This record was changed by someone else; reload it.") from exc
    db.refresh(contact)
    audit.record(
        db, actor, "contact_updated", "contact", contact.id, audit.diff(before, _snapshot(contact, CONTACT_FIELDS))
    )
    return contact


# ------------------------------------------------------------------ contact points


@dataclass(frozen=True)
class AddedContactPoint:
    contact_point: ContactPoint
    possible_duplicate: bool


def _normalize_point(kind: str, value: str, region_hint: str | None) -> str:
    if kind in ("phone", "whatsapp"):
        return normalize_phone(value, region_hint)  # region only helps parse; never decides a market
    if kind == "email":
        return normalize_email(value)
    cleaned = value.strip()
    if not cleaned:
        raise ValidationFailed("VALUE_REQUIRED", "A value is required.")
    return cleaned


def list_contact_points(db: Session, access: Access, contact_id: uuid.UUID) -> list[ContactPoint]:
    _get_contact(db, access, contact_id)
    return list(
        db.scalars(select(ContactPoint).where(ContactPoint.contact_id == contact_id).order_by(ContactPoint.created_at))
    )


def add_contact_point(
    db: Session, actor: Actor, access: Access, contact_id: uuid.UUID, kind: str, value: str, is_primary: bool = False
) -> AddedContactPoint:
    _require_update(access)
    contact, account = _get_contact(db, access, contact_id)
    if kind not in ("phone", "whatsapp", "email", "instagram", "web_chat"):
        raise ValidationFailed("INVALID_KIND", "Kind must be phone, whatsapp, email, instagram or web_chat.")
    normalized = _normalize_point(kind, value, account.country_of_residence)
    same_contact = db.scalar(
        select(ContactPoint.id).where(
            ContactPoint.contact_id == contact.id, ContactPoint.kind == kind, ContactPoint.value == normalized
        )
    )
    if same_contact is not None:
        raise ValidationFailed("DUPLICATE_CONTACT_POINT", "This contact already has that value.")
    duplicate = db.scalar(
        select(func.count())
        .select_from(ContactPoint)
        .join(Contact, Contact.id == ContactPoint.contact_id)
        .where(ContactPoint.kind == kind, ContactPoint.value == normalized, Contact.account_id != account.id)
    )
    point = ContactPoint(
        contact_id=contact.id, kind=kind, value=normalized, is_primary=is_primary, created_by=actor.principal_id
    )
    db.add(point)
    db.flush()
    audit.record(
        db,
        actor,
        "contact_point_added",
        "contact_point",
        point.id,
        {
            "contact_id": str(contact.id),
            "kind": kind,
            "value": mask_contact_value(kind, normalized),
            "possible_duplicate": bool(duplicate),
        },
    )
    return AddedContactPoint(point, possible_duplicate=bool(duplicate))


# ------------------------------------------------------------------ consents


CONSENT_STATUSES = frozenset({"granted", "withdrawn", "denied"})
CONSENT_LEGAL_BASES = frozenset({"consent", "contract", "legitimate_interests", "legal_obligation"})
CONSENT_SOURCES = frozenset({"web_form", "lead_ad_form", "whatsapp_keyword", "email_link", "staff_logged", "import"})
CONSENT_PURPOSES = frozenset(
    {
        "service_messages",
        "marketing_whatsapp",
        "marketing_email",
        "session_recording",
        "ai_assisted_conversation",
        "data_processing",
    }
)


def record_consent(
    db: Session,
    actor: Actor,
    access: Access,
    contact_id: uuid.UUID,
    purpose: str,
    status: str,
    legal_basis: str,
    source: str,
    evidence: dict[str, Any],
    contact_point_id: uuid.UUID | None = None,
) -> Consent:
    access.require_somewhere("crm.consents.record")
    contact, _ = _get_contact(db, access, contact_id)
    if purpose not in CONSENT_PURPOSES:
        raise ValidationFailed("INVALID_PURPOSE", f"Unknown consent purpose '{purpose}'.")
    if status not in CONSENT_STATUSES or legal_basis not in CONSENT_LEGAL_BASES or source not in CONSENT_SOURCES:
        raise ValidationFailed("INVALID_CONSENT", "Status, legal basis or source is not one of the allowed values.")
    if not evidence:
        raise ValidationFailed("EVIDENCE_REQUIRED", "Record what the person agreed to and how (e.g. form wording).")
    if contact_point_id is not None:
        point = db.get(ContactPoint, contact_point_id)
        if point is None or point.contact_id != contact.id:
            raise ValidationFailed("INVALID_CONTACT_POINT", "The contact point does not belong to this contact.")
    consent = Consent(
        contact_id=contact.id,
        contact_point_id=contact_point_id,
        purpose=purpose,
        status=status,
        legal_basis=legal_basis,
        source=source,
        evidence=evidence,
        captured_by=actor.principal_id,
    )
    db.add(consent)
    db.flush()
    audit.record(
        db,
        actor,
        "consent_recorded",
        "consent",
        consent.id,
        {"contact_id": str(contact.id), "purpose": purpose, "status": status, "source": source},
    )
    return consent


def consent_history(db: Session, access: Access, contact_id: uuid.UUID) -> list[Consent]:
    _get_contact(db, access, contact_id)
    return list(
        db.scalars(select(Consent).where(Consent.contact_id == contact_id).order_by(Consent.captured_at, Consent.id))
    )


def current_consents(db: Session, access: Access, contact_id: uuid.UUID) -> list[Consent]:
    """Latest consent per (purpose, contact point)."""
    latest: dict[tuple[str, uuid.UUID | None], Consent] = {}
    for consent in consent_history(db, access, contact_id):
        latest[(consent.purpose, consent.contact_point_id)] = consent
    return sorted(latest.values(), key=lambda c: (c.purpose, str(c.contact_point_id)))


# ------------------------------------------------------------------ students


STUDENT_FIELDS = (
    "first_name",
    "last_name",
    "preferred_name",
    "birth_year",
    "curriculum_id",
    "grade_text",
    "school_name",
    "country_of_study",
    "timezone",
    "goals",
    "status",
    "contact_id",
)
STUDENT_STATUSES = frozenset({"prospective", "active", "paused", "alumni"})


def _learning_aad(student_id: uuid.UUID) -> str:
    return f"students:learning_needs:{student_id}"


@dataclass
class StudentView:
    student: Student
    learning_needs: str | None = None
    learning_needs_restricted: bool = False
    subjects: list[StudentSubject] = field(default_factory=list)
    exams: list[StudentExam] = field(default_factory=list)


def _apply_student_fields(db: Session, student: Student, data: dict[str, Any]) -> None:
    if "first_name" in data:
        if not str(data["first_name"] or "").strip():
            raise ValidationFailed("NAME_REQUIRED", "A first name is required.")
        student.first_name = str(data["first_name"]).strip()
    for key in ("last_name", "preferred_name", "grade_text", "school_name", "goals"):
        if key in data:
            setattr(student, key, data[key])
    if "birth_year" in data:
        year = data["birth_year"]
        if year is not None and not (1950 <= int(year) <= date.today().year):
            raise ValidationFailed("INVALID_BIRTH_YEAR", "Birth year is out of range.")
        student.birth_year = year
    if "curriculum_code" in data:
        code = data["curriculum_code"]
        if code is None:
            student.curriculum_id = None
        else:
            curriculum = reference.curriculum_by_code(db, code)
            if curriculum is None:
                raise ValidationFailed(
                    "UNKNOWN_CURRICULUM",
                    f"'{code}' is not a confirmed curriculum (confirmed: Irish, SABIS, American, British).",
                )
            student.curriculum_id = curriculum.id
    if "country_of_study" in data:
        student.country_of_study = _country(db, data["country_of_study"])
    if "timezone" in data:
        student.timezone = _tz(data["timezone"])
    if "status" in data:
        if data["status"] not in STUDENT_STATUSES:
            raise ValidationFailed("INVALID_STATUS", "Status must be prospective, active, paused or alumni.")
        student.status = data["status"]


def _set_learning_needs(access: Access, student: Student, value: str | None) -> None:
    access.require_somewhere("crm.students.learning_needs.write")
    if value is None or not value.strip():
        student.learning_needs_ciphertext = None
        student.learning_needs_key_id = None
        return
    encrypted = crypto.encrypt_text(value.strip(), _learning_aad(student.id))
    student.learning_needs_ciphertext, student.learning_needs_key_id = encrypted.ciphertext, encrypted.key_id


def _get_student(db: Session, access: Access, student_id: uuid.UUID) -> Student:
    student = db.get(Student, student_id)
    if student is None or student.archived_at is not None:
        raise NotFound("STUDENT_NOT_FOUND", "Student not found.")
    try:
        get_account(db, access, student.account_id)
    except NotFound as exc:
        raise NotFound("STUDENT_NOT_FOUND", "Student not found.") from exc
    return student


def view_student(db: Session, access: Access, student_id: uuid.UUID) -> StudentView:
    student = _get_student(db, access, student_id)
    view = StudentView(student=student)
    if student.learning_needs_ciphertext is not None:
        if access.has_somewhere("crm.students.learning_needs.read"):
            view.learning_needs = crypto.decrypt_text(
                crypto.EncryptedValue(student.learning_needs_ciphertext, student.learning_needs_key_id or ""),
                _learning_aad(student.id),
            )
        else:
            view.learning_needs_restricted = True
    view.subjects = list(
        db.scalars(
            select(StudentSubject)
            .where(StudentSubject.student_id == student.id)
            .order_by(StudentSubject.priority.nulls_last(), StudentSubject.created_at)
        )
    )
    view.exams = list(
        db.scalars(
            select(StudentExam)
            .where(StudentExam.student_id == student.id)
            .order_by(StudentExam.exam_date.nulls_last(), StudentExam.created_at)
        )
    )
    return view


def list_students(db: Session, access: Access, account_id: uuid.UUID) -> list[StudentView]:
    get_account(db, access, account_id)
    ids = db.scalars(
        select(Student.id)
        .where(Student.account_id == account_id, Student.archived_at.is_(None))
        .order_by(Student.created_at)
    )
    return [view_student(db, access, sid) for sid in ids]


def create_student(
    db: Session, actor: Actor, access: Access, account_id: uuid.UUID, data: dict[str, Any]
) -> StudentView:
    access.require_somewhere("crm.students.manage")
    get_account(db, access, account_id)
    if "date_of_birth" in data:
        raise ValidationFailed(
            "FULL_DATE_OF_BIRTH_NOT_COLLECTED", "Only the year of birth is collected (data minimisation)."
        )
    # The id is assigned up front because the learning-needs ciphertext is bound to it.
    student = Student(id=uuid7(), account_id=account_id, first_name="", created_by=actor.principal_id)
    _apply_student_fields(db, student, {"first_name": data.get("first_name"), **data})
    if data.get("contact_id") is not None:
        contact, _ = _get_contact(db, access, data["contact_id"])
        if contact.account_id != account_id:
            raise ValidationFailed("INVALID_CONTACT", "The contact belongs to another account.")
        student.contact_id = contact.id
    if data.get("learning_needs"):
        _set_learning_needs(access, student, data["learning_needs"])
    db.add(student)
    db.flush()
    db.refresh(student)
    audit.record(
        db,
        actor,
        "student_created",
        "student",
        student.id,
        {
            "account_id": str(account_id),
            **audit.diff({}, _snapshot(student, STUDENT_FIELDS)),
            "learning_needs": "[restricted]" if student.learning_needs_ciphertext else None,
        },
    )
    return view_student(db, access, student.id)


def update_student(
    db: Session, actor: Actor, access: Access, student_id: uuid.UUID, expected_version: int | None, data: dict[str, Any]
) -> StudentView:
    access.require_somewhere("crm.students.manage")
    student = _get_student(db, access, student_id)
    _check_version(student, expected_version)
    if "date_of_birth" in data:
        raise ValidationFailed(
            "FULL_DATE_OF_BIRTH_NOT_COLLECTED", "Only the year of birth is collected (data minimisation)."
        )
    allowed = {
        "first_name",
        "last_name",
        "preferred_name",
        "birth_year",
        "curriculum_code",
        "grade_text",
        "school_name",
        "country_of_study",
        "timezone",
        "goals",
        "status",
        "learning_needs",
    }
    unknown = set(data) - allowed
    if unknown:
        raise ValidationFailed("UNKNOWN_FIELDS", f"These fields cannot be changed here: {', '.join(sorted(unknown))}.")
    before = _snapshot(student, STUDENT_FIELDS)
    had_needs = student.learning_needs_ciphertext is not None
    _apply_student_fields(db, student, data)
    if "learning_needs" in data:
        _set_learning_needs(access, student, data["learning_needs"])
    try:
        db.flush()
    except StaleDataError as exc:
        raise PreconditionFailed("VERSION_MISMATCH", "This record was changed by someone else; reload it.") from exc
    db.refresh(student)
    changes = audit.diff(before, _snapshot(student, STUDENT_FIELDS))
    if "learning_needs" in data:
        changes["learning_needs"] = {
            "from": "[restricted]" if had_needs else None,
            "to": "[restricted]" if student.learning_needs_ciphertext else None,
        }
    audit.record(db, actor, "student_updated", "student", student.id, changes)
    return view_student(db, access, student.id)


def add_student_subject(
    db: Session, actor: Actor, access: Access, student_id: uuid.UUID, data: dict[str, Any]
) -> StudentSubject:
    access.require_somewhere("crm.students.manage")
    student = _get_student(db, access, student_id)
    name = str(data.get("subject_name") or "").strip()
    if not name:
        raise ValidationFailed("SUBJECT_REQUIRED", "A subject name is required.")
    board_id = qualification_id = None
    if data.get("exam_board_code") or data.get("qualification_code"):
        if student.curriculum_id is None:
            raise ValidationFailed(
                "CURRICULUM_REQUIRED", "Set the student's curriculum before choosing a board or qualification."
            )
        if data.get("exam_board_code"):
            board = reference.board_by_code(db, student.curriculum_id, data["exam_board_code"])
            if board is None:
                raise ValidationFailed(
                    "BOARD_NOT_IN_CURRICULUM", "That exam board is not listed for the student's curriculum."
                )
            board_id = board.id
        if data.get("qualification_code"):
            qualification = reference.qualification_by_code(db, student.curriculum_id, data["qualification_code"])
            if qualification is None:
                raise ValidationFailed(
                    "QUALIFICATION_NOT_IN_CURRICULUM", "That qualification is not listed for the student's curriculum."
                )
            qualification_id = qualification.id
    status = data.get("status", "interested")
    if status not in ("interested", "active", "completed", "dropped"):
        raise ValidationFailed("INVALID_STATUS", "Status must be interested, active, completed or dropped.")
    subject = StudentSubject(
        student_id=student.id,
        subject_name=name,
        exam_board_id=board_id,
        qualification_id=qualification_id,
        current_grade=data.get("current_grade"),
        target_grade=data.get("target_grade"),
        priority=data.get("priority"),
        status=status,
    )
    db.add(subject)
    db.flush()
    audit.record(
        db,
        actor,
        "student_subject_added",
        "student",
        student.id,
        {"subject": name, "exam_board_id": board_id, "qualification_id": qualification_id},
    )
    return subject


def add_student_exam(
    db: Session, actor: Actor, access: Access, student_id: uuid.UUID, data: dict[str, Any]
) -> StudentExam:
    access.require_somewhere("crm.students.manage")
    student = _get_student(db, access, student_id)
    subject_id = data.get("student_subject_id")
    board_id = qualification_id = None
    if subject_id is not None:
        subject = db.get(StudentSubject, subject_id)
        if subject is None or subject.student_id != student.id:
            raise ValidationFailed("INVALID_SUBJECT", "The subject does not belong to this student.")
        board_id, qualification_id = subject.exam_board_id, subject.qualification_id
    source = data.get("source", "staff")
    if source not in ("customer", "staff", "ai_extracted"):
        raise ValidationFailed("INVALID_SOURCE", "Source must be customer, staff or ai_extracted.")
    if not (data.get("exam_session") or data.get("exam_date")):
        raise ValidationFailed("EXAM_WHEN_REQUIRED", "Give an exam session (e.g. 'May/June 2027') or a date.")
    exam = StudentExam(
        student_id=student.id,
        student_subject_id=subject_id,
        exam_board_id=board_id,
        qualification_id=qualification_id,
        exam_session=data.get("exam_session"),
        exam_date=data.get("exam_date"),
        paper_code=data.get("paper_code"),
        source=source,
        is_confirmed=bool(data.get("is_confirmed")) and source != "ai_extracted",
    )
    db.add(exam)
    db.flush()
    audit.record(
        db,
        actor,
        "student_exam_added",
        "student",
        student.id,
        {"exam_session": exam.exam_session, "exam_date": exam.exam_date, "source": source},
    )
    return exam
