from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote

import app.models as model_registry
import requests
from app.core.config import BACKEND_ROOT
from app.db.base import Base
from app.db.session import build_engine
from app.ingestion.adapters import PdfLegalDocumentAdapter
from app.ingestion.contracts import IngestionJobContext
from app.ingestion.orchestrator import IngestionOrchestrator
from sqlalchemy.orm import Session

_ = model_registry

CBIC_WHATS_NEW_URL = "https://www.cbic.gov.in/api/cbic-content-msts/fetchWhatsNewData"
CBIC_PDF_PREFIX = "https://www.cbic.gov.in/content/pdf/"


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "cbic.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_cbic_whats_new",
        description=(
            "Collect CBIC PDFs from the official whats-new JSON endpoint and ingest them "
            "into the staging DB."
        ),
    )
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--allow-underfilled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true, do not exit non-zero when fewer than --limit PDFs are ingested.",
    )
    parser.add_argument("--parser-version", default="cbic-whats-new-v1")
    parser.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--content-type-start", type=int, default=1)
    parser.add_argument("--content-type-end", type=int, default=200)
    parser.add_argument(
        "--document-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="If true, skip chunk/embedding/graph projections during ingestion.",
    )
    parser.add_argument("--log-every", type=int, default=10)
    return parser


def _headers(*, referer: str = "https://www.cbic.gov.in/") -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    }


def _pdf_json_url(file_path: str) -> str:
    normalized = file_path.strip().lstrip("/")
    return CBIC_PDF_PREFIX + quote(normalized, safe="/")


def _row_date_text(row: dict[str, object]) -> str | None:
    for key in ("publishDt", "contentDt", "refDt1", "createdDt", "updatedDt"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _title_for_doc(row: dict[str, object], doc: dict[str, object], file_path: str) -> str:
    pieces: list[str] = []
    for key in ("docTitleEn", "docTitleHi"):
        value = doc.get(key)
        if isinstance(value, str):
            cleaned = " ".join(value.split()).strip()
            if cleaned and cleaned not in pieces:
                pieces.append(cleaned)
    for key in ("titleEn", "titleHi"):
        value = row.get(key)
        if isinstance(value, str):
            cleaned = " ".join(value.split()).strip()
            if cleaned and cleaned not in pieces:
                pieces.append(cleaned)
    if pieces:
        return " | ".join(pieces[:2])
    return Path(file_path).name or "CBIC PDF"


def _stable_external_id(content_type_id: int, row_id: object, doc_id: object, file_path: str) -> str:
    tail = Path(file_path).name or sha256(file_path.encode("utf-8")).hexdigest()[:16]
    return f"cbic-{content_type_id}-{row_id}-{doc_id}-{tail}"


def _extract_pdf_text(
    http: requests.Session,
    adapter: PdfLegalDocumentAdapter,
    *,
    file_path: str,
    timeout_seconds: float,
    ssl_verify: bool,
) -> str:
    response = http.get(
        _pdf_json_url(file_path),
        headers=_headers(referer="https://www.cbic.gov.in/"),
        timeout=timeout_seconds,
        verify=ssl_verify,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("CBIC PDF endpoint returned a non-dict payload")
    encoded = payload.get("data")
    if not isinstance(encoded, str) or not encoded.strip():
        raise RuntimeError("CBIC PDF endpoint returned no base64 payload")
    pdf_bytes = base64.b64decode(encoded)
    return adapter._extract_pdf_text(pdf_bytes)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    target = max(0, int(args.limit))
    if target == 0:
        print("--limit=0 so nothing to ingest.")
        return 0

    content_type_start = int(args.content_type_start)
    content_type_end = int(args.content_type_end)
    if content_type_start > content_type_end:
        content_type_start, content_type_end = content_type_end, content_type_start

    page_size = max(1, min(500, int(args.page_size)))
    adapter = PdfLegalDocumentAdapter()
    orchestrator = IngestionOrchestrator(document_only=bool(args.document_only))
    http = requests.Session()

    successes = 0
    attempted = 0
    discovered = 0
    seen_paths: set[str] = set()

    with Session(engine) as db_session:
        for content_type_id in range(content_type_start, content_type_end + 1):
            if successes >= target:
                break

            page = 0
            while successes < target:
                try:
                    response = http.get(
                        CBIC_WHATS_NEW_URL,
                        params={
                            "page": page,
                            "size": page_size,
                            "content_type_id": content_type_id,
                        },
                        headers=_headers(),
                        timeout=float(args.timeout_seconds),
                        verify=bool(args.ssl_verify),
                    )
                    response.raise_for_status()
                    rows = response.json()
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[api-skip] content_type_id={content_type_id} page={page} "
                        f"err={type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    break

                if not isinstance(rows, list) or not rows:
                    break

                for row in rows:
                    if successes >= target:
                        break
                    if not isinstance(row, dict):
                        continue

                    docs = row.get("cbicDocMsts")
                    if not isinstance(docs, list):
                        continue

                    for doc in docs:
                        if successes >= target:
                            break
                        if not isinstance(doc, dict):
                            continue

                        for path_key in ("filePathEn", "filePathHi"):
                            raw_path = doc.get(path_key)
                            if not isinstance(raw_path, str):
                                continue
                            file_path = raw_path.strip().lstrip("/")
                            if not file_path or not file_path.lower().endswith(".pdf"):
                                continue
                            if file_path in seen_paths:
                                continue

                            seen_paths.add(file_path)
                            discovered += 1
                            attempted += 1

                            try:
                                extracted_text = _extract_pdf_text(
                                    http,
                                    adapter,
                                    file_path=file_path,
                                    timeout_seconds=float(args.timeout_seconds),
                                    ssl_verify=bool(args.ssl_verify),
                                )
                            except Exception as exc:  # noqa: BLE001
                                print(
                                    f"[skip] file_path={file_path} err={type(exc).__name__}: {exc}",
                                    flush=True,
                                )
                                continue

                            source_url = _pdf_json_url(file_path)
                            context = IngestionJobContext(
                                source_key="cbic",
                                source_url=source_url,
                                parser_version=str(args.parser_version),
                                external_id=_stable_external_id(
                                    content_type_id,
                                    row.get("id"),
                                    doc.get("id"),
                                    file_path,
                                ),
                                inline_payload=extracted_text,
                                metadata={
                                    "court_name": "Central Board of Indirect Taxes and Customs",
                                    "doc_type": "notification",
                                    "practice_areas": ["tax"],
                                    "jurisdiction_binding": ["All India"],
                                    "jurisdiction_persuasive": ["All India"],
                                    "title": _title_for_doc(row, doc, file_path),
                                    "date_text": _row_date_text(row),
                                    "ssl_verify": bool(args.ssl_verify),
                                    "seed_url": CBIC_WHATS_NEW_URL,
                                    "content_type_id": content_type_id,
                                    "cbic_row_id": row.get("id"),
                                    "cbic_doc_id": doc.get("id"),
                                    "file_path": file_path,
                                    "collected_at": datetime.now(UTC).isoformat(),
                                },
                            )
                            try:
                                persisted = orchestrator.ingest(db_session, adapter, context)
                            except Exception as exc:  # noqa: BLE001
                                db_session.rollback()
                                print(f"[skip] url={source_url} err={type(exc).__name__}: {exc}", flush=True)
                                continue

                            successes += 1
                            if int(args.log_every) > 0 and successes % int(args.log_every) == 0:
                                print(
                                    f"[{successes}/{target}] ingested doc_id={persisted.doc_id} "
                                    f"content_type_id={content_type_id} file_path={file_path}",
                                    flush=True,
                                )

                page += 1

    if successes < target:
        msg = (
            f"Only ingested {successes}/{target} CBIC PDFs "
            f"(attempted {attempted}, discovered {discovered})."
        )
        if bool(args.allow_underfilled):
            print(msg, flush=True)
            return 0
        raise SystemExit(msg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
