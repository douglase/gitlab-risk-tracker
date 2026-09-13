"""Build the risks dashboard.

Pulls risk-labelled issues from either forge, snapshots changed field
values to data/history.ndjson, and renders public/index.html.

Two providers, selected with ``RISK_PROVIDER``:

``gitlab`` (default)
    GitLab work items in a group (recursive) via the GraphQL API, with
    Consequence / Likelihood / Priority / Risk Type read from work-item
    custom fields. Needs ``GITLAB_TOKEN`` and ``CI_SERVER_URL`` (or
    ``GITLAB_URL``); ``RISK_GROUP_PATH`` selects the group.

``github``
    GitHub issues via the GraphQL API, with the same four values read
    from organization *issue fields* (``Issue.issueFieldValues``) --
    typed metadata stored on the issue and pinned to an issue type,
    which is the direct analogue of GitLab's custom fields. Needs
    ``GITHUB_TOKEN`` (scope: ``repo``), ``RISK_GITHUB_OWNER`` and
    usually ``RISK_GITHUB_ISSUE_TYPE``.

Everything downstream of normalize() -- history, trends, matrix,
rendering, MSR decks -- is provider-agnostic.

Designed to run inside a GitLab CI job or a GitHub Actions workflow; can
also run locally with the relevant token exported.

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

def env_or(name: str, default: str) -> str:
    """``os.environ.get`` that also falls back when the variable is present
    but blank.

    CI systems routinely export an unset variable as the empty string --
    GitHub Actions does exactly that for ``env: X: ${{ vars.X }}`` when the
    repository variable is undefined -- and a bare
    ``os.environ.get(name, default)`` then yields ``""`` instead of the
    default. For a field name that means matching no field at all, which
    shows up as a silently unpopulated column rather than an error.
    """
    value = os.environ.get(name)
    return default if value is None or not value.strip() else value


GROUP_PATH = env_or("RISK_GROUP_PATH", "stp")
SUBSYSTEMS = ["optics", "thermal", "software", "mechanical", "electrical"]

PROVIDER_GITLAB = "gitlab"
PROVIDER_GITHUB = "github"


def provider() -> str:
    """Which forge to query: ``gitlab`` (default) or ``github``.

    Read from ``RISK_PROVIDER`` on every call rather than cached at
    import, so tests can flip providers with ``patch.dict(os.environ)``.
    """
    p = (os.environ.get("RISK_PROVIDER") or PROVIDER_GITLAB).strip().lower()
    if p not in (PROVIDER_GITLAB, PROVIDER_GITHUB):
        sys.exit(
            f"RISK_PROVIDER must be {PROVIDER_GITLAB!r} or {PROVIDER_GITHUB!r}, "
            f"got {p!r}."
        )
    return p


def provider_name() -> str:
    """Human-readable forge name, for dashboard copy and link titles."""
    return "GitHub" if provider() == PROVIDER_GITHUB else "GitLab"


# Custom-field names. Identical semantics on both providers: GitLab
# work-item custom fields and GitHub issue fields are both looked up by
# display name, via field_key() below. Override when your register names
# them differently (e.g. RISK_FIELD_CONSEQUENCE="Impact").
CF_CONSEQUENCE = env_or("RISK_FIELD_CONSEQUENCE", "Consequence (C)")
CF_LIKELIHOOD = env_or("RISK_FIELD_LIKELIHOOD", "Likelihood (L)")
CF_PRIORITY = env_or("RISK_FIELD_PRIORITY", "Priority Level")
CF_RISK_TYPE = env_or("RISK_FIELD_RISK_TYPE", "Risk Type")


# --- GitHub-only configuration ------------------------------------------
# GitHub "issue fields" are typed, organization-level metadata stored on
# the issue itself, which org admins pin to issue types. That is the direct
# analogue of GitLab work-item custom fields, so the GitHub path reads
# Issue.issueFieldValues.
#
# NOT Projects v2 custom fields: those are a different feature, scoped to
# one board and stored on the issue<->board join row, so they are invisible
# to any issue that has not been added to that board.
def gh_owner() -> str:
    """Organization whose issues to scan."""
    return (os.environ.get("RISK_GITHUB_OWNER") or "").strip()


def gh_issue_type() -> str:
    """GitHub issue-type name to scan, e.g. ``Risk``.

    Optional. When set it becomes a ``type:"..."`` qualifier on the issue
    search, which is the cheapest way to scope the scan; left unset, every
    issue in the org is fetched and ``RISK_LABEL_FILTER`` does the work.
    """
    return (os.environ.get("RISK_GITHUB_ISSUE_TYPE") or "").strip()


def gh_search_query() -> str:
    """The GitHub issue-search query used to enumerate risks.

    Defaults to ``org:<owner> is:issue`` plus the issue-type qualifier.
    ``RISK_GITHUB_SEARCH`` overrides it wholesale, which is how you scan a
    user account (``user:someone is:issue``), a subset of repositories, or
    anything else the advanced-search syntax expresses -- including
    ``field.<name>:`` qualifiers and AND/OR grouping.
    """
    override = (os.environ.get("RISK_GITHUB_SEARCH") or "").strip()
    if override:
        return override
    owner = gh_owner()
    if not owner:
        sys.exit(
            "RISK_PROVIDER=github needs RISK_GITHUB_OWNER (the organization "
            "whose issues to scan), or RISK_GITHUB_SEARCH to supply the whole "
            "search query."
        )
    parts = [f"org:{owner}", "is:issue"]
    if gh_issue_type():
        parts.append(f'type:"{gh_issue_type()}"')
    return " ".join(parts)


def gh_workflow() -> str:
    """Workflow file that rebuilds the dashboard, for the Refresh links."""
    return (os.environ.get("RISK_GITHUB_WORKFLOW") or "dashboard.yml").strip()


def field_key(name: str) -> str:
    """Normalized form for matching a configured field name against the
    names a forge reports: lowercased, whitespace-collapsed, and with a
    trailing parenthetical dropped.

    So the GitLab-flavoured defaults ``Consequence (C)`` / ``Likelihood
    (L)`` also match GitHub issue fields simply named ``Consequence`` /
    ``Likelihood``, and the same risk register needs no RISK_FIELD_*
    configuration on either forge.
    """
    bare = re.sub(r"\s*\([^)]*\)\s*$", "", (name or "").strip())
    return re.sub(r"\s+", " ", bare).strip().lower()
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


def github_url() -> str:
    """Web base URL of the GitHub instance. ``GITHUB_SERVER_URL`` is set
    by GitHub Actions; set it (or ``GITHUB_URL``) by hand for GHES."""
    base = (
        os.environ.get("GITHUB_SERVER_URL")
        or os.environ.get("GITHUB_URL")
        or "https://github.com"
    )
    return base.rstrip("/")


def github_graphql_endpoint() -> str:
    """GraphQL endpoint: ``https://api.github.com/graphql`` on github.com,
    ``https://<host>/api/graphql`` on GHES. Derived from ``GITHUB_API_URL``
    when Actions sets it."""
    api = (os.environ.get("GITHUB_API_URL") or "").rstrip("/")
    if api:
        if api.endswith("/v3"):
            api = api[: -len("/v3")]
        return f"{api}/graphql"
    base = github_url()
    if base == "https://github.com":
        return "https://api.github.com/graphql"
    return f"{base}/api/graphql"


def server_url() -> str:
    """Web base URL of whichever forge we are querying."""
    return github_url() if provider() == PROVIDER_GITHUB else gitlab_url()


def project_path() -> str:
    """``owner/repo`` (GitHub) or ``group/project`` (GitLab) of the
    repository that builds this dashboard, used for the Refresh links."""
    if provider() == PROVIDER_GITHUB:
        return os.environ.get("GITHUB_REPOSITORY", "")
    return os.environ.get("CI_PROJECT_PATH", "")


def scope_label() -> str:
    """What the dashboard title says it covers."""
    if provider() == PROVIDER_GITHUB:
        parts = [p for p in (gh_owner(), gh_issue_type()) if p]
        return " · ".join(parts) or gh_search_query()
    return GROUP_PATH


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
    if resp.status_code == 401:
        sys.exit(
            "GitLab rejected GITLAB_TOKEN (401 Unauthorized).\n"
            "The CI/CD variable is set (the empty-token guard passed) but the\n"
            "token itself is no longer valid. Most common causes:\n"
            "  - the token has EXPIRED — group/project access tokens have an\n"
            "    expiry date; check the source group's Settings → Access tokens\n"
            "  - the token was revoked, or its bot user was removed from the group\n"
            "  - the value picked up stray whitespace/newline when pasted\n"
            f"Token length as seen by this job: {len(token)} chars.\n"
            "Fix: create a new group access token with read_api scope (Reporter\n"
            "role or higher) on the source group, update the GITLAB_TOKEN CI/CD\n"
            "variable on the dashboard project, and retry the pipeline."
        )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        sys.exit(f"GraphQL errors: {json.dumps(payload['errors'], indent=2)}")
    return payload["data"]


def github_graphql(query: str, variables: dict) -> dict:
    """POST to GitHub's GraphQL API. Mirrors graphql() above, including the
    actionable 401 message, which is the failure mode people actually hit."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set.")
    resp = requests.post(
        github_graphql_endpoint(),
        json={"query": query, "variables": variables},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "gitlab-risk-tracker",
        },
        timeout=60,
    )
    if resp.status_code == 401:
        sys.exit(
            "GitHub rejected GITHUB_TOKEN (401 Unauthorized).\n"
            "The variable is set (the empty-token guard passed) but the token\n"
            "itself is not valid. Most common causes:\n"
            "  - the token has EXPIRED - fine-grained PATs and org tokens have\n"
            "    an expiry date; check Settings -> Developer settings -> Tokens\n"
            "  - the token was revoked, or its owner lost access to the org\n"
            "  - the value picked up stray whitespace/newline when pasted\n"
            f"Token length as seen by this job: {len(token)} chars.\n"
            "Fix: mint a token that can read the org's issues - a classic PAT\n"
            "with 'repo', or a fine-grained PAT with Issues: Read-only - store\n"
            "it as the RISK_TOKEN secret and retry. Note a workflow run's own\n"
            "GITHUB_TOKEN is scoped to its repository and cannot read issues\n"
            "across an organization; an org-wide scan needs a PAT."
        )
    if resp.status_code == 403:
        sys.exit(
            "GitHub returned 403 Forbidden for the GraphQL query.\n"
            "Usually the token cannot read the organization's issues: a\n"
            "fine-grained PAT needs Issues: Read-only on the repositories in\n"
            "scope, and some orgs require PATs to be approved before use."
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


GH_PROBE_QUERY = """
query($q: String!) {
  search(query: $q, type: ISSUE_ADVANCED, first: 1) {
    issueCount
    nodes {
      ... on Issue {
        number
        issueType { name }
        issueFieldValues(first: 50) {
          nodes {
            __typename
            ... on IssueFieldNumberValue { field { ... on IssueFieldCommon { name dataType } } }
            ... on IssueFieldSingleSelectValue { field { ... on IssueFieldCommon { name dataType } } }
            ... on IssueFieldMultiSelectValue { field { ... on IssueFieldCommon { name dataType } } }
            ... on IssueFieldTextValue { field { ... on IssueFieldCommon { name dataType } } }
          }
        }
      }
    }
  }
}
"""


def github_schema_check() -> None:
    """Run the search once and report what it found.

    A field name that does not match, or an issue-type name that does not
    exist, is the GitHub equivalent of a GitLab custom-field mismatch: the
    query succeeds and every risk lands silently in the unscored bucket.
    Warn here instead, naming the fields the org actually reports.
    """
    query = gh_search_query()
    try:
        data = github_graphql(GH_PROBE_QUERY, {"q": query})
    except SystemExit:
        raise
    except Exception as e:
        print(f"warning: issue-field probe failed ({e}); continuing.", file=sys.stderr)
        return
    result = data.get("search") or {}
    count = result.get("issueCount")
    print(f"GitHub search {query!r} matches {count} issue(s).", file=sys.stderr)
    if not count:
        print(
            "warning: the search matched nothing. Check RISK_GITHUB_OWNER, and "
            "that RISK_GITHUB_ISSUE_TYPE names an issue type that exists in "
            "the organization -- the search qualifier is an exact match.",
            file=sys.stderr,
        )
        return
    nodes = [n for n in (result.get("nodes") or []) if n]
    if not nodes:
        return

    # Print the mapping unconditionally. An issue field that does not line
    # up with a configured name is invisible in the dashboard -- the column
    # is simply blank -- so make the resolution visible on every run rather
    # than only when something looks wrong.
    seen: dict[str, str | None] = {}
    for v in ((nodes[0].get("issueFieldValues") or {}).get("nodes") or []):
        f = (v or {}).get("field") or {}
        if f.get("name"):
            seen[f["name"]] = f.get("dataType")
    by_key = {field_key(n): n for n in seen}
    print(
        f"Issue fields set on probe issue #{nodes[0].get('number')}: "
        f"{seen or '{}'}",
        file=sys.stderr,
    )
    configured = (
        ("RISK_FIELD_CONSEQUENCE", CF_CONSEQUENCE),
        ("RISK_FIELD_LIKELIHOOD", CF_LIKELIHOOD),
        ("RISK_FIELD_PRIORITY", CF_PRIORITY),
        ("RISK_FIELD_RISK_TYPE", CF_RISK_TYPE),
    )
    missing: list[str] = []
    for var, want in configured:
        hit = by_key.get(field_key(want))
        print(f"  {want!r} ({var}) -> {hit!r}" if hit
              else f"  {want!r} ({var}) -> NOT FOUND", file=sys.stderr)
        if not hit:
            missing.append(want)
    if missing:
        print(
            f"warning: no issue field matched {missing}. Names are matched "
            f"case-insensitively, ignoring a trailing '(C)'-style suffix; "
            f"override with RISK_FIELD_CONSEQUENCE / _LIKELIHOOD / _PRIORITY "
            f"/ _RISK_TYPE. Those columns will be blank. Only the first "
            f"matching issue is probed, so this is a false alarm if that one "
            f"issue simply has the field unset.",
            file=sys.stderr,
        )


def schema_check() -> None:
    """Probe the schema to warn early if this GitLab instance doesn't expose
    what we expect. Non-fatal — some instances restrict GraphQL introspection
    on experimental fields even though the actual query works. Falls through
    to fetch_work_items() which will surface the real error if any."""
    if provider() == PROVIDER_GITHUB:
        return github_schema_check()
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


def dedup_by_id(raw: list[dict]) -> list[dict]:
    """Defensive dedup by global id. Neither provider's pagination should
    return the same node twice, but if it ever does (a project shared
    across two subgroups, an issue added to a board twice, a concurrent
    create during pagination) we would double-count the issue in the
    matrix and the risks table."""
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
            f"warning: fetch returned {duplicates} duplicate node(s); "
            f"deduped by id.",
            file=sys.stderr,
        )
    return items


def fetch_work_items() -> list[dict]:
    if provider() == PROVIDER_GITHUB:
        return fetch_github_issues()
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
    return dedup_by_id(raw)


# --- GitHub -------------------------------------------------------------
# Enumeration goes through issue search: IssueType.issues takes a required
# repositoryId, so it cannot span an organization. ISSUE_ADVANCED is the
# search type that supports the full qualifier grammar.
GH_ISSUES_QUERY = """
query($q: String!, $cursor: String) {
  search(query: $q, type: ISSUE_ADVANCED, first: %(page)d, after: $cursor) {
    issueCount
    pageInfo { endCursor hasNextPage }
    nodes {
      ... on Issue {
        id
        number
        title
        state
        url
        createdAt
        updatedAt
        closedAt
        body
        issueType { name }
        labels(first: 50) { nodes { name } }
        assignees(first: 20) { nodes { login name url } }
        issueFieldValues(first: 50) {
          nodes {
            __typename
            ... on IssueFieldNumberValue {
              value
              field { __typename ... on IssueFieldCommon { name dataType } }
            }
            ... on IssueFieldSingleSelectValue {
              value
              name
              field { __typename ... on IssueFieldCommon { name dataType } }
            }
            ... on IssueFieldMultiSelectValue {
              options { name }
              field { __typename ... on IssueFieldCommon { name dataType } }
            }
            ... on IssueFieldTextValue {
              value
              field { __typename ... on IssueFieldCommon { name dataType } }
            }
          }
        }
      }
    }
  }
}
""" % {"page": PAGE_SIZE}


_UNHANDLED_FIELD_KINDS: set[str] = set()
_UNNAMED_FIELD_KINDS: set[str] = set()


def debug_fields() -> bool:
    """``RISK_DEBUG_FIELDS=1`` dumps every issue's raw issueFieldValues
    nodes to stderr. The fastest way to see why a column is blank."""
    return (os.environ.get("RISK_DEBUG_FIELDS") or "").strip().lower() \
        in ("1", "true", "yes", "on")


def gh_field_values(item: dict) -> dict[str, object]:
    """{field_key(name): value} for one issue's issue-field values.

    Number fields yield floats, single-select the option name, text the
    string, multi-select a list of option names. Keys go through
    field_key() so ``Consequence (C)`` matches a field named
    ``Consequence``.

    `field` is selected inside each inline fragment rather than once on the
    connection because IssueFieldValue is a union, and a union exposes no
    fields of its own.
    """
    out: dict[str, object] = {}
    nodes = (item.get("issueFieldValues") or {}).get("nodes") or []
    if debug_fields():
        print(
            f"RISK_DEBUG_FIELDS issue #{item.get('number')} "
            f"issueFieldValues={json.dumps(nodes, indent=2, default=str)}",
            file=sys.stderr,
        )
    for fv in nodes:
        if not fv:
            continue
        kind = fv.get("__typename")
        name = ((fv.get("field") or {}).get("name") or "").strip()
        if not name:
            # The value is present but its owning field did not resolve a
            # name, so there is nothing to match it against. Never drop
            # this silently: a blank dashboard column with no log line is
            # exactly the failure this cost us once already.
            if kind not in _UNNAMED_FIELD_KINDS:
                _UNNAMED_FIELD_KINDS.add(kind)
                print(
                    f"warning: a {kind} on issue #{item.get('number')} has no "
                    f"resolvable field name, so it cannot be matched and its "
                    f"column will be blank. Raw node: "
                    f"{json.dumps(fv, default=str)}. Re-run with "
                    f"RISK_DEBUG_FIELDS=1 to dump every value node.",
                    file=sys.stderr,
                )
            continue
        if kind == "IssueFieldMultiSelectValue":
            out[field_key(name)] = [
                o["name"] for o in (fv.get("options") or []) if (o or {}).get("name")
            ]
            continue
        # Number and text expose the value as `value`; single-select
        # exposes the chosen option as both `value` and `name`. Take
        # whichever is present rather than matching on __typename, so a
        # value type added to the IssueFieldValue union after this was
        # written still populates instead of silently vanishing.
        value = fv.get("value")
        if value is None:
            value = fv.get("name")
        if value is None:
            if kind and kind not in _UNHANDLED_FIELD_KINDS:
                _UNHANDLED_FIELD_KINDS.add(kind)
                print(
                    f"warning: issue field {name!r} has value type {kind}, which "
                    f"exposes neither `value` nor `name`; ignored. Add it to "
                    f"GH_ISSUES_QUERY to read it.",
                    file=sys.stderr,
                )
            continue
        out[field_key(name)] = value
    return out


def gh_value(values: dict, name: str):
    """Look up a configured field name in a gh_field_values() mapping."""
    return values.get(field_key(name))


_MULTI_FOR_SINGLE_FIELDS: set[str] = set()


def gh_single(values: dict, name: str):
    """Look up a field the dashboard models as single-valued.

    Consequence, Likelihood and Priority Level are expected to be Number
    and single-select issue fields respectively, which is what the
    dashboard's filters and table cells compare against.

    GitHub lets an org declare any issue field MULTI_SELECT, though, and
    such a field returns a list -- ``["Medium"]`` where a scalar is wanted.
    That is a misconfiguration rather than a supported layout, but it is
    tolerated here (first option wins, one warning) because the
    alternative is what this code did originally: return the list, fail a
    scalar type check downstream, and render a blank column with nothing
    in the log. A list is a legitimate value elsewhere -- Risk Type is
    genuinely multi-valued -- so nothing further upstream can catch it.
    """
    value = gh_value(values, name)
    if isinstance(value, list):
        if name not in _MULTI_FOR_SINGLE_FIELDS:
            _MULTI_FOR_SINGLE_FIELDS.add(name)
            print(
                f"warning: issue field {name!r} is multi-select ({value}), "
                f"but the dashboard treats it as single-valued and will use "
                f"{(value[0] if value else None)!r}. Declare it as a "
                f"single-select field.",
                file=sys.stderr,
            )
        value = value[0] if value else None
    return value


def fetch_github_issues() -> list[dict]:
    """Raw GitHub issue nodes matching gh_search_query()."""
    query = gh_search_query()
    raw: list[dict] = []
    cursor: str | None = None
    total: int | None = None
    while True:
        data = github_graphql(GH_ISSUES_QUERY, {"q": query, "cursor": cursor})
        result = data.get("search") or {}
        if total is None:
            total = result.get("issueCount")
        for node in result.get("nodes") or []:
            # Search results are a union; anything that isn't a readable
            # Issue comes back as an empty object.
            if node and node.get("id"):
                raw.append(node)
        page = result.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    if total is not None and len(raw) < total:
        print(
            f"warning: search {query!r} reports {total} matching issue(s) but "
            f"only {len(raw)} came back. GitHub caps how deeply an issue "
            f"search can be paginated, so risks are MISSING from this "
            f"dashboard. Narrow the scan with RISK_GITHUB_ISSUE_TYPE, or a "
            f"RISK_GITHUB_SEARCH query with extra qualifiers.",
            file=sys.stderr,
        )
    # The type qualifier already filters server-side; this also applies the
    # issue type when RISK_GITHUB_SEARCH replaced the generated query.
    want_type = gh_issue_type().lower()
    if want_type:
        before = len(raw)
        raw = [
            r for r in raw
            if ((r.get("issueType") or {}).get("name") or "").strip().lower() == want_type
        ]
        if len(raw) < before:
            print(
                f"Filtered to {len(raw)} of {before} issues by "
                f"RISK_GITHUB_ISSUE_TYPE={gh_issue_type()!r}.",
                file=sys.stderr,
            )
    return dedup_by_id(raw)


def normalize_github(item: dict) -> dict:
    """GitHub issue node -> the same normalized dict normalize() returns
    for GitLab. Everything downstream depends on this shape, so the keys
    here must stay in lockstep with the GitLab branch.

    One knowing gap, documented in docs/github-setup.rst: GitHub has no
    health-status equivalent, so `health_status` is always None.
    """
    values = gh_field_values(item)
    labels = [n["name"] for n in ((item.get("labels") or {}).get("nodes") or [])]
    assignees = [
        {
            "name": (n.get("name") or n.get("login") or "").strip(),
            "username": n.get("login"),
            "web_url": n.get("url"),
        }
        for n in ((item.get("assignees") or {}).get("nodes") or [])
    ]
    subsystems, products, other_labels = label_buckets(labels)
    # Risk Type is multi-select on both forges, but tolerate a
    # single-select field here so either board shape works.
    risk_types = gh_value(values, CF_RISK_TYPE)
    if isinstance(risk_types, str):
        risk_types = [risk_types]
    elif not isinstance(risk_types, list):
        risk_types = []
    priority = gh_single(values, CF_PRIORITY)
    body = item.get("body") or ""
    return {
        "labels": labels,
        "id": item["id"],
        "iid": str(item["number"]),
        "title": item["title"],
        "display_title": clean_title(item["title"]),
        "state": item["state"].lower(),
        "web_url": item["url"],
        "created_at": item.get("createdAt"),
        "updated_at": item.get("updatedAt"),
        "closed_at": item.get("closedAt"),
        "consequence": to_int(gh_single(values, CF_CONSEQUENCE)),
        "likelihood": to_int(gh_single(values, CF_LIKELIHOOD)),
        "priority": None if priority is None else str(priority),
        "risk_types": [r for r in risk_types if r],
        "subsystems": subsystems,
        "products": products,
        "other_labels": other_labels,
        "assignees": assignees,
        "health_status": None,
        "description": body,
        "sections": parse_sections(body),
    }


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
    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        pass
    # GitHub issue-field Number values come back as GraphQL Float, so a
    # Consequence of 4 arrives as 4.0 and int("4.0") raises.
    try:
        return int(float(text))
    except ValueError:
        return None


def label_buckets(labels: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Split an issue's labels into (subsystems, products, everything else).
    Shared by both providers so the two normalize() paths cannot drift."""
    subsystems = sorted(set(labels) & set(SUBSYSTEMS))
    products = match_products(labels)
    other_labels = sorted(set(labels) - set(SUBSYSTEMS) - set(products))
    return subsystems, products, other_labels


def normalize(item: dict) -> dict:
    if provider() == PROVIDER_GITHUB:
        return normalize_github(item)
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
    subsystems, products, other_labels = label_buckets(labels)
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


def forge_links(server: str, path: str) -> dict:
    """Provider-specific deep links for the template.

    The template used to build GitLab URL shapes inline; both providers
    now hand it finished URLs (and a prefix/suffix pair for the
    per-label search, whose middle is the URL-encoded label) so the
    Jinja/JS has no forge-specific paths left in it.
    """
    from urllib.parse import quote
    branch = os.environ.get("CI_DEFAULT_BRANCH") or os.environ.get("RISK_DEFAULT_BRANCH") or "main"
    if provider() == PROVIDER_GITHUB:
        owner = gh_owner()
        actions = f"{server}/{path}/actions" if server and path else ""
        return {
            "provider": PROVIDER_GITHUB,
            "provider_name": "GitHub",
            "ci_noun": "GitHub Actions workflow",
            "run_ci_noun": "the workflow's Actions page",
            "schedules_label": "Open workflow runs",
            # Org/user-wide issue search filtered to one label.
            "label_url_prefix": (
                f"{server}/search?type=issues&q="
                f"{quote(f'org:{owner} is:issue label:')}%22" if server and owner else ""
            ),
            "label_url_suffix": "%22",
            "run_ci_url": f"{actions}/workflows/{gh_workflow()}" if actions else "",
            "schedules_url": f"{actions}/workflows/{gh_workflow()}" if actions else "",
            "commit_link": f"{server}/{path}/commit/{git_version()}" if server and path else "",
        }
    project_url = os.environ.get("CI_PROJECT_URL", "").rstrip("/")
    return {
        "provider": PROVIDER_GITLAB,
        "provider_name": "GitLab",
        "ci_noun": "GitLab pipeline",
        "run_ci_noun": "GitLab's Run-pipeline form",
        "schedules_label": "Open pipeline schedules",
        "label_url_prefix": (
            f"{server}/groups/{quote(GROUP_PATH)}/-/issues?label_name%5B%5D="
            if server else ""
        ),
        "label_url_suffix": "",
        "run_ci_url": f"{server}/{path}/-/pipelines/new?ref={branch}" if server and path else "",
        "schedules_url": f"{server}/{path}/-/pipeline_schedules" if server and path else "",
        "commit_link": f"{project_url}/-/commit/{git_version()}" if project_url else "",
    }


def render(items: list[dict], history: list[dict],
           server_url: str = "", project_path: str = "",
           msr_decks: list[dict] | None = None) -> None:
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
    links = forge_links(server_url.rstrip("/") if server_url else "", project_path)
    html = tpl.render(
        group_path=scope_label(),
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
        **links,
        risks_table_json=json.dumps(risks_table),
        unscored_table_json=json.dumps(unscored_table),
        section_meta=section_meta,
        max_preview_chars=MAX_PREVIEW_CHARS,
        msr_decks=msr_decks or [],
    )
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "index.html").write_text(html)


def main() -> None:
    print(f"Provider: {provider()} (scope: {scope_label()})", file=sys.stderr)
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
    from msr_decks import generate_msr_decks
    decks = generate_msr_decks(
        items, movement(history),
        out_dir=PUBLIC_DIR / "msr",
        template=ROOT / "templates" / "msr_top5.pptx",
    )
    render(
        items, history,
        server_url=server_url(),
        project_path=project_path(),
        msr_decks=decks,
    )
    print(f"Rendered public/index.html with {len(items)} work items "
          f"({sum(1 for i in items if i['state'] != 'closed')} open); "
          f"{len(decks)} Top-5 MSR deck(s) in public/msr/.")


if __name__ == "__main__":
    main()
