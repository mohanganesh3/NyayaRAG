from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from app.ingestion.scripts.open_datasets_common import (
    DATA_ROOT,
    DEFAULT_SPECS,
    RAW_ROOT,
    REQUEST_MANIFEST_PATH,
    DatasetSpec,
    dataclass_to_dict,
    ensure_directories,
    kaggle_cli_available,
    kaggle_credentials_present,
    load_source_config,
    now_iso,
    run_subprocess,
    safe_slug,
    write_json,
)


@dataclass(frozen=True, slots=True)
class DownloadResult:
    dataset_id: str
    status: str
    destination: str | None = None
    detail: str | None = None


def build_download_plan(
    targets: list[str],
    *,
    root: Path = RAW_ROOT,
    dry_run: bool = False,
    request_manifest_path: Path = REQUEST_MANIFEST_PATH,
) -> dict[str, object]:
    ensure_directories()
    config = load_source_config()
    specs = _resolve_specs(targets)
    results = [
        _download_spec(
            spec,
            root=root,
            dry_run=dry_run,
            request_manifest_path=request_manifest_path,
        )
        for spec in specs
    ]
    report = {
        "generated_at": now_iso(),
        "config": config.get("source_id", "open_research_datasets"),
        "raw_root": str(root),
        "data_root": str(DATA_ROOT),
        "results": [dataclass_to_dict(result) for result in results],
    }
    return report


def _resolve_specs(targets: list[str]) -> list[DatasetSpec]:
    if not targets or "all" in targets:
        return list(DEFAULT_SPECS)

    wanted = set(targets)
    selected: list[DatasetSpec] = []
    for spec in DEFAULT_SPECS:
        if (
            spec.dataset_id in wanted
            or spec.family in wanted
            or spec.kind in wanted
            or safe_slug(spec.dataset_id) in wanted
        ):
            selected.append(spec)
    if not selected:
        raise SystemExit(f"no known dataset targets matched: {', '.join(targets)}")
    return selected


def _download_spec(
    spec: DatasetSpec,
    *,
    root: Path,
    dry_run: bool,
    request_manifest_path: Path,
) -> DownloadResult:
    destination = root / spec.local_subdir
    if spec.manual_only:
        payload = {
            "generated_at": now_iso(),
            "dataset_id": spec.dataset_id,
            "family": spec.family,
            "kind": spec.kind,
            "source_url": spec.source_url,
            "notes": spec.notes,
            "instruction": "Acquire manually from the source repository or grant access before rerunning.",
        }
        write_json(request_manifest_path, payload)
        return DownloadResult(
            dataset_id=spec.dataset_id,
            status="manual_request_only",
            destination=str(request_manifest_path),
            detail="wrote request manifest",
        )

    if dry_run:
        return DownloadResult(
            dataset_id=spec.dataset_id,
            status="dry_run",
            destination=str(destination),
            detail="no files were fetched",
        )

    if spec.family == "huggingface":
        return _download_huggingface(spec, destination)
    if spec.family == "kaggle":
        return _download_kaggle(spec, destination)

    return DownloadResult(
        dataset_id=spec.dataset_id,
        status="unsupported",
        destination=str(destination),
        detail="no downloader implemented for this dataset family",
    )


def _download_huggingface(spec: DatasetSpec, destination: Path) -> DownloadResult:
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # pragma: no cover - optional dependency
        return DownloadResult(
            dataset_id=spec.dataset_id,
            status="dependency_missing",
            destination=str(destination),
            detail=f"huggingface_hub unavailable: {type(exc).__name__}: {exc}",
        )

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fetched = snapshot_download(
            repo_id=spec.dataset_id,
            repo_type=spec.repo_type or "dataset",
            local_dir=str(destination),
            local_dir_use_symlinks=False,
            resume_download=True,
            allow_patterns=list(spec.allow_patterns) or None,
        )
        return DownloadResult(
            dataset_id=spec.dataset_id,
            status="downloaded",
            destination=fetched,
            detail="snapshot_download completed",
        )
    except Exception as exc:  # noqa: BLE001
        return DownloadResult(
            dataset_id=spec.dataset_id,
            status="failed",
            destination=str(destination),
            detail=f"{type(exc).__name__}: {exc}",
        )


def _download_kaggle(spec: DatasetSpec, destination: Path) -> DownloadResult:
    if not kaggle_credentials_present():
        return DownloadResult(
            dataset_id=spec.dataset_id,
            status="missing_credentials",
            destination=str(destination),
            detail="set KAGGLE_USERNAME/KAGGLE_KEY or create ~/.kaggle/kaggle.json",
        )
    if not kaggle_cli_available():
        return DownloadResult(
            dataset_id=spec.dataset_id,
            status="dependency_missing",
            destination=str(destination),
            detail="kaggle CLI is not installed",
        )

    destination.mkdir(parents=True, exist_ok=True)
    command = ["kaggle", "datasets", "download", "-d", spec.kaggle_dataset or spec.dataset_id, "-p", str(destination), "--unzip"]
    completed = run_subprocess(command)
    if completed.returncode != 0:
        return DownloadResult(
            dataset_id=spec.dataset_id,
            status="failed",
            destination=str(destination),
            detail=(completed.stderr or completed.stdout or "unknown kaggle failure").strip(),
        )
    return DownloadResult(
        dataset_id=spec.dataset_id,
        status="downloaded",
        destination=str(destination),
        detail="kaggle download completed",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download open research datasets.")
    parser.add_argument("targets", nargs="*", help="Dataset ids, families, or 'all'")
    parser.add_argument("--root", type=Path, default=RAW_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--request-manifest-path", type=Path, default=REQUEST_MANIFEST_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    report = build_download_plan(
        args.targets,
        root=args.root.resolve(),
        dry_run=args.dry_run,
        request_manifest_path=args.request_manifest_path.resolve(),
    )
    if args.output is not None:
        write_json(args.output.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
