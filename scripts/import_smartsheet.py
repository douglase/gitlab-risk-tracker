#!/usr/bin/env python3
"""Migrate Smartsheets risk text into GitLab issue descriptions.

Reads an .xlsx export with (at minimum) these columns:

  - ``GitLab Link``                 — full URL of the issue, e.g.
                                      https://gitlab.example.com/grp/proj/-/issues/123
  - ``Risk Description``            — body for the ``## Risk Description`` section
  - ``Action Plan/ Notes``          — body for the ``## Notes`` section
    (``Action Plan / Notes`` or ``Notes`` are also accepted)
  - ``Risk Mitigation Planning``    — body for the ``## Mitigation Plan`` section
    (``Mitigation Plan`` is also accepted)

For each row:

1. Parse the issue URL → ``server``, ``project_path``, ``iid``.
2. GET the current description via the GitLab REST API.
3. Walk the existing description's markdown headings. If a heading
   matches one of the three canonical sections, replace its body with
   the spreadsheet cell. Append any canonical sections that didn't
   already exist. Leave intro text, screenshots, and unrecognised
   headings alone.
4. If the new description differs from the old, PUT it back.

Designed to be safely re-runnable: running twice with the same xlsx
produces the same description. Heading synonyms mirror
``CANONICAL_SECTIONS`` in build.py so the dashboard recognises whatever
this script writes.

Quick start::

    pip install requests openpyxl
    export GITLAB_TOKEN=<token-with-api-scope>

    # Eyeball one issue first
    python scripts/import_smartsheet.py \\
        --xlsx ESC_Risk_Register.xlsx --issue 555 --dry-run

    # Eyeball the first three matched issues
    python scripts/import_smartsheet.py \\
        --xlsx ESC_Risk_Register.xlsx --limit 3 --dry-run

    # Full run for real
    python scripts/import_smartsheet.py --xlsx ESC_Risk_Register.xlsx

SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Ewan Douglas and contributors
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import openpyxl
import requests


# Mirrors build.py CANONICAL_SECTIONS, but with a *broader* synonym list
# so the importer also recognises legacy heading text. This is a one-way
# migration: legacy headings get replaced with the canonical form.
# Order matters: missing sections are appended in this order.
SECTIONS: list[tuple[str, str, list[str]]] = [
    ("risk_description", "Risk Description",
     ["risk description", "description", "summary"]),
    ("notes", "Notes",
     # Old shapes that should migrate to "Notes":
     ["notes", "action plan / notes", "action plan/ notes",
      "action plan/notes", "action plan", "action"]),
    ("mitigation_plan", "Mitigation Plan",
     ["mitigation plan", "risk mitigation planning", "risk mitigation",
      "mitigation", "plan", "planning"]),
]

# Spreadsheet column header (normalised lowercase) → canonical section key.
COL_HEADERS: dict[str, str] = {
    "risk description": "risk_description",
    "action plan / notes": "notes",
    "action plan/ notes": "notes",
    "action plan/notes": "notes",
    "notes": "notes",
    "risk mitigation planning": "mitigation_plan",
    "mitigation plan": "mitigation_plan",
}

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
ISSUE_URL_RE = re.compile(
    r"(?P<server>https?://[^/\s]+)"
    r"/(?P<path>.+?)"
    r"/-/(?:issues|work_items)/(?P<iid>\d+)"
)


def _normalise_heading(h: str) -> str:
    s = h.strip().rstrip(":").lower()
    s = re.sub(r"\s*/\s*", " / ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def canonical_key(heading: str) -> str | None:
    norm = _normalise_heading(heading)
    for key, _, syns in SECTIONS:
        if norm in syns:
            return key
    return None


def merge_sections(existing: str | None, new_sections: dict[str, str]) -> str:
    """Replace canonical sections in `existing` with `new_sections` values.

    - Sections already in `existing` get their body replaced; the heading
      is normalised to the canonical form (e.g. ``Risk Mitigation Planning``
      → ``Mitigation Plan``).
    - Sections present in `new_sections` but absent from `existing` are
      appended in canonical order.
    - Sections in `existing` that are not canonical are preserved verbatim
      in their original position.
    - If `existing` has more than one heading that resolves to the same
      canonical key, the first is replaced and subsequent duplicates are
      preserved verbatim (no content is dropped).
    """
    text = existing or ""
    matches = list(HEADING_RE.finditer(text))

    out: list[str] = []
    prefix = (text[:matches[0].start()] if matches else text).rstrip()
    if prefix:
        out.append(prefix + "\n\n")

    seen: set[str] = set()
    for i, m in enumerate(matches):
        heading = m.group(2)
        level = m.group(1)
        key = canonical_key(heading)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()

        if key in seen:
            # Already replaced this canonical key once. Preserve the
            # duplicate verbatim (with its original heading) rather than
            # silently dropping it — the user can clean up later.
            chunk = f"{level} {heading}\n\n"
            if body:
                chunk += body + "\n\n"
            out.append(chunk)
            continue
        if key and key in new_sections:
            canonical_h = next(s[1] for s in SECTIONS if s[0] == key)
            out.append(f"## {canonical_h}\n\n{new_sections[key].strip()}\n\n")
            seen.add(key)
        else:
            chunk = f"{level} {heading}\n\n"
            if body:
                chunk += body + "\n\n"
            out.append(chunk)

    # Append canonical sections that didn't already exist.
    for key, canonical_h, _ in SECTIONS:
        if key in new_sections and key not in seen:
            out.append(f"## {canonical_h}\n\n{new_sections[key].strip()}\n\n")

    return "".join(out).rstrip() + "\n"


def parse_issue_url(url: str) -> dict | None:
    m = ISSUE_URL_RE.search(url.strip())
    if not m:
        return None
    return {
        "server": m.group("server"),
        "project_path": m.group("path"),
        "iid": int(m.group("iid")),
    }


def read_xlsx(path: Path, sheet: str | None) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.active
    iter_rows = ws.iter_rows(values_only=True)
    try:
        header_row = next(iter_rows)
    except StopIteration:
        return []
    headers = [str(c or "").strip() for c in header_row]
    rows: list[dict] = []
    for raw in iter_rows:
        if not any(raw):
            continue
        rows.append({h: v for h, v in zip(headers, raw) if h})
    return rows


def extract_sections(row: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for header, value in row.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        key = COL_HEADERS.get(header.lower().strip())
        if key and key not in out:  # first column wins if duplicates
            out[key] = text
    return out


def find_link(row: dict) -> str | None:
    for k, v in row.items():
        if not v:
            continue
        kl = k.lower()
        if "gitlab" in kl and "link" in kl:
            return str(v)
    return None


def get_issue(session: requests.Session, server: str, project: str, iid: int) -> dict:
    url = f"{server}/api/v4/projects/{quote(project, safe='')}/issues/{iid}"
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def put_description(session: requests.Session, server: str, project: str,
                    iid: int, description: str) -> dict:
    url = f"{server}/api/v4/projects/{quote(project, safe='')}/issues/{iid}"
    r = session.put(url, json={"description": description}, timeout=30)
    r.raise_for_status()
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--xlsx", required=True, type=Path,
                    help="Smartsheets .xlsx export")
    ap.add_argument("--token",
                    help="GitLab access token with api scope "
                         "(falls back to GITLAB_TOKEN env var)")
    ap.add_argument("--token-env", default="GITLAB_TOKEN",
                    help="Env var name holding the token (default: GITLAB_TOKEN)")
    ap.add_argument("--server",
                    help="Override GitLab base URL (default: parse from each row's URL)")
    ap.add_argument("--sheet",
                    help="Worksheet name (default: active sheet)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print a unified diff per changed issue; do not write")
    ap.add_argument("--limit", type=int, default=0,
                    help="Process at most N matched rows (0 = no limit)")
    ap.add_argument("--issue", type=int,
                    help="Process only the issue with this iid (debugging)")
    ap.add_argument("--backup", type=Path,
                    default=Path(f"backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.jsonl"),
                    help="Append original issue descriptions to this file before writing")
    args = ap.parse_args()

    token = args.token or os.environ.get(args.token_env)
    if not token:
        print(f"error: set --token or ${args.token_env}", file=sys.stderr)
        return 2

    rows = read_xlsx(args.xlsx, args.sheet)
    print(f"Loaded {len(rows)} rows from {args.xlsx}"
          + (f" (sheet: {args.sheet})" if args.sheet else ""))

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    stats = dict(total=0, no_link=0, no_sections=0, no_change=0,
                 would_update=0, updated=0, errors=0)

    processed = 0
    with args.backup.open("a") as backup_f:
        for row in rows:
            stats["total"] += 1
            link = find_link(row)
            if not link:
                stats["no_link"] += 1
                continue
            parsed = parse_issue_url(str(link))
            if not parsed:
                print(f"  ! Unparseable GitLab Link: {link!r}", file=sys.stderr)
                stats["no_link"] += 1
                continue
            if args.issue and parsed["iid"] != args.issue:
                continue
            new_sections = extract_sections(row)
            if not new_sections:
                stats["no_sections"] += 1
                continue

            server = args.server or parsed["server"]
            project = parsed["project_path"]
            iid = parsed["iid"]
            try:
                issue = get_issue(session, server, project, iid)
            except requests.HTTPError as e:
                print(f"  ! GET {project}#{iid}: {e}", file=sys.stderr)
                stats["errors"] += 1
                continue

            current = issue.get("description") or ""
            backup_f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "server": server, "project": project, "iid": iid,
                "description": current,
            }) + "\n")

            new_desc = merge_sections(current, new_sections)
            if new_desc == current:
                stats["no_change"] += 1
                continue

            print(f"\n--- {project}#{iid} ---  ({issue.get('web_url') or link})")
            if args.dry_run:
                diff = "".join(difflib.unified_diff(
                    current.splitlines(keepends=True),
                    new_desc.splitlines(keepends=True),
                    fromfile="current", tofile="new", lineterm="",
                ))
                sys.stdout.write(diff or "(rewritten with no textual diff)\n")
                stats["would_update"] += 1
            else:
                try:
                    put_description(session, server, project, iid, new_desc)
                    print("  ✓ updated")
                    stats["updated"] += 1
                except requests.HTTPError as e:
                    print(f"  ! PUT {project}#{iid}: {e}", file=sys.stderr)
                    stats["errors"] += 1

            processed += 1
            if args.limit and processed >= args.limit:
                break

    print("\n=== Summary ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\nBackup of original descriptions: {args.backup}")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
