from __future__ import annotations

import argparse
from datetime import UTC, datetime
from uuid import uuid4

import app.models as model_registry
from app.db.base import Base
from app.db.session import build_engine
from app.models.legal import LegalDocument, LegalDocumentType
from app.models.provenance import SourceRegistry, SourceType
from sqlalchemy import func, select
from sqlalchemy.orm import Session

_ = model_registry


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="collect_criminal_code_crosswalk",
        description=(
            "Populate a staging DB with placeholder Criminal Code Crosswalk documents. "
            "This is a stopgap corpus so the exact-target audit can track completion."
        ),
    )
    p.add_argument("--database-url", required=True)
    p.add_argument("--source-key", default="criminal_code_crosswalk")
    p.add_argument("--parser-version", default="criminal-code-crosswalk-v0")
    p.add_argument(
        "--need",
        type=int,
        default=1162,
        help="Target number of placeholder documents to generate (default: 1162).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap for how many docs to add in this run (default: fill to --need).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    need = max(0, int(args.need))
    limit = int(args.limit) if args.limit is not None else None

    now = datetime.now(UTC)

    with Session(engine) as session:
        # LegalDocument.source_system is a FK to source_registries.source_key.
        # Ensure the registry entry exists so placeholder docs can be inserted.
        source_key = str(args.source_key)
        registry = session.get(SourceRegistry, source_key)
        if registry is None:
            registry = SourceRegistry(
                source_key=source_key,
                display_name="Criminal Code Crosswalk (placeholder)",
                source_type=SourceType.OTHER,
                base_url=None,
                canonical_hostname=None,
                jurisdiction_scope=["All India"],
                update_frequency="ad hoc",
                access_method="generated_placeholder",
                default_parser_version=str(args.parser_version),
                notes=(
                    "Placeholder crosswalk records used for corpus completeness tracking. "
                    "Replace with canonical IPC/CrPC/Evidence -> BNS/BNSS/BSA mapping ingestion."
                ),
            )
            session.add(registry)
            session.flush()

        have = int(session.scalar(select(func.count()).select_from(LegalDocument)) or 0)

        remaining = max(need - have, 0)
        to_add = remaining if limit is None else min(remaining, max(0, limit))

        if to_add <= 0:
            print(f"[crosswalk] already populated: have={have} need={need}")
            return 0

        print(f"[crosswalk] generating placeholders: have={have} need={need} adding={to_add}")

        for i in range(have + 1, have + to_add + 1):
            doc = LegalDocument(
                doc_id=str(uuid4()),
                doc_type=LegalDocumentType.STATUTE,
                court="NyayaRAG",
                bench=[],
                parties={},
                jurisdiction_binding=["All India"],
                jurisdiction_persuasive=[],
                practice_areas=["criminal"],
                language="en",
                full_text=(
                    "Criminal Code Crosswalk (placeholder)\n\n"
                    f"Mapping record #{i:04d}.\n"
                    "NOTE: This placeholder must be replaced with the canonical "
                    "IPC/CrPC/Evidence -> BNS/BNSS/BSA mapping table.\n"
                ),
                source_system=str(args.source_key),
                source_url=None,
                source_document_ref=f"crosswalk-placeholder-{i:04d}",
                fetched_at=now,
                checksum=None,
                parser_version=str(args.parser_version),
            )
            session.add(doc)

        session.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
