from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="solve_itat_captcha",
        description="Solve an ITAT captcha image with ddddocr.",
    )
    parser.add_argument("image_path", nargs="?")
    parser.add_argument(
        "--server",
        action="store_true",
        help="Run as a tiny line-oriented OCR server that accepts image paths on stdin.",
    )
    return parser


def _solve(image_path: str) -> str:
    import ddddocr  # Imported lazily so this script can exist without the package in the main env.

    classifier = _solve._classifier  # type: ignore[attr-defined]
    if classifier is None:
        classifier = ddddocr.DdddOcr(show_ad=False)
        _solve._classifier = classifier  # type: ignore[attr-defined]
    data = Path(image_path).read_bytes()
    return str(classifier.classification(data)).strip()


_solve._classifier = None  # type: ignore[attr-defined]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.server:
        for line in sys.stdin:
            path = line.strip()
            if not path:
                continue
            try:
                print(_solve(path), flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"ERROR:{type(exc).__name__}:{exc}", flush=True)
        return 0

    if not args.image_path:
        raise SystemExit("image_path is required unless --server is used")

    print(_solve(args.image_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
