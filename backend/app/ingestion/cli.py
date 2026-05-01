from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import app.models as model_registry
from app.core.config import BACKEND_ROOT
from app.db.base import Base
from app.db.session import build_engine
from app.ingestion.collection_program import CollectionProgram, CollectionRunResult
from app.ingestion.orchestrator import IngestionOrchestrator
from app.models import DocumentChunk, IngestionRun, LegalDocument


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return int(handler(args))


def console_main() -> None:
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nyayarag-collect",
        description="Run NyayaRAG collection manifests against the canonical ingestion stack.",
    )
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser(
        "list-sources",
        help="List collection registry entries and automation status.",
    )
    list_parser.add_argument("--registry-dir", type=Path, default=_default_registry_dir())
    list_parser.set_defaults(handler=_handle_list_sources)

    run_manifest_parser = subparsers.add_parser(
        "run-manifest",
        help="Run a single collection manifest.",
    )
    _add_common_run_args(run_manifest_parser)
    run_manifest_parser.add_argument("--manifest", type=Path, required=True)
    run_manifest_parser.set_defaults(handler=_handle_run_manifest)

    run_all_parser = subparsers.add_parser(
        "run-all-manifests",
        help="Run every TOML manifest in a directory in lexical order.",
    )
    _add_common_run_args(run_all_parser)
    run_all_parser.add_argument("--manifest-dir", type=Path, required=True)
    run_all_parser.set_defaults(handler=_handle_run_all_manifests)

    run_parser = subparsers.add_parser(
        "run",
        help="Run live collection for a single registered source.",
    )
    _add_common_run_args(run_parser)
    run_parser.add_argument("--source", required=True)
    run_parser.add_argument("--limit", type=int, default=10)
    run_parser.add_argument("--delay-seconds", type=float, default=2.0)
    run_parser.set_defaults(handler=_handle_run_source)

    stats_parser = subparsers.add_parser(
        "stats",
        help="Show collected document, chunk, and ingestion-run counts.",
    )
    stats_parser.add_argument("--database-url", default=_default_collection_database_url())
    stats_parser.add_argument("--source", required=False)
    stats_parser.set_defaults(handler=_handle_stats)

    return parser


def _add_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry-dir", type=Path, default=_default_registry_dir())
    parser.add_argument("--database-url", default=_default_collection_database_url())
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create database tables before running manifests.",
    )
    parser.add_argument(
        "--document-only",
        action="store_true",
        help=(
            "Persist only canonical LegalDocument rows (skip chunking, embeddings, graph, and appeal projections). "
            "Recommended for high-volume collection runs; projections can be built later."
        ),
    )


def _build_program(args: argparse.Namespace) -> CollectionProgram:
    orchestrator = IngestionOrchestrator(document_only=bool(getattr(args, "document_only", False)))
    return CollectionProgram(registry_dir=args.registry_dir.resolve(), orchestrator=orchestrator)


def _handle_list_sources(args: argparse.Namespace) -> int:
    program = CollectionProgram(registry_dir=args.registry_dir.resolve())
    for entry in program.registry.values():
        print(
            "\t".join(
                [
                    entry.source_id,
                    entry.automation_status.value,
                    entry.source_key,
                    entry.stage_hint or "",
                    entry.display_name,
                ]
            )
        )
    return 0


def _handle_run_manifest(args: argparse.Namespace) -> int:
    engine = build_engine(args.database_url)
    _maybe_create_schema(engine, args.create_schema)

    program = _build_program(args)
    with Session(engine) as session:
        result = program.run_manifest(session, args.manifest.resolve())

    print(json.dumps(_serialize_run_result(result), indent=2, sort_keys=True))
    return 0


def _handle_run_all_manifests(args: argparse.Namespace) -> int:
    manifest_paths = sorted(args.manifest_dir.resolve().glob("*.toml"))
    if not manifest_paths:
        print(
            json.dumps(
                {
                    "manifest_dir": str(args.manifest_dir.resolve()),
                    "results": [],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    engine = build_engine(args.database_url)
    _maybe_create_schema(engine, args.create_schema)

    program = _build_program(args)
    results: list[dict[str, object]] = []
    with Session(engine) as session:
        for manifest_path in manifest_paths:
            result = program.run_manifest(session, manifest_path)
            results.append(_serialize_run_result(result))

    print(
        json.dumps(
            {
                "manifest_dir": str(args.manifest_dir.resolve()),
                "results": results,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _handle_run_source(args: argparse.Namespace) -> int:
    engine = build_engine(args.database_url)
    _maybe_create_schema(engine, args.create_schema)

    program = _build_program(args)
    with Session(engine) as session:
        result = program.run_source(
            session,
            source_id=args.source,
            limit=args.limit,
            delay_seconds=args.delay_seconds,
        )

    print(json.dumps(_serialize_run_result(result), indent=2, sort_keys=True))
    return 0


def _handle_stats(args: argparse.Namespace) -> int:
    engine = build_engine(args.database_url)
    with Session(engine) as session:
        source_filter = _resolve_source_filter(args.source)
        document_stmt = select(func.count()).select_from(LegalDocument)
        chunk_stmt = select(func.count()).select_from(DocumentChunk)
        run_stmt = select(func.count()).select_from(IngestionRun)

        if source_filter:
            document_stmt = document_stmt.where(LegalDocument.source_system == source_filter)
            chunk_stmt = chunk_stmt.join(
                LegalDocument,
                DocumentChunk.doc_id == LegalDocument.doc_id,
            ).where(LegalDocument.source_system == source_filter)
            run_stmt = run_stmt.where(IngestionRun.source_key == source_filter)

        payload = {
            "source": source_filter,
            "documents": int(session.scalar(document_stmt) or 0),
            "chunks": int(session.scalar(chunk_stmt) or 0),
            "ingestion_runs": int(session.scalar(run_stmt) or 0),
        }

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _serialize_run_result(result: CollectionRunResult) -> dict[str, object]:
    return {
        "manifest_name": result.manifest_name,
        "items": [
            {
                "source_id": item.source_id,
                "status": item.status,
                "reason": item.reason,
                "doc_id": item.doc_id,
                "ingestion_run_id": item.ingestion_run_id,
            }
            for item in result.items
        ],
    }


def _ensure_models_registered() -> None:
    _ = model_registry


def _default_registry_dir() -> Path:
    return BACKEND_ROOT.parent / "data" / "collection" / "sources"


def _default_collection_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "live_corpus.db"
    return f"sqlite+pysqlite:///{db_path}"


def _maybe_create_schema(engine: Engine, requested: bool) -> None:
    if not requested and not str(engine.url).startswith("sqlite"):
        return
    _ensure_models_registered()
    Base.metadata.create_all(engine)


def _resolve_source_filter(source: str | None) -> str | None:
    if source is None:
        return None
    registry_dir = _default_registry_dir()
    if registry_dir.exists():
        entry = CollectionProgram(registry_dir=registry_dir).registry.get(source)
        if entry is not None:
            return entry.source_key
    return source


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
