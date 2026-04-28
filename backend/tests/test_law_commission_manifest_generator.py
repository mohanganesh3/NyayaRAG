from __future__ import annotations

import json
from pathlib import Path

from app.ingestion.scripts.generate_law_commission_manifest import main


def test_generate_law_commission_manifest_emits_inline_payload_paths(tmp_path: Path) -> None:
    raw_dir = tmp_path / "data" / "raw" / "law_commission" / "texts" / "commission-x"
    raw_dir.mkdir(parents=True)
    text_path = raw_dir / "report-280.pdf.txt"
    text_path.write_text("Sample report text", encoding="utf-8")

    index_path = tmp_path / "data" / "raw" / "law_commission" / "law_commission_index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "report_number": "280",
                "report_title": "Reform of the Evidence Act",
                "submission_date": "2018",
                "pdf_url": "https://lawcommissionofindia.nic.in/report_280/report280.pdf",
                "text_path": str(text_path),
                "extraction_status": "downloaded",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    output_manifest = tmp_path / "data" / "collection" / "manifests" / "lc_reports.toml"
    rc = main(
        [
            "--index",
            str(index_path),
            "--output",
            str(output_manifest),
            "--require-text",
            "--max-jobs",
            "10",
        ]
    )
    assert rc == 0

    rendered = output_manifest.read_text(encoding="utf-8")
    assert "[[jobs]]" in rendered
    assert "source_id = \"law_commission_reports\"" in rendered
    assert "inline_payload_path" in rendered
    # Ensure we wrote a relative path (not an absolute one).
    assert str(text_path) not in rendered
    assert "report_number" in rendered
