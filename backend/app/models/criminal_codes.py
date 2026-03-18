from __future__ import annotations

from datetime import date as date_value
from enum import StrEnum

from sqlalchemy import Boolean, Date, Enum, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

CRIMINAL_CODE_CUTOVER = date_value(2024, 7, 1)


class CriminalCode(StrEnum):
    IPC = "IPC"
    CRPC = "CRPC"
    EVIDENCE_ACT = "EVIDENCE_ACT"
    BNS = "BNS"
    BNSS = "BNSS"
    BSA = "BSA"


class CriminalCodeMappingStatus(StrEnum):
    DIRECT = "direct"
    RENAMED = "renamed"
    PARTIAL = "partial"
    COMPLEX = "complex"
    NO_DIRECT_EQUIVALENT = "no_direct_equivalent"


class CriminalCodeMapping(TimestampMixin, UUIDPrimaryKeyMixin, Base):
    __tablename__ = "criminal_code_mappings"
    __table_args__ = (
        UniqueConstraint(
            "legacy_code",
            "legacy_section",
            "new_code",
            "new_section",
            name="uq_criminal_code_mappings_legacy_new",
        ),
    )

    legacy_code: Mapped[CriminalCode] = mapped_column(
        Enum(CriminalCode, native_enum=False),
        nullable=False,
    )
    legacy_section: Mapped[str] = mapped_column(String(50), nullable=False)
    legacy_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    new_code: Mapped[CriminalCode] = mapped_column(
        Enum(CriminalCode, native_enum=False),
        nullable=False,
    )
    new_section: Mapped[str] = mapped_column(String(50), nullable=False)
    new_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mapping_status: Mapped[CriminalCodeMappingStatus] = mapped_column(
        Enum(CriminalCodeMappingStatus, native_enum=False),
        nullable=False,
        default=CriminalCodeMappingStatus.DIRECT,
    )
    effective_from: Mapped[date_value] = mapped_column(
        Date,
        nullable=False,
        default=CRIMINAL_CODE_CUTOVER,
    )
    effective_until: Mapped[date_value | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    transition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
