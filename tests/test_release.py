# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest


@pytest.mark.skipif(os.name == "nt", reason="The release script requires a POSIX shell")
def test_standalone_release_contains_license(tmp_path):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "ptzsim").mkdir()
    shutil.copyfile(
        Path(__file__).resolve().parents[1] / "scripts" / "build-release.sh",
        project / "scripts" / "build-release.sh",
    )
    (project / "ptzsim" / "__init__.py").write_text("", encoding="utf-8")
    (project / "ptzsim" / "cli.py").write_text("def main():\n    pass\n", encoding="utf-8")
    license_text = "The complete license for this release.\n"
    (project / "LICENSE").write_text(license_text, encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\n[ "$1" = build ] || exit 1\nmkdir -p dist\n', encoding="utf-8")
    uv.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", os.defpath)
    result = subprocess.run(
        ["sh", str(project / "scripts" / "build-release.sh")],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Release build failed:\n{result.stdout}\n{result.stderr}"

    with zipfile.ZipFile(project / "dist" / "ptzsim.pyz") as archive:
        assert "LICENSE" in archive.namelist()
        assert archive.read("LICENSE").decode("utf-8") == license_text
