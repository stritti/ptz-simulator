#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Stephan Strittmatter
# SPDX-License-Identifier: MIT

"""Validate NDI PTZ metadata XML (ntk_ptz_* elements) against the reference rules.

Reads metadata from a file argument or stdin (one or more XML elements), checks each
element: known ntk_ptz_* tag, required attributes present and numeric, preset index an
integer 0..99. Out-of-range values are reported as WARN (the reference clamps them);
unknown tags, missing or non-numeric attributes fail.

Usage:
    python3 ndi_metadata_check.py messages.xml
    cat messages.xml | python3 ndi_metadata_check.py

Exits 0 when no element FAILs (warnings allowed), 1 otherwise.
Standard library only, Python 3.8+.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

# tag -> {attribute: (low, high, is_int)}; "special" tags are checked in code
SPECS = {
    "ntk_ptz_pan_tilt": {"pan": (-1.0, 1.0, False), "tilt": (-1.0, 1.0, False)},
    "ntk_ptz_pan_tilt_speed": {"pan_speed": (-1.0, 1.0, False), "tilt_speed": (-1.0, 1.0, False)},
    "ntk_ptz_zoom": {"zoom": (0.0, 1.0, False)},
    "ntk_ptz_zoom_speed": {"zoom_speed": (-1.0, 1.0, False)},
    "ntk_ptz_focus_speed": {"distance": (-1.0, 1.0, False)},
    "ntk_ptz_store_preset": {"index": (0, 99, True)},
    "ntk_ptz_recall_preset": {"index": (0, 99, True), "speed": (0.0, 1.0, False)},
    # accepted by the reference but not simulated:
    "ntk_ptz_exposure": {},
    "ntk_ptz_iris": {},
    "ntk_ptz_flip": {},
}
SPECIAL = {"ntk_ptz_focus", "ntk_ptz_white_balance"}
WB_MODES = {"auto", "indoor", "outdoor", "one_shot", "manual"}


def check_element(elem, results):
    tag = elem.tag
    if not tag.startswith("ntk_ptz"):
        results.append(("FAIL", tag, "not an ntk_ptz_* element"))
        return
    if tag not in SPECS and tag not in SPECIAL:
        results.append(("FAIL", tag, "unknown ntk_ptz_* command (reference ignores it, not executed)"))
        return
    if tag in ("ntk_ptz_focus",):
        mode = elem.get("mode")
        if mode == "auto":
            results.append(("PASS", tag, "mode=auto"))
            return
        if mode == "manual" and "distance" in elem.attrib:
            level, detail = check_numeric("distance", elem.get("distance"), 0.0, 1.0)
            results.append((level, tag, detail))
            return
        results.append(("FAIL", tag, 'needs mode="auto" or mode="manual" distance="0..1"'))
        return
    if tag == "ntk_ptz_white_balance":
        mode = elem.get("mode")
        if mode in ("auto", "indoor", "outdoor", "one_shot"):
            results.append(("PASS", tag, "mode=%s" % mode))
            return
        if mode == "manual":
            if "red" not in elem.attrib or "blue" not in elem.attrib:
                results.append(("FAIL", tag, 'mode="manual" needs both red and blue (the reference rejects it)'))
                return
            levels = [check_numeric(n, elem.get(n), 0.0, 1.0) for n in ("red", "blue")]
            worst = "FAIL" if any(l == "FAIL" for l, _ in levels) else ("WARN" if any(l == "WARN" for l, _ in levels) else "PASS")
            results.append((worst, tag, "; ".join(d for _, d in levels)))
            return
        results.append(("WARN", tag, "unknown mode %r accepted+logged by the reference" % mode))
        return
    spec = SPECS[tag]
    levels = []
    for name, (low, high, is_int) in spec.items():
        if name not in elem.attrib:
            if tag == "ntk_ptz_recall_preset" and name == "speed":
                continue  # optional, defaults to 1
            levels.append(("FAIL", "missing attribute %r" % name))
            continue
        levels.append(check_numeric(name, elem.get(name), low, high, is_int))
    worst = "FAIL" if any(l == "FAIL" for l, _ in levels) else ("WARN" if any(l == "WARN" for l, _ in levels) else "PASS")
    results.append((worst, tag, "; ".join(d for _, d in levels) or " ".join("%s=%s" % kv for kv in sorted(elem.attrib.items()))))


def check_numeric(name, raw, low, high, is_int=False):
    """Return (level, detail) for one numeric attribute; the reference clamps floats
    but rejects an out-of-range preset index."""
    try:
        if is_int:
            # the reference parses preset indices with int(): "3.0"/"3e0" are rejected
            value = int(raw)
            if not isinstance(value, int):
                raise ValueError
        else:
            value = float(raw)
    except (TypeError, ValueError):
        return "FAIL", "attribute %r=%r is not a%s number" % (name, raw, "n integer" if is_int else "")
    if not low <= value <= high:
        if is_int:
            return "FAIL", "attribute %s=%s out of range %s..%s (the reference rejects it, not executed)" % (name, raw, low, high)
        return "WARN", "attribute %s=%s out of range %s..%s (the reference clamps)" % (name, raw, low, high)
    return "PASS", "%s=%s" % (name, raw)


def main() -> int:
    text = open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read()
    # a standalone document (possibly with an XML declaration) parses directly;
    # multiple sibling elements are parsed via a wrapper root
    try:
        root = ET.fromstring(text)
        elements = [root]
    except ET.ParseError:
        try:
            root = ET.fromstring("<root>%s</root>" % text)
            elements = list(root)
        except ET.ParseError as err:
            print("FAIL parse — not well-formed XML: %s" % err)
            return 1
    results = []
    for elem in elements:
        check_element(elem, results)
    for level, tag, detail in results:
        print("%s <%s> — %s" % (level, tag, detail))
    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print("\n%d elements: %d pass, %d warn, %d fail" % (len(results), len(results) - len(fails) - len(warns), len(warns), len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
