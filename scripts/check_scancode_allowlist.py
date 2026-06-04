#!/usr/bin/env python3
"""Fail CI if scancode-toolkit detects any license outside our allowlist.

Reads a scancode JSON output file (the `--json-pp` artifact) and walks
every file's `license_detections`. Each detection's `license_expression`
is split into its underlying license keys (SPDX-ish identifiers with
AND/OR/WITH operators removed) and every key is checked against
ALLOWED below. Any unrecognized key fails the script with a non-zero
exit code and a report.

SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Ewan Douglas and contributors
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# ScanCode license keys we accept in this repository, with rationale.
# Add new entries here (with a comment) when a legitimate detection
# triggers a failure.
ALLOWED: dict[str, str] = {
    # Our own code.
    "gpl-3.0-plus": "GPL-3.0-or-later — this project's own license.",
    "gpl-3.0": "GPL-3.0 — alias often co-detected with -plus from the LICENSE file.",
    # The GPL text itself references older GPL versions.
    "gpl-1.0-plus": "GPL-1.0-or-later — referenced by the GPL-3.0 license text.",
    "gpl-2.0-plus": "GPL-2.0-or-later — referenced by the GPL-3.0 license text.",
    # Runtime / docs dependencies (permissive, GPL-compatible).
    "apache-2.0":    "Apache-2.0 — requests dependency.",
    "bsd-new":       "BSD-3-Clause — Jinja2, sphinx_rtd_theme.",
    "bsd-simplified":"BSD-2-Clause — markdown, sphinx.",
    "mit":           "MIT — myst-parser, bundled jQuery in Sphinx output.",
    # Fonts bundled by sphinx_rtd_theme into built docs (excluded by ignore
    # patterns in CI, but listed here for completeness).
    "ofl-1.1": "OFL-1.1 — Lato / Font Awesome fonts in built docs.",
    # NASA Risk Management Handbook excerpts cited in test fixtures.
    "public-domain": "Public Domain — NASA-authored content cited in tests.",
}

OPERATORS = {"and", "or", "with"}
_TOKEN_RE = re.compile(r"[\s()]+")


def license_keys(expression: str) -> set[str]:
    return {
        t for t in _TOKEN_RE.split(expression.lower())
        if t and t not in OPERATORS
    }


def find_json(path: Path) -> Path:
    if path.is_file():
        return path
    if path.is_dir():
        for p in path.rglob("*.json"):
            try:
                if json.loads(p.read_text()).get("headers") is not None:
                    return p
            except (json.JSONDecodeError, OSError):
                continue
        raise SystemExit(f"No scancode JSON output found under {path}")
    raise SystemExit(f"Not found: {path}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: check_scancode_allowlist.py <path-to-scancode.json-or-dir>",
              file=sys.stderr)
        return 2
    src = find_json(Path(sys.argv[1]))
    data = json.loads(src.read_text())
    bad: list[tuple[str, str, str]] = []
    scanned = 0
    for f in data.get("files", []):
        if f.get("type") != "file":
            continue
        scanned += 1
        for det in (f.get("license_detections") or []):
            expr = det.get("license_expression") or ""
            for key in license_keys(expr):
                if key not in ALLOWED:
                    bad.append((f["path"], expr, key))
    if not bad:
        print(f"OK: scanned {scanned} files; all detected licenses are in "
              f"the allowlist ({len(ALLOWED)} keys).")
        return 0
    print(f"FAIL: {len(bad)} detection(s) outside the allowlist:")
    for path, expr, key in bad:
        print(f"  {path}\n    expression: {expr}\n    unrecognized key: {key!r}")
    print()
    print("If a finding is legitimate, add the key to ALLOWED in "
          "scripts/check_scancode_allowlist.py with a one-line rationale.")
    print("If a finding is from generated / vendored content that shouldn't"
          " be scanned, add an --ignore pattern to .github/workflows/scancode.yml.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
