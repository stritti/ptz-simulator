# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_conventional_commits.py"
spec = importlib.util.spec_from_file_location("check_conventional_commits", SCRIPT)
ccc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ccc)

TYPES = ccc.allowed_types()


def test_types_come_from_release_please_config():
    assert {"feat", "fix", "perf", "docs", "refactor", "test", "ci", "chore"} <= set(TYPES)


@pytest.mark.parametrize(
    "header",
    [
        "feat: add NDI tally",
        "fix(onvif): report zoom position in GetStatus",
        "feat(cli)!: rename --port to --visca-port",
        "chore(main): release 0.2.0",
        "chore: update uv.lock",
    ],
)
def test_valid_headers(header):
    assert ccc.check(header, TYPES) is None


@pytest.mark.parametrize(
    "header",
    [
        "Update README",
        "WIP",
        "feature: add something",
        "fix:missing space",
        "fix(ONVIF): uppercase scope",
        "fix: ",
        "feat: " + "x" * 100,
    ],
)
def test_invalid_headers(header):
    assert ccc.check(header, TYPES) is not None
