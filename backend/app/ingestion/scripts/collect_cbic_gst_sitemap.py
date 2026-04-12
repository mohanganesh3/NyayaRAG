from __future__ import annotations

import argparse

from app.core.config import BACKEND_ROOT
from app.ingestion.scripts.collect_pdf_seed import main as collect_pdf_seed_main


DEFAULT_SEED_URL = "https://cbic-gst.gov.in/sitemap.html"


def _default_database_url() -> str:
    # NOTE: The collection is commonly referred to as CBIC.
    # Use a stable, generic DB name so audits/targets do not drift.
    db_path = BACKEND_ROOT.parent / "data" / "collection" / "staging" / "cbic.db"
    return f"sqlite+pysqlite:///{db_path}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collect_cbic_gst_sitemap",
        description=(
            "Collect CBIC-GST PDFs by seeding from the public sitemap.html and ingesting PDFs into a staging DB. "
            "This is a pragmatic fallback when the taxinformation.cbic.gov.in API download endpoints are unstable."
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
    parser.add_argument("--parser-version", default="cbic-gst-sitemap-v1")
    parser.add_argument(
        "--doc-type",
        default="circular",
        help="circular|notification|instruction (instruction maps to circular)",
    )
    parser.add_argument("--ssl-verify", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--crawl-depth",
        type=int,
        default=0,
        help="Usually 0 because sitemap.html already contains direct PDF links.",
    )
    parser.add_argument("--max-pages", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # Delegate to the generic collector so we keep behavior consistent.
    forwarded: list[str] = [
        "--database-url",
        str(args.database_url),
        "--source-key",
        # Use the canonical key "cbic" for provenance/audit, even though the seed URL is cbic-gst.gov.in.
        "cbic",
        "--parser-version",
        str(args.parser_version),
        "--seed-url",
        DEFAULT_SEED_URL,
        "--limit",
        str(int(args.limit)),
        "--doc-type",
        str(args.doc_type),
        "--court-name",
        "CBIC (cbic-gst.gov.in)",
        "--practice-area",
        "tax",
        "--jurisdiction-binding",
        "All India",
        "--crawl-depth",
        str(int(args.crawl_depth)),
        "--max-pages",
        str(int(args.max_pages)),
    ]

    if bool(args.allow_underfilled):
        forwarded.append("--allow-underfilled")
    else:
        forwarded.append("--no-allow-underfilled")

    if bool(args.ssl_verify):
        forwarded.append("--ssl-verify")
    else:
        forwarded.append("--no-ssl-verify")

    return int(collect_pdf_seed_main(forwarded))


if __name__ == "__main__":
    raise SystemExit(main())
