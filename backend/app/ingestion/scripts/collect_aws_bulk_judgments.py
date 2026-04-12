from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path

import app.models as model_registry
from app.core.config import BACKEND_ROOT
from app.db.base import Base
from app.db.session import build_engine
from app.ingestion.aws_bulk import (
    AwsBulkCollector,
    select_priority_high_courts,
    summarize_high_court_catalog,
)
from app.ingestion.collector_utils import ensure_collection_control_schema
from sqlalchemy.orm import Session

_ = model_registry


def _default_database_url() -> str:
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "live_corpus.db"
    return f"sqlite+pysqlite:///{db_path}"


def _default_raw_root() -> Path:
    return BACKEND_ROOT.parent / "data" / "raw"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_aws_bulk_judgments",
        description="Discover, download, and ingest the AWS bulk Indian court datasets.",
    )
    parser.add_argument("--database-url", default=_default_database_url())
    parser.add_argument("--raw-root", type=Path, default=_default_raw_root())
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--commit-every",
        type=int,
        default=25,
        help="Commit every N processed documents (smaller = more visible progress, more overhead).",
    )
    parser.add_argument(
        "--commit-interval-seconds",
        type=float,
        default=30.0,
        help="Force a commit at least every N seconds while progress is being made.",
    )
    parser.add_argument(
        "--skip-chunks",
        action="store_true",
        help="Persist documents and metadata without building chunks during bulk backfill.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify", help="Show live Supreme Court and High Court discovery.")
    verify.set_defaults(handler=_handle_verify)

    discover_hc = subparsers.add_parser("discover-high-courts", help="Emit live High Court code mapping.")
    discover_hc.add_argument("--json", action="store_true")
    discover_hc.set_defaults(handler=_handle_discover_high_courts)

    sc = subparsers.add_parser("collect-supreme-court", help="Collect Supreme Court AWS bulk data.")
    sc.add_argument("--limit", type=int, default=None)
    sc.add_argument("--years", nargs="*", type=int)
    sc.add_argument("--include-regional", action="store_true")
    sc.set_defaults(handler=_handle_collect_supreme_court)

    hc = subparsers.add_parser("collect-high-courts", help="Collect High Court AWS bulk data.")
    hc.add_argument("--limit", type=int, default=None)
    hc.add_argument("--years", nargs="*", type=int)
    hc.add_argument("--court", dest="courts", action="append")
    hc.add_argument("--court-code", dest="court_codes", action="append")
    hc.add_argument("--priority1", action="store_true")
    hc.set_defaults(handler=_handle_collect_high_courts)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return int(args.handler(args))


def _collector(args: argparse.Namespace, session: Session) -> AwsBulkCollector:
    Base.metadata.create_all(session.get_bind())
    ensure_collection_control_schema(session)
    return AwsBulkCollector(
        session,
        database_label="collect_aws_bulk_judgments",
        raw_root=args.raw_root.resolve(),
        commit_every=int(args.commit_every),
        commit_interval_seconds=float(args.commit_interval_seconds),
        build_chunks=not bool(args.skip_chunks),
    )


def _handle_verify(args: argparse.Namespace) -> int:
    engine = build_engine(args.database_url)
    with Session(engine) as session:
        collector = _collector(args, session)
        sc_archives = collector.discover_supreme_court_archives()
        hc_catalog = collector.discover_high_court_catalog()
        payload = {
            "supreme_court": {
                "archive_count": len(sc_archives),
                "latest_year": sc_archives[0].year if sc_archives else None,
                "latest_archive_key": sc_archives[0].archive_key if sc_archives else None,
            },
            "high_courts": {
                "court_count": len(hc_catalog),
                "priority_1": summarize_high_court_catalog(select_priority_high_courts(hc_catalog)),
            },
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _handle_discover_high_courts(args: argparse.Namespace) -> int:
    engine = build_engine(args.database_url)
    with Session(engine) as session:
        collector = _collector(args, session)
        catalog = collector.discover_high_court_catalog()
        if args.json:
            print(json.dumps(summarize_high_court_catalog(catalog), indent=2, sort_keys=True))
            return 0
        for entry in catalog:
            print(f"{entry.court_code}\t{entry.sample_bench}\t{entry.court_name}")
    return 0


def _handle_collect_supreme_court(args: argparse.Namespace) -> int:
    engine = build_engine(args.database_url)
    with Session(engine) as session:
        collector = _collector(args, session)
        descriptors = collector.discover_supreme_court_archives(
            include_regional=bool(args.include_regional),
            years=args.years,
        )
        stats = collector.collect_archives(
            descriptors,
            limit_documents=args.limit,
            source_snapshot_url="https://registry.opendata.aws/indian-supreme-court-judgments/",
        )
    print(json.dumps(asdict(stats), indent=2, sort_keys=True))
    return 0


def _handle_collect_high_courts(args: argparse.Namespace) -> int:
    engine = build_engine(args.database_url)
    with Session(engine) as session:
        collector = _collector(args, session)
        courts = list(args.courts or [])
        court_codes = list(args.court_codes or [])
        if args.priority1:
            courts.extend(
                entry.court_name
                for entry in select_priority_high_courts(collector.discover_high_court_catalog())
            )
        descriptors = collector.discover_high_court_archives(
            years=args.years,
            court_names=courts or None,
            court_codes=court_codes or None,
        )
        stats = collector.collect_archives(
            descriptors,
            limit_documents=args.limit,
            source_snapshot_url="https://registry.opendata.aws/indian-high-court-judgments/",
        )
    print(json.dumps(asdict(stats), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
