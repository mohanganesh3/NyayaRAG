from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ingestion.scripts.open_datasets_common import (
    DATA_ROOT,
    DEFAULT_SPECS,
    INDEX_PATH,
    RAW_ROOT,
    SUMMARY_PATH,
    DatasetSpec,
    ensure_directories,
    file_checksum,
    file_mtime_iso,
    iter_files,
    load_source_config,
    now_iso,
    write_json,
    write_jsonl,
)


def build_index(
    root: Path = RAW_ROOT,
    *,
    output_index: Path = INDEX_PATH,
    output_summary: Path = SUMMARY_PATH,
) -> dict[str, object]:
    ensure_directories()
    config = load_source_config()
    rows: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []

    for spec in DEFAULT_SPECS:
        base = root / spec.local_subdir
        files = iter_files(base)
        summaries.append(_summary_for_spec(spec, base, files))
        rows.extend(_rows_for_spec(spec, base, files))

    write_jsonl(output_index, rows)
    summary = {
        "generated_at": now_iso(),
        "config": config.get("source_id", "open_research_datasets"),
        "raw_root": str(root),
        "data_root": str(DATA_ROOT),
        "summary": summaries,
    }
    write_json(output_summary, summary)
    return {
        "index_path": str(output_index),
        "summary_path": str(output_summary),
        "files_indexed": len(rows),
        "datasets_indexed": len(summaries),
    }


def _summary_for_spec(spec: DatasetSpec, base: Path, files: list[Path]) -> dict[str, object]:
    return {
        "dataset_id": spec.dataset_id,
        "family": spec.family,
        "kind": spec.kind,
        "local_path": str(base),
        "exists": base.exists(),
        "file_count": len(files),
        "byte_count": sum(path.stat().st_size for path in files),
        "manual_only": spec.manual_only,
        "notes": spec.notes,
    }


def _rows_for_spec(spec: DatasetSpec, base: Path, files: list[Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in files:
        stat = path.stat()
        rows.append(
            {
                "dataset_id": spec.dataset_id,
                "family": spec.family,
                "kind": spec.kind,
                "local_path": str(path),
                "relative_path": str(path.relative_to(base)),
                "size": stat.st_size,
                "sha256": file_checksum(path),
                "modified_at": file_mtime_iso(path),
                "manual_only": spec.manual_only,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Index open research dataset artifacts.")
    parser.add_argument("--root", type=Path, default=RAW_ROOT)
    parser.add_argument("--output-index", type=Path, default=INDEX_PATH)
    parser.add_argument("--output-summary", type=Path, default=SUMMARY_PATH)
    args = parser.parse_args(argv)

    report = build_index(
        args.root.resolve(),
        output_index=args.output_index.resolve(),
        output_summary=args.output_summary.resolve(),
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
