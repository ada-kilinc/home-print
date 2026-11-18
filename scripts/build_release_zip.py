"""Build the release zip that HACS installs (``hacs.json``: ``zip_release``).

HACS downloads ``home_print.zip`` from the GitHub release and extracts it into
``custom_components/home_print/``, so the zip holds the integration's files at
its root. One archive means an update is either fully installed or not at all,
never a half-downloaded folder (for example a missing card file).

Usage:
    python scripts/build_release_zip.py --tag v0.3.5 \
        --source custom_components/home_print --out dist/home_print.zip

The tag must match ``manifest.json``'s version (a leading "v" is allowed).
The build fails if a file the integration can't run without is missing.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

REQUIRED = (
    "manifest.json",
    "__init__.py",
    "frontend/__init__.py",
    "frontend/home-print-card.js",
    "translations/en.json",
)
# Fixed timestamp: the same tree always gives the same bytes.
_EPOCH = (1980, 1, 1, 0, 0, 0)


def _files(source: Path) -> list[Path]:
    return sorted(
        path
        for path in source.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in (".pyc", ".pyo")
    )


def build(tag: str, source: Path, out: Path) -> int:
    """Write the zip; return the number of files, or raise ``SystemExit``."""
    manifest = source / "manifest.json"
    try:
        version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError) as err:
        raise SystemExit(f"Cannot read the version from {manifest}: {err}") from err
    if tag.removeprefix("v") != version:
        raise SystemExit(f"Tag {tag!r} does not match the manifest version {version!r}")
    files = _files(source)
    names = {path.relative_to(source).as_posix() for path in files}
    missing = [name for name in REQUIRED if name not in names]
    if missing:
        raise SystemExit("Missing from the integration: " + ", ".join(missing))

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), _EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    tmp.replace(out)
    return len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="release tag, e.g. v0.3.5")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    count = build(args.tag, args.source, args.out)
    print(f"{args.out}: {count} files for {args.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
