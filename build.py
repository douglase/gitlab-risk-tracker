"""Build the stp risks dashboard.

Pulls work-item issues from the `stp` group (recursive), snapshots changed
field values to data/history.ndjson, and renders public/index.html.

Designed to run inside a GitLab CI job; can also run locally with
GITLAB_TOKEN and (optionally) CI_SERVER_URL exported.

SPDX-License-Identifier: GPL-3.0-or-later
Copyright (C) 2026 Ewan Douglas and contributors
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import markdown as md_lib
import nh3
import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "data" / "history.ndjson"
PUBLIC_DIR = ROOT / "public"
TEMPLATE_DIR = ROOT / "templates"

GROUP_PATH = os.environ.get("RISK_GROUP_PATH", "stp")
SUBSYSTEMS = ["optics", "thermal", "software", "mechanical", "electrical"]

CF_CONSEQUENCE = "Consequence (C)"
CF_LIKELIHOOD = "Likelihood (L)"
CF_PRIORITY = "Priority Level"
CF_RISK_TYPE = "Risk Type"

PAGE_SIZE = 100

RISK_PREFIX_RE = re.compile(
    r"^\s*risk\s*#\s*[A-Z0-9]+\s*[:\-–—]?\s*",
    re.IGNORECASE,
)

# Regex patterns identifying product labels. Any label matching one of these
# regexes (case-insensitive) is collected into the combined "Product" filter.
PRODUCT_PATTERNS: list[str] = [
    r"^TO\d",
    r"^ESC",
    r"^WCC",
]
PRODUCT_REGEXES = [re.compile(p, re.IGNORECASE) for p in PRODUCT_PATTERNS]


def match_products(labels: list[str]) -> list[str]:
    matched = {l for l in labels if any(r.match(l) for r in PRODUCT_REGEXES)}
    return sorted(matched)


def risk_label_filter() -> str:
    """Substring (case-insensitive) that must appear in at least one of
    an issue's labels for that issue to be included in the dashboard.

    Set the ``RISK_LABEL_FILTER`` env var to override; default ``"risk"``.
    Set it to the empty string to disable the filter and include every
    work item the GraphQL query returns.
    """
    return os.environ.get("RISK_LABEL_FILTER", "risk")


def is_risk_labelled(item: dict) -> bool:
    """True iff at least one of `item`'s labels contains the
    ``risk_label_filter()`` substring (case-insensitive). When the
    filter is empty, returns True for everything."""
    needle = risk_label_filter().lower()
    if not needle:
        return True
    return any(needle in lbl.lower() for lbl in item.get("labels", []))


MAX_PREVIEW_CHARS = 280

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

# Canonical section keys + accepted heading synonyms (normalized form).
CANONICAL_SECTIONS: list[tuple[str, str, list[str]]] = [
    ("risk_description", "Risk Description",
     ["risk description", "description", "summary"]),
    ("notes", "Notes",
     ["notes"]),
    ("mitigation_plan", "Mitigation Plan",
     ["mitigation plan", "risk mitigation planning", "risk mitigation",
      "mitigation", "plan", "planning"]),
]


def _normalize_heading(heading: str) -> str:
    s = heading.strip().rstrip(":").lower()
    s = re.sub(r"\s*/\s*", " / ", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _canonical_section_key(heading: str) -> str | None:
    norm = _normalize_heading(heading)
    for key, _, syns in CANONICAL_SECTIONS:
        if norm in syns:
            return key
    return None


def parse_sections(markdown_text: str | None) -> dict[str, str]:
    """Parse markdown into {canonical_key: raw_markdown_content}.

    Fallback: when no ``risk_description`` heading is present but the
    description has leading prose (any text before the first markdown
    heading, or the whole body if there are no headings at all), that
    prose becomes the Risk Description. This lets issues whose body is
    just a one-liner risk statement — no ``## Risk Description`` header —
    still surface their description in the dashboard.
    """
    if not markdown_text:
        return {}
    sections: dict[str, str] = {}
    matches = list(HEADING_RE.finditer(markdown_text))
    for i, m in enumerate(matches):
        key = _canonical_section_key(m.group(2))
        if not key:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown_text)
        sections[key] = markdown_text[start:end].strip()
    if "risk_description" not in sections:
        leading_end = matches[0].start() if matches else len(markdown_text)
        leading = markdown_text[:leading_end].strip()
        if leading:
            sections["risk_description"] = leading
    return sections


_MD = md_lib.Markdown(
    extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
    output_format="html5",
)

# Allowlist for nh3 HTML sanitization. Issue descriptions are user-controlled
# text, so the rendered HTML must be sanitized before it's injected into the
# dashboard via innerHTML. Covers everything Python-Markdown can emit with
# the extensions we enable; raw <script>, <iframe>, javascript: URLs, etc.
# are dropped by default.
_HTML_TAGS: set[str] = {
    "a", "abbr", "b", "blockquote", "br", "code", "del", "em",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "i", "img", "ins", "li", "ol", "p", "pre", "strong",
    "sub", "sup", "table", "tbody", "td", "th", "thead", "tr", "ul",
}
_HTML_ATTRS: dict[str, set[str]] = {
    "*": {"class"},
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "th": {"align"},
    "td": {"align"},
}
_URL_SCHEMES: set[str] = {"http", "https", "mailto"}


def render_markdown(text: str | None) -> str:
    if not text:
        return ""
    _MD.reset()
    return nh3.clean(
        _MD.convert(text),
        tags=_HTML_TAGS,
        attributes=_HTML_ATTRS,
        url_schemes=_URL_SCHEMES,
    )


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def plain_text(html: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub("", html or "")).strip()


def truncate_preview(text: str, n: int = MAX_PREVIEW_CHARS) -> tuple[str, bool]:
    text = (text or "").strip()
    if len(text) <= n:
        return text, False
    return text[:n].rstrip() + "…", True


def render_section(md_text: str | None) -> dict:
    html = render_markdown(md_text)
    full = plain_text(html)
    preview, has_more = truncate_preview(full)
    return {"html": html, "preview": preview, "full_text": full, "has_more": has_more}


_SLUG_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def _slugify(s: str) -> str:
    """Match GitLab's heading-id slug for a header text (lowercase,
    non-alphanumerics collapsed to dashes, stripped)."""
    return _SLUG_NON_ALNUM.sub("-", s).strip("-").lower()


def clean_title(title: str | None) -> str:
    if not title:
        return ""
    stripped = RISK_PREFIX_RE.sub("", title).strip()
    return stripped or title.strip()


def gitlab_url() -> str:
    base = os.environ.get("CI_SERVER_URL") or os.environ.get("GITLAB_URL")
    if not base:
        sys.exit("Set CI_SERVER_URL or GITLAB_URL (e.g. https://gitlab.example.com).")
    return base.rstrip("/")


def graphql(query: str, variables: dict) -> dict:
    token = os.environ.get("GITLAB_TOKEN")
    if not token:
        sys.exit("GITLAB_TOKEN is not set.")
    resp = requests.post(
        f"{gitlab_url()}/api/graphql",
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        sys.exit(f"GraphQL errors: {json.dumps(payload['errors'], indent=2)}")
    return payload["data"]


SCHEMA_CHECK_QUERY = """
{
  __type(name: "Group") {
    fields { name }
  }
  workItemsField: __type(name: "Group") {
    fields(includeDeprecated: false) {
      name
      args { name }
    }
  }
  widgets: __type(name: "WorkItemWidgetCustomFields") {
    name
    fields { name }
  }
}
"""


def schema_check() -> None:
    """Probe the schema to warn early if this GitLab instance doesn't expose
    what we expect. Non-fatal — some instances restrict GraphQL introspection
    on experimental fields even though the actual query works. Falls through
    to fetch_work_items() which will surface the real error if any."""
    try:
        data = graphql(SCHEMA_CHECK_QUERY, {})
    except SystemExit:
        raise
    except Exception as e:
        print(f"warning: schema introspection failed ({e}); continuing.", file=sys.stderr)
        return
    group_fields = {f["name"] for f in (data.get("workItemsField") or {}).get("fields", [])}
    if "workItems" not in group_fields:
        print(
            "warning: Group.workItems not visible via introspection on this instance. "
            "This is sometimes a permissions / introspection-restriction quirk on "
            "experimental fields; will attempt the real query anyway.",
            file=sys.stderr,
        )
        return
    work_items_args = next(
        (f["args"] for f in data["workItemsField"]["fields"] if f["name"] == "workItems"),
        [],
    )
    arg_names = {a["name"] for a in work_items_args}
    if "includeDescendants" not in arg_names:
        print(
            f"warning: Group.workItems(includeDescendants:) not visible via introspection. "
            f"Available args: {sorted(arg_names)}. Continuing.",
            file=sys.stderr,
        )
    if not data.get("widgets"):
        print(
            "warning: WorkItemWidgetCustomFields type not visible via introspection. Continuing.",
            file=sys.stderr,
        )


WORK_ITEMS_QUERY = """
query($group: ID!, $cursor: String) {
  group(fullPath: $group) {
    workItems(
      types: [ISSUE]
      includeDescendants: true
      first: %d
      after: $cursor
    ) {
      pageInfo { endCursor hasNextPage }
      nodes {
        id
        iid
        title
        state
        webUrl
        createdAt
        updatedAt
        closedAt
        widgets {
          ... on WorkItemWidgetLabels {
            type
            labels { nodes { title } }
          }
          ... on WorkItemWidgetDescription {
            type
            description
          }
          ... on WorkItemWidgetAssignees {
            type
            assignees {
              nodes { id username name webUrl }
            }
          }
          ... on WorkItemWidgetHealthStatus {
            type
            healthStatus
          }
          ... on WorkItemWidgetCustomFields {
            type
            customFieldValues {
              customField { id name fieldType }
              ... on WorkItemSelectFieldValue {
                selectedOptions { id value }
              }
              ... on WorkItemNumberFieldValue { value }
              ... on WorkItemTextFieldValue { value }
            }
          }
        }
      }
    }
  }
}
""" % PAGE_SIZE


def fetch_work_items() -> list[dict]:
    raw: list[dict] = []
    cursor: str | None = None
    while True:
        data = graphql(WORK_ITEMS_QUERY, {"group": GROUP_PATH, "cursor": cursor})
        group = data.get("group")
        if not group:
            sys.exit(f"Group '{GROUP_PATH}' not found or token lacks access.")
        conn = group["workItems"]
        raw.extend(conn["nodes"])
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    # Defensive dedup by global id. GitLab's recursive group.workItems
    # pagination should not return the same node twice, but if it ever
    # does (e.g. due to a project being shared across two subgroups or
    # a concurrent create during pagination), we'd double-count the
    # issue in the matrix and the risks table.
    seen: set[str] = set()
    items: list[dict] = []
    duplicates = 0
    for it in raw:
        gid = it.get("id")
        if gid and gid in seen:
            duplicates += 1
            continue
        if gid:
            seen.add(gid)
        items.append(it)
    if duplicates:
        print(
            f"warning: fetch_work_items returned {duplicates} duplicate node(s); "
            f"deduped by id.",
            file=sys.stderr,
        )
    return items


def select_value(values: list, name: str) -> str | None:
    for v in values:
        if v["customField"]["name"] == name:
            opts = v.get("selectedOptions") or []
            if opts:
                return opts[0]["value"]
            return v.get("value")
    return None


def select_multi(values: list, name: str) -> list[str]:
    for v in values:
        if v["customField"]["name"] == name:
            opts = v.get("selectedOptions") or []
            return [o["value"] for o in opts]
    return []


def to_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def normalize(item: dict) -> dict:
    labels: list[str] = []
    cf_values: list = []
    description: str = ""
    assignees: list[dict] = []
    health_status: str | None = None
    for w in item.get("widgets") or []:
        wtype = w.get("type")
        if wtype == "LABELS":
            labels = [n["title"] for n in (w.get("labels") or {}).get("nodes", [])]
        elif wtype == "DESCRIPTION":
            description = w.get("description") or ""
        elif wtype == "ASSIGNEES":
            assignees = [
                {
                    "name": (n.get("name") or n.get("username") or "").strip(),
                    "username": n.get("username"),
                    "web_url": n.get("webUrl"),
                }
                for n in (w.get("assignees") or {}).get("nodes", [])
            ]
        elif wtype == "HEALTH_STATUS":
            health_status = w.get("healthStatus")
        elif wtype == "CUSTOM_FIELDS":
            cf_values = w.get("customFieldValues") or []
    subsystems = sorted(set(labels) & set(SUBSYSTEMS))
    products = match_products(labels)
    other_labels = sorted(set(labels) - set(SUBSYSTEMS) - set(products))
    return {
        "labels": labels,
        "id": item["id"],
        "iid": item["iid"],
        "title": item["title"],
        "display_title": clean_title(item["title"]),
        "state": item["state"].lower(),
        "web_url": item["webUrl"],
        "created_at": item.get("createdAt"),
        "updated_at": item.get("updatedAt"),
        "closed_at": item.get("closedAt"),
        "consequence": to_int(select_value(cf_values, CF_CONSEQUENCE)),
        "likelihood": to_int(select_value(cf_values, CF_LIKELIHOOD)),
        "priority": select_value(cf_values, CF_PRIORITY),
        "risk_types": select_multi(cf_values, CF_RISK_TYPE),
        "subsystems": subsystems,
        "products": products,
        "other_labels": other_labels,
        "assignees": assignees,
        "health_status": health_status,
        "description": description,
        "sections": parse_sections(description),
    }


SNAPSHOT_FIELDS = (
    "state",
    "consequence",
    "likelihood",
    "priority",
    "risk_types",
    "subsystems",
)


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    rows: list[dict] = []
    with HISTORY_PATH.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def snapshot_tuple(row: dict) -> tuple:
    return tuple(
        tuple(row[k]) if isinstance(row.get(k), list) else row.get(k)
        for k in SNAPSHOT_FIELDS
    )


def append_history(rows_to_append: list[dict]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_PATH.open("a") as f:
        for r in rows_to_append:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def update_history(current: list[dict], history: list[dict]) -> list[dict]:
    """Append change-events for new/changed items and synthetic closures
    for items that disappeared from the query."""
    latest_by_id: dict[str, dict] = {}
    for r in history:
        latest_by_id[r["id"]] = r

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_rows: list[dict] = []

    current_ids = set()
    for item in current:
        current_ids.add(item["id"])
        prev = latest_by_id.get(item["id"])
        row = {
            "ts": now,
            "id": item["id"],
            "iid": item["iid"],
            "title": item["title"],
            "state": item["state"],
            "consequence": item["consequence"],
            "likelihood": item["likelihood"],
            "priority": item["priority"],
            "risk_types": item["risk_types"],
            "subsystems": item["subsystems"],
            "web_url": item["web_url"],
        }
        if prev is None or snapshot_tuple(prev) != snapshot_tuple(row):
            new_rows.append(row)

    for hid, prev in latest_by_id.items():
        if hid in current_ids:
            continue
        if prev.get("state") == "closed":
            continue
        new_rows.append(
            {
                **prev,
                "ts": now,
                "state": "closed",
            }
        )

    append_history(new_rows)
    return history + new_rows


def severity_tier(c: int | None, l: int | None) -> str:
    if c is None or l is None:
        return "unscored"
    score = c * l
    if score >= 16:
        return "critical"
    if score >= 10:
        return "high"
    if score >= 5:
        return "medium"
    return "low"


def reconstruct_state_at(history: list[dict], when: datetime) -> dict[str, dict]:
    cutoff = when.isoformat(timespec="seconds")
    latest: dict[str, dict] = {}
    for r in history:
        if r["ts"] <= cutoff:
            latest[r["id"]] = r
    return latest


def trend_series(history: list[dict], days: int = 90) -> dict:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    labels: list[str] = []
    series: dict[str, list[int]] = {
        "critical": [],
        "high": [],
        "medium": [],
        "low": [],
    }
    for i in range(days):
        day = start + timedelta(days=i)
        labels.append(day.isoformat())
        when = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)
        state = reconstruct_state_at(history, when)
        counts = Counter()
        for r in state.values():
            if r.get("state") == "closed":
                continue
            counts[severity_tier(r.get("consequence"), r.get("likelihood"))] += 1
        for tier in series:
            series[tier].append(counts.get(tier, 0))
    return {"labels": labels, "series": series}


def risk_score_series(history: list[dict], current_items: list[dict],
                      days: int = 90) -> dict:
    """Per-risk score (consequence * likelihood) over the last `days` days.

    Returns one series per risk id that currently exists in `current_items`
    and is scored. Score on a given day is null if the risk wasn't yet known
    or was closed. Attaches current filterable attributes so the JS chart
    can hide non-matching series when filters change.
    """
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    labels = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    by_id = {it["id"]: it for it in current_items}
    score_by_day: dict[str, list[int | None]] = {
        rid: [None] * days for rid in by_id
    }
    for i in range(days):
        day = start + timedelta(days=i)
        when = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)
        state = reconstruct_state_at(history, when)
        for rid in by_id:
            r = state.get(rid)
            if not r or r.get("state") == "closed":
                continue
            c = r.get("consequence")
            l = r.get("likelihood")
            if c is not None and l is not None:
                score_by_day[rid][i] = c * l
    series: list[dict] = []
    for rid, scores in score_by_day.items():
        it = by_id[rid]
        c, l = it["consequence"], it["likelihood"]
        if c is None or l is None or not (1 <= c <= 5 and 1 <= l <= 5):
            continue
        series.append({
            "iid": it["iid"],
            "title": it["title"],
            "display_title": it["display_title"],
            "web_url": it["web_url"],
            "state": it["state"],
            "subsystems": it["subsystems"],
            "priority": it["priority"],
            "risk_types": it["risk_types"],
            "products": it["products"],
            "other_labels": it["other_labels"],
            "tier": severity_tier(c, l),
            "current_score": c * l,
            "scores": scores,
        })
    return {"labels": labels, "series": series}


def movement(history: list[dict], days: int = 30) -> dict:
    today = datetime.now(timezone.utc).date()
    start_dt = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) - timedelta(days=days)
    by_id: dict[str, list[dict]] = defaultdict(list)
    for r in history:
        by_id[r["id"]].append(r)
    escalated: list[dict] = []
    deescalated: list[dict] = []
    new_items: list[dict] = []
    closed_items: list[dict] = []
    start_iso = start_dt.isoformat(timespec="seconds")
    for rid, rows in by_id.items():
        rows_sorted = sorted(rows, key=lambda r: r["ts"])
        first_seen = rows_sorted[0]
        if first_seen["ts"] >= start_iso:
            new_items.append(first_seen)
        recent = [r for r in rows_sorted if r["ts"] >= start_iso]
        if not recent:
            continue
        for i in range(1, len(recent)):
            prev, cur = recent[i - 1], recent[i]
            prev_score = (prev.get("consequence") or 0) * (prev.get("likelihood") or 0)
            cur_score = (cur.get("consequence") or 0) * (cur.get("likelihood") or 0)
            if cur_score > prev_score:
                escalated.append(cur)
            elif cur_score < prev_score and cur.get("state") != "closed":
                deescalated.append(cur)
            if cur.get("state") == "closed" and prev.get("state") != "closed":
                closed_items.append(cur)
    return {
        "escalated": escalated,
        "deescalated": deescalated,
        "new": new_items,
        "closed": closed_items,
    }


def build_matrix(items: list[dict]) -> dict:
    cells: dict[tuple[int, int], list[dict]] = {(c, l): [] for c in range(1, 6) for l in range(1, 6)}
    unscored: list[dict] = []
    for it in items:
        c, l = it["consequence"], it["likelihood"]
        if c is None or l is None or not (1 <= c <= 5 and 1 <= l <= 5):
            unscored.append(it)
            continue
        cells[(c, l)].append(it)
    return {"cells": cells, "unscored": unscored}


def git_version() -> str:
    """Short identifier for the version of this tool that produced the
    dashboard. Prefers ``CI_COMMIT_SHORT_SHA`` / ``CI_COMMIT_SHA`` env
    vars (set by GitLab CI), falls back to ``git rev-parse HEAD`` for
    local runs, and returns ``"unknown"`` if neither is available
    (e.g. running outside a git checkout)."""
    sha = (
        os.environ.get("CI_COMMIT_SHORT_SHA")
        or os.environ.get("CI_COMMIT_SHA")
        or os.environ.get("GITHUB_SHA")
    )
    if sha:
        return sha[:12]
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT), capture_output=True, text=True,
            timeout=5, check=False,
        )
        if result.returncode == 0:
            out = result.stdout.strip()
            if out:
                return out[:12]
    except (OSError, Exception):
        pass
    return "unknown"


def render(items: list[dict], history: list[dict],
           server_url: str = "", project_path: str = "") -> None:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["clean_title"] = clean_title
    tpl = env.get_template("index.html.j2")
    matrix = build_matrix(items)
    subsystem_counts = Counter()
    for it in items:
        if it["state"] == "closed":
            continue
        for s in it["subsystems"]:
            subsystem_counts[s] += 1
    cells_serializable = {
        f"{c}-{l}": [
            {
                "iid": it["iid"],
                "title": it["title"],
                "display_title": it["display_title"],
                "web_url": it["web_url"],
                "state": it["state"],
                "subsystems": it["subsystems"],
                "priority": it["priority"],
                "risk_types": it["risk_types"],
                "products": it["products"],
                "other_labels": it["other_labels"],
                "tier": severity_tier(c, l),
            }
            for it in matrix["cells"][(c, l)]
        ]
        for c in range(1, 6)
        for l in range(1, 6)
    }
    product_options: set[str] = set()
    all_label_options: set[str] = set()
    for it in items:
        if it["state"] == "closed":
            continue
        product_options.update(it["products"])
        all_label_options.update(it["subsystems"])
        all_label_options.update(it["products"])
        all_label_options.update(it["other_labels"])
    product_options_sorted = sorted(product_options)
    all_label_options_sorted = sorted(all_label_options)

    section_meta = [
        {"key": key, "header": header, "slug": _slugify(header)}
        for key, header, _ in CANONICAL_SECTIONS
    ]
    risks_table: list[dict] = []
    for it in items:
        c, l = it["consequence"], it["likelihood"]
        if c is None or l is None or not (1 <= c <= 5 and 1 <= l <= 5):
            continue
        rendered_sections = {
            key: render_section(it["sections"].get(key, ""))
            for key, _, _ in CANONICAL_SECTIONS
        }
        risks_table.append({
            "iid": it["iid"],
            "title": it["title"],
            "display_title": it["display_title"],
            "web_url": it["web_url"],
            "state": it["state"],
            "consequence": c,
            "likelihood": l,
            "score": c * l,
            "tier": severity_tier(c, l),
            "created_at": it.get("created_at"),
            "closed_at": it.get("closed_at"),
            "priority": it["priority"],
            "risk_types": it["risk_types"],
            "subsystems": it["subsystems"],
            "products": it["products"],
            "other_labels": it["other_labels"],
            "assignees": it["assignees"],
            "health_status": it["health_status"],
            "sections": rendered_sections,
        })
    risks_table.sort(key=lambda r: (-r["score"], -r["consequence"], -r["likelihood"]))

    # Risks without a Consequence × Likelihood score don't belong on the
    # 5×5 matrix or the sortable risks table (no severity to sort by).
    # Surface them in their own list so the team notices and assigns
    # values in GitLab.
    unscored_table: list[dict] = []
    for it in items:
        c, l = it["consequence"], it["likelihood"]
        if c is not None and l is not None and 1 <= c <= 5 and 1 <= l <= 5:
            continue
        unscored_table.append({
            "iid": it["iid"],
            "title": it["title"],
            "display_title": it["display_title"],
            "web_url": it["web_url"],
            "state": it["state"],
            "consequence": c,
            "likelihood": l,
            "priority": it["priority"],
            "risk_types": it["risk_types"],
            "subsystems": it["subsystems"],
            "products": it["products"],
            "other_labels": it["other_labels"],
            "assignees": it["assignees"],
            "created_at": it.get("created_at"),
            "closed_at": it.get("closed_at"),
        })
    unscored_table.sort(key=lambda r: (r["state"], r["iid"]))
    html = tpl.render(
        group_path=GROUP_PATH,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        subsystems=SUBSYSTEMS,
        matrix=matrix,
        rows=range(5, 0, -1),
        cols=range(1, 6),
        severity_tier=severity_tier,
        cells_json=json.dumps(cells_serializable),
        trends=trend_series(history),
        risk_trends=risk_score_series(history, items),
        movement=movement(history),
        subsystem_counts=dict(subsystem_counts),
        priorities=["High", "Medium", "Low"],
        risk_types=["Technical", "Cost", "Schedule"],
        product_options=product_options_sorted,
        all_label_options=all_label_options_sorted,
        product_patterns=PRODUCT_PATTERNS,
        server_url=server_url.rstrip("/") if server_url else "",
        project_path=project_path,
        git_sha=git_version(),
        commit_url=os.environ.get("CI_PROJECT_URL", "").rstrip("/"),
        risks_table_json=json.dumps(risks_table),
        unscored_table_json=json.dumps(unscored_table),
        section_meta=section_meta,
        max_preview_chars=MAX_PREVIEW_CHARS,
    )
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "index.html").write_text(html)


def main() -> None:
    schema_check()
    raw = fetch_work_items()
    all_items = [normalize(it) for it in raw]
    items = [it for it in all_items if is_risk_labelled(it)]
    if len(items) < len(all_items):
        print(
            f"Filtered to {len(items)} of {len(all_items)} work items by "
            f"RISK_LABEL_FILTER={risk_label_filter()!r} (case-insensitive "
            f"substring match on label names). Set RISK_LABEL_FILTER='' "
            f"to include everything.",
            file=sys.stderr,
        )
    history = load_history()
    history = update_history(items, history)
    render(
        items, history,
        server_url=gitlab_url(),
        project_path=os.environ.get("CI_PROJECT_PATH", ""),
    )
    print(f"Rendered public/index.html with {len(items)} work items "
          f"({sum(1 for i in items if i['state'] != 'closed')} open).")


if __name__ == "__main__":
    main()
