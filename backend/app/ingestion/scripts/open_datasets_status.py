from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.ingestion.scripts.open_datasets_common import (
    DATA_ROOT,
    DEFAULT_SPECS,
    RAW_ROOT,
    DatasetSpec,
    DatasetState,
    dataclass_to_dict,
    ensure_directories,
    huggingface_available,
    kaggle_cli_available,
    kaggle_credentials_present,
    local_state,
    load_source_config,
    now_iso,
    write_json,
)


def build_status_report(
    root: Path = RAW_ROOT,
    *,
    remote: bool = False,
) -> dict[str, object]:
    ensure_directories()
    config = load_source_config()
    rows: list[dict[str, object]] = []
    for spec in DEFAULT_SPECS:
        state = local_state(spec, root=root)
        rows.append(_to_status_row(spec, state, remote=remote))

    report = {
        "generated_at": now_iso(),
        "config": config.get("source_id", "open_research_datasets"),
        "raw_root": str(root),
        "data_root": str(DATA_ROOT),
        "targets": rows,
        "summary": {
            "local_ready": sum(1 for row in rows if row["exists"]),
            "manual_only": sum(1 for row in rows if row["manual_only"]),
            "credentialed_targets": sum(1 for row in rows if row["credentials_available"]),
        },
    }
    return report


def _to_status_row(
    spec: DatasetSpec,
    state: DatasetState,
    *,
    remote: bool,
) -> dict[str, object]:
    row = {
        **dataclass_to_dict(state),
        "family": spec.family,
        "kind": spec.kind,
        "manual_only": spec.manual_only,
        "credentials_available": _credentials_for(spec),
        "dependency_available": _dependency_for(spec),
    }
    if remote:
        row.update(_remote_status(spec))
    else:
        row["remote_status"] = "not_checked"
        row["remote_detail"] = "pass --remote to perform live availability checks"
    return row


def _credentials_for(spec: DatasetSpec) -> bool | None:
    if spec.family == "kaggle":
        return kaggle_credentials_present()
    if spec.family == "huggingface":
        return True
    return None


def _dependency_for(spec: DatasetSpec) -> bool | None:
    if spec.family == "kaggle":
        return kaggle_cli_available()
    if spec.family == "huggingface":
        return huggingface_available()
    return None


def _remote_status(spec: DatasetSpec) -> dict[str, object]:
    if spec.manual_only:
        return {
            "remote_status": "manual_request_only",
            "remote_detail": "The dataset is not directly downloadable; use the request workflow.",
        }

    if spec.family == "huggingface":
        return _remote_hf_status(spec)
    if spec.family == "kaggle":
        return _remote_kaggle_status(spec)
    return {
        "remote_status": "unknown",
        "remote_detail": "No remote probe implemented for this dataset family.",
    }


def _remote_hf_status(spec: DatasetSpec) -> dict[str, object]:
    try:
        from huggingface_hub import HfApi
    except Exception as exc:  # pragma: no cover - optional dependency
        return {
            "remote_status": "dependency_missing",
            "remote_detail": f"huggingface_hub unavailable: {type(exc).__name__}: {exc}",
        }

    try:
        api = HfApi()
        info = api.repo_info(repo_id=spec.dataset_id, repo_type=spec.repo_type or "dataset")
        siblings = getattr(info, "siblings", None) or []
        return {
            "remote_status": "available",
            "remote_detail": f"{len(siblings)} files exposed by repository metadata",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "remote_status": "unavailable",
            "remote_detail": f"{type(exc).__name__}: {exc}",
        }


def _remote_kaggle_status(spec: DatasetSpec) -> dict[str, object]:
    if not kaggle_credentials_present():
        return {
            "remote_status": "missing_credentials",
            "remote_detail": "Set KAGGLE_USERNAME/KAGGLE_KEY or place ~/.kaggle/kaggle.json.",
        }

    if not kaggle_cli_available():
        return {
            "remote_status": "dependency_missing",
            "remote_detail": "kaggle CLI is not available on PATH.",
        }

    return {
        "remote_status": "ready",
        "remote_detail": f"Kaggle CLI and credentials are present for {spec.dataset_id}.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report open research dataset readiness.")
    parser.add_argument("--root", type=Path, default=RAW_ROOT)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--remote", action="store_true")
    args = parser.parse_args(argv)

    report = build_status_report(args.root.resolve(), remote=args.remote)
    if args.output is not None:
        write_json(args.output.resolve(), report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
