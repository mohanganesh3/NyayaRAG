from __future__ import annotations

import argparse
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import build_engine
from app.models import DocumentChunk, IngestionRun, LegalDocument


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quality_gate",
        description="Run lightweight source-level quality checks over the corpus database.",
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--source-key", required=True)
    parser.add_argument("--label", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = build_engine(args.database_url)
    with Session(engine) as session:
        documents = int(
            session.scalar(
                select(func.count()).select_from(LegalDocument).where(
                    LegalDocument.source_system == args.source_key
                )
            )
            or 0
        )
        full_text_missing = int(
            session.scalar(
                select(func.count()).select_from(LegalDocument).where(
                    LegalDocument.source_system == args.source_key,
                    (LegalDocument.full_text.is_(None) | (LegalDocument.full_text == "")),
                )
            )
            or 0
        )
        neutral_missing = int(
            session.scalar(
                select(func.count()).select_from(LegalDocument).where(
                    LegalDocument.source_system == args.source_key,
                    LegalDocument.neutral_citation.is_(None),
                )
            )
            or 0
        )

        date_missing = int(
            session.scalar(
                select(func.count()).select_from(LegalDocument).where(
                    LegalDocument.source_system == args.source_key,
                    LegalDocument.date.is_(None),
                )
            )
            or 0
        )

        # The canonical "case number" is currently stored in headnotes[0] by the
        # AWS bulk ingest pipeline (see AwsBulkCollector._upsert_record).
        case_number_missing = int(
            session.scalar(
                select(func.count()).select_from(LegalDocument).where(
                    LegalDocument.source_system == args.source_key,
                    (LegalDocument.headnotes.is_(None) | (LegalDocument.headnotes == [])),
                )
            )
            or 0
        )
        chunks = int(
            session.scalar(
                select(func.count()).select_from(DocumentChunk).join(
                    LegalDocument,
                    DocumentChunk.doc_id == LegalDocument.doc_id,
                ).where(LegalDocument.source_system == args.source_key)
            )
            or 0
        )
        runs = int(
            session.scalar(
                select(func.count()).select_from(IngestionRun).where(
                    IngestionRun.source_key == args.source_key
                )
            )
            or 0
        )
    payload = {
        "label": args.label or args.source_key,
        "source_key": args.source_key,
        "documents": documents,
        "chunks": chunks,
        "ingestion_runs": runs,
        "missing_full_text": full_text_missing,
        "missing_neutral_citation": neutral_missing,
        "missing_date": date_missing,
        "missing_case_number": case_number_missing,
        "neutral_citation_required": args.source_key == "supreme_court_aws_bulk",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
