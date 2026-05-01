from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import sleep
from typing import Any

from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.models as _model_registry  # noqa: E402, F401
from app.db.base import Base  # noqa: E402
from app.db.session import build_engine  # noqa: E402
from app.ingestion.adapters.indiacode import IndiaCodeActAdapter  # noqa: E402
from app.ingestion.contracts import IngestionJobContext  # noqa: E402
from app.ingestion.orchestrator import IngestionOrchestrator  # noqa: E402
from app.ingestion.pipeline import IngestionPipelineRunner  # noqa: E402

DEFAULT_HANDLES = Path("data/collection/india_code_act_handles.json")
DEFAULT_DATABASE_URL = "sqlite+pysqlite:///data/collection/live_corpus.db"
DEFAULT_STAGING_DIR = Path("data/collection/staging")
DEFAULT_RAW_ROOT = Path("data/raw/india_code")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a slice of India Code acts.")
    parser.add_argument("--agent-id", required=True, type=int)
    parser.add_argument("--start-index", required=True, type=int)
    parser.add_argument("--end-index", required=True, type=int)
    parser.add_argument("--handles", type=Path, default=DEFAULT_HANDLES)
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING_DIR)
    parser.add_argument("--act-delay-seconds", type=float, default=2.0)
    parser.add_argument("--section-delay-seconds", type=float, default=1.0)
    args = parser.parse_args()

    handles = json.loads(args.handles.read_text(encoding="utf-8"))
    slice_entries = handles[args.start_index : args.end_index + 1]

    args.staging_dir.mkdir(parents=True, exist_ok=True)
    engine = build_engine(args.database_url)
    Base.metadata.create_all(engine)

    adapter = IndiaCodeActAdapter()
    runner = IngestionPipelineRunner()
    orchestrator = IngestionOrchestrator(runner=runner)

    report: dict[str, Any] = {
        "agent_id": args.agent_id,
        "slice_start": args.start_index,
        "slice_end": args.end_index,
        "total_attempted": 0,
        "total_succeeded": 0,
        "total_failed": 0,
        "total_sections_collected": 0,
        "failed_handles": [],
        "started_at": datetime.now(UTC).isoformat(),
    }

    with Session(engine) as session:
        for offset, entry in enumerate(slice_entries):
            report["total_attempted"] += 1
            if offset > 0 and args.act_delay_seconds > 0:
                sleep(args.act_delay_seconds)

            handle = str(entry["handle"])
            context = IngestionJobContext(
                source_key="india_code",
                source_url=str(entry["detail_url"]),
                parser_version="indiacode-text-v1",
                external_id=handle,
                metadata={
                    "practice_areas": ["civil", "corporate", "statutory"],
                    "request_delay_seconds": float(args.section_delay_seconds),
                },
            )

            try:
                execution = runner.run(adapter, context)
                staging_path = args.staging_dir / f"act_{handle}.json"
                staging_path.write_text(
                    json.dumps(
                        _build_staging_payload(handle, entry, execution),
                        indent=2,
                        ensure_ascii=True,
                    ),
                    encoding="utf-8",
                )

                persisted = orchestrator.persister.persist(session, execution, context)
                orchestrator.embedding_pipeline.project(
                    session,
                    execution=execution,
                    doc_id=persisted.doc_id,
                )
                orchestrator.graph_projector.project(session, execution, persisted.doc_id)
                orchestrator.appeal_chain_builder.persist(session, execution, persisted.doc_id)
                session.commit()

                live_bundle = json.loads(execution.fetched.raw_content)
                report["total_succeeded"] += 1
                report["total_sections_collected"] += len(live_bundle.get("sections", []))
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                report["total_failed"] += 1
                report["failed_handles"].append(
                    {
                        "handle": handle,
                        "title": entry.get("title"),
                        "url": entry.get("detail_url"),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    report["completed_at"] = datetime.now(UTC).isoformat()
    report_path = args.staging_dir / f"agent_{args.agent_id}_run_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    print(f"COLLECTION AGENT {args.agent_id} COMPLETE")
    print(f"Acts attempted: {report['total_attempted']}")
    print(f"Acts succeeded: {report['total_succeeded']}")
    print(f"Acts failed: {report['total_failed']}")
    print(f"Total sections collected: {report['total_sections_collected']}")
    print(f"Failed handles written to: {report_path}")
    return 0


def _build_staging_payload(
    handle: str,
    entry: dict[str, Any],
    execution: Any,
) -> dict[str, Any]:
    live_bundle = json.loads(execution.fetched.raw_content)
    metadata_rows = live_bundle.get("metadata_rows", {})
    raw_root = DEFAULT_RAW_ROOT / handle
    act_file = raw_root / "act.html"
    sections: list[dict[str, Any]] = []
    for section in live_bundle.get("sections", []):
        section_id = str(section.get("section_id", ""))
        section_file = raw_root / "sections" / f"{section_id}.json"
        sections.append(
            {
                "section_number": section.get("section_number"),
                "heading": section.get("heading"),
                "text": _clean_text(section.get("content_html")),
                "subsections": [],
                "raw_artifact_path": str(section_file),
                "checksum": _checksum_for_file(section_file),
                "section_id": section_id,
            }
        )

    return {
        "handle": handle,
        "title": metadata_rows.get("Short Title") or entry.get("title"),
        "act_number": metadata_rows.get("Act Number"),
        "year": _coerce_int(metadata_rows.get("Act Year")) or _coerce_int(entry.get("year")),
        "ministry": metadata_rows.get("Ministry"),
        "enactment_date": metadata_rows.get("Enactment Date"),
        "commencement_date": metadata_rows.get("Enforcement Date"),
        "is_repealed": False,
        "actid": metadata_rows.get("Act ID") or live_bundle.get("act_id"),
        "sections": sections,
        "source_url": entry.get("detail_url"),
        "fetch_timestamp": execution.fetched.fetched_at.isoformat(),
        "checksum": _checksum_for_file(act_file),
        "raw_artifact_path": str(act_file),
    }


def _checksum_for_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return sha256(path.read_bytes()).hexdigest()


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text.isdigit():
        return None
    return int(text)


def _clean_text(content_html: Any) -> str:
    if content_html is None:
        return ""
    text = str(content_html)
    text = text.replace("</br>", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    import re

    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split()).strip()


if __name__ == "__main__":
    raise SystemExit(main())
