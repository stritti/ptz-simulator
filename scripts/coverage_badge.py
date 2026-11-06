# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Write a shields.io endpoint badge JSON for the measured test coverage.

The docs deployment (``.github/workflows/pages.yml``) runs the test suite and
this script on every push to ``main`` and publishes the result as
``coverage.json`` on GitHub Pages. The coverage badge in ``README.md`` and
``docs/index.md`` reads it via shields.io, so it always shows the coverage of
the latest ``main``:

    https://img.shields.io/endpoint?url=<urlencoded>/coverage.json

Usage: ``python3 scripts/coverage_badge.py [DATA_FILE] [OUTPUT_JSON]``
(defaults: ``.coverage`` -> ``docs/public/coverage.json``).
"""

import io
import json
import sys
from pathlib import Path

GATE = 80.0  # keep in sync with fail_under in pyproject.toml


def color_for(percent: float) -> str:
    """Badge colour by threshold; green means the coverage gate is met."""
    if percent >= 90:
        return "brightgreen"
    if percent >= GATE:
        return "green"
    if percent >= 60:
        return "yellow"
    if percent >= 40:
        return "orange"
    return "red"


def badge(percent: float, label: str = "coverage") -> dict:
    """shields.io endpoint badge payload (schemaVersion 1)."""
    return {
        "schemaVersion": 1,
        "label": label,
        "message": f"{percent:.1f}%",
        "color": color_for(percent),
        "cacheSeconds": 300,
    }


def total_percent(data_file: str) -> float:
    """Total statement coverage in percent from a coverage.py data file."""
    from coverage import Coverage

    cov = Coverage(data_file=data_file)
    cov.load()
    return cov.report(file=io.StringIO(), show_missing=False, skip_covered=True)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    data_file = argv[0] if len(argv) > 0 else ".coverage"
    output = argv[1] if len(argv) > 1 else str(Path("docs") / "public" / "coverage.json")
    percent = total_percent(data_file)
    payload = badge(percent)
    Path(output).write_text(json.dumps(payload) + "\n", encoding="utf-8")
    print(f"coverage badge: {payload['message']} ({payload['color']}) -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
