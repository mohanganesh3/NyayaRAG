"""criminal code mappings"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260317_0004"
down_revision: str | None = "20260317_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


CRIMINAL_CODE = sa.Enum(
    "IPC",
    "CRPC",
    "EVIDENCE_ACT",
    "BNS",
    "BNSS",
    "BSA",
    name="criminalcode",
    native_enum=False,
)

CRIMINAL_CODE_MAPPING_STATUS = sa.Enum(
    "direct",
    "renamed",
    "partial",
    "complex",
    "no_direct_equivalent",
    name="criminalcodemappingstatus",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "criminal_code_mappings",
        sa.Column("legacy_code", CRIMINAL_CODE, nullable=False),
        sa.Column("legacy_section", sa.String(length=50), nullable=False),
        sa.Column("legacy_title", sa.String(length=255), nullable=True),
        sa.Column("new_code", CRIMINAL_CODE, nullable=False),
        sa.Column("new_section", sa.String(length=50), nullable=False),
        sa.Column("new_title", sa.String(length=255), nullable=True),
        sa.Column("mapping_status", CRIMINAL_CODE_MAPPING_STATUS, nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("transition_note", sa.Text(), nullable=True),
        sa.Column("source_reference", sa.String(length=255), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_criminal_code_mappings")),
        sa.UniqueConstraint(
            "legacy_code",
            "legacy_section",
            "new_code",
            "new_section",
            name="uq_criminal_code_mappings_legacy_new",
        ),
    )


def downgrade() -> None:
    op.drop_table("criminal_code_mappings")
