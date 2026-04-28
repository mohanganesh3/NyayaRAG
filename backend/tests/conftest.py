from __future__ import annotations

from collections.abc import Callable

import pytest
from app.models import ApprovalStatus, SourceRegistry, SourceType
from sqlalchemy.orm import Session


@pytest.fixture
def ensure_source_registry() -> Callable[[Session, str], None]:
    """Ensure a `SourceRegistry` row exists for a given `source_key`.

    Many unit tests create ephemeral SQLite DBs and insert `LegalDocument` rows (or
    run ingestion orchestrators) that reference `source_registries` via FK.
    """

    def _ensure(
        session: Session,
        source_key: str,
        *,
        display_name: str | None = None,
        source_type: SourceType = SourceType.OTHER,
    ) -> None:
        if session.get(SourceRegistry, source_key) is not None:
            return

        session.add(
            SourceRegistry(
                source_key=source_key,
                display_name=display_name or source_key,
                source_type=source_type,
                base_url=None,
                canonical_hostname=None,
                jurisdiction_scope=["All India"],
                update_frequency=None,
                access_method=None,
                is_public=True,
                is_active=True,
                approval_status=ApprovalStatus.APPROVED,
                default_parser_version=None,
                notes=None,
            )
        )
        session.flush()

    return _ensure
