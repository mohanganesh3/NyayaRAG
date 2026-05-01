from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ingestion.collection_audits import ExactAuditRow, SOURCE_STATUS_RANK


@dataclass(frozen=True)
class AuditPaths:
    staging_dir: Path
    exact_targets: Path
    exact_audit_md: Path
    exact_audit_json: Path
    metadata_audit_md: Path
    court_grade_targets: Path
    court_grade_audit_md: Path
    court_grade_audit_json: Path


def _repo_root() -> Path:
    env_root = os.environ.get("NYAYARAG_ROOT_DIR")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parents[4]


def _audit_paths(repo_root: Path) -> AuditPaths:
    collection_dir = repo_root / "data" / "collection"
    exact_audit_md = collection_dir / "EXACT_TARGET_AUDIT.md"
    court_grade_audit_md = collection_dir / "COURT_GRADE_COMPLETENESS_AUDIT.md"
    return AuditPaths(
        staging_dir=collection_dir / "staging",
        exact_targets=collection_dir / "exact_targets.json",
        exact_audit_md=exact_audit_md,
        exact_audit_json=exact_audit_md.with_suffix(".json"),
        metadata_audit_md=collection_dir / "METADATA_QUALITY_AUDIT.md",
        court_grade_targets=collection_dir / "court_grade_targets.json",
        court_grade_audit_md=court_grade_audit_md,
        court_grade_audit_json=court_grade_audit_md.with_suffix(".json"),
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autopilot_exact_targets",
        description=(
            "Watch NyayaRAG exact + court-grade audits and keep restarting broken collectors "
            "until both meters are green. "
            "Enforces: after (re)starting any collector, wait N seconds and confirm HAVE grows."
        ),
    )
    p.add_argument(
        "--verify-wait-seconds",
        type=int,
        default=600,
        help="Wait time after starting collectors before verifying HAVE growth (default: 600).",
    )
    p.add_argument(
        "--idle-sleep-seconds",
        type=int,
        default=300,
        help="Sleep when nothing needed restarting (default: 300).",
    )
    p.add_argument(
        "--max-restarts-per-cycle",
        type=int,
        default=3,
        help="Max sources to restart per cycle (default: 3).",
    )
    p.add_argument(
        "--exit-when-done",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exit with 0 once exact + court-grade audits both report DONE (default: true).",
    )
    p.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="If true, do not start/stop any screens; only print intended actions.",
    )
    return p


def _run_audit(repo_root: Path, paths: AuditPaths) -> None:
    cmd = [
        sys.executable,
        "-m",
        "app.ingestion.scripts.update_exact_target_audit",
        "--staging-dir",
        str(paths.staging_dir),
        "--output",
        str(paths.exact_audit_md),
        "--targets",
        str(paths.exact_targets),
        "--metadata-output",
        str(paths.metadata_audit_md),
        "--court-grade-targets",
        str(paths.court_grade_targets),
        "--court-grade-output",
        str(paths.court_grade_audit_md),
    ]
    subprocess.run(cmd, check=True, cwd=str(repo_root / "backend"))


def _load_exact_rows(summary_path: Path) -> list[ExactAuditRow]:
    if not summary_path.exists():
        return []
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    rows_raw = payload.get("rows", [])
    rows: list[ExactAuditRow] = []
    for raw in rows_raw:
        if not isinstance(raw, dict):
            continue
        rows.append(ExactAuditRow.from_json(raw))
    return rows


def _load_court_grade_rows(summary_path: Path) -> list[dict[str, Any]]:
    if not summary_path.exists():
        return []
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    rows_raw = payload.get("rows", [])
    return [dict(row) for row in rows_raw if isinstance(row, dict)]


def _job_script_for_source_key(repo_root: Path, source_key: str) -> Path | None:
    screen_jobs = repo_root / "backend" / "app" / "ingestion" / "screen_jobs"
    explicit: dict[str, str] = {
        "sc_supreme_court": "sc_full.sh",
        "gazette": "egazette_full.sh",
        "cbic": "cbic_gst_full.sh",
        "cbdt": "cbdt_circulars_full.sh",
        "india_code_central_acts": "india_code_central_acts_full.sh",
    }
    if source_key in explicit:
        path = screen_jobs / explicit[source_key]
        return path if path.exists() else None

    hc_path = screen_jobs / f"{source_key}_full.sh"
    if hc_path.exists():
        return hc_path

    pdf_seed = screen_jobs / f"{source_key}_pdf_seed_full.sh"
    if pdf_seed.exists():
        return pdf_seed

    fallback = screen_jobs / f"{source_key}_full.sh"
    if fallback.exists():
        return fallback
    return None


def _screen_session_name(source_key: str) -> str:
    return source_key


def _screen_list() -> str:
    proc = subprocess.run(["screen", "-ls"], capture_output=True, text=True, check=False)
    return (proc.stdout or "") + (proc.stderr or "")


def _screen_quit(session_name: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] screen quit {session_name}", flush=True)
        return
    subprocess.run(["screen", "-S", session_name, "-X", "quit"], check=False)


def _screen_start(session_name: str, *, command: str, cwd: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] screen start {session_name}: (cwd={cwd}) {command}", flush=True)
        return
    subprocess.run(
        ["screen", "-dmS", session_name, "bash", "-lc", command],
        check=True,
        cwd=str(cwd),
    )


def _restart_source(repo_root: Path, source_key: str, *, dry_run: bool) -> bool:
    script = _job_script_for_source_key(repo_root, source_key)
    if script is None:
        print(f"[autopilot] no job script for source_key={source_key}", flush=True)
        return False
    session = _screen_session_name(source_key)
    _screen_quit(session, dry_run=dry_run)
    cmd = f"bash {shlex.quote(str(script))}"
    _screen_start(session, command=cmd, cwd=repo_root, dry_run=dry_run)
    print(f"[autopilot] restarted {source_key} -> {script.name} (screen={session})", flush=True)
    return True


def _status_summary(rows: list[ExactAuditRow]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return ", ".join(
        f"{status}={count}"
        for status, count in sorted(counts.items(), key=lambda item: SOURCE_STATUS_RANK.get(item[0], 99))
    )


def _family_summary(rows: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status", "DISCOVERING"))
        counts[status] = counts.get(status, 0) + 1
    return ", ".join(
        f"{status}={count}"
        for status, count in sorted(counts.items(), key=lambda item: SOURCE_STATUS_RANK.get(item[0], 99))
    )


def _all_exact_done(rows: list[ExactAuditRow]) -> bool:
    return bool(rows) and all(row.status == "DONE" for row in rows)


def _all_court_grade_done(rows: list[dict[str, Any]]) -> bool:
    return bool(rows) and all(str(row.get("status", "")) == "DONE" for row in rows)


def _restart_candidate_rank(row: ExactAuditRow) -> tuple[int, int, int, int, str]:
    restart_priority = {
        "DISCOVERING": 0,
        "BROKEN": 1,
        "PATCHING": 2,
        "RUNNING_HEALTHY": 3,
    }.get(row.status, 99)
    zero_bias = 0 if row.have == 0 else 1
    critical_bias = 0 if row.critical else 1
    remaining = row.remaining or 0
    return (restart_priority, zero_bias, critical_bias, -remaining, row.key)


def _select_restart_candidates(rows: list[ExactAuditRow], screen_listing: str) -> list[ExactAuditRow]:
    candidates: list[ExactAuditRow] = []
    for row in rows:
        if row.status in {"DONE", "COUNT_DONE_METADATA_PENDING", "BLOCKED_EXTERNALLY"}:
            continue
        session_name = _screen_session_name(row.key)
        session_running = session_name in screen_listing
        if row.status in {"DISCOVERING", "BROKEN"}:
            candidates.append(row)
            continue
        if row.status in {"PATCHING", "RUNNING_HEALTHY"} and not session_running and (row.remaining or 0) > 0:
            candidates.append(row)
    return sorted(candidates, key=_restart_candidate_rank)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    repo_root = _repo_root()
    paths = _audit_paths(repo_root)

    if not paths.staging_dir.exists():
        raise SystemExit(f"Missing staging dir: {paths.staging_dir}")
    if not paths.exact_targets.exists():
        raise SystemExit(f"Missing targets config: {paths.exact_targets}")
    if not paths.court_grade_targets.exists():
        raise SystemExit(f"Missing court-grade targets config: {paths.court_grade_targets}")

    print(f"[autopilot] repo_root={repo_root}", flush=True)

    while True:
        started_at = datetime.now(UTC)
        print(f"\n[autopilot] === cycle @ {started_at.isoformat()} ===", flush=True)
        try:
            _run_audit(repo_root, paths)
        except Exception as exc:  # noqa: BLE001
            print(f"[autopilot] audit failed: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(30)
            continue

        exact_rows = _load_exact_rows(paths.exact_audit_json)
        court_grade_rows = _load_court_grade_rows(paths.court_grade_audit_json)
        if not exact_rows:
            print(f"[autopilot] could not parse exact audit summary from {paths.exact_audit_json}", flush=True)
            time.sleep(60)
            continue

        print(f"[autopilot] exact_status_summary: {_status_summary(exact_rows)}", flush=True)
        if court_grade_rows:
            print(f"[autopilot] court_grade_summary: {_family_summary(court_grade_rows)}", flush=True)

        if _all_exact_done(exact_rows) and _all_court_grade_done(court_grade_rows):
            print("[autopilot] DUAL FINISH ACHIEVED ✅", flush=True)
            return 0 if bool(args.exit_when_done) else 0

        screen_listing = _screen_list()
        candidates = _select_restart_candidates(exact_rows, screen_listing)
        before_counts = {row.key: row.have for row in exact_rows}
        restarts: list[str] = []

        for row in candidates[: max(0, int(args.max_restarts_per_cycle))]:
            ok = _restart_source(repo_root, row.key, dry_run=bool(args.dry_run))
            if ok:
                restarts.append(row.key)

        if not restarts:
            if _all_exact_done(exact_rows) and not _all_court_grade_done(court_grade_rows):
                print(
                    "[autopilot] exact sources are done, but court-grade families are still incomplete",
                    flush=True,
                )
            idle_sleep_seconds = int(args.idle_sleep_seconds)
            print(f"[autopilot] no restart candidates; sleeping {idle_sleep_seconds}s", flush=True)
            time.sleep(idle_sleep_seconds)
            continue

        print(f"[autopilot] restarted_sources={restarts}", flush=True)
        print(f"[autopilot] verifying growth after {int(args.verify_wait_seconds)}s", flush=True)
        time.sleep(int(args.verify_wait_seconds))

        try:
            _run_audit(repo_root, paths)
        except Exception as exc:  # noqa: BLE001
            print(f"[autopilot] audit failed during verify: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(30)
            continue

        after_rows = {row.key: row for row in _load_exact_rows(paths.exact_audit_json)}
        for key in restarts:
            before = int(before_counts.get(key, 0))
            after_row = after_rows.get(key)
            after = int(after_row.have) if after_row is not None else before
            delta = after - before
            if delta > 0:
                print(f"[autopilot] growth OK: {key} {before:,} -> {after:,} (Δ {delta:+,})", flush=True)
                continue
            print(
                f"[autopilot] growth FAIL: {key} {before:,} -> {after:,} (Δ {delta:+,}); restarting again",
                flush=True,
            )
            _restart_source(repo_root, key, dry_run=bool(args.dry_run))

        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
