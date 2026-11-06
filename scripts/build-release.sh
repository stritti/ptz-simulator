#!/bin/sh
# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

# Builds the release artifacts into dist/: wheel, sdist and the standalone
# ptzsim.pyz (runs with any Python >= 3.8, no installation needed).
set -eu
cd "$(dirname "$0")/.."

rm -rf dist build/pyz
uv build

mkdir -p build/pyz
cp -R ptzsim build/pyz/
find build/pyz -name __pycache__ -type d -prune -exec rm -rf {} +
find build/pyz -type f ! -name '*.py' -delete
cp LICENSE build/pyz/LICENSE
python3 -m zipapp build/pyz -m "ptzsim.cli:main" -p "/usr/bin/env python3" -c -o dist/ptzsim.pyz
rm -rf build/pyz

python3 dist/ptzsim.pyz --help > /dev/null
ls -l dist
