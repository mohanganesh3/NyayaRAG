from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader


@dataclass(frozen=True, slots=True)
class CADownload:
    collection_slug: str
    item_id: str
    item_url: str | None
    download_url: str | None
    pdf_path: Path
    pdf_filename: str
    date_text: str | None
    title: str | None
    language: str | None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate_ca_debates_manifest",
        description=(
            "Generate a NyayaRAG collection manifest for Constituent Assembly debate PDFs "
            "stored under data/raw/constituent_assembly."
        ),
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        required=True,
        help="Root directory containing downloaded items (e.g. data/raw/constituent_assembly).",
    )
    parser.add_argument(
        "--texts-dir",
        type=Path,
        required=True,
        help="Directory where extracted plain-text payloads will be written.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the generated TOML manifest.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="If > 0, only emit the first N jobs (useful for smoke runs).",
    )
    parser.add_argument(
        "--skip-existing-text",
        action="store_true",
        help="Do not re-extract text when a .txt payload already exists.",
    )
    args = parser.parse_args(argv)

    raw_dir = args.raw_dir.resolve()
    texts_dir = args.texts_dir.resolve()
    output = args.output.resolve()

    downloads = list(_discover_downloads(raw_dir))
    downloads.sort(key=lambda d: (d.collection_slug, d.date_text or "", d.item_id, d.pdf_filename))

    if args.limit and args.limit > 0:
        downloads = downloads[: args.limit]

    jobs: list[dict[str, Any]] = []
    for download in downloads:
        payload_path = _ensure_text_payload(
            download,
            texts_dir=texts_dir,
            skip_existing=bool(args.skip_existing_text),
        )
        payload_rel = _relative_to(payload_path, base_dir=output.parent)

        external_id = f"ca-{download.collection_slug}-{download.item_id}-{payload_path.stem}"
        title = download.title or f"Constituent Assembly Debate ({download.collection_slug})"
        if download.date_text:
            title = f"{title} — {download.date_text}"

        metadata: dict[str, Any] = {
            "doc_type": "cab_debate",
            "court_name": "Constituent Assembly of India",
            "practice_areas": ["constitutional"],
            "title": title,
            "date_text": download.date_text,
            "collection_slug": download.collection_slug,
            "item_id": download.item_id,
            "pdf_filename": download.pdf_filename,
        }
        if download.item_url:
            metadata["item_url"] = download.item_url
        if download.download_url:
            metadata["download_url"] = download.download_url
        if download.language:
            metadata["language"] = download.language

        jobs.append(
            {
                "source_id": "ca_debates",
                "source_url": download.item_url or download.download_url or str(download.pdf_path),
                "external_id": external_id,
                "parser_version": "cab-debate-pdf-v1",
                "inline_payload_path": payload_rel,
                "enabled": True,
                "metadata": {k: v for k, v in metadata.items() if v is not None},
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_manifest(jobs, raw_dir=raw_dir), encoding="utf-8")
    print(
        json.dumps(
            {
                "raw_dir": str(raw_dir),
                "texts_dir": str(texts_dir),
                "output": str(output),
                "job_count": len(jobs),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _discover_downloads(raw_dir: Path) -> list[CADownload]:
    downloads: list[CADownload] = []
    if not raw_dir.exists():
        return downloads

    for collection_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        for item_dir in sorted(p for p in collection_dir.iterdir() if p.is_dir()):
            metadata_path = item_dir / "metadata.json"
            if not metadata_path.exists():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            item_id = str(metadata.get("item_id") or "").strip() or item_dir.name.replace(
                "item_", ""
            )
            collection_slug = str(metadata.get("collection_slug") or collection_dir.name).strip()
            item_url = _optional_str(metadata.get("item_url"))

            dc = metadata.get("dc")
            dc_obj = dc if isinstance(dc, dict) else {}
            date_text = _first_str(dc_obj.get("DC.date"))
            title = _first_str(dc_obj.get("DC.title")) or _first_str(dc_obj.get("citation_title"))
            language = _first_str(dc_obj.get("DC.language")) or _first_str(
                dc_obj.get("citation_language")
            )

            for dl in metadata.get("downloads", []) if isinstance(metadata.get("downloads"), list) else []:
                if not isinstance(dl, dict):
                    continue
                pdf_path = Path(str(dl.get("path") or "")).expanduser()
                pdf_filename = str(dl.get("filename") or pdf_path.name).strip()
                if not pdf_filename.lower().endswith(".pdf"):
                    continue
                if not pdf_path.exists():
                    continue

                downloads.append(
                    CADownload(
                        collection_slug=collection_slug,
                        item_id=item_id,
                        item_url=item_url,
                        download_url=_optional_str(dl.get("url")),
                        pdf_path=pdf_path,
                        pdf_filename=pdf_filename,
                        date_text=date_text,
                        title=title,
                        language=language,
                    )
                )

    return downloads


def _ensure_text_payload(download: CADownload, *, texts_dir: Path, skip_existing: bool) -> Path:
    subdir = texts_dir / download.collection_slug
    subdir.mkdir(parents=True, exist_ok=True)

    safe_stem = download.pdf_path.stem
    if download.date_text and not safe_stem.startswith(download.date_text):
        safe_stem = f"{download.date_text}_{download.item_id}_{safe_stem}"

    text_path = subdir / f"{safe_stem}.txt"
    if skip_existing and text_path.exists() and text_path.stat().st_size > 0:
        return text_path

    text = _extract_pdf_text(download.pdf_path)
    # Ensure we always have *some* payload; empty payloads are legal but not useful.
    if not text.strip():
        text = f"{download.title or 'Constituent Assembly Debate'}\n\n(Empty text extraction.)\n"

    text_path.write_text(text, encoding="utf-8")
    return text_path


def _extract_pdf_text(path: Path) -> str:
    with path.open("rb") as handle:
        reader = PdfReader(handle)
        parts: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            if text.strip():
                parts.append(text)
        return "\n\n".join(parts).strip()


def _render_manifest(jobs: list[dict[str, Any]], *, raw_dir: Path) -> str:
    lines: list[str] = []
    lines.append(f"name = {_toml_str('Constituent Assembly Debates')}")
    lines.append(
        f"description = {_toml_str('Ingest Constituent Assembly debate PDFs from local raw downloads.') }"
    )
    lines.append("")

    for job in jobs:
        lines.append("[[jobs]]")
        lines.append(f"source_id = {_toml_str(str(job['source_id']))}")
        lines.append(f"source_url = {_toml_str(str(job['source_url']))}")
        lines.append(f"external_id = {_toml_str(str(job['external_id']))}")
        lines.append(f"parser_version = {_toml_str(str(job['parser_version']))}")
        lines.append(f"inline_payload_path = {_toml_str(str(job['inline_payload_path']))}")
        lines.append(f"enabled = {str(bool(job.get('enabled', True))).lower()}")

        metadata = job.get("metadata")
        if isinstance(metadata, dict) and metadata:
            lines.append("[jobs.metadata]")
            for key in sorted(metadata):
                lines.append(f"{key} = {_toml_value(metadata[key])}")

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _toml_value(value: Any) -> str:
    if value is None:
        return "\"\""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    return _toml_str(str(value))


def _toml_str(value: str) -> str:
    # JSON-style escaping yields a valid TOML basic string.
    return json.dumps(value, ensure_ascii=False)


def _optional_str(value: object | None) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _first_str(value: object | None) -> str | None:
    if isinstance(value, list) and value:
        return _optional_str(value[0])
    if isinstance(value, str):
        return _optional_str(value)
    return None


def _relative_to(path: Path, *, base_dir: Path) -> str:
    # Use a filesystem relative path even when `path` is outside `base_dir`.
    rel = os.path.relpath(path.resolve(), start=base_dir.resolve())
    return Path(rel).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
