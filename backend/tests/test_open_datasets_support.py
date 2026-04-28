from __future__ import annotations

import json
from pathlib import Path

from app.ingestion.scripts.open_datasets_download import build_download_plan
from app.ingestion.scripts.open_datasets_index import build_index
from app.ingestion.scripts.open_datasets_status import build_status_report


def _make_dataset_file(root: Path, relative_path: str, contents: str = "sample") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


def test_open_datasets_status_reports_local_and_manual_only(tmp_path) -> None:
    root = tmp_path / "raw"
    _make_dataset_file(root, "huggingface/InJudgements_dataset/readme.txt")

    report = build_status_report(root, remote=False)

    assert report["raw_root"] == str(root)
    assert report["summary"]["local_ready"] == 1
    assert report["summary"]["manual_only"] == 1
    assert len(report["targets"]) == 4

    by_id = {row["dataset_id"]: row for row in report["targets"]}
    assert by_id["opennyaiorg/InJudgements_dataset"]["exists"] is True
    assert by_id["ILDC"]["manual_only"] is True
    assert by_id["ILDC"]["remote_status"] == "not_checked"


def test_open_datasets_download_dry_run_and_request_manifest(tmp_path) -> None:
    root = tmp_path / "raw"
    request_manifest = tmp_path / "request_manifest.json"
    report = build_download_plan(
        ["all"],
        root=root,
        dry_run=True,
        request_manifest_path=request_manifest,
    )

    statuses = {row["dataset_id"]: row["status"] for row in report["results"]}
    assert statuses["ILDC"] == "manual_request_only"
    assert statuses["opennyaiorg/InJudgements_dataset"] == "dry_run"
    assert statuses["adarshsingh0903/legal-dataset-sc-judgments-india-19502024"] == "dry_run"

    assert request_manifest.exists()
    payload = json.loads(request_manifest.read_text(encoding="utf-8"))
    assert payload["dataset_id"] == "ILDC"


def test_open_datasets_index_builds_jsonl_and_summary(tmp_path) -> None:
    root = tmp_path / "raw"
    _make_dataset_file(root, "kaggle/sc_judgments/case_a.txt", "alpha")
    _make_dataset_file(root, "huggingface/InLegalNER/sample.json", "{\"ok\": true}")

    index_path = tmp_path / "index.jsonl"
    summary_path = tmp_path / "summary.json"
    report = build_index(root, output_index=index_path, output_summary=summary_path)

    assert report["files_indexed"] == 2
    assert report["datasets_indexed"] == 4
    assert index_path.exists()
    assert summary_path.exists()

    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    assert {row["dataset_id"] for row in index_rows} == {
        "opennyaiorg/InLegalNER",
        "adarshsingh0903/legal-dataset-sc-judgments-india-19502024",
    }
