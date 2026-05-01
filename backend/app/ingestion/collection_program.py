from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from app.ingestion.adapters import (
    ConstitutionDocumentAdapter,
    CriminalCodeStatuteAdapter,
    HighCourtHtmlAdapter,
    IndiaCodeActAdapter,
    LawCommissionReportTextAdapter,
    PdfLegalDocumentAdapter,
    SupremeCourtHtmlAdapter,
    TribunalOrderHtmlAdapter,
)
from app.ingestion.contracts import BaseIngestionAdapter, IngestionJobContext
from app.ingestion.orchestrator import IngestionOrchestrator
from app.ingestion.persistence import PersistedIngestionResult

_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_INDIA_CODE_RESULTS_PATTERN = re.compile(r"Results\s+\d+-\d+\s+of\s+(\d+)")
_INDIA_CODE_ROW_PATTERN = re.compile(
    r"<tr><td[^>]*>(?P<enactment_date>.*?)</td>"
    r"<td[^>]*>(?P<act_number>.*?)</td>"
    r"<td[^>]*>(?P<title>.*?)</td>"
    r'<td[^>]*><a href="(?P<href>/handle/123456789/\d+\?view_type=search[^"]*)">'
    r"View\.\.\.</a></td></tr>",
    re.IGNORECASE | re.DOTALL,
)


class AutomationStatus(StrEnum):
    SUPPORTED = "supported"
    BLOCKED_PENDING_ADAPTER = "blocked_pending_adapter"
    PLANNED = "planned"


@dataclass(frozen=True, slots=True)
class CollectionSourceRegistryEntry:
    source_id: str
    display_name: str
    source_key: str
    adapter_key: str | None
    default_source_url: str | None
    default_parser_version: str | None
    default_external_id: str | None
    automation_status: AutomationStatus
    stage_hint: str | None = None
    notes: str | None = None
    default_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CollectionManifestJob:
    source_id: str
    source_url: str | None = None
    external_id: str | None = None
    parser_version: str | None = None
    inline_payload_path: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CollectionManifest:
    name: str
    description: str | None
    jobs: list[CollectionManifestJob]
    manifest_path: Path


@dataclass(frozen=True, slots=True)
class CollectionRunItem:
    source_id: str
    status: str
    reason: str | None = None
    doc_id: str | None = None
    ingestion_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionRunResult:
    manifest_name: str
    items: list[CollectionRunItem]


class CollectionProgram:
    def __init__(
        self,
        registry_dir: Path,
        orchestrator: IngestionOrchestrator | None = None,
    ) -> None:
        self.registry_dir = registry_dir
        self.orchestrator = orchestrator or IngestionOrchestrator()
        self.registry = self._load_registry(registry_dir)

    def load_manifest(self, manifest_path: Path) -> CollectionManifest:
        raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        jobs = [
            CollectionManifestJob(
                source_id=str(job["source_id"]),
                source_url=self._optional_str(job.get("source_url")),
                external_id=self._optional_str(job.get("external_id")),
                parser_version=self._optional_str(job.get("parser_version")),
                inline_payload_path=self._optional_str(job.get("inline_payload_path")),
                enabled=bool(job.get("enabled", True)),
                metadata=self._coerce_dict(job.get("metadata")),
            )
            for job in raw.get("jobs", [])
        ]
        return CollectionManifest(
            name=str(raw["name"]),
            description=self._optional_str(raw.get("description")),
            jobs=jobs,
            manifest_path=manifest_path,
        )

    def run_manifest(self, session: Session, manifest_path: Path) -> CollectionRunResult:
        manifest = self.load_manifest(manifest_path)
        items: list[CollectionRunItem] = []
        for job in manifest.jobs:
            if not job.enabled:
                items.append(
                    CollectionRunItem(
                        source_id=job.source_id,
                        status="skipped",
                        reason="job_disabled",
                    )
                )
                continue

            source = self.registry.get(job.source_id)
            if source is None:
                items.append(
                    CollectionRunItem(
                        source_id=job.source_id,
                        status="skipped",
                        reason="unknown_source_id",
                    )
                )
                continue

            if (
                source.automation_status is not AutomationStatus.SUPPORTED
                or source.adapter_key is None
            ):
                items.append(
                    CollectionRunItem(
                        source_id=job.source_id,
                        status="skipped",
                        reason=source.automation_status.value,
                    )
                )
                continue

            adapter = self._build_adapter(source.adapter_key)
            context = self._build_context(source, job, manifest.manifest_path)
            persisted = self.orchestrator.ingest(session, adapter, context)
            items.append(self._success_item(job.source_id, persisted))

        return CollectionRunResult(manifest_name=manifest.name, items=items)

    def run_source(
        self,
        session: Session,
        source_id: str,
        limit: int | None = None,
        delay_seconds: float = 2.0,
    ) -> CollectionRunResult:
        source = self.registry.get(source_id)
        if source is None:
            return CollectionRunResult(
                manifest_name=source_id,
                items=[
                    CollectionRunItem(
                        source_id=source_id,
                        status="skipped",
                        reason="unknown_source_id",
                    )
                ],
            )

        if (
            source.automation_status is not AutomationStatus.SUPPORTED
            or source.adapter_key is None
        ):
            return CollectionRunResult(
                manifest_name=source_id,
                items=[
                    CollectionRunItem(
                        source_id=source_id,
                        status="skipped",
                        reason=source.automation_status.value,
                    )
                ],
            )

        jobs = self._discover_jobs_for_source(source, limit=limit, delay_seconds=delay_seconds)
        items: list[CollectionRunItem] = []
        adapter = self._build_adapter(source.adapter_key)
        for job in jobs:
            context = self._build_context(source, job, self.registry_dir)
            persisted = self.orchestrator.ingest(session, adapter, context)
            items.append(self._success_item(source_id, persisted))

        return CollectionRunResult(manifest_name=source_id, items=items)

    def _build_context(
        self,
        source: CollectionSourceRegistryEntry,
        job: CollectionManifestJob,
        manifest_path: Path,
    ) -> IngestionJobContext:
        source_url = job.source_url or source.default_source_url
        parser_version = job.parser_version or source.default_parser_version
        if source_url is None:
            raise ValueError(f"Missing source_url for source_id={source.source_id}")
        if parser_version is None:
            raise ValueError(f"Missing parser_version for source_id={source.source_id}")

        inline_payload = None
        if job.inline_payload_path is not None:
            payload_path = (manifest_path.parent / job.inline_payload_path).resolve()
            inline_payload = payload_path.read_text(encoding="utf-8")

        metadata = {**source.default_metadata, **job.metadata}
        return IngestionJobContext(
            source_key=source.source_key,
            source_url=source_url,
            parser_version=parser_version,
            external_id=job.external_id or source.default_external_id,
            inline_payload=inline_payload,
            metadata=metadata,
        )

    def _load_registry(self, registry_dir: Path) -> dict[str, CollectionSourceRegistryEntry]:
        registry: dict[str, CollectionSourceRegistryEntry] = {}
        for path in sorted(registry_dir.glob("*.toml")):
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
            entry = CollectionSourceRegistryEntry(
                source_id=str(raw["source_id"]),
                display_name=str(raw["display_name"]),
                source_key=str(raw["source_key"]),
                adapter_key=self._optional_str(raw.get("adapter_key")),
                default_source_url=self._optional_str(raw.get("default_source_url")),
                default_parser_version=self._optional_str(raw.get("default_parser_version")),
                default_external_id=self._optional_str(raw.get("default_external_id")),
                automation_status=AutomationStatus(
                    str(raw.get("automation_status", AutomationStatus.PLANNED.value))
                ),
                stage_hint=self._optional_str(raw.get("stage_hint")),
                notes=self._optional_str(raw.get("notes")),
                default_metadata=self._coerce_dict(raw.get("default_metadata")),
            )
            registry[entry.source_id] = entry
        return registry

    def _discover_jobs_for_source(
        self,
        source: CollectionSourceRegistryEntry,
        limit: int | None,
        delay_seconds: float,
    ) -> list[CollectionManifestJob]:
        if source.source_id == "india_code_central_acts":
            return self._discover_india_code_jobs(source, limit=limit, delay_seconds=delay_seconds)
        raise ValueError(f"Live run discovery is not yet implemented for {source.source_id}")

    def _discover_india_code_jobs(
        self,
        source: CollectionSourceRegistryEntry,
        limit: int | None,
        delay_seconds: float,
    ) -> list[CollectionManifestJob]:
        requested_limit = limit or 10
        jobs: list[CollectionManifestJob] = []
        start = 0

        while len(jobs) < requested_limit:
            page_size = min(100, requested_limit - len(jobs))
            query = urlencode(
                {
                    "query": "",
                    "searchradio": "acts",
                    "sort_by": "dc.title_sort",
                    "order": "asc",
                    "rpp": str(page_size),
                    "etal": "0",
                    "start": str(start),
                }
            )
            url = f"https://www.indiacode.nic.in/handle/123456789/1362/simple-search?{query}"
            html = self._http_get_text(url)
            rows = list(_INDIA_CODE_ROW_PATTERN.finditer(html))
            if not rows:
                break

            for row in rows:
                if len(jobs) >= requested_limit:
                    break
                href = row.group("href").replace("view_type=search", "view_type=browse")
                handle_id_match = re.search(r"/handle/123456789/(\d+)", href)
                handle_id = (
                    handle_id_match.group(1)
                    if handle_id_match
                    else f"handle-{start}-{len(jobs)}"
                )
                jobs.append(
                    CollectionManifestJob(
                        source_id=source.source_id,
                        source_url=urljoin("https://www.indiacode.nic.in", href),
                        external_id=handle_id,
                        metadata={
                            "request_delay_seconds": delay_seconds,
                            "title": self._clean_html_fragment(row.group("title")),
                            "act_number": self._clean_html_fragment(row.group("act_number")),
                            "enactment_date": self._clean_html_fragment(
                                row.group("enactment_date")
                            ),
                        },
                    )
                )

            total_match = _INDIA_CODE_RESULTS_PATTERN.search(html)
            total_results = int(total_match.group(1)) if total_match is not None else len(jobs)
            start += page_size
            if start >= total_results:
                break

        return jobs

    def _build_adapter(self, adapter_key: str) -> BaseIngestionAdapter:
        factories: dict[str, type[BaseIngestionAdapter]] = {
            "constitution_document": ConstitutionDocumentAdapter,
            "indiacode_act": IndiaCodeActAdapter,
            "criminal_code_statute": CriminalCodeStatuteAdapter,
            "supreme_court_html": SupremeCourtHtmlAdapter,
            "high_court_html": HighCourtHtmlAdapter,
            "tribunal_order_html": TribunalOrderHtmlAdapter,
            "pdf_legal_document": PdfLegalDocumentAdapter,
            "law_commission_report_text": LawCommissionReportTextAdapter,
        }
        factory = factories.get(adapter_key)
        if factory is None:
            raise ValueError(f"Unsupported adapter_key={adapter_key}")
        return factory()

    def _success_item(
        self,
        source_id: str,
        persisted: PersistedIngestionResult,
    ) -> CollectionRunItem:
        return CollectionRunItem(
            source_id=source_id,
            status="ingested",
            doc_id=persisted.doc_id,
            ingestion_run_id=persisted.ingestion_run_id,
        )

    def _coerce_dict(self, value: object | None) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        return {}

    def _optional_str(self, value: object | None) -> str | None:
        return value if isinstance(value, str) else None

    def _http_get_text(self, url: str) -> str:
        request = Request(url, headers=_REQUEST_HEADERS)
        with urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="ignore")

    def _clean_html_fragment(self, fragment: str) -> str:
        without_tags = re.sub(r"<[^>]+>", " ", fragment)
        return unescape(re.sub(r"\s+", " ", without_tags)).strip()
