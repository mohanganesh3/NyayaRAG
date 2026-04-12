from __future__ import annotations

import argparse
from typing import Iterable

import app.models as model_registry
from app.core.config import BACKEND_ROOT
from app.db.base import Base
from app.db.session import build_engine
from app.ingestion.adapters import PdfLegalDocumentAdapter
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.orchestrator import IngestionOrchestrator
from sqlalchemy.orm import Session

_ = model_registry

OFFICIAL_PAGE_URL = "https://www.legislative.gov.in/constitution-of-india"
OFFICIAL_PDF_CANDIDATES = (
    "https://www.legislative.gov.in/static/uploads/2025/07/86f73abe946eaefe5da5707583fa788a.pdf",
)


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "constitution_of_india.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="collect_constitution_of_india",
        description=(
            "Ingest the official Constitution of India PDF from the Legislative Department "
            "into the staging DB."
        ),
    )
    p.add_argument("--database-url", default=_default_database_url())
    p.add_argument(
        "--source-url",
        action="append",
        default=[],
        help=(
            "Repeatable official PDF URL candidate. If omitted, the collector uses the "
            "checked-in Legislative Department PDF candidate list."
        ),
    )
    p.add_argument("--page-url", default=OFFICIAL_PAGE_URL)
    p.add_argument("--parser-version", default="constitution-official-pdf-v1")
    p.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true (default), skip chunk/embedding/graph projections during ingestion.",
    )
    p.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=True)
    return p


def _candidate_urls(args: argparse.Namespace) -> list[str]:
    urls = [str(value).strip() for value in (args.source_url or []) if str(value).strip()]
    if urls:
        return urls
    return list(OFFICIAL_PDF_CANDIDATES)


def _pick_live_pdf_url(urls: Iterable[str]) -> str:
    adapter = PdfLegalDocumentAdapter()
    last_error: str | None = None
    for url in urls:
        try:
            payload = adapter.fetch(
                IngestionJobContext(
                    source_key="constitution_of_india",
                    source_url=url,
                    parser_version="constitution-probe-v1",
                    external_id="constitution-of-india-probe",
                    metadata={"ssl_verify": True},
                )
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        if payload.raw_content and len(payload.raw_content.strip()) > 10_000:
            return url
        last_error = "fetched content was unexpectedly short"

    raise RuntimeError(
        "Could not resolve a live official Constitution PDF URL"
        + (f" ({last_error})" if last_error else "")
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    pdf_url = _pick_live_pdf_url(_candidate_urls(args))

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))

    context = IngestionJobContext(
        source_key="constitution_of_india",
        source_url=pdf_url,
        parser_version=str(args.parser_version),
        external_id="constitution-of-india-official",
        metadata={
            "court_name": "Republic of India",
            "doc_type": "constitution",
            "practice_areas": ["constitutional"],
            "jurisdiction_binding": ["All India"],
            "jurisdiction_persuasive": [],
            "title": "Constitution of India",
            "citation": "Constitution of India",
            "date_text": "1950-01-26",
            "ssl_verify": bool(args.ssl_verify),
            "http_headers": {"Referer": str(args.page_url)},
            "source_page_url": str(args.page_url),
        },
    )

    with Session(engine) as session:
        persisted = orchestrator.ingest(session, adapter, context)
        session.commit()

    print(f"pdf_url={pdf_url}")
    print(f"doc_id={persisted.doc_id}")
    print("status=ingested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
