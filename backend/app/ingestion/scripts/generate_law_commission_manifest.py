from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class IndexRecord:
    report_number: str | None
    report_title: str | None
    submission_date: str | None
    pdf_url: str
    text_path: str | None
    extraction_status: str


DEFAULT_INDEX = Path(__file__).resolve().parents[4] / "data" / "raw" / "law_commission" / "law_commission_index.jsonl"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[4] / "data" / "collection" / "manifests" / "law_commission_reports.toml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_law_commission_manifest",
        description="Generate a NyayaRAG collection manifest from law_commission_index.jsonl.",
    )
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--name", default="law_commission_reports")
    parser.add_argument("--description", default="Law Commission of India reports (PDF-extracted text).")
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Optional limit on number of jobs emitted.",
    )
    parser.add_argument(
        "--require-text",
        action="store_true",
        help="Only emit jobs that have an extracted text file present.",
    )
    parser.add_argument(
        "--include-status",
        action="append",
        default=["downloaded"],
        help="Include only index rows with these extraction_status values (repeatable). Default: downloaded.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    records = load_index(args.index)
    statuses = {str(value) for value in (args.include_status or [])}

    jobs: list[dict[str, Any]] = []
    for record in records:
        if record.extraction_status not in statuses:
            continue
        if args.require_text and not record.text_path:
            continue
        text_path = Path(record.text_path) if record.text_path else None
        if args.require_text and (text_path is None or not text_path.exists()):
            continue

        job: dict[str, Any] = {
            "source_id": "law_commission_reports",
            "source_url": record.pdf_url,
            "external_id": _build_external_id(record),
            "parser_version": "law-commission-report-text-v1",
        }
        if text_path is not None:
            job["inline_payload_path"] = _relative_to(text_path, base_dir=args.output.parent)

        metadata: dict[str, Any] = {}
        if record.report_number:
            metadata["report_number"] = record.report_number
        if record.report_title:
            metadata["report_title"] = record.report_title
        if record.submission_date:
            metadata["submission_date"] = record.submission_date
        if metadata:
            job["metadata"] = metadata

        jobs.append(job)
        if args.max_jobs is not None and len(jobs) >= int(args.max_jobs):
            break

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_manifest(name=args.name, description=args.description, jobs=jobs) + "\n", encoding="utf-8")
    return 0


def load_index(path: Path) -> list[IndexRecord]:
    records: list[IndexRecord] = []
    if not path.exists():
        raise SystemExit(f"Index not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            records.append(
                IndexRecord(
                    report_number=_optional_str(raw.get("report_number")),
                    report_title=_optional_str(raw.get("report_title")),
                    submission_date=_optional_str(raw.get("submission_date")),
                    pdf_url=str(raw.get("pdf_url")),
                    text_path=_optional_str(raw.get("text_path")),
                    extraction_status=str(raw.get("extraction_status") or "pending"),
                )
            )
    return records


def render_manifest(*, name: str, description: str | None, jobs: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append(f"name = {_toml_string(name)}")
    if description is not None:
        lines.append(f"description = {_toml_string(description)}")
    lines.append("")

    for job in jobs:
        lines.append("[[jobs]]")
        for key in ("source_id", "source_url", "external_id", "parser_version", "inline_payload_path"):
            if key in job and job[key] is not None:
                lines.append(f"{key} = {_toml_string(str(job[key]))}")
        if "enabled" in job:
            lines.append(f"enabled = {str(bool(job['enabled'])).lower()}")

        metadata = job.get("metadata")
        if isinstance(metadata, dict) and metadata:
            lines.append("[jobs.metadata]")
            for meta_key, meta_value in metadata.items():
                lines.append(f"{meta_key} = {_toml_string(str(meta_value))}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _toml_string(value: str) -> str:
    # JSON string escaping is compatible with TOML basic strings for our usage.
    return json.dumps(value, ensure_ascii=False)


def _optional_str(value: object | None) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _build_external_id(record: IndexRecord) -> str | None:
    if record.report_number:
        suffix = record.report_number
        if record.report_title:
            suffix = f"{suffix}-{_slug(record.report_title)}"
        return f"lc-report-{suffix}"[:180]
    return None


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")[:60] or "report"


def _relative_to(path: Path, *, base_dir: Path) -> str:
    return os.path.relpath(path.resolve(), start=base_dir.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
