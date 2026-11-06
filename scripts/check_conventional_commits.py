#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Check that PR titles and commit subjects follow Conventional Commits.

The allowed types are read from the changelog sections in
release-please-config.json, so the check and Release Please never disagree.

Usage:
    check_conventional_commits.py "feat(onvif): add GetNodes"   # check arguments
    git log --format=%s base..head | check_conventional_commits.py -   # check stdin
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Iterable, List, Optional

CONFIG = Path(__file__).resolve().parent.parent / "release-please-config.json"
MAX_LENGTH = 100


def allowed_types(config_path: Path = CONFIG) -> List[str]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    types = []
    for package in config.get("packages", {}).values():
        for section in package.get("changelog-sections", []):
            if section["type"] not in types:
                types.append(section["type"])
    return types


def header_pattern(types: Iterable[str]) -> "re.Pattern[str]":
    alternatives = "|".join(re.escape(t) for t in types)
    return re.compile(
        r"^(?P<type>" + alternatives + r")"
        r"(?:\((?P<scope>[a-z0-9][a-z0-9._/-]*)\))?"
        r"(?P<breaking>!)?"
        r": (?P<description>\S.*)$"
    )


def check(header: str, types: List[str]) -> Optional[str]:
    """Return an error message, or None if the header is valid."""
    if not header_pattern(types).match(header):
        return (
            "expected '<type>[(scope)][!]: <description>' with type one of "
            + ", ".join(types)
        )
    if len(header) > MAX_LENGTH:
        return "longer than {} characters".format(MAX_LENGTH)
    return None


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    headers = sys.stdin.read().splitlines() if argv == ["-"] else argv
    types = allowed_types()
    failures = 0
    for header in (h.strip() for h in headers):
        if not header:
            continue
        error = check(header, types)
        if error:
            failures += 1
            print("✗ {!r}: {}".format(header, error))
        else:
            print("✓ {!r}".format(header))
    if failures:
        print(
            "\n{} header(s) do not follow Conventional Commits; see AGENTS.md "
            "(Pull request titles and commit messages).".format(failures)
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
