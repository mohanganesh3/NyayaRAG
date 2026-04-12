from __future__ import annotations

import json
import logging
import re
import tarfile
import time
from dataclasses import dataclass
from datetime import UTC, date as date_value, datetime
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import boto3
import fitz
import pyarrow.parquet as pq
from pypdf import PdfReader
from botocore import UNSIGNED
from botocore.client import Config
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.ingestion.chunker import LegalAwareChunker
from app.ingestion.contracts import ExtractedMetadata, IngestionJobContext, ParsedDocument
from app.models import (
    ApprovalStatus,
    DocumentChunk,
    IngestionRun,
    IngestionRunStatus,
    LegalDocument,
    LegalDocumentType,
    SourceRegistry,
    SourceType,
    ValidityStatus,
)

LOGGER = logging.getLogger(__name__)
_PUBLIC_S3_CONFIG = Config(signature_version=UNSIGNED)
_NEUTRAL_CITATION_PATTERN = re.compile(r"\b(\d{4}\s*INSC\s*\d+)\b", re.IGNORECASE)
_REPORTER_CITATION_PATTERN = re.compile(
    r"(\(\d{4}\)\s*\d+\s*SCC\s*(?:\(Cri\)\s*)?\d+|AIR\s+\d{4}\s+SC\s+\d+|\[\d{4}\]\s+\d+\s+S\.C\.R\.\s+\d+)",
    re.IGNORECASE,
)
_CASE_NUMBER_PATTERNS = (
    re.compile(
        r"(?:Case\s+No\.?\s*:?\s*)([A-Z][A-Z .()/&-]*\d[\w./() -]*\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b((?:CIVIL|CRIMINAL|WRIT|TRANSFER|REVIEW|SPECIAL LEAVE|SLP|WP|WA|FAO|LPA|ITA|OA|CP|IA)[A-Z .()/-]*No\.?\s*[\w./()-]+\s*(?:of|/)\s*\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b([A-Z]{1,12}/\d{1,8}/\d{4})\b"),
)
_OUTCOME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bappeal\(s\)?\s+allowed\b", re.IGNORECASE), "ALLOWED"),
    (re.compile(r"\bappeal\(s\)?\s+dismissed\b", re.IGNORECASE), "DISMISSED"),
    (re.compile(r"\bwrit petition(?:s)?\s+allowed\b", re.IGNORECASE), "ALLOWED"),
    (re.compile(r"\bwrit petition(?:s)?\s+dismissed\b", re.IGNORECASE), "DISMISSED"),
    (re.compile(r"\bdisposed of\b", re.IGNORECASE), "DISPOSED"),
    (re.compile(r"\bset aside\b", re.IGNORECASE), "SET_ASIDE"),
    (re.compile(r"\bremanded\b", re.IGNORECASE), "REMANDED"),
    (re.compile(r"\bpartly allowed\b", re.IGNORECASE), "PARTLY_ALLOWED"),
    (re.compile(r"\bmodified\b", re.IGNORECASE), "MODIFIED"),
)
_SUPREME_COURT_PRIORITY = ("Supreme Court of India",)
_HIGH_COURT_PRIORITY = (
    "High Court of Delhi",
    "Bombay High Court",
    "Madras High Court",
    "Calcutta High Court",
    "Allahabad High Court",
    "High Court of Karnataka",
)


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_key: str
    display_name: str
    source_type: SourceType
    base_url: str
    canonical_hostname: str
    jurisdiction_scope: list[str]
    update_frequency: str
    access_method: str
    parser_version: str
    notes: str


@dataclass(frozen=True, slots=True)
class ArchiveDescriptor:
    source_family: str
    source_key: str
    year: int
    bucket: str
    archive_key: str
    index_key: str
    metadata_key: str
    local_dir: Path
    court_name: str
    language: str = "english"
    court_code: str | None = None
    bench: str | None = None


@dataclass(frozen=True, slots=True)
class HighCourtCatalogEntry:
    court_code: str
    court_name: str
    sample_bench: str


@dataclass(slots=True)
class BulkRunStats:
    """Execution stats for a single bulk-archive scan.

    Notes:
    - `seen_pdfs` counts PDF members encountered in the tar (even if skipped).
    - `discovered` counts PDFs that had a metadata row (or a synthesized fallback row).
    """

    seen_pdfs: int = 0
    discovered: int = 0
    processed: int = 0
    skipped_existing: int = 0
    failed_text: int = 0
    failed_metadata: int = 0


@dataclass(frozen=True, slots=True)
class ParsedJudgmentRecord:
    source_document_ref: str
    source_url: str
    title: str
    court: str
    decision_date: date_value | None
    citation: str | None
    neutral_citation: str | None
    case_number: str | None
    bench: list[str]
    parties: dict[str, str]
    disposition: str | None
    practice_areas: list[str]
    full_text: str
    checksum: str
    language: str
    fetched_at: datetime
    metadata: dict[str, Any]


SOURCE_DEFINITIONS = {
    "supreme_court_aws_bulk": SourceDefinition(
        source_key="supreme_court_aws_bulk",
        display_name="Supreme Court of India AWS Bulk Dataset",
        source_type=SourceType.COURT_PORTAL,
        base_url="https://registry.opendata.aws/indian-supreme-court-judgments/",
        canonical_hostname="registry.opendata.aws",
        jurisdiction_scope=["All India"],
        update_frequency="bi-monthly",
        access_method="aws_s3_public_bulk",
        parser_version="aws-bulk-judgment-v1",
        notes="Public S3 dataset managed by Dattam Labs and listed in the AWS Open Data Registry.",
    ),
    "high_court_aws_bulk": SourceDefinition(
        source_key="high_court_aws_bulk",
        display_name="Indian High Courts AWS Bulk Dataset",
        source_type=SourceType.COURT_PORTAL,
        base_url="https://registry.opendata.aws/indian-high-court-judgments/",
        canonical_hostname="registry.opendata.aws",
        jurisdiction_scope=["India"],
        update_frequency="quarterly",
        access_method="aws_s3_public_bulk",
        parser_version="aws-bulk-judgment-v1",
        notes="Public S3 dataset managed by Dattam Labs and listed in the AWS Open Data Registry.",
    ),
}


class PublicS3Client:
    def __init__(self, *, region_name: str = "ap-south-1") -> None:
        self._client = boto3.client(
            "s3",
            region_name=region_name,
            config=_PUBLIC_S3_CONFIG,
        )

    def list_common_prefixes(self, bucket: str, prefix: str) -> list[str]:
        prefixes: list[str] = []
        continuation_token: str | None = None
        while True:
            kwargs: dict[str, object] = {
                "Bucket": bucket,
                "Prefix": prefix,
                "Delimiter": "/",
            }
            if continuation_token is not None:
                kwargs["ContinuationToken"] = continuation_token
            response = self._client.list_objects_v2(**kwargs)
            prefixes.extend(entry["Prefix"] for entry in response.get("CommonPrefixes", []))
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")
        return prefixes

    def list_objects(self, bucket: str, prefix: str, *, suffix: str | None = None) -> list[str]:
        keys: list[str] = []
        continuation_token: str | None = None
        while True:
            kwargs: dict[str, object] = {
                "Bucket": bucket,
                "Prefix": prefix,
            }
            if continuation_token is not None:
                kwargs["ContinuationToken"] = continuation_token
            response = self._client.list_objects_v2(**kwargs)
            for entry in response.get("Contents", []):
                key = entry["Key"]
                if suffix is None or key.endswith(suffix):
                    keys.append(key)
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")
        return keys

    def download(self, bucket: str, key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.stat().st_size > 0:
            return destination
        self._client.download_file(bucket, key, str(destination))
        return destination


class AwsBulkCollector:
    def __init__(
        self,
        session: Session,
        *,
        database_label: str,
        raw_root: Path,
        commit_every: int = 25,
        commit_interval_seconds: float = 30.0,
        build_chunks: bool = True,
    ) -> None:
        self.session = session
        self.database_label = database_label
        self.raw_root = raw_root
        self.s3 = PublicS3Client()
        self.chunker = LegalAwareChunker()
        self.commit_every = max(int(commit_every), 1)
        self.commit_interval_seconds = max(float(commit_interval_seconds), 1.0)
        self.build_chunks = bool(build_chunks)

    def _commit_with_retry(self, *, attempts: int = 8, base_sleep_seconds: float = 1.0) -> None:
        """Commit with retries to tolerate transient SQLite write locks.

        Long-running collectors may overlap with other writers (e.g. merger job).
        When SQLite is temporarily busy/locked, SQLAlchemy raises OperationalError
        and the Session must be rolled back before reuse.
        """

        for attempt in range(1, attempts + 1):
            try:
                self.session.commit()
                return
            except OperationalError as exc:
                # Always rollback before continuing to use the Session.
                self.session.rollback()

                msg = str(exc).lower()
                is_lock = "database is locked" in msg or "database table is locked" in msg or "sqlite" in msg
                if not is_lock or attempt == attempts:
                    raise

                sleep_seconds = base_sleep_seconds * (2 ** (attempt - 1))
                sleep_seconds = min(sleep_seconds, 60.0)
                LOGGER.warning(
                    "SQLite lock during commit; retrying in %.1fs (attempt %s/%s)",
                    sleep_seconds,
                    attempt,
                    attempts,
                )
                time.sleep(sleep_seconds)

    def _flush_with_retry(self, *, attempts: int = 8, base_sleep_seconds: float = 1.0) -> None:
        """Flush pending ORM changes, retrying on common SQLite lock errors.

        Some ingestion paths explicitly call Session.flush(); when SQLite is
        temporarily locked by another writer, flush can raise OperationalError.
        Without retries, long-running collectors crash.
        """

        for attempt in range(1, attempts + 1):
            try:
                self.session.flush()
                return
            except OperationalError as exc:
                # Always rollback before continuing to use the Session.
                self.session.rollback()

                msg = str(exc).lower()
                is_lock = (
                    "database is locked" in msg
                    or "database table is locked" in msg
                    or "database schema is locked" in msg
                    or "database is busy" in msg
                    or "busy" in msg
                    or "locked" in msg
                )
                if not is_lock or attempt == attempts:
                    raise

                sleep_seconds = base_sleep_seconds * (2 ** (attempt - 1))
                sleep_seconds = min(sleep_seconds, 60.0)
                LOGGER.warning(
                    "SQLite lock during flush; retrying in %.1fs (attempt %s/%s)",
                    sleep_seconds,
                    attempt,
                    attempts,
                )
                time.sleep(sleep_seconds)

    def discover_supreme_court_archives(
        self,
        *,
        include_regional: bool = False,
        years: list[int] | None = None,
    ) -> list[ArchiveDescriptor]:
        bucket = "indian-supreme-court-judgments"
        year_prefixes = self.s3.list_common_prefixes(bucket, "metadata/parquet/")
        discovered_years = sorted(
            {
                int(prefix.rstrip("/").split("year=")[1])
                for prefix in year_prefixes
                if "year=" in prefix
            },
            reverse=True,
        )
        if years is not None:
            wanted = set(years)
            discovered_years = [year for year in discovered_years if year in wanted]

        archive_types = ["english", "regional"] if include_regional else ["english"]
        descriptors: list[ArchiveDescriptor] = []
        for year in discovered_years:
            metadata_key = f"metadata/parquet/year={year}/metadata.parquet"
            for archive_type in archive_types:
                base_prefix = f"data/tar/year={year}/{archive_type}/"
                archive_keys = self.s3.list_objects(bucket, base_prefix, suffix=".tar")
                index_keys = self.s3.list_objects(bucket, base_prefix, suffix=".index.json")
                if not archive_keys or not index_keys:
                    continue
                descriptors.append(
                    ArchiveDescriptor(
                        source_family="supreme_court",
                        source_key="supreme_court_aws_bulk",
                        year=year,
                        bucket=bucket,
                        archive_key=archive_keys[0],
                        index_key=index_keys[0],
                        metadata_key=metadata_key,
                        local_dir=self.raw_root / "supreme_court_aws" / f"year={year}" / archive_type,
                        court_name="Supreme Court of India",
                        language=archive_type,
                    )
                )
        return descriptors

    def discover_high_court_catalog(self, *, sample_year: int | None = None) -> list[HighCourtCatalogEntry]:
        bucket = "indian-high-court-judgments"
        available_years = self.list_high_court_years()
        if not available_years:
            return []
        sample_year = sample_year or available_years[0]
        prefixes = self.s3.list_common_prefixes(
            bucket,
            f"metadata/parquet/year={sample_year}/",
        )
        catalog: list[HighCourtCatalogEntry] = []
        for prefix in prefixes:
            parquet_keys = self.s3.list_objects(bucket, prefix, suffix=".parquet")
            if not parquet_keys:
                continue
            parquet_key = parquet_keys[0]
            with TemporaryDirectory() as temp_dir:
                parquet_path = self.s3.download(
                    bucket,
                    parquet_key,
                    Path(temp_dir) / "metadata.parquet",
                )
                table = pq.read_table(parquet_path, columns=["court"])
                court_name = (
                    table.column("court")[0].as_py()
                    if table.num_rows
                    else prefix.rstrip("/").split("/")[-1]
                )
            court_code = prefix.rstrip("/").split("/")[-1].split("=", 1)[1]
            bench = parquet_key.split("/")[-2].split("=", 1)[1]
            catalog.append(
                HighCourtCatalogEntry(
                    court_code=court_code,
                    court_name=str(court_name),
                    sample_bench=bench,
                )
            )
        return sorted(catalog, key=lambda entry: entry.court_name.lower())

    def list_high_court_years(self) -> list[int]:
        bucket = "indian-high-court-judgments"
        prefixes = self.s3.list_common_prefixes(bucket, "data/tar/")
        return sorted(
            {
                int(prefix.rstrip("/").split("year=")[1])
                for prefix in prefixes
                if "year=" in prefix
            },
            reverse=True,
        )

    def discover_high_court_archives(
        self,
        *,
        years: list[int] | None = None,
        court_names: list[str] | None = None,
        court_codes: list[str] | None = None,
    ) -> list[ArchiveDescriptor]:
        bucket = "indian-high-court-judgments"
        catalog = {entry.court_code: entry for entry in self.discover_high_court_catalog()}
        available_years = self.list_high_court_years()
        if years is not None:
            allowed_years = set(years)
            available_years = [year for year in available_years if year in allowed_years]

        filtered_names = {_normalize_name(name) for name in court_names or []}
        filtered_codes = set(court_codes or [])
        descriptors: list[ArchiveDescriptor] = []
        for year in available_years:
            court_prefixes = self.s3.list_common_prefixes(
                bucket,
                f"data/tar/year={year}/",
            )
            for court_prefix in court_prefixes:
                court_code = court_prefix.rstrip("/").split("/")[-1].split("=", 1)[1]
                catalog_entry = catalog.get(court_code)
                court_name = catalog_entry.court_name if catalog_entry is not None else court_code
                if filtered_codes and court_code not in filtered_codes:
                    continue
                if filtered_names and _normalize_name(court_name) not in filtered_names:
                    continue

                bench_prefixes = self.s3.list_common_prefixes(bucket, court_prefix)
                for bench_prefix in bench_prefixes:
                    bench = bench_prefix.rstrip("/").split("/")[-1].split("=", 1)[1]
                    archive_keys = self.s3.list_objects(bucket, bench_prefix, suffix=".tar")
                    index_keys = self.s3.list_objects(bucket, bench_prefix, suffix=".index.json")
                    metadata_prefix = (
                        f"metadata/parquet/year={year}/court={court_code}/bench={bench}/"
                    )
                    parquet_keys = self.s3.list_objects(bucket, metadata_prefix, suffix=".parquet")
                    if not archive_keys or not index_keys or not parquet_keys:
                        continue
                    descriptors.append(
                        ArchiveDescriptor(
                            source_family="high_court",
                            source_key="high_court_aws_bulk",
                            year=year,
                            bucket=bucket,
                            archive_key=archive_keys[0],
                            index_key=index_keys[0],
                            metadata_key=parquet_keys[0],
                            local_dir=(
                                self.raw_root
                                / "high_courts_aws"
                                / _slugify(court_name)
                                / f"year={year}"
                                / f"bench={bench}"
                            ),
                            court_name=court_name,
                            court_code=court_code,
                            bench=bench,
                        )
                    )
        return descriptors

    def collect_archives(
        self,
        descriptors: list[ArchiveDescriptor],
        *,
        limit_documents: int | None = None,
        source_snapshot_url: str,
    ) -> BulkRunStats:
        if not descriptors:
            return BulkRunStats()

        source_key = descriptors[0].source_key
        source_definition = SOURCE_DEFINITIONS[source_key]
        Base.metadata.create_all(self.session.get_bind())
        registry = self._ensure_source_registry(source_definition)
        ingestion_run = IngestionRun(
            source_registry=registry,
            status=IngestionRunStatus.RUNNING,
            parser_version=source_definition.parser_version,
            triggered_by=self.database_label,
            started_at=datetime.now(UTC),
            checksum_algorithm="sha256",
            source_snapshot_url=source_snapshot_url,
            approval_status=ApprovalStatus.APPROVED,
        )
        self.session.add(ingestion_run)
        self._flush_with_retry()

        stats = BulkRunStats()
        try:
            for descriptor in descriptors:
                if limit_documents is not None and stats.processed >= limit_documents:
                    break
                stats = self._collect_single_archive(
                    descriptor,
                    ingestion_run=ingestion_run,
                    stats=stats,
                    limit_documents=limit_documents,
                )

            ingestion_run.status = IngestionRunStatus.SUCCEEDED
            ingestion_run.completed_at = datetime.now(UTC)
            ingestion_run.document_count = stats.discovered
            ingestion_run.new_document_count = stats.processed
            ingestion_run.updated_document_count = 0
            ingestion_run.failed_document_count = stats.failed_text + stats.failed_metadata
            self._commit_with_retry()
            return stats
        except Exception as exc:
            # If the failure happened during flush/commit, the Session may be in an
            # invalid state until rollback() is called.
            self.session.rollback()
            ingestion_run.status = IngestionRunStatus.FAILED
            ingestion_run.error_summary = str(exc)
            ingestion_run.completed_at = datetime.now(UTC)
            self.session.add(ingestion_run)
            self._commit_with_retry()
            raise

    def _collect_single_archive(
        self,
        descriptor: ArchiveDescriptor,
        *,
        ingestion_run: IngestionRun,
        stats: BulkRunStats,
        limit_documents: int | None,
    ) -> BulkRunStats:
        descriptor.local_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = self.s3.download(
            descriptor.bucket,
            descriptor.metadata_key,
            descriptor.local_dir / Path(descriptor.metadata_key).name,
        )
        index_path = self.s3.download(
            descriptor.bucket,
            descriptor.index_key,
            descriptor.local_dir / Path(descriptor.index_key).name,
        )

        metadata_rows = self._load_metadata_rows(descriptor, metadata_path)
        row_lookup = self._build_row_lookup(descriptor, metadata_rows)
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))

        # The upstream datasets may split a year/court into multiple tar parts
        # (e.g., english.tar + part-*.tar). The part list is captured in the
        # index file. We must iterate every part to avoid silently missing data.
        archive_prefix = str(Path(descriptor.archive_key).parent).rstrip("/")
        part_names = _index_part_names(index_payload)
        if not part_names:
            part_names = [Path(descriptor.archive_key).name]

        last_progress_log = time.time()
        last_commit_time = time.time()
        last_committed_processed = stats.processed

        for part_name in part_names:
            if limit_documents is not None and stats.processed >= limit_documents:
                break
            archive_key = f"{archive_prefix}/{part_name}"
            archive_path = self.s3.download(
                descriptor.bucket,
                archive_key,
                descriptor.local_dir / part_name,
            )

            LOGGER.info(
                "Processing %s year=%s archive=%s",
                descriptor.court_name,
                descriptor.year,
                archive_path.name,
            )

            with tarfile.open(archive_path, "r") as archive:
                for member in archive:
                    if limit_documents is not None and stats.processed >= limit_documents:
                        break
                    if not member.isfile() or not member.name.lower().endswith(".pdf"):
                        continue

                    stats.seen_pdfs += 1

                    now = time.time()
                    # Periodic progress logging for long-running tar scans.
                    # Log even if `processed` remains 0 (e.g., when everything is skipped
                    # as existing or metadata lookups fail).
                    if (now - last_progress_log) >= 60.0:
                        LOGGER.info(
                            "Progress %s year=%s: seen_pdfs=%s discovered=%s processed=%s skipped_existing=%s failed_text=%s failed_metadata=%s",
                            descriptor.court_name,
                            descriptor.year,
                            stats.seen_pdfs,
                            stats.discovered,
                            stats.processed,
                            stats.skipped_existing,
                            stats.failed_text,
                            stats.failed_metadata,
                        )
                        last_progress_log = now

                    member_name = Path(member.name).name
                    if descriptor.source_family == "supreme_court":
                        row = None
                        for candidate in _supreme_court_lookup_keys(member_name):
                            row = row_lookup.get(candidate)
                            if row is not None:
                                break
                    else:
                        row = row_lookup.get(member_name) or row_lookup.get(_member_stem(member_name))
                    if row is None:
                        # The upstream parquet metadata can lag the tar archives or use
                        # slightly different naming. Prefer ingesting with a synthesized
                        # row rather than silently skipping PDFs forever.
                        stats.failed_metadata += 1
                        row = {
                            "title": f"{descriptor.court_name} {descriptor.year} {member_name}",
                            "court": descriptor.court_name,
                            "path": _member_stem(member_name),
                        }

                    stats.discovered += 1
                    source_document_ref = _source_document_ref(descriptor, row, member_name)
                    if self._document_exists(descriptor.source_key, source_document_ref):
                        stats.skipped_existing += 1
                        continue

                    extracted = archive.extractfile(member)
                    if extracted is None:
                        stats.failed_text += 1
                        continue
                    pdf_bytes = extracted.read()
                    record = self._parse_record(
                        descriptor,
                        archive_key=archive_key,
                        member_name=member_name,
                        pdf_bytes=pdf_bytes,
                        row=row,
                    )
                    if record is None:
                        stats.failed_text += 1
                        continue

                    self._upsert_record(
                        ingestion_run=ingestion_run,
                        source_key=descriptor.source_key,
                        parser_version=SOURCE_DEFINITIONS[descriptor.source_key].parser_version,
                        record=record,
                    )
                    stats.processed += 1

                    now = time.time()
                    # Commit frequently so external COUNT(*) checks reflect real progress.
                    if stats.processed % self.commit_every == 0:
                        self._commit_with_retry()
                        last_commit_time = now
                        last_committed_processed = stats.processed
                    elif (
                        stats.processed > last_committed_processed
                        and (now - last_commit_time) >= self.commit_interval_seconds
                    ):
                        self._commit_with_retry()
                        last_commit_time = now
                        last_committed_processed = stats.processed

        self._commit_with_retry()

        index_copy = descriptor.local_dir / "archive.index.summary.json"
        if not index_copy.exists():
            index_copy.write_text(json.dumps(index_payload, indent=2), encoding="utf-8")
        return stats

    def _load_metadata_rows(
        self,
        descriptor: ArchiveDescriptor,
        metadata_path: Path,
    ) -> list[dict[str, Any]]:
        if descriptor.source_family == "supreme_court":
            columns = [
                "title",
                "petitioner",
                "respondent",
                "judge",
                "citation",
                "case_id",
                "cnr",
                "decision_date",
                "disposal_nature",
                "court",
                "path",
                "nc_display",
                "available_languages",
            ]
        else:
            columns = [
                "court_code",
                "title",
                "description",
                "judge",
                "pdf_link",
                "cnr",
                "date_of_registration",
                "decision_date",
                "disposal_nature",
                "court",
                "pdf_exists",
            ]
        return pq.ParquetFile(metadata_path).read(columns=columns).to_pylist()

    def _build_row_lookup(
        self,
        descriptor: ArchiveDescriptor,
        rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        lookup: dict[str, dict[str, Any]] = {}
        if descriptor.source_family == "supreme_court":
            for row in rows:
                path = str(row.get("path") or "").strip()
                if not path:
                    continue
                for candidate in _supreme_court_lookup_keys(path):
                    lookup[candidate] = row
        else:
            for row in rows:
                pdf_link = str(row.get("pdf_link") or "").strip()
                if not pdf_link:
                    continue
                name = Path(pdf_link).name
                lookup[name] = row
                lookup[_member_stem(name)] = row
        return lookup

    def _parse_record(
        self,
        descriptor: ArchiveDescriptor,
        *,
        archive_key: str,
        member_name: str,
        pdf_bytes: bytes,
        row: dict[str, Any],
    ) -> ParsedJudgmentRecord | None:
        text = _extract_pdf_text(pdf_bytes)
        if len(text.strip()) < 100:
            # Many upstream "PDF" files are image-only or partially corrupted.
            # When we cannot extract enough text from bytes, fall back to rich
            # metadata fields so we can still ingest the record (and later
            # backfill full text via improved extraction/OCR).
            title_fallback = _coerce_text(row.get("title"))
            description_fallback = _coerce_text(row.get("description"))
            pdf_link_fallback = _coerce_text(row.get("pdf_link"))
            meta_text = "\n".join(
                part
                for part in (
                    title_fallback,
                    description_fallback,
                    pdf_link_fallback,
                )
                if part
            ).strip()
            if len(meta_text) >= 100:
                text = meta_text
            else:
                # Some upstream archives contain corrupt/non-PDF bytes (often HTML error pages)
                # and sparse metadata. We still ingest a minimal document so the corpus isn't
                # silently stalled at ZERO/STOPPED.
                safe_row: dict[str, Any] = {}
                for key, value in row.items():
                    if value is None:
                        continue
                    # Avoid extremely large/verbose fields.
                    if key.lower() in {"raw_html", "full_text", "text"}:
                        continue
                    coerced = _coerce_text(value)
                    if coerced is not None:
                        safe_row[str(key)] = coerced[:2000]

                synthesized = {
                    "source_family": descriptor.source_family,
                    "court": descriptor.court_name,
                    "year": descriptor.year,
                    "archive_key": archive_key,
                    "member": member_name,
                    "metadata": safe_row,
                }
                text = (
                    "[PDF_TEXT_UNAVAILABLE]\n"
                    + json.dumps(synthesized, ensure_ascii=False, sort_keys=True)
                )

        title = _coerce_text(row.get("title")) or _derive_title_from_text(text, descriptor.court_name)
        citation = _coerce_text(row.get("citation")) or _first_match(_REPORTER_CITATION_PATTERN, text)
        neutral_citation = _normalize_neutral_citation(
            _coerce_text(row.get("case_id"))
            or _coerce_text(row.get("nc_display"))
            or _first_match(_NEUTRAL_CITATION_PATTERN, text)
        )
        case_number = _extract_case_number(row, text, member_name)
        bench = _extract_bench(row, text)
        parties = _extract_parties(row, title)
        decision_date = _parse_date(row.get("decision_date"))
        disposition = _extract_outcome(row, text)
        practice_areas = _practice_areas_for_court(descriptor.court_name, text)
        source_document_ref = _source_document_ref(descriptor, row, member_name)
        source_url = f"s3://{descriptor.bucket}/{archive_key}#{member_name}"

        return ParsedJudgmentRecord(
            source_document_ref=source_document_ref,
            source_url=source_url,
            title=title,
            court=descriptor.court_name,
            decision_date=decision_date,
            citation=citation,
            neutral_citation=neutral_citation,
            case_number=case_number,
            bench=bench,
            parties=parties,
            disposition=disposition,
            practice_areas=practice_areas,
            full_text=text,
            checksum=sha256(pdf_bytes).hexdigest(),
            language="en" if descriptor.language == "english" else descriptor.language,
            fetched_at=datetime.now(UTC),
            metadata={
                "year": descriptor.year,
                "court_code": descriptor.court_code,
                "bench": descriptor.bench,
                "archive_key": archive_key,
                "member_name": member_name,
                "case_number": case_number,
                "raw_metadata": row,
            },
        )

    def _document_exists(self, source_key: str, source_document_ref: str) -> bool:
        doc_id = _doc_id(source_key, source_document_ref)
        return self.session.get(LegalDocument, doc_id) is not None

    def _upsert_record(
        self,
        *,
        ingestion_run: IngestionRun,
        source_key: str,
        parser_version: str,
        record: ParsedJudgmentRecord,
    ) -> None:
        doc_id = _doc_id(source_key, record.source_document_ref)
        document = self.session.get(LegalDocument, doc_id)
        if document is None:
            document = LegalDocument(
                doc_id=doc_id,
                doc_type=LegalDocumentType.JUDGMENT,
            )
            self.session.add(document)
            self._flush_with_retry()

        document.doc_type = LegalDocumentType.JUDGMENT
        document.court = record.court
        document.bench = record.bench
        document.coram = len(record.bench) or None
        document.date = record.decision_date
        document.citation = record.citation
        document.neutral_citation = record.neutral_citation
        document.parties = record.parties
        document.jurisdiction_binding = _binding_for_court(record.court)
        document.jurisdiction_persuasive = []
        document.current_validity = ValidityStatus.GOOD_LAW
        document.distinguished_by = []
        document.followed_by = []
        document.statutes_interpreted = []
        document.statutes_applied = []
        document.citations_made = _extract_citations(record.full_text)
        primary_identifier = (
            record.case_number
            or record.neutral_citation
            or record.citation
            or record.source_document_ref
        )
        document.headnotes = [primary_identifier] if primary_identifier else []
        document.ratio_decidendi = None
        document.obiter_dicta = []
        document.practice_areas = record.practice_areas
        document.language = record.language
        document.full_text = record.full_text
        document.source_system = source_key
        document.source_url = record.source_url
        document.source_document_ref = record.source_document_ref
        document.fetched_at = record.fetched_at
        document.checksum = record.checksum
        document.parser_version = parser_version
        document.ingestion_run = ingestion_run
        document.approval_status = ApprovalStatus.APPROVED
        document.projection_stale = False
        document.stale_reason = None

        if self.build_chunks:
            document.chunks.clear()
            for chunk in self._build_chunks(source_key, parser_version, record, doc_id):
                document.chunks.append(chunk)

        self._flush_with_retry()

    def _build_chunks(
        self,
        source_key: str,
        parser_version: str,
        record: ParsedJudgmentRecord,
        doc_id: str,
    ) -> list[DocumentChunk]:
        paragraphs = _paragraphs(record.full_text)
        parsed = ParsedDocument(
            title=record.title,
            body_text=record.full_text,
            paragraphs=paragraphs,
            section_headers=[],
            source_document_ref=record.source_document_ref,
            attributes={},
        )
        metadata = ExtractedMetadata(
            doc_type=LegalDocumentType.JUDGMENT,
            court=record.court,
            date_text=record.decision_date.isoformat() if record.decision_date else None,
            citation=record.citation,
            neutral_citation=record.neutral_citation,
            bench=record.bench,
            parties=record.parties,
            language=record.language,
            source_document_ref=record.source_document_ref,
            attributes={
                "jurisdiction_binding": _binding_for_court(record.court),
                "jurisdiction_persuasive": [],
                "practice_areas": record.practice_areas,
                "case_number": record.case_number,
            },
        )
        context = IngestionJobContext(
            source_key=source_key,
            source_url=record.source_url,
            parser_version=parser_version,
            external_id=record.source_document_ref,
            metadata={},
        )
        chunk_drafts = self.chunker.chunk(parsed, metadata, context)
        total_chunks = len(chunk_drafts)
        return [
            DocumentChunk(
                chunk_id=str(uuid4()),
                doc_id=doc_id,
                doc_type=LegalDocumentType.JUDGMENT,
                text=chunk.text,
                text_normalized=chunk.text.lower(),
                chunk_index=index,
                total_chunks=total_chunks,
                section_header=chunk.section_header,
                court=record.court,
                date=record.decision_date,
                citation=record.citation or record.neutral_citation,
                jurisdiction_binding=_binding_for_court(record.court),
                jurisdiction_persuasive=[],
                current_validity=ValidityStatus.GOOD_LAW,
                practice_area=record.practice_areas,
                needs_reembedding=False,
                projection_stale=False,
            )
            for index, chunk in enumerate(chunk_drafts)
        ]

    def _ensure_source_registry(self, definition: SourceDefinition) -> SourceRegistry:
        registry = self.session.get(SourceRegistry, definition.source_key)
        if registry is None:
            registry = SourceRegistry(
                source_key=definition.source_key,
                display_name=definition.display_name,
                source_type=definition.source_type,
                base_url=definition.base_url,
                canonical_hostname=definition.canonical_hostname,
                jurisdiction_scope=definition.jurisdiction_scope,
                update_frequency=definition.update_frequency,
                access_method=definition.access_method,
                is_public=True,
                is_active=True,
                approval_status=ApprovalStatus.APPROVED,
                default_parser_version=definition.parser_version,
                notes=definition.notes,
            )
            self.session.add(registry)
            self._flush_with_retry()
            return registry

        registry.display_name = definition.display_name
        registry.base_url = definition.base_url
        registry.canonical_hostname = definition.canonical_hostname
        registry.jurisdiction_scope = definition.jurisdiction_scope
        registry.update_frequency = definition.update_frequency
        registry.access_method = definition.access_method
        registry.default_parser_version = definition.parser_version
        registry.approval_status = ApprovalStatus.APPROVED
        registry.notes = definition.notes
        return registry


def select_priority_high_courts(catalog: list[HighCourtCatalogEntry]) -> list[HighCourtCatalogEntry]:
    wanted = {_normalize_name(name) for name in _HIGH_COURT_PRIORITY}
    return [
        entry
        for entry in catalog
        if _normalize_name(entry.court_name) in wanted
    ]


def summarize_high_court_catalog(catalog: list[HighCourtCatalogEntry]) -> list[dict[str, str]]:
    return [
        {
            "court_code": entry.court_code,
            "court_name": entry.court_name,
            "sample_bench": entry.sample_bench,
        }
        for entry in catalog
    ]


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    text = ""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            text_parts = [page.get_text("text") for page in document]
        text = "\n".join(part for part in text_parts if part).strip()
    except Exception as exc:  # pragma: no cover
        # Some upstream archives contain corrupted PDFs. We'll try a secondary
        # parser before giving up.
        LOGGER.warning("Failed to extract PDF text (pymupdf); will try fallback: %s", exc)

    # Fallback extraction via pypdf often succeeds where pymupdf fails.
    if len(text.strip()) < 100:
        try:
            from io import BytesIO

            reader = PdfReader(BytesIO(pdf_bytes))
            parts: list[str] = []
            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    parts.append(page_text)
            fallback_text = "\n".join(parts).strip()
            if len(fallback_text) > len(text):
                text = fallback_text
        except Exception as exc:  # pragma: no cover
            LOGGER.warning("Failed to extract PDF text (pypdf fallback): %s", exc)

    return text.strip()


def _derive_title_from_text(text: str, court_name: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:20]:
        if len(line.split()) >= 4 and court_name.lower() not in line.lower():
            return line
    return lines[0] if lines else court_name


def _paragraphs(text: str) -> list[str]:
    chunks = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if chunks:
        return chunks
    return [line.strip() for line in text.splitlines() if line.strip()]


def _coerce_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_neutral_citation(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", value.replace("INSC", " INSC ")).strip()
    match = _NEUTRAL_CITATION_PATTERN.search(normalized)
    if match is None:
        return value
    return re.sub(r"\s+", " ", match.group(1)).upper()


def _extract_case_number(row: dict[str, Any], text: str, member_name: str) -> str | None:
    candidates = [
        _coerce_text(row.get("raw_html")),
        _coerce_text(row.get("title")),
        text[:3000],
        member_name,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        for pattern in _CASE_NUMBER_PATTERNS:
            match = pattern.search(candidate)
            if match is not None:
                return re.sub(r"\s+", " ", match.group(1)).strip(" :-|")
    return None


def _extract_bench(row: dict[str, Any], text: str) -> list[str]:
    judge_text = _coerce_text(row.get("judge"))
    if judge_text:
        judges = [part.strip() for part in re.split(r"[,;]| and ", judge_text) if part.strip()]
        if judges:
            return judges
    coram_match = re.search(r"(?:Coram|Bench)\s*:?\s*([^\n]+)", text[:2000], re.IGNORECASE)
    if coram_match:
        return [
            part.strip()
            for part in re.split(r",| and ", coram_match.group(1))
            if part.strip()
        ]
    return []


def _extract_parties(row: dict[str, Any], title: str) -> dict[str, str]:
    petitioner = _coerce_text(row.get("petitioner"))
    respondent = _coerce_text(row.get("respondent"))
    if petitioner or respondent:
        parties: dict[str, str] = {}
        if petitioner:
            parties["petitioner"] = petitioner
        if respondent:
            parties["respondent"] = respondent
        return parties

    clean_title = re.sub(r"\b(?:WP|WA|LPA|ITA|CP|IA|OA|CIVIL APPEAL|CRIMINAL APPEAL)[^A-Za-z]+", "", title, count=1, flags=re.IGNORECASE).strip()
    for separator in (" versus ", " Vs ", " VS ", " vs ", " v. ", " VERSUS "):
        if separator in clean_title:
            left, right = clean_title.split(separator, 1)
            return {
                "petitioner": left.strip(" -"),
                "respondent": right.strip(" -"),
            }
    return {}


def _parse_date(value: object | None) -> date_value | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_value):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _extract_outcome(row: dict[str, Any], text: str) -> str | None:
    disposition = _coerce_text(row.get("disposal_nature"))
    if disposition:
        return disposition
    tail = text[-4000:]
    for pattern, label in _OUTCOME_PATTERNS:
        if pattern.search(tail):
            return label
    return None


def _extract_citations(text: str) -> list[str]:
    citations = {
        re.sub(r"\s+", " ", match.group(1)).strip()
        for match in _REPORTER_CITATION_PATTERN.finditer(text)
    }
    neutral = {
        _normalize_neutral_citation(match.group(1))
        for match in _NEUTRAL_CITATION_PATTERN.finditer(text)
    }
    return sorted(citation for citation in citations.union(neutral) if citation)


def _practice_areas_for_court(court_name: str, text: str) -> list[str]:
    lowered = f"{court_name}\n{text[:4000]}".lower()
    areas: list[str] = []
    if "tax" in lowered or "assessment" in lowered:
        areas.append("tax")
    if "environment" in lowered or "forest" in lowered:
        areas.append("environment")
    if "company" in lowered or "insolvency" in lowered:
        areas.append("corporate")
    if "constitution" in lowered or "article " in lowered:
        areas.append("constitutional")
    if "bail" in lowered or "criminal" in lowered or "convict" in lowered:
        areas.append("criminal")
    if "arbitration" in lowered or "contract" in lowered or "civil" in lowered:
        areas.append("civil")
    if not areas:
        if "supreme court" in court_name.lower():
            areas = ["constitutional", "civil", "criminal"]
        else:
            areas = ["civil", "criminal"]
    return list(dict.fromkeys(areas))


def _index_part_names(payload: dict[str, Any]) -> list[str]:
    """Return ordered tar part names from an index.json payload.

    Both datasets can split archives into multiple parts. The canonical V2 shape
    uses a top-level `parts` list, each with a `name`.
    """
    parts = payload.get("parts")
    if not isinstance(parts, list):
        return []
    names: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        name = part.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    # Preserve declared ordering but ensure uniqueness.
    return list(dict.fromkeys(names))


def _source_document_ref(
    descriptor: ArchiveDescriptor,
    row: dict[str, Any],
    member_name: str,
) -> str:
    if descriptor.source_family == "supreme_court":
        lang_suffix = _supreme_court_language_suffix(member_name)
        # Preserve non-English/regional variants as distinct documents instead
        # of collapsing them onto the English row when sidecar metadata matches.
        if lang_suffix and lang_suffix != "EN":
            return Path(member_name).stem

    for candidate in (
        _coerce_text(row.get("cnr")),
        _coerce_text(row.get("case_id")),
        _coerce_text(row.get("path")),
        _supreme_court_base_stem(member_name) if descriptor.source_family == "supreme_court" else _member_stem(member_name),
    ):
        if candidate:
            return candidate
    return member_name


def _binding_for_court(court_name: str) -> list[str]:
    lowered = court_name.lower()
    if "supreme court" in lowered:
        return ["All India"]
    return [court_name]


def _doc_id(source_key: str, source_document_ref: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{source_key}|{source_document_ref}"))


def _member_stem(member_name: str) -> str:
    stem = Path(member_name).stem
    for suffix in ("_EN", "_RG"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _supreme_court_base_stem(value: str) -> str:
    stem = Path(value).stem
    lang_suffix = _supreme_court_language_suffix(value)
    if lang_suffix is not None:
        return stem[: -(len(lang_suffix) + 1)]
    return stem


def _supreme_court_language_suffix(value: str) -> str | None:
    stem = Path(value).stem
    if "_" not in stem:
        return None
    suffix = stem.rsplit("_", 1)[-1].upper()
    if re.fullmatch(r"[A-Z]{2,5}", suffix) is None:
        return None
    return suffix


def _supreme_court_lookup_keys(value: str) -> list[str]:
    raw = str(value).strip()
    if not raw:
        return []

    candidates: list[str] = []

    def add(item: str | None) -> None:
        if item is None:
            return
        normalized = item.strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    path = Path(raw)
    name = path.name or raw
    stem = path.stem or raw
    base = _supreme_court_base_stem(name)

    add(raw)
    add(name)
    add(stem)
    add(base)
    add(f"{base}.pdf")

    # Regional Supreme Court archives carry language codes like HIN/PUN/MAR.
    for suffix in ("EN", "RG", "HIN", "PUN", "MAR", "TAM", "TEL", "KAN", "MAL", "GUJ", "BEN", "ODI", "URD"):
        add(f"{base}_{suffix}")
        add(f"{base}_{suffix}.pdf")

    return candidates


def _first_match(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match is not None else None


def _normalize_name(value: str) -> str:
    lowered = value.lower()
    lowered = lowered.replace("&", "and")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _slugify(value: str) -> str:
    return _normalize_name(value).replace(" ", "_")
