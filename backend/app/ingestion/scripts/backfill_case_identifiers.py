from __future__ import annotations

import argparse
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import build_engine
from app.models import LegalDocument


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backfill_case_identifiers",
        description=(
            "Backfill LegalDocument.headnotes[0] with a stable identifier when missing. "
            "This is used as the canonical case identifier in the corpus."
        ),
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--source-key",
        action="append",
        dest="source_keys",
        help="Restrict to a specific source_system (can be repeated).",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _choose_identifier(doc: LegalDocument) -> str | None:
    # Prefer neutral citation when available (e.g., 2025 INSC 1234), else fall back.
    return doc.neutral_citation or doc.citation or doc.source_document_ref


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = build_engine(args.database_url)
    source_keys = list(args.source_keys or [])

    updated = 0
    scanned = 0
    with Session(engine) as session:
        stmt = select(LegalDocument)
        if source_keys:
            stmt = stmt.where(LegalDocument.source_system.in_(source_keys))

        for doc in session.scalars(stmt):
            scanned += 1
            if doc.headnotes:
                continue
            identifier = _choose_identifier(doc)
            if not identifier:
                continue
            doc.headnotes = [identifier]
            updated += 1

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    payload = {
        "scanned": scanned,
        "updated": updated,
        "dry_run": bool(args.dry_run),
        "source_keys": source_keys or None,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
