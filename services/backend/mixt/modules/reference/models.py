"""Reference data: countries, currencies, markets, languages, curricula and academic taxonomy."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from mixt.core.db import Base, created_at_col, updated_at_col, uuid_pk


class Country(Base):
    __tablename__ = "countries"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)  # ISO 3166-1 alpha-2
    name: Mapped[str] = mapped_column(Text)
    is_excluded: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    exclusion_reason: Mapped[str | None] = mapped_column(Text)


class Currency(Base):
    __tablename__ = "currencies"
    __table_args__ = (CheckConstraint("minor_units BETWEEN 0 AND 4", name="minor_units"),)

    code: Mapped[str] = mapped_column(String(3), primary_key=True)  # ISO 4217
    name: Mapped[str] = mapped_column(Text)
    minor_units: Mapped[int] = mapped_column(SmallInteger)
    display_prefix: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Market(Base):
    """A country Mixt operates in (BD-004). Excluded countries (the US) are blocked by trigger (DB-01)."""

    __tablename__ = "markets"
    __table_args__ = (CheckConstraint("status IN ('planned','active','inactive')", name="status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(ForeignKey("countries.code"), unique=True)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    default_timezone: Mapped[str] = mapped_column(Text)
    default_language: Mapped[str | None] = mapped_column(ForeignKey("languages.code"))
    decision_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class Language(Base):
    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(Text, primary_key=True)  # BCP-47
    name: Mapped[str] = mapped_column(Text)


class Curriculum(Base):
    """Confirmed curriculum categories (BD-007). New ones need Owner approval + decision ref (BD-008)."""

    __tablename__ = "curricula"
    __table_args__ = (CheckConstraint("decision_ref ~ '^BD-[0-9]{3}$'", name="decision_ref_format"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    decision_ref: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class ExamBoard(Base):
    __tablename__ = "exam_boards"
    __table_args__ = (UniqueConstraint("curriculum_id", "code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    curriculum_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("curricula.id"))
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Qualification(Base):
    __tablename__ = "qualifications"
    __table_args__ = (UniqueConstraint("curriculum_id", "code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    curriculum_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("curricula.id"))
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class BoardQualificationOffering(Base):
    """Which board x qualification combinations Mixt teaches. Empty until confirmed (Q-ACA-02)."""

    __tablename__ = "board_qualification_offerings"

    exam_board_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exam_boards.id"), primary_key=True)
    qualification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("qualifications.id"), primary_key=True)
    offered_by_mixt: Mapped[bool | None] = mapped_column(Boolean)
    decision_ref: Mapped[str | None] = mapped_column(Text)


class GradeLevel(Base):
    """Per-curriculum grade lists. Empty until supplied (Q-ACA-03); grades are free text meanwhile."""

    __tablename__ = "grade_levels"
    __table_args__ = (UniqueConstraint("curriculum_id", "code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    curriculum_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("curricula.id"))
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class Subject(Base):
    """Controlled subject list. Empty until supplied (Q-ACA-01); subjects are free text meanwhile."""

    __tablename__ = "subjects"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
