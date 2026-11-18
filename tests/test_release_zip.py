"""The release zip that HACS installs (zip_release)."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "build_release_zip.py"
SOURCE = ROOT / "custom_components" / "home_print"


def _version() -> str:
    return json.loads((SOURCE / "manifest.json").read_text())["version"]


def _build(tmp_path, tag, source=SOURCE):
    out = tmp_path / "home_print.zip"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(SCRIPT),
            "--tag",
            tag,
            "--source",
            str(source),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result, out


def test_zip_has_the_integration_files_at_its_root(tmp_path):
    result, out = _build(tmp_path, f"v{_version()}")
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
        assert archive.testzip() is None
    # HACS extracts the zip into custom_components/home_print/ itself.
    for required in (
        "manifest.json",
        "__init__.py",
        "frontend/home-print-card.js",
        "frontend/__init__.py",
        "translations/en.json",
        "translations/tr.json",
        "escl/client.py",
        "convert/render.py",
        "brand/icon.png",
    ):
        assert required in names, required
    assert not any(n.startswith("custom_components/") for n in names)
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    expected = {
        str(p.relative_to(SOURCE)).replace("\\", "/")
        for p in SOURCE.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    assert names == expected


def test_zip_is_reproducible(tmp_path):
    first, out1 = _build(tmp_path / "a", f"v{_version()}")
    second, out2 = _build(tmp_path / "b", f"v{_version()}")
    assert first.returncode == second.returncode == 0
    assert out1.read_bytes() == out2.read_bytes()


@pytest.mark.parametrize("tag", ["v0.0.1", "0.0.1", "latest"])
def test_tag_must_match_manifest_version(tmp_path, tag):
    result, out = _build(tmp_path, tag)
    assert result.returncode != 0
    assert "manifest" in result.stderr
    assert not out.exists()


def test_missing_card_file_fails_the_build(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps({"version": "1.2.3"}))
    (source / "__init__.py").write_text("")
    result, out = _build(tmp_path, "v1.2.3", source)
    assert result.returncode != 0
    assert "frontend/home-print-card.js" in result.stderr
    assert not out.exists()


def test_hacs_json_installs_the_zip():
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "home_print.zip"


def test_release_workflow_uploads_the_zip():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "build_release_zip.py" in workflow
    assert "gh release upload" in workflow
    assert "home_print.zip" in workflow
