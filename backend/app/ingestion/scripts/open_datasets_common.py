from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11 fallback is not used here
    tomllib = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = REPO_ROOT / "data" / "collection"
RAW_ROOT = REPO_ROOT / "data" / "raw" / "open_research_datasets"
SOURCE_CONFIG_PATH = DATA_ROOT / "sources" / "open_research_datasets.toml"
REQUEST_MANIFEST_PATH = DATA_ROOT / "open_research_datasets_request_manifest.json"
INDEX_PATH = DATA_ROOT / "open_research_datasets_index.jsonl"
SUMMARY_PATH = DATA_ROOT / "open_research_datasets_summary.json"


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    dataset_id: str
    family: str
    kind: str
    source_url: str | None
    repo_type: str | None
    local_subdir: str
    manual_only: bool = False
    kaggle_dataset: str | None = None
    allow_patterns: tuple[str, ...] = ()
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetState:
    dataset_id: str
    family: str
    kind: str
    source_url: str | None
    local_path: str
    exists: bool
    file_count: int
    byte_count: int
    last_modified: str | None
    manual_only: bool
    credentials_available: bool | None = None
    dependency_available: bool | None = None
    remote_status: str | None = None
    remote_detail: str | None = None
    notes: str | None = None


DEFAULT_SPECS: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        dataset_id="opennyaiorg/InJudgements_dataset",
        family="huggingface",
        kind="dataset",
        source_url="https://huggingface.co/datasets/opennyaiorg/InJudgements_dataset",
        repo_type="dataset",
        local_subdir="huggingface/InJudgements_dataset",
        notes="Representative Supreme Court judgment sample used for parsing validation.",
    ),
    DatasetSpec(
        dataset_id="opennyaiorg/InLegalNER",
        family="huggingface",
        kind="dataset",
        source_url="https://huggingface.co/datasets/opennyaiorg/InLegalNER",
        repo_type="dataset",
        local_subdir="huggingface/InLegalNER",
        notes="Annotated legal NER sample for extraction quality checks.",
    ),
    DatasetSpec(
        dataset_id="ILDC",
        family="research",
        kind="dataset",
        source_url="https://github.com/Exploration-Lab/CJPE",
        repo_type=None,
        local_subdir="ildc",
        manual_only=True,
        notes="Request-only dataset; this tool writes an acquisition placeholder and status.",
    ),
    DatasetSpec(
        dataset_id="adarshsingh0903/legal-dataset-sc-judgments-india-19502024",
        family="kaggle",
        kind="dataset",
        source_url="https://www.kaggle.com/datasets/adarshsingh0903/legal-dataset-sc-judgments-india-19502024",
        repo_type=None,
        local_subdir="kaggle/sc_judgments",
        kaggle_dataset="adarshsingh0903/legal-dataset-sc-judgments-india-19502024",
        notes="Validation dataset for Supreme Court judgment coverage and consistency.",
    ),
)


def load_source_config(path: Path = SOURCE_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists() or tomllib is None:
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def ensure_directories() -> None:
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def safe_slug(value: str) -> str:
    return value.replace("/", "__").replace(":", "_").replace(" ", "_")


def dataset_path(spec: DatasetSpec, root: Path = RAW_ROOT) -> Path:
    return root / spec.local_subdir


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(base_dir: Path) -> list[Path]:
    if not base_dir.exists():
        return []
    return sorted(path for path in base_dir.rglob("*") if path.is_file())


def local_state(spec: DatasetSpec, root: Path = RAW_ROOT) -> DatasetState:
    base = dataset_path(spec, root)
    files = iter_files(base)
    latest_mtime: float | None = None
    for file_path in files:
        mtime = file_path.stat().st_mtime
        if latest_mtime is None or mtime > latest_mtime:
            latest_mtime = mtime
    return DatasetState(
        dataset_id=spec.dataset_id,
        family=spec.family,
        kind=spec.kind,
        source_url=spec.source_url,
        local_path=str(base),
        exists=base.exists(),
        file_count=len(files),
        byte_count=sum(file_path.stat().st_size for file_path in files),
        last_modified=datetime.fromtimestamp(latest_mtime, tz=UTC).isoformat()
        if latest_mtime is not None
        else None,
        manual_only=spec.manual_only,
        notes=spec.notes,
    )


def file_mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def kaggle_credentials_present() -> bool:
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return True
    return (Path.home() / ".kaggle" / "kaggle.json").exists()


def kaggle_cli_available() -> bool:
    return shutil.which("kaggle") is not None


def huggingface_available() -> bool:
    try:
        import huggingface_hub  # noqa: F401
    except Exception:  # pragma: no cover - dependency may be absent in stripped envs
        return False
    return True


def run_subprocess(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        capture_output=True,
        text=True,
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def dataclass_to_dict(instance: object) -> dict[str, Any]:
    return asdict(instance)
