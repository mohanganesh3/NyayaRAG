from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import build_engine
from app.models import LegalDocument, LegalDocumentType

_NEUTRAL_CITATION_PATTERN = re.compile(r"\b(\d{4}\s*INSC\s*\d+)\b", re.IGNORECASE)
_REPORTER_CITATION_PATTERN = re.compile(
    r"(\(\d{4}\)\s*\d+\s*SCC\s*(?:\(Cri\)\s*)?\d+|AIR\s+\d{4}\s+SC\s+\d+|\[\d{4}\]\s+\d+\s+S\.C\.R\.\s+\d+)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ExportStats:
    scanned_documents: int = 0
    paragraphs_scanned: int = 0
    citations_extracted: int = 0
    unresolved_total: int = 0
    unresolved_unique_tracked: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "scanned_documents": self.scanned_documents,
            "paragraphs_scanned": self.paragraphs_scanned,
            "citations_extracted": self.citations_extracted,
            "unresolved_total": self.unresolved_total,
            "unresolved_unique_tracked": self.unresolved_unique_tracked,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_unresolved_citations",
        description=(
            "Scan judgment full_text for reporter/neutral citations and export the most frequent citations "
            "that cannot be resolved against in-DB citation fields (citation / neutral_citation / source_document_ref). "
            "This produces a targeted collection backlog."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=f"sqlite+pysqlite:///{REPO_ROOT / data / collection / live_corpus.db}",
        help="SQLAlchemy database URL (sqlite+pysqlite:///...)",
    )
    parser.add_argument(
        "--source-key",
        action="append",
        dest="source_keys",
        default=[],
        help="Restrict scanning to one or more LegalDocument.source_system values (repeatable).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of documents to scan (0 = no limit).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=500,
        help="How many unresolved citations to output (default: 500).",
    )
    parser.add_argument(
        "--max-unique",
        type=int,
        default=200_000,
        help=(
            "Maximum number of unique unresolved citation strings to track in memory. "
            "If exceeded, new unique citations are ignored (existing ones still counted). (default: 200000)"
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output path for JSON (default: print to stdout).",
    )
    return parser


def _normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_neutral(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.replace("INSC", " INSC ")).strip()
    match = _NEUTRAL_CITATION_PATTERN.search(normalized)
    if match is None:
        return normalized
    return re.sub(r"\s+", " ", match.group(1)).upper().strip()


def _paragraphs(text_value: str) -> list[str]:
    chunks = [part.strip() for part in re.split(r"\n\s*\n", text_value) if part.strip()]
    if chunks:
        return chunks
    return [line.strip() for line in text_value.splitlines() if line.strip()]


def _extract_citation_texts(paragraph: str) -> list[str]:
    citations: list[str] = []
    for match in _REPORTER_CITATION_PATTERN.finditer(paragraph):
        citations.append(_normalize_ws(match.group(1)))
    for match in _NEUTRAL_CITATION_PATTERN.finditer(paragraph):
        citations.append(_normalize_neutral(match.group(1)))

    seen: set[str] = set()
    ordered: list[str] = []
    for item in citations:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _build_known_index(session: Session) -> set[str]:
    known: set[str] = set()

    stmt = select(
        LegalDocument.citation,
        LegalDocument.neutral_citation,
        LegalDocument.source_document_ref,
    ).where(
        (LegalDocument.citation.is_not(None))
        | (LegalDocument.neutral_citation.is_not(None))
        | (LegalDocument.source_document_ref.is_not(None))
    )

    for citation, neutral, source_ref in session.execute(stmt):
        if citation:
            known.add(_normalize_ws(str(citation)))
        if neutral:
            known.add(_normalize_neutral(str(neutral)))
        if source_ref:
            known.add(_normalize_ws(str(source_ref)))

    return known


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    source_keys = [str(x) for x in args.source_keys if str(x).strip()]
    limit = max(0, int(args.limit))
    top_n = max(1, int(args.top))
    max_unique = max(1, int(args.max_unique))

    started_at = datetime.now(UTC)
    engine = build_engine(args.database_url)

    stats = ExportStats()
    unresolved = Counter()
    sample_doc_id: dict[str, str] = {}

    with Session(engine) as session:
        known = _build_known_index(session)

        stmt = select(LegalDocument.doc_id, LegalDocument.full_text).where(
            LegalDocument.doc_type == LegalDocumentType.JUDGMENT,
            LegalDocument.full_text.is_not(None),
            LegalDocument.full_text != "",
        )
        if source_keys:
            stmt = stmt.where(LegalDocument.source_system.in_(source_keys))

        for doc_id, full_text in session.execute(stmt):
            if limit and stats.scanned_documents >= limit:
                break
            stats.scanned_documents += 1

            text_value = str(full_text)
            paragraphs = _paragraphs(text_value)
            stats.paragraphs_scanned += len(paragraphs)

            for paragraph in paragraphs:
                citation_texts = _extract_citation_texts(paragraph)
                if not citation_texts:
                    continue

                for citation_text in citation_texts:
                    stats.citations_extracted += 1
                    if citation_text in known:
                        continue

                    # Cap unique keys to prevent unbounded memory growth.
                    if citation_text not in unresolved and len(unresolved) >= max_unique:
                        continue

                    unresolved[citation_text] += 1
                    stats.unresolved_total += 1
                    if citation_text not in sample_doc_id:
                        sample_doc_id[citation_text] = str(doc_id)

    stats.unresolved_unique_tracked = len(unresolved)
    completed_at = datetime.now(UTC)

    top_items = []
    for citation_text, count in unresolved.most_common(top_n):
        top_items.append(
            {
                "citation_text": citation_text,
                "count": int(count),
                "sample_doc_id": sample_doc_id.get(citation_text),
            }
        )

    payload = {
        "database_url": args.database_url,
        "source_keys": source_keys or None,
        "limit": limit or None,
        "top": top_n,
        "max_unique": max_unique,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round((completed_at - started_at).total_seconds(), 2),
        "known_index_size": len(known),
        "stats": stats.to_dict(),
        "unresolved_top": top_items,
    }

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(str(args.out))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
