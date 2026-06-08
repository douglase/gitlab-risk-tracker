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
3. For each canonical section:

   - If the existing section's body matches the spreadsheet cell
     (modulo trailing whitespace / blank-line runs), do nothing.
   - If they differ, OR if the issue has no such section yet, append
     a clearly-marked **proposal block** at the end of the description
     containing the spreadsheet text and a unified diff against the
     current section. **The existing canonical section is never
     modified.**
4. If the new description differs from the old, PUT it back.

Designed to be safely re-runnable: each proposal block is wrapped in
``<!-- spreadsheet-import:proposal:KEY -->`` markers; the next run
strips its own prior blocks before evaluating, so unchanged data
produces no churn and updated spreadsheet rows refresh the block in
place.

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

import requests

# openpyxl is imported lazily inside read_xlsx() so the rest of this
# module (merge_sections, parse_issue_url, the heading-normalisation
# helpers, etc.) can be imported and unit-tested without it.


# Mirrors build.py CANONICAL_SECTIONS, but with a *broader* synonym list
# so the importer also recognises legacy heading text.
# Note: legacy headings are *preserved* in-place; the canonical form is
# only used for proposal block labels and for matching/comparison.
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


PROPOSAL_RE = re.compile(
    r"<!-- spreadsheet-import:proposal:(?P<key>[\w-]+) -->"
    r".*?"
    r"<!-- /spreadsheet-import:proposal:(?P=key) -->\n?",
    re.DOTALL,
)


def _normalise_heading(h: str) -> str:
    s = h.strip().rstrip(":").lower()
    s = re.sub(r"\s*/\s*", " / ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _normalise_body(body: str) -> str:
    """Trim trailing whitespace per line and collapse blank-line runs so
    whitespace-only differences are treated as a match."""
    if not body:
        return ""
    out: list[str] = []
    prev_blank = False
    for line in body.splitlines():
        line = line.rstrip()
        if not line:
            if not prev_blank:
                out.append("")
            prev_blank = True
        else:
            out.append(line)
            prev_blank = False
    return "\n".join(out).strip()


def _strip_proposals(text: str) -> str:
    """Remove any blocks previously appended by this script so re-runs
    don't accumulate duplicates."""
    return PROPOSAL_RE.sub("", text or "")


def canonical_key(heading: str) -> str | None:
    norm = _normalise_heading(heading)
    for key, _, syns in SECTIONS:
        if norm in syns:
            return key
    return None


def _build_proposal_block(key: str, canonical_h: str, new_body: str,
                          existing_body: str, today: str) -> str:
    """Render a markdown block proposing a new section value, with a diff."""
    diff_lines = list(difflib.unified_diff(
        existing_body.splitlines(),
        new_body.splitlines(),
        fromfile="current",
        tofile="spreadsheet",
        lineterm="",
    ))
    diff_text = "\n".join(diff_lines) if diff_lines else (
        "(no textual diff — whitespace or formatting only)"
    )
    if existing_body:
        intro = (
            f"The Smartsheets export differs from this issue's existing "
            f"`## {canonical_h}` content. Review the proposed text and diff "
            f"below. To accept, replace the section above with the proposed "
            f"text and delete this block."
        )
    else:
        intro = (
            f"The Smartsheets export has content for `## {canonical_h}` but "
            f"this issue does not yet have that section. Review and add it "
            f"manually; delete this block when done."
        )
    return (
        f"<!-- spreadsheet-import:proposal:{key} -->\n"
        f"### Spreadsheet import: proposed {canonical_h} ({today})\n\n"
        f"{intro}\n\n"
        f"**Proposed content:**\n\n"
        f"{new_body.rstrip()}\n\n"
        f"<details><summary>Unified diff vs current</summary>\n\n"
        f"```diff\n{diff_text}\n```\n\n"
        f"</details>\n"
        f"<!-- /spreadsheet-import:proposal:{key} -->"
    )


def merge_sections(existing: str | None, new_sections: dict[str, str],
                   today: str | None = None) -> str:
    """Append a 'proposed update' block for each canonical section whose
    body in ``existing`` differs from the value in ``new_sections``.

    Never modifies existing content: the canonical sections (and any other
    headings or prose) in ``existing`` are preserved verbatim. New
    information from the spreadsheet is appended at the end of the
    description, wrapped in HTML markers so re-runs can detect and
    refresh prior proposal blocks rather than duplicate them.

    Behavior per canonical section:

    - If the existing canonical section body matches the spreadsheet
      value (modulo trailing whitespace and blank-line runs), nothing
      is appended for that section.
    - If they differ, OR if no matching canonical heading exists in
      ``existing``, a proposal block is appended at the end of the
      description with the new content and a unified diff for review.
    - Sections not present in ``new_sections`` are ignored.

    Idempotent: prior proposal blocks (matched by HTML markers) are
    stripped before new ones are appended, so re-running the importer
    with unchanged spreadsheet data does not accumulate duplicate
    blocks.
    """
    if today is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Strip out any proposal blocks added by a prior run; otherwise
    # we'd compare the spreadsheet against our own earlier proposal.
    text = _strip_proposals(existing or "")

    # Find the first body for each canonical section already in text.
    matches = list(HEADING_RE.finditer(text))
    existing_bodies: dict[str, str] = {}
    for i, m in enumerate(matches):
        key = canonical_key(m.group(2))
        if not key or key in existing_bodies:
            continue
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        existing_bodies[key] = text[body_start:body_end].strip()

    # Build proposal blocks for canonical keys whose bodies differ.
    proposals: list[str] = []
    for key, canonical_h, _ in SECTIONS:
        if key not in new_sections:
            continue
        new_body = new_sections[key].strip()
        existing_body = existing_bodies.get(key, "")
        if _normalise_body(existing_body) == _normalise_body(new_body):
            continue
        proposals.append(_build_proposal_block(
            key, canonical_h, new_body, existing_body, today,
        ))

    if not proposals:
        return text
    sep = "\n\n" if text else ""
    return f"{text}{sep}" + "\n\n".join(proposals) + "\n"


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
    import openpyxl  # lazy: only needed for the main CLI flow
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
