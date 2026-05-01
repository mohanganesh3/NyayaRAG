from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from app.ingestion.collection_audits import (
    AuditArtifact,
    generate_court_grade_audit,
    generate_exact_target_audit,
    generate_metadata_quality_audit,
    load_court_grade_targets_config,
    load_exact_targets_config,
    save_snapshot_counts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update_exact_target_audit",
        description=(
            "Compute NyayaRAG collection control-plane audits: exact targets, "
            "metadata quality, and court-grade family completeness."
        ),
    )
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--targets",
        type=Path,
        default=None,
        help=(
            "Operational exact-target registry JSON. "
            "If omitted, the exact audit still renders coverage but skips source gating."
        ),
    )
    parser.add_argument(
        "--court-grade-targets",
        type=Path,
        default=None,
        help=(
            "Court-grade family registry JSON. "
            "If omitted, the script will auto-discover `court_grade_targets.json` next to the output."
        ),
    )
    parser.add_argument(
        "--metadata-output",
        type=Path,
        default=None,
        help=(
            "Optional metadata audit Markdown output path. "
            "Defaults to `METADATA_QUALITY_AUDIT.md` next to the exact audit output."
        ),
    )
    parser.add_argument(
        "--court-grade-output",
        type=Path,
        default=None,
        help=(
            "Optional court-grade audit Markdown output path. "
            "Defaults to `COURT_GRADE_COMPLETENESS_AUDIT.md` next to the exact audit output."
        ),
    )
    parser.add_argument(
        "--sqlite-timeout-seconds",
        type=float,
        default=2.0,
        help="SQLite connection timeout (seconds). Lower values avoid hanging on locked DBs.",
    )
    parser.add_argument(
        "--busy-timeout-ms",
        type=int,
        default=2000,
        help="SQLite PRAGMA busy_timeout (milliseconds).",
    )
    parser.add_argument(
        "--per-db-timeout-seconds",
        type=float,
        default=5.0,
        help=(
            "Maximum time budget per DB (seconds). "
            "If exceeded, that DB is classified via the control-plane fallback path."
        ),
    )
    return parser


def _write_artifact(markdown_path: Path, artifact: AuditArtifact) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(artifact.markdown, encoding="utf-8")
    summary_path = markdown_path.with_suffix(".json")
    summary_path.write_text(json.dumps(artifact.summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _default_metadata_output(exact_output: Path) -> Path:
    return exact_output.with_name("METADATA_QUALITY_AUDIT.md")


def _default_court_grade_output(exact_output: Path) -> Path:
    return exact_output.with_name("COURT_GRADE_COMPLETENESS_AUDIT.md")


def _discover_court_grade_targets(
    *,
    explicit_path: Path | None,
    exact_output: Path,
) -> Path | None:
    if explicit_path is not None:
        return explicit_path

    inferred = exact_output.parent / "court_grade_targets.json"
    if inferred.exists():
        return inferred
    return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    staging_dir: Path = args.staging_dir
    exact_output: Path = args.output
    metadata_output: Path = args.metadata_output or _default_metadata_output(exact_output)
    court_grade_output: Path = args.court_grade_output or _default_court_grade_output(exact_output)

    targets = load_exact_targets_config(Path(args.targets)) if args.targets is not None else None
    exact_artifact, exact_rows, _per_db_rows = generate_exact_target_audit(
        staging_dir=staging_dir,
        output_path=exact_output,
        targets=targets,
        sqlite_timeout_seconds=float(args.sqlite_timeout_seconds),
        busy_timeout_ms=int(args.busy_timeout_ms),
        per_db_timeout_seconds=float(args.per_db_timeout_seconds),
    )
    _write_artifact(exact_output, exact_artifact)
    if exact_artifact.snapshot_counts is not None:
        snapshot_path = exact_output.with_suffix(exact_output.suffix + ".snapshot.json")
        save_snapshot_counts(
            snapshot_path,
            timestamp=datetime.fromisoformat(str(exact_artifact.summary["updated_at"])),
            counts=exact_artifact.snapshot_counts,
        )

    metadata_artifact = generate_metadata_quality_audit(exact_rows=exact_rows)
    _write_artifact(metadata_output, metadata_artifact)

    court_grade_targets_path = _discover_court_grade_targets(
        explicit_path=args.court_grade_targets,
        exact_output=exact_output,
    )
    if court_grade_targets_path is not None:
        if not court_grade_targets_path.exists():
            raise SystemExit(f"Missing court-grade targets config: {court_grade_targets_path}")
        court_grade_targets = load_court_grade_targets_config(court_grade_targets_path)
        court_grade_artifact = generate_court_grade_audit(
            court_grade_targets=court_grade_targets,
            exact_rows=exact_rows,
        )
        _write_artifact(court_grade_output, court_grade_artifact)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
