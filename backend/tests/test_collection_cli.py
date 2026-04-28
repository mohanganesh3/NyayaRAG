from __future__ import annotations

import json
import tomllib
from pathlib import Path

from app.db.base import Base
from app.db.session import build_engine
from app.ingestion.cli import main
from app.models import LegalDocument
from sqlalchemy import select
from sqlalchemy.orm import Session


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _registry_dir() -> Path:
    return _repo_root() / "data" / "collection" / "sources"


def _manifest(name: str) -> Path:
    return _repo_root() / "data" / "collection" / "manifests" / name


def test_collection_cli_lists_sources(capsys) -> None:
    exit_code = main(
        [
            "list-sources",
            "--registry-dir",
            str(_registry_dir()),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "supreme_court_official\tsupported\tsupreme_court" in captured.out
    assert "ecourts_district_history\tblocked_pending_adapter" in captured.out


def test_collection_cli_runs_manifest_and_emits_json(capsys, tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'collection_cli.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)

    exit_code = main(
        [
            "run-manifest",
            "--registry-dir",
            str(_registry_dir()),
            "--manifest",
            str(_manifest("stage_1_national_core_sample.toml")),
            "--database-url",
            database_url,
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["manifest_name"] == "stage_1_national_core_sample"
    assert [item["status"] for item in payload["items"]] == [
        "ingested",
        "ingested",
        "ingested",
        "ingested",
    ]

    with Session(engine) as session:
        documents = session.execute(select(LegalDocument)).scalars().all()
        assert len(documents) == 4


def test_collection_cli_runs_all_manifests(capsys, tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'collection_all.db'}"

    manifest_dir = _repo_root() / "data" / "collection" / "manifests"

    exit_code = main(
        [
            "run-all-manifests",
            "--registry-dir",
            str(_registry_dir()),
            "--manifest-dir",
            str(manifest_dir),
            "--database-url",
            database_url,
            "--create-schema",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0

    expected_manifest_names = [
        tomllib.loads(p.read_text(encoding="utf-8"))["name"]
        for p in sorted(manifest_dir.glob("*.toml"))
    ]
    actual_manifest_names = [result["manifest_name"] for result in payload["results"]]
    assert actual_manifest_names == expected_manifest_names

    results_by_name = {result["manifest_name"]: result for result in payload["results"]}
    stage_2 = results_by_name["stage_2_representative_fanout_sample"]
    assert stage_2["items"][-1]["status"] == "skipped"
    assert stage_2["items"][-1]["reason"] == "blocked_pending_adapter"
