from __future__ import annotations

import json
import multiprocessing as mp
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCE_STATUSES: tuple[str, ...] = (
    "DISCOVERING",
    "BROKEN",
    "PATCHING",
    "RUNNING_HEALTHY",
    "COUNT_DONE_METADATA_PENDING",
    "DONE",
    "BLOCKED_EXTERNALLY",
)

SOURCE_STATUS_RANK: dict[str, int] = {
    "DISCOVERING": 0,
    "BROKEN": 1,
    "PATCHING": 2,
    "RUNNING_HEALTHY": 3,
    "COUNT_DONE_METADATA_PENDING": 4,
    "DONE": 5,
    "BLOCKED_EXTERNALLY": 6,
}

CORE_METADATA_FIELDS: tuple[str, ...] = (
    "doc_id",
    "source_system",
    "source_url",
    "source_document_ref",
    "checksum",
    "parser_version",
    "collector_run_id",
    "doc_type",
    "artifact_url",
    "source_surface",
    "provenance_tier",
)

CURRENT_SCHEMA_GAPS: tuple[str, ...] = ()

CASE_LAW_SOURCE_KEYS: set[str] = {
    "sc_supreme_court",
    "itat",
    "nclt",
    "nclat",
    "cestat",
    "ncdrc",
    "cat",
    "aft",
    "ngt",
    "drt",
    "sat",
    "tdsat",
    "aptel",
}

REGULATORY_SOURCE_KEYS: set[str] = {
    "sebi",
    "rbi",
    "cci",
    "trai",
    "irdai",
    "cbic",
    "ibbi",
    "cbdt",
    "pfrda",
    "gazette",
}

LEGISLATIVE_SOURCE_KEYS: set[str] = {
    "constitution_of_india",
    "india_code_central_acts",
    "criminal_code_crosswalk",
    "ca_debates",
    "law_commission_reports",
}


@dataclass(frozen=True)
class TargetSource:
    key: str
    display: str
    db: str
    need: int | None
    critical: bool = True
    authority_layer: str | None = None
    source_family: str | None = None
    metadata_expectations: tuple[str, ...] = ()
    notes: str | None = None


@dataclass(frozen=True)
class TargetsConfig:
    sources: dict[str, TargetSource]


@dataclass(frozen=True)
class CourtGradeFamily:
    key: str
    display: str
    depends_on_exact: tuple[str, ...]
    depends_on_families: tuple[str, ...]
    critical: bool
    layer: str | None
    notes: str | None
    blocker_note: str | None
    manual_status: str | None


@dataclass(frozen=True)
class CourtGradeTargetsConfig:
    families: dict[str, CourtGradeFamily]


@dataclass(frozen=True)
class DbMetadataStats:
    total_docs: int
    available_columns: tuple[str, ...]
    field_non_null: dict[str, int]
    duplicate_source_url_groups: int
    duplicate_source_url_rows: int

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "DbMetadataStats":
        return cls(
            total_docs=int(payload.get("total_docs", 0)),
            available_columns=tuple(str(x) for x in payload.get("available_columns", [])),
            field_non_null={
                str(k): int(v)
                for k, v in dict(payload.get("field_non_null", {})).items()
                if not isinstance(v, bool)
            },
            duplicate_source_url_groups=int(payload.get("duplicate_source_url_groups", 0)),
            duplicate_source_url_rows=int(payload.get("duplicate_source_url_rows", 0)),
        )


@dataclass(frozen=True)
class DbScanResult:
    db_name: str
    status: str
    docs: int | None
    metadata: DbMetadataStats | None
    used_last_known_count: bool = False


@dataclass(frozen=True)
class MetadataGateResult:
    gate_pass: bool
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...]
    field_ratios: dict[str, float]
    missing_columns: tuple[str, ...]
    duplicate_source_url_groups: int
    duplicate_source_url_rows: int
    notes: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "gate_pass": self.gate_pass,
            "required_fields": list(self.required_fields),
            "optional_fields": list(self.optional_fields),
            "field_ratios": self.field_ratios,
            "missing_columns": list(self.missing_columns),
            "duplicate_source_url_groups": self.duplicate_source_url_groups,
            "duplicate_source_url_rows": self.duplicate_source_url_rows,
            "notes": list(self.notes),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "MetadataGateResult":
        return cls(
            gate_pass=bool(payload.get("gate_pass", False)),
            required_fields=tuple(str(x) for x in payload.get("required_fields", [])),
            optional_fields=tuple(str(x) for x in payload.get("optional_fields", [])),
            field_ratios={
                str(k): float(v)
                for k, v in dict(payload.get("field_ratios", {})).items()
                if not isinstance(v, bool)
            },
            missing_columns=tuple(str(x) for x in payload.get("missing_columns", [])),
            duplicate_source_url_groups=int(payload.get("duplicate_source_url_groups", 0)),
            duplicate_source_url_rows=int(payload.get("duplicate_source_url_rows", 0)),
            notes=tuple(str(x) for x in payload.get("notes", [])),
        )


@dataclass(frozen=True)
class ExactAuditRow:
    key: str
    display: str
    db: str
    have: int
    need: int | None
    percent: float | None
    delta_docs: int | None
    rate_docs_per_hour: float | None
    remaining: int | None
    count_gate_pass: bool
    metadata_gate_pass: bool
    status: str
    critical: bool
    scan_status: str
    used_last_known_count: bool
    positive_windows: int
    no_growth_windows: int
    is_slow: bool
    metadata: MetadataGateResult
    notes: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "display": self.display,
            "db": self.db,
            "have": self.have,
            "need": self.need,
            "percent": self.percent,
            "delta_docs": self.delta_docs,
            "rate_docs_per_hour": self.rate_docs_per_hour,
            "remaining": self.remaining,
            "count_gate_pass": self.count_gate_pass,
            "metadata_gate_pass": self.metadata_gate_pass,
            "status": self.status,
            "critical": self.critical,
            "scan_status": self.scan_status,
            "used_last_known_count": self.used_last_known_count,
            "positive_windows": self.positive_windows,
            "no_growth_windows": self.no_growth_windows,
            "is_slow": self.is_slow,
            "metadata": self.metadata.to_json(),
            "notes": list(self.notes),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "ExactAuditRow":
        return cls(
            key=str(payload.get("key", "")),
            display=str(payload.get("display", "")),
            db=str(payload.get("db", "")),
            have=int(payload.get("have", 0)),
            need=None if payload.get("need") is None else int(payload["need"]),
            percent=None if payload.get("percent") is None else float(payload["percent"]),
            delta_docs=None if payload.get("delta_docs") is None else int(payload["delta_docs"]),
            rate_docs_per_hour=(
                None
                if payload.get("rate_docs_per_hour") is None
                else float(payload["rate_docs_per_hour"])
            ),
            remaining=None if payload.get("remaining") is None else int(payload["remaining"]),
            count_gate_pass=bool(payload.get("count_gate_pass", False)),
            metadata_gate_pass=bool(payload.get("metadata_gate_pass", False)),
            status=str(payload.get("status", "DISCOVERING")),
            critical=bool(payload.get("critical", True)),
            scan_status=str(payload.get("scan_status", "error")),
            used_last_known_count=bool(payload.get("used_last_known_count", False)),
            positive_windows=int(payload.get("positive_windows", 0)),
            no_growth_windows=int(payload.get("no_growth_windows", 0)),
            is_slow=bool(payload.get("is_slow", False)),
            metadata=MetadataGateResult.from_json(dict(payload.get("metadata", {}))),
            notes=tuple(str(x) for x in payload.get("notes", [])),
        )


@dataclass(frozen=True)
class AuditArtifact:
    markdown: str
    summary: dict[str, Any]
    snapshot_counts: dict[str, int] | None = None


def _classify_sqlite_operational_error(exc: sqlite3.OperationalError) -> str:
    message = str(exc).lower()
    if "interrupted" in message:
        return "timeout"
    if "database is locked" in message or "database table is locked" in message:
        return "locked"
    if "no such table" in message:
        return "no_schema"
    return "operational_error"


def load_exact_targets_config(path: Path) -> TargetsConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    sources_raw = data.get("sources")
    if not isinstance(sources_raw, dict):
        return TargetsConfig(sources={})

    sources: dict[str, TargetSource] = {}
    for key, raw in sources_raw.items():
        if not isinstance(raw, dict):
            continue
        db_raw = raw.get("db")
        if not isinstance(db_raw, str) or not db_raw.endswith(".db"):
            raise ValueError(f"targets.sources[{key!r}].db must be a .db filename")

        need_raw = raw.get("need")
        need = None if need_raw is None else int(need_raw)
        metadata_expectations_raw = raw.get("metadata_expectations") or []
        metadata_expectations = tuple(
            str(field)
            for field in metadata_expectations_raw
            if isinstance(field, str) and field.strip()
        )
        sources[str(key)] = TargetSource(
            key=str(key),
            display=str(raw.get("display") or key),
            db=str(db_raw),
            need=need,
            critical=bool(raw.get("critical", True)),
            authority_layer=(
                str(raw.get("authority_layer")) if raw.get("authority_layer") else None
            ),
            source_family=(str(raw.get("source_family")) if raw.get("source_family") else None),
            metadata_expectations=metadata_expectations,
            notes=(str(raw.get("notes")) if raw.get("notes") else None),
        )
    return TargetsConfig(sources=sources)


def load_court_grade_targets_config(path: Path) -> CourtGradeTargetsConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    families_raw = data.get("families")
    if not isinstance(families_raw, dict):
        return CourtGradeTargetsConfig(families={})

    families: dict[str, CourtGradeFamily] = {}
    for key, raw in families_raw.items():
        if not isinstance(raw, dict):
            continue
        manual_status = raw.get("manual_status")
        if manual_status is not None and str(manual_status) not in SOURCE_STATUSES:
            raise ValueError(f"court_grade.families[{key!r}].manual_status is invalid")
        families[str(key)] = CourtGradeFamily(
            key=str(key),
            display=str(raw.get("display") or key),
            depends_on_exact=tuple(
                str(x)
                for x in raw.get("depends_on_exact", [])
                if isinstance(x, str) and x.strip()
            ),
            depends_on_families=tuple(
                str(x)
                for x in raw.get("depends_on_families", [])
                if isinstance(x, str) and x.strip()
            ),
            critical=bool(raw.get("critical", True)),
            layer=str(raw.get("layer")) if raw.get("layer") else None,
            notes=str(raw.get("notes")) if raw.get("notes") else None,
            blocker_note=str(raw.get("blocker_note")) if raw.get("blocker_note") else None,
            manual_status=str(manual_status) if manual_status else None,
        )
    return CourtGradeTargetsConfig(families=families)


def load_previous_summary(summary_path: Path) -> tuple[datetime | None, dict[str, ExactAuditRow]]:
    if not summary_path.exists():
        return None, {}
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None, {}

    ts_raw = payload.get("updated_at")
    updated_at = datetime.fromisoformat(ts_raw) if isinstance(ts_raw, str) else None
    if updated_at is not None and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)

    rows_raw = payload.get("rows")
    if not isinstance(rows_raw, list):
        return updated_at, {}
    rows: dict[str, ExactAuditRow] = {}
    for raw in rows_raw:
        if not isinstance(raw, dict):
            continue
        row = ExactAuditRow.from_json(raw)
        if row.key:
            rows[row.key] = row
    return updated_at, rows


def load_snapshot_counts(path: Path) -> tuple[datetime | None, dict[str, int]]:
    if not path.exists():
        return None, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, {}
    ts = data.get("timestamp")
    timestamp = datetime.fromisoformat(ts) if isinstance(ts, str) else None
    if timestamp is not None and timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    counts_raw = data.get("counts", {})
    counts: dict[str, int] = {}
    if isinstance(counts_raw, dict):
        for key, value in counts_raw.items():
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            counts[str(key)] = int(value)
    return timestamp, counts


def save_snapshot_counts(path: Path, *, timestamp: datetime, counts: dict[str, int]) -> None:
    payload = {"timestamp": timestamp.isoformat(), "counts": counts}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _open_sqlite_readonly(
    db_path: Path,
    *,
    sqlite_timeout_seconds: float,
    busy_timeout_ms: int,
) -> sqlite3.Connection:
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=float(sqlite_timeout_seconds),
        check_same_thread=False,
    )
    with closing(conn.cursor()) as cursor:
        cursor.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        cursor.execute("PRAGMA query_only=ON")
    return conn


def _fetch_table_columns(conn: sqlite3.Connection) -> set[str]:
    with closing(conn.cursor()) as cursor:
        rows = cursor.execute("PRAGMA table_info(legal_documents)").fetchall()
    return {str(row[1]) for row in rows if len(row) > 1}


def _presence_expr(column: str, *, json_field: bool = False) -> str:
    if json_field:
        return (
            f"SUM(CASE WHEN {column} IS NOT NULL "
            f"AND trim(CAST({column} AS TEXT)) NOT IN ('', '[]', '{{}}', 'null') "
            f"THEN 1 ELSE 0 END) AS {column}"
        )
    return (
        f"SUM(CASE WHEN {column} IS NOT NULL "
        f"AND trim(CAST({column} AS TEXT)) != '' "
        f"THEN 1 ELSE 0 END) AS {column}"
    )


def _scan_db_live(
    db_path: Path,
    *,
    sqlite_timeout_seconds: float,
    busy_timeout_ms: int,
    per_db_timeout_seconds: float,
    collect_metadata: bool,
) -> dict[str, Any]:
    with closing(
        _open_sqlite_readonly(
            db_path,
            sqlite_timeout_seconds=sqlite_timeout_seconds,
            busy_timeout_ms=busy_timeout_ms,
        )
    ) as conn:
        start = time.monotonic()

        def _progress_handler() -> int:
            if time.monotonic() - start > float(per_db_timeout_seconds):
                return 1
            return 0

        conn.set_progress_handler(_progress_handler, 10_000)
        try:
            with closing(conn.cursor()) as cursor:
                total_docs = int(cursor.execute("SELECT COUNT(*) FROM legal_documents").fetchone()[0])
                if not collect_metadata:
                    return {"status": "ok", "docs": total_docs, "metadata": None}

                columns = _fetch_table_columns(conn)
                tracked_fields = (
                    "doc_id",
                    "source_system",
                    "source_url",
                    "source_document_ref",
                    "checksum",
                    "parser_version",
                    "ingestion_run_id",
                    "collector_run_id",
                    "doc_type",
                    "title",
                    "date_text",
                    "decision_date",
                    "publication_date",
                    "seed_url",
                    "detail_url",
                    "artifact_url",
                    "source_surface",
                    "provenance_tier",
                    "mime_type",
                    "is_ocr",
                    "ocr_confidence",
                    "date",
                    "court",
                    "citation",
                    "parties",
                    "bench",
                )
                aggregate_parts: list[str] = ["COUNT(*) AS total_docs"]
                for field in tracked_fields:
                    if field not in columns:
                        continue
                    aggregate_parts.append(
                        _presence_expr(field, json_field=field in {"parties", "bench"})
                    )
                aggregate_sql = f"SELECT {', '.join(aggregate_parts)} FROM legal_documents"
                row = cursor.execute(aggregate_sql).fetchone()
                field_non_null: dict[str, int] = {}
                if row is not None:
                    description = [desc[0] for desc in cursor.description or []]
                    for idx, name in enumerate(description):
                        if name == "total_docs":
                            continue
                        field_non_null[str(name)] = int(row[idx] or 0)

                duplicate_groups = 0
                duplicate_rows = 0
                if {"source_system", "source_url"}.issubset(columns):
                    dup_row = cursor.execute(
                        """
                        SELECT COUNT(*), COALESCE(SUM(cnt - 1), 0)
                        FROM (
                            SELECT COUNT(*) AS cnt
                            FROM legal_documents
                            WHERE source_system IS NOT NULL
                              AND trim(CAST(source_system AS TEXT)) != ''
                              AND source_url IS NOT NULL
                              AND trim(CAST(source_url AS TEXT)) != ''
                            GROUP BY source_system, source_url
                            HAVING COUNT(*) > 1
                        )
                        """
                    ).fetchone()
                    if dup_row is not None:
                        duplicate_groups = int(dup_row[0] or 0)
                        duplicate_rows = int(dup_row[1] or 0)

                metadata = DbMetadataStats(
                    total_docs=total_docs,
                    available_columns=tuple(sorted(columns)),
                    field_non_null=field_non_null,
                    duplicate_source_url_groups=duplicate_groups,
                    duplicate_source_url_rows=duplicate_rows,
                )
                return {"status": "ok", "docs": total_docs, "metadata": metadata.to_json()}
        finally:
            conn.set_progress_handler(None, 0)


def _scan_db_worker(
    db_path_str: str,
    sqlite_timeout_seconds: float,
    busy_timeout_ms: int,
    per_db_timeout_seconds: float,
    collect_metadata: bool,
    conn,
) -> None:
    db_path = Path(db_path_str)
    try:
        conn.send(
            _scan_db_live(
                db_path,
                sqlite_timeout_seconds=sqlite_timeout_seconds,
                busy_timeout_ms=busy_timeout_ms,
                per_db_timeout_seconds=per_db_timeout_seconds,
                collect_metadata=collect_metadata,
            )
        )
    except sqlite3.OperationalError as exc:
        conn.send(
            {
                "status": _classify_sqlite_operational_error(exc),
                "docs": None,
                "metadata": None,
            }
        )
    except Exception:
        conn.send({"status": "error", "docs": None, "metadata": None})
    finally:
        try:
            conn.close()
        except Exception:
            pass


def scan_db_with_timeout(
    db_path: Path,
    *,
    sqlite_timeout_seconds: float,
    busy_timeout_ms: int,
    per_db_timeout_seconds: float,
    collect_metadata: bool,
    last_known_docs: int | None = None,
) -> DbScanResult:
    ctx = mp.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_scan_db_worker,
        args=(
            str(db_path),
            float(sqlite_timeout_seconds),
            int(busy_timeout_ms),
            float(per_db_timeout_seconds),
            bool(collect_metadata),
            child_conn,
        ),
        daemon=True,
    )
    proc.start()
    try:
        proc.join(timeout=float(per_db_timeout_seconds))
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=1.0)
            status = "timeout"
            docs = last_known_docs if last_known_docs is not None else None
            return DbScanResult(
                db_name=db_path.name,
                status="timeout_last_known" if docs is not None else status,
                docs=docs,
                metadata=None,
                used_last_known_count=docs is not None,
            )

        if not parent_conn.poll(0.1):
            return DbScanResult(db_name=db_path.name, status="error", docs=None, metadata=None)

        payload = parent_conn.recv()
        status = str(payload.get("status", "error"))
        docs_raw = payload.get("docs")
        metadata_payload = payload.get("metadata")
        docs = None if docs_raw is None else int(docs_raw)
        metadata = (
            DbMetadataStats.from_json(metadata_payload)
            if isinstance(metadata_payload, dict)
            else None
        )

        if status == "ok":
            return DbScanResult(db_name=db_path.name, status=status, docs=docs, metadata=metadata)

        if last_known_docs is not None:
            return DbScanResult(
                db_name=db_path.name,
                status=f"{status}_last_known",
                docs=int(last_known_docs),
                metadata=None,
                used_last_known_count=True,
            )

        return DbScanResult(db_name=db_path.name, status=status, docs=None, metadata=None)
    finally:
        try:
            parent_conn.close()
        except Exception:
            pass


def scan_staging_dbs(
    staging_dir: Path,
    *,
    sqlite_timeout_seconds: float,
    busy_timeout_ms: int,
    per_db_timeout_seconds: float,
    previous_counts_by_db: dict[str, int],
) -> tuple[list[DbScanResult], dict[str, int], int]:
    per_db_rows: list[DbScanResult] = []
    counts_by_db: dict[str, int] = {}
    total_scanned_docs = 0

    for db_path in sorted(staging_dir.glob("*.db")):
        row = scan_db_with_timeout(
            db_path,
            sqlite_timeout_seconds=sqlite_timeout_seconds,
            busy_timeout_ms=busy_timeout_ms,
            per_db_timeout_seconds=per_db_timeout_seconds,
            collect_metadata=False,
            last_known_docs=previous_counts_by_db.get(db_path.name),
        )
        per_db_rows.append(row)
        if row.docs is None:
            continue
        counts_by_db[db_path.name] = int(row.docs)
        total_scanned_docs += int(row.docs)
    return per_db_rows, counts_by_db, total_scanned_docs


def _default_metadata_profile(source_key: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if source_key.startswith("hc_") or source_key in CASE_LAW_SOURCE_KEYS:
        return ("date", "court", "title"), ("citation", "parties", "bench", "detail_url")
    if source_key in REGULATORY_SOURCE_KEYS:
        return ("date", "court", "title"), ("citation", "detail_url")
    if source_key in LEGISLATIVE_SOURCE_KEYS:
        return ("date", "title"), ("citation", "seed_url")
    return ("date", "court", "title"), ("detail_url",)


def evaluate_metadata_gate(
    source: TargetSource,
    metadata: DbMetadataStats | None,
    previous: MetadataGateResult | None = None,
) -> MetadataGateResult:
    if metadata is None:
        if previous is not None:
            return previous
        return MetadataGateResult(
            gate_pass=False,
            required_fields=CORE_METADATA_FIELDS,
            optional_fields=(),
            field_ratios={},
            missing_columns=(),
            duplicate_source_url_groups=0,
            duplicate_source_url_rows=0,
            notes=("metadata_unavailable",),
        )

    required_identity_fields, default_optional_fields = _default_metadata_profile(source.key)
    optional_fields = source.metadata_expectations or default_optional_fields
    required_fields = CORE_METADATA_FIELDS + required_identity_fields

    total_docs = max(0, int(metadata.total_docs))
    available_columns = set(metadata.available_columns)
    field_ratios: dict[str, float] = {}
    missing_columns: list[str] = []

    all_fields = tuple(dict.fromkeys(required_fields + optional_fields))
    for field in all_fields:
        if field not in available_columns:
            missing_columns.append(field)
            field_ratios[field] = 0.0
            continue
        present = int(metadata.field_non_null.get(field, 0))
        field_ratios[field] = 0.0 if total_docs <= 0 else present / total_docs

    notes: list[str] = []
    if total_docs <= 0:
        notes.append("no_documents")
    if missing_columns:
        notes.append("schema_gap")
    if metadata.duplicate_source_url_groups > 0:
        notes.append("duplicate_source_url")

    required_pass = total_docs > 0 and all(field_ratios.get(field, 0.0) >= 1.0 for field in required_fields)
    optional_pass = all(field_ratios.get(field, 0.0) >= 0.95 for field in optional_fields)
    duplicate_pass = metadata.duplicate_source_url_groups == 0
    gate_pass = required_pass and optional_pass and duplicate_pass

    if not required_pass:
        notes.append("required_fields_below_gate")
    if optional_fields and not optional_pass:
        notes.append("optional_fields_below_gate")

    return MetadataGateResult(
        gate_pass=gate_pass,
        required_fields=required_fields,
        optional_fields=optional_fields,
        field_ratios=field_ratios,
        missing_columns=tuple(sorted(missing_columns)),
        duplicate_source_url_groups=metadata.duplicate_source_url_groups,
        duplicate_source_url_rows=metadata.duplicate_source_url_rows,
        notes=tuple(dict.fromkeys(notes)),
    )


def _compute_docs_per_hour(delta_docs: int, delta_seconds: float | None) -> float | None:
    if delta_seconds is None or delta_seconds <= 0:
        return None
    return (float(delta_docs) / delta_seconds) * 3600.0


def _format_rate(docs_per_hour: float | None) -> str:
    if docs_per_hour is None:
        return "—"
    return f"{docs_per_hour:.0f}/h"


def _format_percent(have: int, need: int | None) -> str:
    if need is None or need <= 0:
        return "—"
    return f"{(have / need) * 100:.1f}%"


def _format_gate(value: bool) -> str:
    return "PASS" if value else "FAIL"


def _determine_exact_status(
    *,
    source: TargetSource,
    have: int,
    need: int | None,
    delta_docs: int | None,
    metadata_gate: MetadataGateResult,
    scan_result: DbScanResult | None,
    previous_row: ExactAuditRow | None,
    rate_docs_per_hour: float | None,
) -> tuple[str, int, int, bool, tuple[str, ...]]:
    notes: list[str] = []
    previous_positive = previous_row.positive_windows if previous_row else 0
    previous_no_growth = previous_row.no_growth_windows if previous_row else 0

    if scan_result is not None and scan_result.used_last_known_count and previous_row is not None:
        notes.append("using_last_known_count")
        return (
            previous_row.status,
            previous_row.positive_windows,
            previous_row.no_growth_windows,
            previous_row.is_slow,
            tuple(dict.fromkeys(notes + list(previous_row.notes))),
        )

    if delta_docs is None:
        positive_windows = 1 if have > 0 else 0
        no_growth_windows = 0
    elif delta_docs > 0:
        positive_windows = previous_positive + 1
        no_growth_windows = 0
    else:
        positive_windows = 0
        no_growth_windows = previous_no_growth + 1

    count_gate_pass = need is not None and need > 0 and have >= need
    remaining = None if need is None else max(int(need) - int(have), 0)
    is_slow = bool(
        rate_docs_per_hour is not None
        and rate_docs_per_hour < 100.0
        and remaining is not None
        and remaining > 0
    )
    if is_slow:
        notes.append("slow_growth")

    if count_gate_pass:
        status = "DONE" if metadata_gate.gate_pass else "COUNT_DONE_METADATA_PENDING"
    elif have == 0:
        status = "DISCOVERING" if previous_row is None or previous_row.have == 0 else "BROKEN"
    elif delta_docs is None:
        status = "PATCHING"
    elif delta_docs > 0:
        status = "RUNNING_HEALTHY" if positive_windows >= 2 else "PATCHING"
    else:
        status = "BROKEN"

    if scan_result is not None and scan_result.status.endswith("_last_known"):
        notes.append(scan_result.status)
    elif scan_result is not None and scan_result.status != "ok":
        notes.append(scan_result.status)

    return status, positive_windows, no_growth_windows, is_slow, tuple(dict.fromkeys(notes))


def generate_exact_target_audit(
    *,
    staging_dir: Path,
    output_path: Path,
    targets: TargetsConfig | None,
    sqlite_timeout_seconds: float,
    busy_timeout_ms: int,
    per_db_timeout_seconds: float,
    now: datetime | None = None,
) -> tuple[AuditArtifact, dict[str, ExactAuditRow], list[DbScanResult]]:
    timestamp = now or datetime.now(UTC)
    snapshot_path = output_path.with_suffix(output_path.suffix + ".snapshot.json")
    summary_path = output_path.with_suffix(".json")

    _prev_snapshot_ts, prev_counts_by_key = load_snapshot_counts(snapshot_path)
    prev_summary_ts, prev_rows_by_key = load_previous_summary(summary_path)
    delta_seconds = (
        (timestamp - prev_summary_ts).total_seconds() if prev_summary_ts is not None else None
    )

    previous_counts_by_db = {
        row.db: row.have for row in prev_rows_by_key.values() if row.db and row.have >= 0
    }
    per_db_rows, counts_by_db, total_scanned_docs = scan_staging_dbs(
        staging_dir,
        sqlite_timeout_seconds=sqlite_timeout_seconds,
        busy_timeout_ms=busy_timeout_ms,
        per_db_timeout_seconds=per_db_timeout_seconds,
        previous_counts_by_db=previous_counts_by_db,
    )
    db_scan_by_name = {row.db_name: row for row in per_db_rows}

    metadata_results_by_db: dict[str, DbScanResult] = {}
    if targets is not None:
        for source in targets.sources.values():
            db_path = staging_dir / source.db
            if not db_path.exists():
                continue
            metadata_results_by_db[source.db] = scan_db_with_timeout(
                db_path,
                sqlite_timeout_seconds=sqlite_timeout_seconds,
                busy_timeout_ms=busy_timeout_ms,
                per_db_timeout_seconds=max(10.0, per_db_timeout_seconds),
                collect_metadata=True,
                last_known_docs=counts_by_db.get(source.db),
            )
            if metadata_results_by_db[source.db].docs is not None:
                counts_by_db[source.db] = int(metadata_results_by_db[source.db].docs)
    total_scanned_docs = sum(int(count) for count in counts_by_db.values())

    exact_rows: dict[str, ExactAuditRow] = {}
    lines: list[str] = []
    lines.append("# NyayaRAG Exact Target Audit (staging)")
    lines.append(f"Last updated: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    lines.append(
        "HAVE counts use `SELECT COUNT(*) FROM legal_documents` on each staging DB, "
        "and locked DBs reuse the last known good count when available."
    )
    lines.append(
        "Source status uses the collection control-plane model: "
        "`DISCOVERING`, `BROKEN`, `PATCHING`, `RUNNING_HEALTHY`, "
        "`COUNT_DONE_METADATA_PENDING`, `DONE`, `BLOCKED_EXTERNALLY`."
    )
    if prev_summary_ts is not None and delta_seconds is not None:
        lines.append(
            f"Previous snapshot: {prev_summary_ts.strftime('%Y-%m-%d %H:%M:%S UTC')} "
            f"(Δ {delta_seconds/60.0:.1f} min)"
        )
    lines.append("")
    lines.append("## Coverage")
    lines.append("")
    if per_db_rows:
        lines.append("| staging db | status | documents |")
        lines.append("|---|---|---:|")
        for row in per_db_rows:
            doc_text = f"{row.docs:,}" if row.docs is not None else "—"
            lines.append(f"| `{row.db_name}` | {row.status} | {doc_text} |")
    else:
        lines.append("No staging DBs found.")
    lines.append("")
    lines.append(f"Scanned documents (sum across readable or last-known DBs): **{total_scanned_docs:,}**")
    lines.append("")
    lines.append("## HAVE vs NEED (targets)")
    lines.append("")

    snapshot_counts: dict[str, int] = {}
    rows_for_sort: list[ExactAuditRow] = []
    if targets is None or not targets.sources:
        lines.append("No targets config found (or it does not define `sources`).")
        lines.append("")
    else:
        lines.append("| source | HAVE | NEED | % | Δ docs | rate | count gate | metadata gate | status |")
        lines.append("|---|---:|---:|---:|---:|---:|---|---|---|")

        for source in targets.sources.values():
            scan_result = metadata_results_by_db.get(source.db) or db_scan_by_name.get(source.db)
            have = int(counts_by_db.get(source.db, 0))
            snapshot_counts[source.key] = have
            previous_row = prev_rows_by_key.get(source.key)
            prev_have = previous_row.have if previous_row is not None else prev_counts_by_key.get(source.key)
            delta_docs = (have - prev_have) if prev_have is not None else None
            rate_docs_per_hour = (
                _compute_docs_per_hour(int(delta_docs), delta_seconds)
                if delta_docs is not None
                else None
            )

            previous_metadata = previous_row.metadata if previous_row is not None else None
            metadata_gate = evaluate_metadata_gate(
                source,
                metadata_results_by_db.get(source.db).metadata if source.db in metadata_results_by_db else None,
                previous=previous_metadata,
            )
            count_gate_pass = bool(source.need is not None and source.need > 0 and have >= source.need)
            status, positive_windows, no_growth_windows, is_slow, notes = _determine_exact_status(
                source=source,
                have=have,
                need=source.need,
                delta_docs=delta_docs,
                metadata_gate=metadata_gate,
                scan_result=scan_result,
                previous_row=previous_row,
                rate_docs_per_hour=rate_docs_per_hour,
            )

            remaining = None if source.need is None else max(int(source.need) - int(have), 0)
            percent = None if source.need is None or source.need <= 0 else (have / source.need) * 100.0
            row = ExactAuditRow(
                key=source.key,
                display=source.display,
                db=source.db,
                have=have,
                need=source.need,
                percent=percent,
                delta_docs=delta_docs,
                rate_docs_per_hour=rate_docs_per_hour,
                remaining=remaining,
                count_gate_pass=count_gate_pass,
                metadata_gate_pass=metadata_gate.gate_pass,
                status=status,
                critical=source.critical,
                scan_status=scan_result.status if scan_result is not None else "missing_db",
                used_last_known_count=bool(scan_result and scan_result.used_last_known_count),
                positive_windows=positive_windows,
                no_growth_windows=no_growth_windows,
                is_slow=is_slow,
                metadata=metadata_gate,
                notes=notes,
            )
            exact_rows[source.key] = row
            rows_for_sort.append(row)

        def _row_sort(row: ExactAuditRow) -> tuple[int, int, str]:
            remaining = row.remaining or 0
            return (SOURCE_STATUS_RANK.get(row.status, 99), -remaining, row.key)

        total_need = 0
        total_have_capped = 0
        total_remaining = 0
        for row in sorted(rows_for_sort, key=_row_sort):
            if row.need is not None and row.need > 0:
                total_need += int(row.need)
                total_have_capped += min(int(row.have), int(row.need))
                total_remaining += max(int(row.need) - int(row.have), 0)
            lines.append(
                f"| {row.display} | {row.have:,} | "
                f"{'—' if row.need is None else f'{row.need:,}'} | "
                f"{_format_percent(row.have, row.need)} | "
                f"{'—' if row.delta_docs is None else f'{int(row.delta_docs):+,}'} | "
                f"{_format_rate(row.rate_docs_per_hour)} | "
                f"{_format_gate(row.count_gate_pass)} | "
                f"{_format_gate(row.metadata_gate_pass)} | "
                f"{row.status} |"
            )
        lines.append("")
        if total_need > 0:
            pct_total = (total_have_capped / total_need) * 100.0
            lines.append(
                f"TOTAL (targets): **{total_have_capped:,} / {total_need:,}** "
                f"({pct_total:.1f}%) — STILL NEEDED: **{total_remaining:,}**"
            )
        else:
            lines.append("TOTAL (targets): **0 / 0** (no numeric targets configured)")
        lines.append("")

    summary = {
        "audit_type": "exact_targets",
        "updated_at": timestamp.isoformat(),
        "rows": [row.to_json() for row in sorted(rows_for_sort, key=lambda row: row.key)],
        "totals": {
            "scanned_documents": total_scanned_docs,
            "target_have": sum(
                min(int(row.have), int(row.need))
                for row in rows_for_sort
                if row.need is not None and row.need > 0
            ),
            "target_need": sum(
                int(row.need) for row in rows_for_sort if row.need is not None and row.need > 0
            ),
            "remaining": sum(
                max(int(row.need) - int(row.have), 0)
                for row in rows_for_sort
                if row.need is not None and row.need > 0
            ),
        },
    }
    return (
        AuditArtifact(markdown="\n".join(lines) + "\n", summary=summary, snapshot_counts=snapshot_counts),
        exact_rows,
        per_db_rows,
    )


def generate_metadata_quality_audit(
    *,
    exact_rows: dict[str, ExactAuditRow],
    now: datetime | None = None,
) -> AuditArtifact:
    timestamp = now or datetime.now(UTC)
    lines: list[str] = []
    lines.append("# NyayaRAG Metadata Quality Audit")
    lines.append(f"Last updated: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    lines.append(
        "This audit enforces the auditable subset of the court-grade metadata contract "
        "on the current canonical `legal_documents` schema."
    )
    lines.append("")
    lines.append("## Current Schema Gaps")
    lines.append("")
    if CURRENT_SCHEMA_GAPS:
        for field in CURRENT_SCHEMA_GAPS:
            lines.append(
                f"- `{field}` is part of the target contract but is not yet stored on `legal_documents`."
            )
    else:
        lines.append("No unresolved schema gaps in the currently audited metadata contract.")
    lines.append("")
    lines.append("## Source Metadata Gate")
    lines.append("")
    lines.append("| source | docs | required 100% | optional >=95% | duplicate groups | gate |")
    lines.append("|---|---:|---|---|---:|---|")

    rows_json: list[dict[str, Any]] = []
    for row in sorted(exact_rows.values(), key=lambda item: item.key):
        required_text = ", ".join(
            f"{field} {row.metadata.field_ratios.get(field, 0.0) * 100:.1f}%"
            for field in row.metadata.required_fields
        ) or "—"
        optional_text = (
            ", ".join(
                f"{field} {row.metadata.field_ratios.get(field, 0.0) * 100:.1f}%"
                for field in row.metadata.optional_fields
            )
            if row.metadata.optional_fields
            else "—"
        )
        lines.append(
            f"| {row.display} | {row.have:,} | {required_text} | {optional_text} | "
            f"{row.metadata.duplicate_source_url_groups} | "
            f"{'PASS' if row.metadata.gate_pass else 'FAIL'} |"
        )
        rows_json.append(
            {
                "key": row.key,
                "display": row.display,
                "docs": row.have,
                "gate_pass": row.metadata.gate_pass,
                "required_fields": list(row.metadata.required_fields),
                "optional_fields": list(row.metadata.optional_fields),
                "field_ratios": row.metadata.field_ratios,
                "duplicate_source_url_groups": row.metadata.duplicate_source_url_groups,
                "duplicate_source_url_rows": row.metadata.duplicate_source_url_rows,
                "missing_columns": list(row.metadata.missing_columns),
                "notes": list(row.metadata.notes),
            }
        )
    lines.append("")
    summary = {
        "audit_type": "metadata_quality",
        "updated_at": timestamp.isoformat(),
        "rows": rows_json,
        "schema_gaps": list(CURRENT_SCHEMA_GAPS),
    }
    return AuditArtifact(markdown="\n".join(lines) + "\n", summary=summary)


def _family_status_from_dependencies(
    family: CourtGradeFamily,
    *,
    exact_rows: dict[str, ExactAuditRow],
    family_rows: dict[str, dict[str, Any]],
) -> tuple[str, tuple[str, ...]]:
    notes: list[str] = []
    if family.blocker_note:
        return "BLOCKED_EXTERNALLY", (family.blocker_note,)
    if family.manual_status:
        return family.manual_status, (family.notes,) if family.notes else ()
    if not family.depends_on_exact and not family.depends_on_families:
        notes.append("collector_or_registry_missing")
        if family.notes:
            notes.append(family.notes)
        return "DISCOVERING", tuple(notes)

    dependency_statuses: list[str] = []
    dependency_rows: list[ExactAuditRow] = []
    for exact_key in family.depends_on_exact:
        dependency_row = exact_rows.get(exact_key)
        if dependency_row is None:
            dependency_statuses.append("DISCOVERING")
            continue
        dependency_statuses.append(dependency_row.status)
        dependency_rows.append(dependency_row)

    for family_key in family.depends_on_families:
        other = family_rows.get(family_key)
        dependency_statuses.append(str(other.get("status", "DISCOVERING")) if other else "DISCOVERING")

    if dependency_statuses and all(status == "DONE" for status in dependency_statuses):
        return "DONE", tuple(notes)
    if dependency_statuses and all(
        status in {"DONE", "COUNT_DONE_METADATA_PENDING"} for status in dependency_statuses
    ):
        notes.append("dependency_metadata_pending")
        return "COUNT_DONE_METADATA_PENDING", tuple(notes)
    if any(status == "BROKEN" for status in dependency_statuses):
        notes.append("broken_dependency")
        return "BROKEN", tuple(notes)
    if any(status == "PATCHING" for status in dependency_statuses):
        notes.append("patching_dependency")
        return "PATCHING", tuple(notes)
    if any(status == "RUNNING_HEALTHY" for status in dependency_statuses):
        notes.append("running_dependency")
        return "RUNNING_HEALTHY", tuple(notes)
    if any(status == "COUNT_DONE_METADATA_PENDING" for status in dependency_statuses):
        notes.append("dependency_metadata_pending")
        return "COUNT_DONE_METADATA_PENDING", tuple(notes)
    notes.append("dependency_missing")
    return "DISCOVERING", tuple(notes)


def generate_court_grade_audit(
    *,
    court_grade_targets: CourtGradeTargetsConfig,
    exact_rows: dict[str, ExactAuditRow],
    now: datetime | None = None,
) -> AuditArtifact:
    timestamp = now or datetime.now(UTC)
    lines: list[str] = []
    lines.append("# NyayaRAG Court-Grade Completeness Audit")
    lines.append(f"Last updated: {timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")
    lines.append(
        "This audit measures mandatory family coverage for the public-law minimum, "
        "not raw document counts. Each family contributes `0/1` until its dependencies "
        "reach `DONE`."
    )
    lines.append("")
    lines.append("| family | layer | dependencies | gate | status |")
    lines.append("|---|---|---:|---:|---|")

    family_rows: dict[str, dict[str, Any]] = {}
    ordered_families = list(court_grade_targets.families.values())
    unresolved = set(court_grade_targets.families)
    while unresolved:
        progressed = False
        for key in list(unresolved):
            family = court_grade_targets.families[key]
            if any(dep not in family_rows for dep in family.depends_on_families):
                continue
            status, notes = _family_status_from_dependencies(
                family,
                exact_rows=exact_rows,
                family_rows=family_rows,
            )
            gate_pass = status == "DONE"
            deps_total = len(family.depends_on_exact) + len(family.depends_on_families)
            deps_done = sum(
                1
                for dep in family.depends_on_exact
                if dep in exact_rows and exact_rows[dep].status == "DONE"
            ) + sum(
                1
                for dep in family.depends_on_families
                if dep in family_rows and family_rows[dep]["status"] == "DONE"
            )
            family_rows[key] = {
                "key": family.key,
                "display": family.display,
                "layer": family.layer,
                "dependencies_total": deps_total,
                "dependencies_done": deps_done,
                "status": status,
                "gate_pass": gate_pass,
                "critical": family.critical,
                "notes": list(notes),
            }
            unresolved.remove(key)
            progressed = True
        if not progressed:
            for key in list(unresolved):
                family = court_grade_targets.families[key]
                family_rows[key] = {
                    "key": family.key,
                    "display": family.display,
                    "layer": family.layer,
                    "dependencies_total": len(family.depends_on_exact) + len(family.depends_on_families),
                    "dependencies_done": 0,
                    "status": "DISCOVERING",
                    "gate_pass": False,
                    "critical": family.critical,
                    "notes": ["dependency_cycle_or_missing_registry"],
                }
                unresolved.remove(key)

    for family in ordered_families:
        row = family_rows[family.key]
        lines.append(
            f"| {row['display']} | {row.get('layer') or '—'} | "
            f"{row['dependencies_done']}/{row['dependencies_total']} | "
            f"{1 if row['gate_pass'] else 0}/1 | {row['status']} |"
        )

    total_need = len(family_rows)
    total_have = sum(1 for row in family_rows.values() if row["gate_pass"])
    pct_total = 0.0 if total_need <= 0 else (total_have / total_need) * 100.0
    lines.append("")
    lines.append(
        f"TOTAL (court-grade families): **{total_have} / {total_need}** ({pct_total:.1f}%)"
    )
    lines.append("")
    summary = {
        "audit_type": "court_grade_families",
        "updated_at": timestamp.isoformat(),
        "rows": [family_rows[family.key] for family in ordered_families],
        "totals": {"have": total_have, "need": total_need},
    }
    return AuditArtifact(markdown="\n".join(lines) + "\n", summary=summary)
