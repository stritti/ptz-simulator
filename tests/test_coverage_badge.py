# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Tests for scripts/coverage_badge.py (the shields.io coverage badge)."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("coverage_badge", ROOT / "scripts" / "coverage_badge.py")
badge_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(badge_script)

BADGE_URL = "https://img.shields.io/endpoint?url=" + quote(
    "https://stritti.github.io/ptz-simulator/coverage.json", safe="")


@pytest.mark.parametrize("percent, color", [
    (100.0, "brightgreen"), (94.7, "brightgreen"), (90.0, "brightgreen"),
    (80.0, "green"), (87.3, "green"), (79.9, "yellow"), (60.0, "yellow"),
    (59.9, "orange"), (40.0, "orange"), (39.9, "red"), (0.0, "red"),
])
def test_color_thresholds(percent, color):
    assert badge_script.color_for(percent) == color
    assert badge_script.GATE == 80.0  # the coverage gate in pyproject.toml


def test_badge_payload_is_shields_endpoint_schema():
    payload = badge_script.badge(94.68)
    assert payload == {
        "schemaVersion": 1,
        "label": "coverage",
        "message": "94.7%",
        "color": "brightgreen",
        "cacheSeconds": 300,
    }


def run_coverage(tmp_path, source):
    """Measure a small script with coverage.py and return the data file path."""
    target = tmp_path / "sample.py"
    target.write_text(source, encoding="utf-8")
    data_file = tmp_path / ".coverage"
    subprocess.run(
        [sys.executable, "-m", "coverage", "run", f"--data-file={data_file}", str(target)],
        cwd=tmp_path, check=True, capture_output=True)
    return data_file


def test_total_percent_of_a_fully_covered_script(tmp_path):
    data_file = run_coverage(tmp_path, "x = 1\nprint(x)\n")
    assert badge_script.total_percent(str(data_file)) == pytest.approx(100.0)


def test_total_percent_of_a_partially_covered_script(tmp_path):
    data_file = run_coverage(tmp_path, "x = 1\nif x > 5:\n    y = 2\n")
    percent = badge_script.total_percent(str(data_file))
    assert 0.0 < percent < 100.0  # the untaken branch line is missed


def test_main_writes_the_endpoint_json(tmp_path):
    data_file = run_coverage(tmp_path, "x = 1\nprint(x)\n")
    output = tmp_path / "public" / "coverage.json"
    output.parent.mkdir()
    assert badge_script.main([str(data_file), str(output)]) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == 1
    assert payload["label"] == "coverage"
    assert payload["message"] == "100.0%"
    assert payload["color"] == "brightgreen"


def test_main_defaults_to_the_docs_public_output(tmp_path, monkeypatch):
    data_file = run_coverage(tmp_path, "x = 1\n")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs" / "public").mkdir(parents=True)
    assert badge_script.main([str(data_file)]) == 0
    payload = json.loads((tmp_path / "docs" / "public" / "coverage.json").read_text(encoding="utf-8"))
    assert payload["message"].endswith("%")


def test_readme_and_docs_link_the_badge_to_the_published_json():
    for path in (ROOT / "README.md", ROOT / "docs" / "index.md"):
        text = path.read_text(encoding="utf-8")
        assert BADGE_URL in text, f"{path.name}: coverage badge with endpoint URL is missing"
