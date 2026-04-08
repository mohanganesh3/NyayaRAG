from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from html import unescape
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from app.ingestion.adapters.statute_text import StructuredStatuteTextAdapter
from app.ingestion.contracts import (
    FetchedPayload,
    IngestionJobContext,
    NormalizedPayload,
    ParsedDocument,
)

_CONTENT_TYPE_LIVE = "application/vnd.nyayarag.indiacode.bundle+json"
_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_XHR_HEADERS = {
    **_REQUEST_HEADERS,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}
_TAG_BREAK_PATTERN = re.compile(r"<(?:/p|/div|/tr|/li|/h1|/h2|/h3|br\s*/?)>", re.IGNORECASE)
_TAG_STRIP_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_SECTION_LINK_PATTERN = re.compile(
    r"<a\b[^>]*href=(?:\"|')?(?P<href>/show-data\?[^\"'>\s]*?sectionId=(?P<section_id>\d+)"
    r"[^\"'>\s]*?sectionno=(?P<section_number>[^&\"'>\s]+)[^\"'>\s]*?orderno="
    r"(?P<orderno>\d+)[^\"'>\s]*)(?:\"|')?[^>]*>"
    r"(?P<label>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_METADATA_ROW_PATTERN = re.compile(
    r'<tr><td class="metadataFieldLabel">(?P<label>[^<:]+):&nbsp;</td>'
    r'<td[^>]*class="metadataFieldValue"[^>]*>(?P<value>.*?)</td></tr>',
    re.IGNORECASE | re.DOTALL,
)
_SCHEDULE_TITLE_PATTERN = re.compile(
    r"<h4[^>]*class=\"panel-title\"[^>]*>\s*(Schedule\s+\d+\.\s*.*?)</h4>",
    re.IGNORECASE | re.DOTALL,
)
_PDF_URL_PATTERN = re.compile(
    r'<meta name="citation_pdf_url" content="([^"]+)"',
    re.IGNORECASE,
)
_PDF_PAGE_NUMBER_PATTERN = re.compile(r"^\d+$")
_PDF_SECTION_START_PATTERN = re.compile(
    r"^(?P<number>(?:\d+|[IVXLCDM]+))\.\s*(?P<body>.+)$",
    re.IGNORECASE,
)
_PDF_PREAMBLE_START_PATTERN = re.compile(
    r"^(?:An Act for|It is hereby enacted|Be it enacted|WHEREAS|Whereas)\b",
    re.IGNORECASE,
)
_PDF_SCHEDULE_PATTERN = re.compile(
    r"^\s*(?:THE\s+)?(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|"
    r"TENTH|ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH|SIXTEENTH|"
    r"SEVENTEENTH|EIGHTEENTH|NINETEENTH|TWENTIETH|[IVXLCDM]+|\d+)\s+SCHEDULE"
    r"(?:\s*[.-].*)?$|^\s*SCHEDULE(?:\s+[IVXLCDM]+|\s+\d+)(?:\s*[.-].*)?$|^\s*SCHEDULE\.?$",
    re.IGNORECASE,
)
_ACT_ID_SCRIPT_PATTERN = re.compile(r"act_id='([^']+)'")
_ACT_ID_HREF_PATTERN = re.compile(
    r"/show-data\?[^\"'>\s]*?\bactid=([^&\"'>\s]+)",
    re.IGNORECASE,
)
_ACT_ID_PREAMBLE_PATTERN = re.compile(
    r'<a id="([^"#]+)" class="preambletitle"',
    re.IGNORECASE,
)
_TITLE_PATTERN = re.compile(r"<title>India Code:\s*(.*?)</title>", re.IGNORECASE | re.DOTALL)
_DEFAULT_TIMEOUT_SECONDS = 60
_MAX_HTTP_ATTEMPTS = 3
_RETRYABLE_STATUS_CODES = {429, 503}
_BACKOFF_SECONDS = 10.0


class IndiaCodeActAdapter(StructuredStatuteTextAdapter):
    practice_areas = ["civil", "corporate", "statutory"]

    @property
    def adapter_name(self) -> str:
        return "indiacode-act-adapter"

    def fetch(self, context: IngestionJobContext) -> FetchedPayload:
        if self._is_plain_text_sample(context):
            return super().fetch(context)

        act_html = (
            context.inline_payload
            if context.inline_payload is not None
            else self._http_get_text(context.source_url)
        )
        live_bundle = self._build_live_bundle(context, act_html)
        raw_content = json.dumps(live_bundle, ensure_ascii=True)

        return FetchedPayload(
            source_key=context.source_key,
            source_url=context.source_url,
            external_id=context.external_id,
            raw_content=raw_content,
            content_type=_CONTENT_TYPE_LIVE,
            fetched_at=datetime.now(UTC),
            checksum=sha256(raw_content.encode("utf-8")).hexdigest(),
        )

    def normalize(self, fetched: FetchedPayload, context: IngestionJobContext) -> NormalizedPayload:
        if fetched.content_type != _CONTENT_TYPE_LIVE:
            return super().normalize(fetched, context)

        live_bundle = json.loads(fetched.raw_content)
        sections = live_bundle.get("sections", [])
        lines = [
            str(live_bundle.get("metadata_rows", {}).get("Short Title", "India Code Act")).strip(),
        ]
        for section in sections:
            section_number = str(section.get("section_number", "")).strip()
            heading = str(section.get("heading", "")).strip()
            if section_number or heading:
                lines.append(f"Section {section_number}: {heading}".strip())

        return NormalizedPayload(
            source_key=fetched.source_key,
            source_url=fetched.source_url,
            raw_content=fetched.raw_content,
            clean_text="\n".join(line for line in lines if line),
            lines=[line for line in lines if line],
            checksum=fetched.checksum,
        )

    def parse(self, normalized: NormalizedPayload, context: IngestionJobContext) -> ParsedDocument:
        if not normalized.raw_content.startswith("{"):
            return super().parse(normalized, context)

        live_bundle = json.loads(normalized.raw_content)
        metadata_rows = self._as_str_dict(live_bundle.get("metadata_rows"))
        sections_payload = live_bundle.get("sections", [])
        sections: list[dict[str, object]] = []
        paragraphs: list[str] = []
        section_headers: list[str] = []

        for section_payload in sections_payload:
            if not isinstance(section_payload, dict):
                continue
            section_number = str(section_payload.get("section_number", "")).strip()
            heading = str(section_payload.get("heading", "")).strip()
            raw_text = str(section_payload.get("content_html", ""))
            text = self._clean_fragment(raw_text)
            footnote = self._clean_fragment(str(section_payload.get("footnote_html", "")))
            if not section_number:
                continue

            section_headers.append(f"Section {section_number} - {heading}".strip())
            section_body = f"Section {section_number}. {heading}\n{text}".strip()
            if footnote:
                section_body = f"{section_body}\nFootnote: {footnote}"
            paragraphs.append(section_body)
            sections.append(
                {
                    "section_number": section_number,
                    "heading": heading or None,
                    "text": text or heading or section_number,
                    "original_text": text or heading or section_number,
                    "is_in_force": "[Omitted]" not in heading,
                    "cases_interpreting": [],
                    "amendments": [],
                }
            )

        title = (
            metadata_rows.get("Short Title")
            or metadata_rows.get("Long Title")
            or str(live_bundle.get("page_title", "India Code Act"))
        )
        source_document_ref = (
            context.external_id
            or str(live_bundle.get("handle_id") or live_bundle.get("act_id") or title)
        )

        return ParsedDocument(
            title=title,
            body_text="\n\n".join(paragraphs),
            paragraphs=paragraphs,
            section_headers=section_headers,
            source_document_ref=source_document_ref,
            attributes={
                "statute_document": {
                    "act_name": title,
                    "short_title": metadata_rows.get("Short Title"),
                    "jurisdiction": "Central",
                    "enforcement_date": self._iso_date(metadata_rows.get("Enforcement Date")),
                    "current_validity": True,
                    "current_sections_in_force": [
                        str(section["section_number"])
                        for section in sections
                        if bool(section["is_in_force"])
                    ],
                    "sections": sections,
                    "act_id": metadata_rows.get("Act ID") or live_bundle.get("act_id"),
                    "act_number": metadata_rows.get("Act Number"),
                    "act_year": metadata_rows.get("Act Year"),
                    "ministry": metadata_rows.get("Ministry"),
                    "department": metadata_rows.get("Department"),
                    "long_title": metadata_rows.get("Long Title"),
                    "last_updated": self._iso_date(metadata_rows.get("Last Updated")),
                    "schedules": live_bundle.get("schedule_titles", []),
                },
            },
        )

    def _build_live_bundle(self, context: IngestionJobContext, act_html: str) -> dict[str, object]:
        handle_id = self._extract_handle_id(context.source_url)
        metadata_rows = self._extract_metadata_rows(act_html)
        section_refs = self._extract_section_refs(act_html)
        act_id = self._extract_act_id(
            act_html,
            metadata_rows=metadata_rows,
            section_refs=section_refs,
        )
        if act_id is None:
            raise ValueError(f"Could not extract India Code act_id from {context.source_url}")

        raw_dir = self._raw_dir(handle_id)
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "act.html").write_text(act_html, encoding="utf-8")

        schedule_titles = self._extract_schedule_titles(act_html)
        sections: list[dict[str, object]] = []
        delay_seconds = self._request_delay_seconds(context)

        if section_refs:
            for index, section_ref in enumerate(section_refs):
                query = urlencode(
                    {
                        "actid": act_id,
                        "sectionID": section_ref["section_id"],
                    }
                )
                section_content_url = f"https://www.indiacode.nic.in/SectionPageContent?{query}"
                section_body = self._http_get_text(section_content_url, headers=_XHR_HEADERS)
                section_json = json.loads(section_body)
                section_record: dict[str, object] = {
                    **section_ref,
                    "content_html": str(section_json.get("content", "")),
                    "footnote_html": str(section_json.get("footnote", "")),
                    "section_content_url": section_content_url,
                }
                sections.append(section_record)

                section_file = raw_dir / "sections" / f"{section_ref['section_id']}.json"
                section_file.parent.mkdir(parents=True, exist_ok=True)
                section_file.write_text(section_body, encoding="utf-8")

                if delay_seconds > 0 and index < len(section_refs) - 1:
                    sleep(delay_seconds)
        else:
            pdf_url = self._extract_pdf_url(act_html)
            if pdf_url is not None:
                pdf_bytes = self._http_get_bytes(pdf_url)
                (raw_dir / "act.pdf").write_bytes(pdf_bytes)
                pdf_sections, pdf_schedule_titles = self._extract_pdf_sections(
                    pdf_bytes,
                    pdf_url=pdf_url,
                    act_id=act_id,
                    raw_dir=raw_dir,
                )
                sections.extend(pdf_sections)
                for title in pdf_schedule_titles:
                    if title not in schedule_titles:
                        schedule_titles.append(title)

        page_title_match = _TITLE_PATTERN.search(act_html)
        return {
            "mode": "indiacode_live_v1",
            "handle_id": handle_id,
            "act_id": act_id,
            "page_title": (
                self._clean_fragment(page_title_match.group(1))
                if page_title_match is not None
                else None
            ),
            "metadata_rows": metadata_rows,
            "schedule_titles": schedule_titles,
            "sections": sections,
        }

    def _extract_pdf_url(self, act_html: str) -> str | None:
        match = _PDF_URL_PATTERN.search(act_html)
        if match is None:
            return None
        return unescape(match.group(1)).strip() or None

    def _extract_pdf_sections(
        self,
        pdf_bytes: bytes,
        *,
        pdf_url: str,
        act_id: str,
        raw_dir: Path,
    ) -> tuple[list[dict[str, object]], list[str]]:
        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - dependency issue
            raise RuntimeError(
                "PyMuPDF is required for India Code PDF fallback extraction"
            ) from exc

        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        raw_text = "\n".join(
            document.load_page(page_index).get_text("text")
            for page_index in range(document.page_count)
        )
        sections: list[dict[str, object]] = []
        schedule_titles: list[str] = []
        current: dict[str, object] | None = None
        in_body = False

        for raw_line in raw_text.splitlines():
            line = self._clean_pdf_line(raw_line)
            if not line or _PDF_PAGE_NUMBER_PATTERN.fullmatch(line):
                continue

            if _PDF_PREAMBLE_START_PATTERN.match(line):
                in_body = True

            if self._is_pdf_schedule_heading(line) and (in_body or current is not None):
                if "Schedule" not in schedule_titles:
                    schedule_titles.append("Schedule")
                if current is not None:
                    sections.append(current)
                    current = None
                break

            section_match = _PDF_SECTION_START_PATTERN.match(line)
            if section_match is not None and (in_body or current is not None):
                section_body = section_match.group("body").strip()
                if self._is_pdf_footnote_body(section_body):
                    if current is not None:
                        footnote_text = f"{section_match.group('number')}. {section_body}".strip()
                        existing = str(current.get("footnote_html", "")).strip()
                        current["footnote_html"] = (
                            f"{existing}\n{footnote_text}".strip() if existing else footnote_text
                        )
                    continue

                if current is not None:
                    sections.append(current)
                section_number = section_match.group("number").upper()
                heading, body_text = self._split_pdf_section_heading(section_body)
                current = {
                    "section_id": f"pdf-{len(sections) + 1}",
                    "section_number": section_number,
                    "heading": heading,
                    "content_html": body_text or section_body,
                    "footnote_html": "",
                    "section_content_url": pdf_url,
                    "source_format": "pdf",
                    "act_id": act_id,
                }
                in_body = True
                continue

            if in_body and current is not None:
                current["content_html"] = f"{current['content_html']}\n{line}".strip()

        if current is not None:
            sections.append(current)

        if not sections and raw_text.strip():
            current = {
                "section_id": "pdf-1",
                "section_number": "1",
                "heading": None,
                "content_html": raw_text.strip(),
                "footnote_html": "",
                "section_content_url": pdf_url,
                "source_format": "pdf",
                "act_id": act_id,
            }
            sections.append(current)

        self._write_pdf_sections(raw_dir, sections)
        return sections, schedule_titles

    def _write_pdf_sections(self, raw_dir: Path, sections: list[dict[str, object]]) -> None:
        section_dir = raw_dir / "sections"
        section_dir.mkdir(parents=True, exist_ok=True)
        for section in sections:
            section_id = str(section.get("section_id", "pdf"))
            section_path = section_dir / f"{section_id}.json"
            section_path.write_text(
                json.dumps(section, indent=2, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )

    def _http_get_bytes(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        last_error: Exception | None = None
        for attempt in range(1, _MAX_HTTP_ATTEMPTS + 1):
            request = Request(url, headers=headers or _REQUEST_HEADERS)
            try:
                with urlopen(request, timeout=_DEFAULT_TIMEOUT_SECONDS) as response:
                    return response.read()
            except HTTPError as exc:
                last_error = exc
                if exc.code not in _RETRYABLE_STATUS_CODES:
                    if attempt >= _MAX_HTTP_ATTEMPTS:
                        raise
                    sleep(float(attempt))
                    continue
            except (TimeoutError, URLError) as exc:
                last_error = exc

            if attempt >= _MAX_HTTP_ATTEMPTS:
                if last_error is not None:
                    raise last_error
                raise RuntimeError(f"Failed to fetch {url}")
            sleep(_BACKOFF_SECONDS)

        raise RuntimeError(f"Failed to fetch {url}")

    def _split_pdf_section_heading(self, section_body: str) -> tuple[str | None, str]:
        body = section_body.strip()
        if not body:
            return None, ""

        heading_match = re.match(
            r"^(?P<heading>[^.—]{3,120}?)(?:\s*[.—-]\s+)(?P<text>.+)$",
            body,
        )
        if heading_match is None:
            return None, body

        heading = self._clean_fragment(heading_match.group("heading"))
        text = self._clean_fragment(heading_match.group("text"))
        return heading or None, text or body

    def _clean_pdf_line(self, line: str) -> str:
        cleaned = line.replace("\u00ad", "").replace("\ufeff", "").strip()
        return re.sub(r"\s+", " ", cleaned)

    def _is_pdf_footnote_body(self, body: str) -> bool:
        cleaned = self._clean_fragment(body).strip()
        lowered = cleaned.lower()
        amendment_prefixes = (
            "ins. by",
            "subs. by",
            "omitted by",
            "inserted by",
            "substituted by",
            "renumbered by",
            "certain words ",
            "the words ",
            "words ",
            "clause ",
            "sub-section ",
            "sub-clause ",
            "explanation ",
            "existing explanation ",
            "the explanation ",
            "proviso ",
            "paragraph ",
            "item ",
            "entry ",
            "entries ",
            "rule ",
            "schedule ",
        )
        amendment_keywords = (
            " omitted",
            " substituted",
            " inserted",
            " renumbered",
            " amended",
            " by act ",
            " by the act ",
            " ibid.",
            "(w.e.f.",
            "(w.r.e.f.",
        )
        return lowered.startswith(amendment_prefixes) and any(
            keyword in lowered for keyword in amendment_keywords
        )

    def _is_pdf_schedule_heading(self, line: str) -> bool:
        cleaned = self._clean_fragment(line).strip()
        lowered = cleaned.lower()
        if "[" in cleaned or "]" in cleaned or "see section" in lowered:
            return False
        return bool(_PDF_SCHEDULE_PATTERN.match(cleaned))

    def _extract_handle_id(self, source_url: str) -> str:
        match = re.search(r"/handle/123456789/(\d+)", source_url)
        if match is None:
            parsed = urlparse(source_url)
            query = parse_qs(parsed.query)
            fallback = query.get("handle_id")
            if fallback:
                return fallback[0]
            return "unknown-handle"
        return match.group(1)

    def _extract_act_id(
        self,
        act_html: str,
        *,
        metadata_rows: dict[str, str] | None = None,
        section_refs: list[dict[str, str]] | None = None,
    ) -> str | None:
        script_match = _ACT_ID_SCRIPT_PATTERN.search(act_html)
        if script_match is not None:
            return script_match.group(1)

        href_match = _ACT_ID_HREF_PATTERN.search(act_html)
        if href_match is not None:
            return unescape(href_match.group(1))

        preamble_match = _ACT_ID_PREAMBLE_PATTERN.search(act_html)
        if preamble_match is not None:
            return unescape(preamble_match.group(1))

        for section_ref in section_refs or self._extract_section_refs(act_html):
            parsed = urlparse(section_ref["href"])
            query = parse_qs(parsed.query)
            act_id = query.get("actid")
            if act_id:
                return act_id[0]

        if metadata_rows is not None:
            public_act_id = metadata_rows.get("Act ID")
            if public_act_id:
                return public_act_id
        return None

    def _extract_section_refs(self, act_html: str) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for match in _SECTION_LINK_PATTERN.finditer(act_html):
            href = match.group("href").replace("&amp;", "&").strip()
            section_id = match.group("section_id")
            section_number = unescape(match.group("section_number")).strip()
            label = self._clean_fragment(match.group("label"))
            if not section_number or section_number.lower() == "none":
                continue
            key = (section_id, section_number)
            if key in seen:
                continue
            seen.add(key)
            heading = re.sub(
                rf"^Section\s+{re.escape(section_number)}\.?\s*",
                "",
                label,
                flags=re.IGNORECASE,
            ).strip()
            refs.append(
                {
                    "href": href,
                    "section_id": section_id,
                    "section_number": section_number,
                    "orderno": match.group("orderno"),
                    "heading": heading or label,
                }
            )
        return refs

    def _extract_metadata_rows(self, act_html: str) -> dict[str, str]:
        rows: dict[str, str] = {}
        for match in _METADATA_ROW_PATTERN.finditer(act_html):
            label = self._clean_fragment(match.group("label")).rstrip(":")
            value = self._clean_fragment(match.group("value"))
            if label:
                rows[label] = value
        return rows

    def _extract_schedule_titles(self, act_html: str) -> list[str]:
        titles: list[str] = []
        seen: set[str] = set()
        for match in _SCHEDULE_TITLE_PATTERN.finditer(act_html):
            title = self._clean_fragment(match.group(1))
            if title and title not in seen:
                seen.add(title)
                titles.append(title)
        return titles

    def _http_get_text(self, url: str, headers: dict[str, str] | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(1, _MAX_HTTP_ATTEMPTS + 1):
            request = Request(url, headers=headers or _REQUEST_HEADERS)
            try:
                with urlopen(request, timeout=_DEFAULT_TIMEOUT_SECONDS) as response:
                    return response.read().decode("utf-8", errors="ignore")
            except HTTPError as exc:
                last_error = exc
                if exc.code not in _RETRYABLE_STATUS_CODES:
                    if attempt >= _MAX_HTTP_ATTEMPTS:
                        raise
                    sleep(float(attempt))
                    continue
            except (TimeoutError, URLError) as exc:
                last_error = exc

            if attempt >= _MAX_HTTP_ATTEMPTS:
                if last_error is not None:
                    raise last_error
                raise RuntimeError(f"Failed to fetch {url}")
            sleep(_BACKOFF_SECONDS)

        raise RuntimeError(f"Failed to fetch {url}")

    def _request_delay_seconds(self, context: IngestionJobContext) -> float:
        value = context.metadata.get("request_delay_seconds")
        if isinstance(value, (int, float)):
            return float(value)
        return 2.0

    def _is_plain_text_sample(self, context: IngestionJobContext) -> bool:
        payload = context.inline_payload
        if payload is None:
            return False
        return not payload.lstrip().startswith("<")

    def _iso_date(self, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
            return cleaned
        if re.fullmatch(r"\d{2}-\d{2}-\d{4}", cleaned):
            day, month, year = cleaned.split("-")
            return f"{year}-{month}-{day}"
        return cleaned or None

    def _clean_fragment(self, fragment: str) -> str:
        with_breaks = _TAG_BREAK_PATTERN.sub("\n", fragment)
        without_tags = _TAG_STRIP_PATTERN.sub(" ", with_breaks)
        normalized = unescape(without_tags)
        return "\n".join(
            line
            for line in (
                _WHITESPACE_PATTERN.sub(" ", part).strip()
                for part in normalized.splitlines()
            )
            if line
        )

    def _raw_dir(self, handle_id: str) -> Path:
        return Path(__file__).resolve().parents[4] / "data" / "raw" / "india_code" / handle_id

    def _as_str_dict(self, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {
            str(key): str(inner)
            for key, inner in value.items()
            if isinstance(key, (str, int, float)) and isinstance(inner, (str, int, float))
        }
