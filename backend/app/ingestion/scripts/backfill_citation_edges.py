from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.models import LegalDocument, LegalDocumentType


_NEUTRAL_CITATION_PATTERN = re.compile(r"\b(\d{4}\s*INSC\s*\d+)\b", re.IGNORECASE)
_REPORTER_CITATION_PATTERN = re.compile(
    r"(\(\d{4}\)\s*\d+\s*SCC\s*(?:\(Cri\)\s*)?\d+|AIR\s+\d{4}\s+SC\s+\d+|\[\d{4}\]\s+\d+\s+S\.C\.R\.\s+\d+)",
    re.IGNORECASE,
)

_SUPPORTED_TYPES = {
    "follows",
    "distinguishes",
    "overrules",
    "approves",
    "disapproves",
    "doubts",
    "explains",
    "refers_to",
    "affirms",
}

_CLASSIFICATION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("overrules", (" overruled ", " overrule ", " reversed ", " reverses ")),
    ("distinguishes", (" distinguished ", " distinguish ", " distinguished from ")),
    ("disapproves", (" disapproved ", " disapproves ")),
    ("doubts", (" doubted ", " doubts ")),
    ("approves", (" approved ", " approves ")),
    ("affirms", (" affirmed ", " affirms ")),
    ("follows", (" followed ", " follows ", " relied on ", " relies on ", " applied ")),
    ("explains", (" explained ", " explains ", " clarified ", " clarifies ")),
)


@dataclass(slots=True)
class BackfillStats:
    scanned_documents: int = 0
    paragraphs_scanned: int = 0
    citations_extracted: int = 0
    candidates_resolved: int = 0
    edges_attempted: int = 0
    edges_inserted: int = 0
    unresolved_references: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "scanned_documents": self.scanned_documents,
            "paragraphs_scanned": self.paragraphs_scanned,
            "citations_extracted": self.citations_extracted,
            "candidates_resolved": self.candidates_resolved,
            "edges_attempted": self.edges_attempted,
            "edges_inserted": self.edges_inserted,
            "unresolved_references": self.unresolved_references,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backfill_citation_edges",
        description=(
            "Backfill citation_edges for judgments by scanning full_text paragraphs for reporter/neutral citations, "
            "resolving them against in-DB citation/neutral_citation fields, and inserting typed edges. "
            "This is a pilot backfill tool; it is safe to run in --dry-run mode."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=f"sqlite+pysqlite:///{REPO_ROOT / 'data' / 'collection' / 'live_corpus.db'}",
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
        "--commit-every",
        type=int,
        default=500,
        help="Commit after this many scanned documents (default: 500).",
    )
    parser.add_argument("--dry-run", action="store_true")
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


def _classify_edge_type(*, raw_text: str, candidate_type: str | None) -> str:
    candidate_type = (candidate_type or "").strip().lower()
    if candidate_type in _SUPPORTED_TYPES and candidate_type != "refers_to":
        return candidate_type

    normalized = f" {raw_text.lower()} "
    for citation_type, markers in _CLASSIFICATION_RULES:
        if any(marker in normalized for marker in markers):
            return citation_type
    return "refers_to"


def _extract_citation_texts(paragraph: str) -> list[str]:
    citations: list[str] = []
    for match in _REPORTER_CITATION_PATTERN.finditer(paragraph):
        citations.append(_normalize_ws(match.group(1)))
    for match in _NEUTRAL_CITATION_PATTERN.finditer(paragraph):
        citations.append(_normalize_neutral(match.group(1)))
    # Preserve order but ensure uniqueness.
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


def _build_resolution_index(session: Session) -> dict[str, str]:
    """Map citation-like identifiers to doc_id.

    Index keys include:
    - LegalDocument.citation
    - LegalDocument.neutral_citation
    - LegalDocument.source_document_ref

    We intentionally avoid case-name fuzzy matching in this backfill.
    """

    index: dict[str, str] = {}
    stmt = select(
        LegalDocument.doc_id,
        LegalDocument.citation,
        LegalDocument.neutral_citation,
        LegalDocument.source_document_ref,
    ).where(
        (LegalDocument.citation.is_not(None))
        | (LegalDocument.neutral_citation.is_not(None))
        | (LegalDocument.source_document_ref.is_not(None))
    )

    for doc_id, citation, neutral, source_ref in session.execute(stmt):
        if citation:
            index[_normalize_ws(str(citation))] = doc_id
        if neutral:
            index[_normalize_neutral(str(neutral))] = doc_id
        if source_ref:
            index[_normalize_ws(str(source_ref))] = doc_id
    return index


def _insert_edges_sqlite(session: Session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    stmt = text(
        """
        INSERT OR IGNORE INTO citation_edges (id, source_doc_id, target_doc_id, citation_type)
        VALUES (:id, :source_doc_id, :target_doc_id, :citation_type)
        """
    )
    session.execute(stmt, rows)
    # SQLite changes() counts only the last statement; rowcount is unreliable with executemany.
    # We return 0 here and compute inserted edges by diffing counts in the caller when needed.
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    source_keys = [str(x) for x in args.source_keys if str(x).strip()]
    limit = max(0, int(args.limit))
    commit_every = max(1, int(args.commit_every))

    stats = BackfillStats()
    edge_type_counts: dict[str, int] = {}
    started_at = datetime.now(UTC)

    with Session(engine) as session:
        resolution_index = _build_resolution_index(session)

        baseline_edges = int(session.execute(text("SELECT COUNT(*) FROM citation_edges")).scalar() or 0)

        stmt = select(LegalDocument.doc_id, LegalDocument.full_text).where(
            LegalDocument.doc_type == LegalDocumentType.JUDGMENT,
            LegalDocument.full_text.is_not(None),
            LegalDocument.full_text != "",
        )
        if source_keys:
            stmt = stmt.where(LegalDocument.source_system.in_(source_keys))

        rows_to_insert: list[dict[str, Any]] = []
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
                    target_doc_id = resolution_index.get(citation_text)
                    if not target_doc_id or target_doc_id == doc_id:
                        stats.unresolved_references += 1
                        continue

                    citation_type = _classify_edge_type(raw_text=paragraph, candidate_type=None)
                    edge_type_counts[citation_type] = edge_type_counts.get(citation_type, 0) + 1
                    edge_id = str(uuid5(NAMESPACE_URL, f"{doc_id}|{target_doc_id}|{citation_type}"))

                    rows_to_insert.append(
                        {
                            "id": edge_id,
                            "source_doc_id": doc_id,
                            "target_doc_id": target_doc_id,
                            "citation_type": citation_type,
                        }
                    )
                    stats.candidates_resolved += 1
                    stats.edges_attempted += 1

            if len(rows_to_insert) >= 5000:
                if not args.dry_run:
                    _insert_edges_sqlite(session, rows_to_insert)
                rows_to_insert.clear()

            if stats.scanned_documents % commit_every == 0:
                print(
                    (
                        f"[backfill] scanned={stats.scanned_documents} "
                        f"edges_attempted={stats.edges_attempted} "
                        f"resolved={stats.candidates_resolved} "
                        f"unresolved={stats.unresolved_references}"
                    ),
                    file=sys.stderr,
                )
                if args.dry_run:
                    session.rollback()
                else:
                    session.commit()

        # Flush remaining inserts
        if rows_to_insert:
            if not args.dry_run:
                _insert_edges_sqlite(session, rows_to_insert)
            rows_to_insert.clear()

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

        final_edges = int(session.execute(text("SELECT COUNT(*) FROM citation_edges")).scalar() or 0)

    completed_at = datetime.now(UTC)

    payload = {
        "database_url": args.database_url,
        "source_keys": source_keys or None,
        "dry_run": bool(args.dry_run),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round((completed_at - started_at).total_seconds(), 2),
        "resolution_index_size": len(resolution_index),
        "baseline_edges": baseline_edges,
        "final_edges": final_edges,
        "edges_inserted": max(final_edges - baseline_edges, 0),
        "stats": stats.to_dict(),
        "edge_type_counts": dict(sorted(edge_type_counts.items())),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
