"""Tests for the GitHub provider path in build.py.

The GitLab path is covered by tests/test_build.py and is deliberately left
untouched here. The point of this file is the *seam*: that
``RISK_PROVIDER=github`` produces the same normalized item dicts the rest
of build.py already knows how to handle, so history, trends, the matrix
and the MSR decks keep working unchanged.

GitHub's risk values come from **issue fields** — organization-level typed
metadata on the issue itself, pinned to issue types — read off
``Issue.issueFieldValues``. They are NOT Projects v2 item fields, which are
per-board and invisible to an issue that is not on the board;
``test_query_reads_issue_fields_not_projects_v2`` guards that distinction.

Run:
    python -m pytest tests/test_build_github.py -v
or directly:
    python tests/test_build_github.py
"""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build  # noqa: E402

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")

GH_ENV = {
    "RISK_PROVIDER": "github",
    "RISK_GITHUB_OWNER": "example-org",
    "GITHUB_TOKEN": "gh-token",
    "RISK_LABEL_FILTER": "",
}


# --------------------------------------------------------------- fixtures
def _gh_issue(
    number: int,
    title: str,
    c: float | None,
    l: float | None,
    priority: str | None,
    risk_types: list[str],
    labels: list[str],
    state: str = "OPEN",
    body: str = "",
    assignees: list[dict] | None = None,
    issue_type: str | None = "Risk",
    consequence_field: str | None = None,
    likelihood_field: str | None = None,
) -> dict:
    """One Issue node of the ISSUE_ADVANCED search, shaped like
    GH_ISSUES_QUERY returns it.

    ``consequence_field`` / ``likelihood_field`` override the field *names*
    so the field_key() normalization can be exercised.
    """
    fvs: list[dict] = []
    for name, value in ((consequence_field or build.CF_CONSEQUENCE, c),
                        (likelihood_field or build.CF_LIKELIHOOD, l)):
        if value is not None:
            fvs.append({
                "__typename": "IssueFieldNumberValue",
                "value": value,
                "field": {"name": name},
            })
    if priority is not None:
        fvs.append({
            "__typename": "IssueFieldSingleSelectValue",
            "value": priority,
            "field": {"name": build.CF_PRIORITY},
        })
    if risk_types:
        fvs.append({
            "__typename": "IssueFieldMultiSelectValue",
            "options": [{"name": rt} for rt in risk_types],
            "field": {"name": build.CF_RISK_TYPE},
        })
    node = {
        "id": f"I_kwDO{number:06d}",
        "number": number,
        "title": title,
        "state": state,
        "url": f"https://github.com/example-org/repo/issues/{number}",
        "createdAt": NOW,
        "updatedAt": NOW,
        "closedAt": None,
        "body": body,
        "labels": {"nodes": [{"name": n} for n in labels]},
        "assignees": {"nodes": [
            {"login": a["username"], "name": a.get("name", a["username"]),
             "url": f"https://github.com/{a['username']}"}
            for a in (assignees or [])
        ]},
        "issueFieldValues": {"nodes": fvs},
    }
    if issue_type is not None:
        node["issueType"] = {"name": issue_type}
    return node


def _gl_item(
    iid: int,
    title: str,
    c: str | None,
    l: str | None,
    priority: str | None,
    risk_types: list[str],
    labels: list[str],
    state: str = "OPEN",
    description: str = "",
    assignees: list[dict] | None = None,
) -> dict:
    """The GitLab-shaped equivalent, for the parity test."""
    cf: list[dict] = []
    for name, vals in (
        (build.CF_CONSEQUENCE, [c] if c else []),
        (build.CF_LIKELIHOOD, [l] if l else []),
        (build.CF_PRIORITY, [priority] if priority else []),
        (build.CF_RISK_TYPE, risk_types),
    ):
        if vals:
            cf.append({
                "customField": {"id": "gid://x", "name": name,
                                "fieldType": "SINGLE_SELECT"},
                "selectedOptions": [{"id": f"gid://opt/{v}", "value": v} for v in vals],
            })
    widgets: list[dict] = [
        {"type": "LABELS", "labels": {"nodes": [{"title": n} for n in labels]}},
        {"type": "CUSTOM_FIELDS", "customFieldValues": cf},
        {"type": "DESCRIPTION", "description": description},
        {"type": "ASSIGNEES", "assignees": {"nodes": [
            {"id": f"gid://user/{a['username']}", "username": a["username"],
             "name": a.get("name", a["username"]),
             "webUrl": f"https://gitlab.example.com/{a['username']}"}
            for a in (assignees or [])
        ]}},
    ]
    return {
        "id": f"gid://gitlab/WorkItem/{iid}",
        "iid": str(iid),
        "title": title,
        "state": state,
        "webUrl": f"https://gitlab.example.com/stp/sub/-/work_items/{iid}",
        "createdAt": NOW,
        "updatedAt": NOW,
        "closedAt": None,
        "widgets": widgets,
    }


def _search_pages(nodes: list[dict], per_page: int = 2, issue_count: int | None = None):
    """Split nodes into search responses, mimicking cursor pagination."""
    pages: list[dict] = []
    total = len(nodes) if issue_count is None else issue_count
    for i in range(0, max(len(nodes), 1), per_page):
        chunk = nodes[i:i + per_page]
        last = i + per_page >= len(nodes)
        pages.append({"search": {
            "issueCount": total,
            "pageInfo": {"endCursor": f"cur{i}", "hasNextPage": not last},
            "nodes": chunk,
        }})
    return pages


def _replay(pages: list[dict], calls: list[dict]):
    def fake(query: str, variables: dict) -> dict:
        calls.append(variables)
        return pages[min(len(calls) - 1, len(pages) - 1)]
    return fake


# ------------------------------------------------------------------ tests
def test_provider_selection() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("RISK_PROVIDER", None)
        assert build.provider() == "gitlab", "gitlab must stay the default"
        assert build.provider_name() == "GitLab"
    with patch.dict(os.environ, {"RISK_PROVIDER": "GitHub"}):
        assert build.provider() == "github", "value should be case-insensitive"
        assert build.provider_name() == "GitHub"
    with patch.dict(os.environ, {"RISK_PROVIDER": "bitbucket"}):
        try:
            build.provider()
            raise AssertionError("expected SystemExit on unknown provider")
        except SystemExit as e:
            assert "RISK_PROVIDER" in str(e)


def test_query_reads_issue_fields_not_projects_v2() -> None:
    """Regression guard for the original implementation error: risk values
    live on Issue.issueFieldValues (org-level issue fields), not on
    Projects v2 item fields."""
    q = build.GH_ISSUES_QUERY
    assert "issueFieldValues" in q
    assert "IssueFieldNumberValue" in q
    assert "IssueFieldMultiSelectValue" in q, "Risk Type must support multi-select"
    assert "ISSUE_ADVANCED" in q
    assert "projectV2" not in q and "ProjectV2" not in q, \
        "Projects v2 item fields are a different feature; do not read them"
    # `field` must be selected inside each inline fragment, because
    # IssueFieldValue is a union and unions expose no fields of their own.
    assert q.count("field { __typename ... on IssueFieldCommon { name dataType } }") == 4


def test_normalize_github_matches_gitlab() -> None:
    """The whole design rests on this: both providers must hand the rest of
    build.py the same dict. Only the keys that cannot match by construction
    are excluded."""
    title = "Risk #12: Optical contamination during integration"
    desc = "## Risk Description\n\nContamination of M1 during integration."
    labels = ["risk", "optics", "TO12-primary"]
    who = [{"username": "adevs", "name": "A Dev"}]

    gh = build.normalize_github(_gh_issue(
        42, title, 4.0, 3.0, "High", ["Technical", "Cost"], labels,
        body=desc, assignees=who,
    ))
    with patch.dict(os.environ, {"RISK_PROVIDER": "gitlab"}):
        gl = build.normalize(_gl_item(
            42, title, "4", "3", "High", ["Technical", "Cost"], labels,
            description=desc, assignees=who,
        ))

    differ_by_construction = {"id", "web_url", "health_status", "assignees"}
    assert set(gh) == set(gl), "normalized key sets must be identical"
    for key in set(gl) - differ_by_construction:
        assert gh[key] == gl[key], f"{key}: github={gh[key]!r} gitlab={gl[key]!r}"
    assert gh["iid"] == gl["iid"] == "42"
    assert gh["consequence"] == 4 and gh["likelihood"] == 3
    assert gh["risk_types"] == ["Technical", "Cost"], \
        "multi-select issue fields give real parity with GitLab"
    assert gh["health_status"] is None, "GitHub has no health-status equivalent"
    assert gh["web_url"].startswith("https://github.com/")
    assert gh["assignees"] == [{"name": "A Dev", "username": "adevs",
                                "web_url": "https://github.com/adevs"}]


def test_field_names_match_without_the_gitlab_suffix() -> None:
    """An org whose issue fields are plainly named `Consequence` and
    `Likelihood` must work against the `Consequence (C)` defaults, with no
    RISK_FIELD_* configuration."""
    assert build.field_key("Consequence (C)") == "consequence"
    assert build.field_key("  consequence ") == "consequence"
    assert build.field_key("Likelihood (L)") == build.field_key("Likelihood")
    assert build.field_key("Priority Level") == "priority level"

    item = _gh_issue(1, "Risk", 5.0, 2.0, "High", ["Cost"], ["risk"],
                     consequence_field="Consequence", likelihood_field="Likelihood")
    norm = build.normalize_github(item)
    assert norm["consequence"] == 5 and norm["likelihood"] == 2


def test_blank_env_var_falls_back_to_the_default_field_name() -> None:
    """GitHub Actions interpolates an UNDEFINED repository variable to the
    empty string, so `env: RISK_FIELD_PRIORITY: ${{ vars.X }}` with X unset
    used to hand build.py "" -- which matched no field and left the
    Priority column silently blank. env_or() must treat blank as unset."""
    with patch.dict(os.environ, {"RISK_FIELD_PRIORITY": ""}):
        assert build.env_or("RISK_FIELD_PRIORITY", "Priority Level") == "Priority Level"
    with patch.dict(os.environ, {"RISK_FIELD_PRIORITY": "   "}):
        assert build.env_or("RISK_FIELD_PRIORITY", "Priority Level") == "Priority Level"
    with patch.dict(os.environ, {"RISK_FIELD_PRIORITY": "Severity"}):
        assert build.env_or("RISK_FIELD_PRIORITY", "Priority Level") == "Severity"
    with patch.dict(os.environ, {}, clear=True):
        assert build.env_or("RISK_FIELD_PRIORITY", "Priority Level") == "Priority Level"
    # A blank configured name must never match a real field either.
    assert build.gh_value({"priority level": "High"}, "") is None


def test_single_select_priority_populates() -> None:
    """Regression: Consequence/Likelihood (Number) populated while Priority
    (single select) came back empty."""
    item = _gh_issue(1, "Risk", 4.0, 3.0, "High", ["Cost"], ["risk"])
    norm = build.normalize_github(item)
    assert norm["priority"] == "High"
    assert norm["consequence"] == 4 and norm["likelihood"] == 3

    # Single-select exposes the chosen option as both `value` and `name`;
    # either alone must work, so the query selecting both is safe.
    only_name = {"issueFieldValues": {"nodes": [{
        "__typename": "IssueFieldSingleSelectValue",
        "name": "Medium",
        "field": {"name": build.CF_PRIORITY},
    }]}}
    assert build.gh_value(build.gh_field_values(only_name), build.CF_PRIORITY) == "Medium"
    frag = build.GH_ISSUES_QUERY.split("... on IssueFieldSingleSelectValue {")[1]
    frag = frag.split("field {")[0]
    assert "value" in frag and "name" in frag, \
        "the single-select fragment should select both value and name"


def test_value_with_unresolvable_field_name_warns() -> None:
    """If `field` comes back without a name there is nothing to match the
    value against. That must be a log line, not a silently blank column —
    the exact failure mode that cost two debugging rounds."""
    build._UNNAMED_FIELD_KINDS.clear()
    orphan = {"number": 212, "issueFieldValues": {"nodes": [{
        "__typename": "IssueFieldSingleSelectValue",
        "value": "Medium",
        "name": "Medium",
        "field": {},          # interface fragment matched nothing
    }]}}
    err = io.StringIO()
    with redirect_stderr(err):
        assert build.gh_field_values(orphan) == {}
    msg = err.getvalue()
    assert "IssueFieldSingleSelectValue" in msg
    assert "212" in msg, "should name the issue"
    assert "Medium" in msg, "should dump the raw node so the cause is visible"
    assert "RISK_DEBUG_FIELDS" in msg, "should point at the full dump"
    build._UNNAMED_FIELD_KINDS.clear()


def test_debug_fields_dumps_raw_nodes() -> None:
    item = _gh_issue(7, "Risk", 4.0, 3.0, "Medium", ["Cost"], ["risk"])
    err = io.StringIO()
    with patch.dict(os.environ, {"RISK_DEBUG_FIELDS": "1"}), redirect_stderr(err):
        build.gh_field_values(item)
    assert "RISK_DEBUG_FIELDS issue #7" in err.getvalue()
    assert "IssueFieldSingleSelectValue" in err.getvalue()
    err = io.StringIO()
    with patch.dict(os.environ, {"RISK_DEBUG_FIELDS": ""}), redirect_stderr(err):
        build.gh_field_values(item)
    assert err.getvalue() == "", "must stay quiet unless asked"


# Verbatim from a real org's probe output (puffins-mission issue #31) taken
# while Priority Level was still declared MULTI_SELECT. That org has since
# switched it to single-select -- which is what the dashboard expects, and
# what _gh_issue() above emits -- but this payload is kept as the
# regression fixture for the bug it exposed.
REAL_MULTISELECT_PRIORITY = {
    "id": "I_real31",
    "number": 31,
    "title": "Risk #31: something",
    "state": "OPEN",
    "url": "https://github.com/o/r/issues/31",
    "createdAt": NOW, "updatedAt": NOW, "closedAt": None,
    "body": "",
    "issueType": {"name": "Risk"},
    "labels": {"nodes": [{"name": "risk"}]},
    "assignees": {"nodes": []},
    "issueFieldValues": {"nodes": [
        {"__typename": "IssueFieldNumberValue", "value": 1.0,
         "field": {"__typename": "IssueFieldNumber",
                   "name": "Likelihood (L)", "dataType": "NUMBER"}},
        {"__typename": "IssueFieldNumberValue", "value": 1.0,
         "field": {"__typename": "IssueFieldNumber",
                   "name": "Consequence (C)", "dataType": "NUMBER"}},
        {"__typename": "IssueFieldMultiSelectValue",
         "options": [{"name": "Cost"}, {"name": "Schedule"}],
         "field": {"__typename": "IssueFieldMultiSelect",
                   "name": "Risk Type", "dataType": "MULTI_SELECT"}},
        {"__typename": "IssueFieldMultiSelectValue",
         "options": [{"name": "Medium"}],
         "field": {"__typename": "IssueFieldMultiSelect",
                   "name": "Priority Level", "dataType": "MULTI_SELECT"}},
    ]},
}


def test_multiselect_priority_collapses_to_a_scalar() -> None:
    """Regression: Priority Level declared MULTI_SELECT yielded ["Medium"],
    which failed the `isinstance(priority, str)` guard and wrote null to
    history while Consequence/Likelihood (NUMBER) populated fine. The
    template compares priority against a scalar, so it must be one.

    Single-select is now the expected declaration, so this also asserts
    the misconfiguration is reported rather than silently absorbed."""
    build._MULTI_FOR_SINGLE_FIELDS.clear()
    err = io.StringIO()
    with redirect_stderr(err):
        norm = build.normalize_github(REAL_MULTISELECT_PRIORITY)
    assert "Priority Level" in err.getvalue(), \
        "a multi-select Priority Level is a misconfiguration; say so"
    assert "single-select" in err.getvalue()
    build._MULTI_FOR_SINGLE_FIELDS.clear()
    assert norm["priority"] == "Medium", "a one-option multi-select is a scalar here"
    assert isinstance(norm["priority"], str)
    assert norm["consequence"] == 1 and norm["likelihood"] == 1
    assert norm["risk_types"] == ["Cost", "Schedule"], \
        "Risk Type stays genuinely multi-valued"


def test_single_select_is_the_expected_shape_and_stays_quiet() -> None:
    """The configuration this org now has: Priority Level single-select.
    It must resolve without any warning at all."""
    build._MULTI_FOR_SINGLE_FIELDS.clear()
    item = _gh_issue(31, "Risk #31", 1.0, 1.0, "Medium",
                     ["Cost", "Schedule"], ["risk"])
    prio = [fv for fv in item["issueFieldValues"]["nodes"]
            if fv["field"]["name"] == build.CF_PRIORITY]
    assert prio and prio[0]["__typename"] == "IssueFieldSingleSelectValue", \
        "fixture should model the current single-select declaration"
    err = io.StringIO()
    with redirect_stderr(err):
        norm = build.normalize_github(item)
    assert norm["priority"] == "Medium"
    assert norm["risk_types"] == ["Cost", "Schedule"]
    assert err.getvalue() == "", "the expected shape must not warn"


def test_single_valued_field_with_several_options_warns_and_takes_first() -> None:
    item = json.loads(json.dumps(REAL_MULTISELECT_PRIORITY))
    for fv in item["issueFieldValues"]["nodes"]:
        if fv.get("field", {}).get("name") == "Priority Level":
            fv["options"] = [{"name": "High"}, {"name": "Low"}]
    build._MULTI_FOR_SINGLE_FIELDS.clear()
    err = io.StringIO()
    with redirect_stderr(err):
        norm = build.normalize_github(item)
    assert norm["priority"] == "High"
    msg = err.getvalue()
    assert "Priority Level" in msg and "single-valued" in msg
    build._MULTI_FOR_SINGLE_FIELDS.clear()


def test_numeric_fields_tolerate_multiselect_too() -> None:
    """Same collapse applies to Consequence/Likelihood, in case an org
    declares those multi-select as well."""
    item = json.loads(json.dumps(REAL_MULTISELECT_PRIORITY))
    item["issueFieldValues"]["nodes"] = [
        {"__typename": "IssueFieldMultiSelectValue", "options": [{"name": "4"}],
         "field": {"name": "Consequence (C)"}},
        {"__typename": "IssueFieldMultiSelectValue", "options": [{"name": "3"}],
         "field": {"name": "Likelihood (L)"}},
    ]
    norm = build.normalize_github(item)
    assert norm["consequence"] == 4 and norm["likelihood"] == 3


def test_unknown_value_type_is_not_silently_dropped() -> None:
    """A value type added to the IssueFieldValue union after this was
    written must still populate if it exposes `value` or `name`, rather
    than vanishing into a blank column."""
    future = {"issueFieldValues": {"nodes": [{
        "__typename": "IssueFieldSomethingNewValue",
        "value": "whatever",
        "field": {"name": build.CF_PRIORITY},
    }]}}
    assert build.gh_value(build.gh_field_values(future), build.CF_PRIORITY) == "whatever"

    # One that exposes neither is skipped, but says so.
    build._UNHANDLED_FIELD_KINDS.clear()
    opaque = {"issueFieldValues": {"nodes": [{
        "__typename": "IssueFieldOpaqueValue",
        "field": {"name": build.CF_PRIORITY},
    }]}}
    err = io.StringIO()
    with redirect_stderr(err):
        assert build.gh_field_values(opaque) == {}
    assert "IssueFieldOpaqueValue" in err.getvalue()
    build._UNHANDLED_FIELD_KINDS.clear()


def test_number_fields_survive_float_round_trip() -> None:
    """Issue number fields are GraphQL Float, so a Consequence of 4 arrives
    as 4.0 and int('4.0') raises. Regression guard for to_int."""
    assert build.to_int(4.0) == 4
    assert build.to_int("4.0") == 4
    assert build.to_int("4") == 4
    assert build.to_int(None) is None
    assert build.to_int("n/a") is None


def test_search_query_construction() -> None:
    with patch.dict(os.environ, GH_ENV, clear=True):
        assert build.gh_search_query() == "org:example-org is:issue"
    with patch.dict(os.environ, {**GH_ENV, "RISK_GITHUB_ISSUE_TYPE": "Risk"}, clear=True):
        assert build.gh_search_query() == 'org:example-org is:issue type:"Risk"'
    with patch.dict(os.environ, {**GH_ENV, "RISK_GITHUB_SEARCH": "user:me is:issue"},
                    clear=True):
        assert build.gh_search_query() == "user:me is:issue", \
            "an explicit search must win, so user accounts and repo subsets work"
    with patch.dict(os.environ, {"RISK_PROVIDER": "github"}, clear=True):
        try:
            build.gh_search_query()
            raise AssertionError("expected SystemExit with no owner and no search")
        except SystemExit as e:
            assert "RISK_GITHUB_OWNER" in str(e)


def test_fetch_paginates_and_applies_issue_type() -> None:
    nodes = [
        _gh_issue(1, "Risk A", 4.0, 4.0, "High", ["Technical"], ["risk"]),
        _gh_issue(2, "Risk B", 2.0, 2.0, "Low", ["Cost"], ["risk"]),
        _gh_issue(5, "An ordinary task", 1.0, 1.0, None, [], ["risk"],
                  issue_type="Task"),
    ]
    calls: list[dict] = []
    with patch.dict(os.environ, {**GH_ENV, "RISK_GITHUB_ISSUE_TYPE": "Risk"}), \
         patch.object(build, "github_graphql",
                      _replay(_search_pages(nodes, 2), calls)), \
         redirect_stderr(io.StringIO()):
        raw = build.fetch_github_issues()

    assert len(calls) == 2, "should have followed every cursor"
    assert calls[0]["cursor"] is None and calls[1]["cursor"] == "cur0"
    assert calls[0]["q"] == 'org:example-org is:issue type:"Risk"'
    assert [r["number"] for r in raw] == [1, 2], \
        "issues of another type must be dropped even if search returns them"


def test_fetch_skips_non_issue_nodes_and_dedups() -> None:
    good = _gh_issue(9, "Risk dup", 3.0, 3.0, "Medium", ["Schedule"], ["risk"])
    pages = [{"search": {
        "issueCount": 1,
        "pageInfo": {"endCursor": None, "hasNextPage": False},
        # Search results are a union: unreadable or non-Issue hits come
        # back as empty objects.
        "nodes": [good, {}, None, good],
    }}]
    with patch.dict(os.environ, GH_ENV), \
         patch.object(build, "github_graphql", _replay(pages, [])), \
         redirect_stderr(io.StringIO()):
        raw = build.fetch_github_issues()
    assert [r["number"] for r in raw] == [9]


def test_fetch_warns_when_search_result_cap_truncates() -> None:
    """GitHub caps issue-search pagination depth. Silently rendering a
    partial risk register would be the worst possible failure, so it must
    be loud."""
    nodes = [_gh_issue(i, f"Risk {i}", 3.0, 3.0, "Low", ["Cost"], ["risk"])
             for i in range(1, 5)]
    err = io.StringIO()
    with patch.dict(os.environ, GH_ENV), \
         patch.object(build, "github_graphql",
                      _replay(_search_pages(nodes, 4, issue_count=1337), [])), \
         redirect_stderr(err):
        raw = build.fetch_github_issues()
    assert len(raw) == 4
    msg = err.getvalue()
    assert "1337" in msg and "MISSING" in msg
    assert "RISK_GITHUB_SEARCH" in msg, "the warning should say how to fix it"


def test_github_graphql_401_exits_with_actionable_message() -> None:
    class _Resp401:
        status_code = 401
        def raise_for_status(self):
            raise AssertionError("401 branch should exit before raise_for_status")
        def json(self):
            return {}

    with patch.dict(os.environ, {"GITHUB_TOKEN": "expired-token-value"}), \
         patch.object(build.requests, "post", return_value=_Resp401()):
        try:
            build.github_graphql("query {}", {})
            raise AssertionError("expected SystemExit on 401")
        except SystemExit as e:
            msg = str(e)
            assert "401" in msg and "EXPIRED" in msg
            assert str(len("expired-token-value")) in msg


def test_graphql_endpoint_resolution() -> None:
    cases = [
        ({}, "https://api.github.com/graphql"),
        ({"GITHUB_API_URL": "https://api.github.com"}, "https://api.github.com/graphql"),
        ({"GITHUB_API_URL": "https://ghe.example.com/api/v3"},
         "https://ghe.example.com/api/graphql"),
        ({"GITHUB_SERVER_URL": "https://ghe.example.com"},
         "https://ghe.example.com/api/graphql"),
    ]
    for env, expected in cases:
        with patch.dict(os.environ, env, clear=True):
            assert build.github_graphql_endpoint() == expected, env


def test_forge_links_are_provider_specific() -> None:
    with patch.dict(os.environ, {"RISK_PROVIDER": "gitlab",
                                 "CI_PROJECT_URL": "https://gitlab.example.com/stp/dash",
                                 "CI_DEFAULT_BRANCH": "main"}):
        gl = build.forge_links("https://gitlab.example.com", "stp/dash")
    assert gl["provider_name"] == "GitLab"
    assert gl["label_url_prefix"] == \
        "https://gitlab.example.com/groups/stp/-/issues?label_name%5B%5D="
    assert gl["label_url_suffix"] == ""
    assert gl["run_ci_url"] == "https://gitlab.example.com/stp/dash/-/pipelines/new?ref=main"
    assert gl["schedules_url"].endswith("/-/pipeline_schedules")
    assert "/-/commit/" in gl["commit_link"]

    with patch.dict(os.environ, {**GH_ENV, "GITHUB_SHA": "abcdef1234567890"}):
        gh = build.forge_links("https://github.com", "example-org/dash")
    assert gh["provider_name"] == "GitHub"
    assert gh["label_url_prefix"].startswith("https://github.com/search?type=issues&q=")
    assert "org%3Aexample-org" in gh["label_url_prefix"]
    assert gh["label_url_prefix"].endswith("%22") and gh["label_url_suffix"] == "%22"
    assert gh["run_ci_url"] == \
        "https://github.com/example-org/dash/actions/workflows/dashboard.yml"
    assert gh["commit_link"] == "https://github.com/example-org/dash/commit/abcdef123456"
    assert "/-/" not in gh["label_url_prefix"] + gh["run_ci_url"] + gh["commit_link"]


def test_schema_check_warns_on_unmatched_field_names() -> None:
    node = _gh_issue(7, "Risk", 4.0, 4.0, "High", ["Cost"], ["risk"],
                     consequence_field="Severity")   # wrong name on purpose
    for fv in node["issueFieldValues"]["nodes"]:
        fv["field"]["dataType"] = "NUMBER"
    probe = {"search": {"issueCount": 3, "nodes": [node]}}
    err = io.StringIO()
    with patch.dict(os.environ, {**GH_ENV, "RISK_GITHUB_ISSUE_TYPE": "Risk"}), \
         patch.object(build, "github_graphql", lambda q, v: probe), \
         redirect_stderr(err):
        build.github_schema_check()
    msg = err.getvalue()
    assert "matches 3 issue(s)" in msg
    assert build.CF_CONSEQUENCE in msg, "should name the field it could not find"
    assert "Severity" in msg, "should list the fields the issue actually has"

    err = io.StringIO()
    with patch.dict(os.environ, GH_ENV), \
         patch.object(build, "github_graphql",
                      lambda q, v: {"search": {"issueCount": 0, "nodes": []}}), \
         redirect_stderr(err):
        build.github_schema_check()
    assert "matched nothing" in err.getvalue()


def test_end_to_end_github_render(tmp_path: Path) -> None:
    """main() against a fabricated org: history, matrix and HTML all come
    out of the provider-agnostic half of build.py untouched."""
    raw = [
        _gh_issue(1, "Risk #A: Planetary contamination", 5.0, 4.0, "High",
                  ["Technical", "Schedule"], ["risk", "thermal"],
                  body="## Risk Description\n\nAerocapture breakup."),
        _gh_issue(2, "Risk #B: Staffing for legacy software", 2.0, 2.0, "Low",
                  ["Schedule"], ["risk", "software"],
                  body="Only two people know the codebase."),
        _gh_issue(3, "Risk #C: Unscored", None, None, None, [], ["risk", "optics"]),
    ]
    env = {**GH_ENV, "RISK_GITHUB_ISSUE_TYPE": "Risk",
           "GITHUB_REPOSITORY": "example-org/risks-dashboard",
           "GITHUB_SHA": "0123456789ab"}
    with patch.dict(os.environ, env), \
         patch.object(build, "HISTORY_PATH", tmp_path / "data" / "history.ndjson"), \
         patch.object(build, "PUBLIC_DIR", tmp_path / "public"), \
         patch.object(build, "schema_check", lambda: None), \
         patch.object(build, "fetch_work_items", lambda: raw), \
         redirect_stderr(io.StringIO()):
        build.main()

    html = (tmp_path / "public" / "index.html").read_text()
    assert "Risk Dashboard — example-org · Risk" in html
    assert "Planetary contamination" in html
    assert "Score them in GitHub to bring them in." in html
    assert 'const PROVIDER_NAME = "GitHub";' in html
    assert "/-/issues?label_name" not in html, "no GitLab URL shapes on the GitHub path"
    assert "/-/pipelines/new" not in html
    assert "actions/workflows/dashboard.yml" in html

    rows = [json.loads(l) for l in
            (tmp_path / "data" / "history.ndjson").read_text().splitlines() if l.strip()]
    assert {r["iid"] for r in rows} == {"1", "2", "3"}
    first = [r for r in rows if r["iid"] == "1"][0]
    assert first["consequence"] == 5
    assert first["risk_types"] == ["Technical", "Schedule"]


if __name__ == "__main__":
    import tempfile
    test_provider_selection()
    test_query_reads_issue_fields_not_projects_v2()
    test_normalize_github_matches_gitlab()
    test_field_names_match_without_the_gitlab_suffix()
    test_blank_env_var_falls_back_to_the_default_field_name()
    test_single_select_priority_populates()
    test_value_with_unresolvable_field_name_warns()
    test_debug_fields_dumps_raw_nodes()
    test_multiselect_priority_collapses_to_a_scalar()
    test_single_select_is_the_expected_shape_and_stays_quiet()
    test_single_valued_field_with_several_options_warns_and_takes_first()
    test_numeric_fields_tolerate_multiselect_too()
    test_unknown_value_type_is_not_silently_dropped()
    test_number_fields_survive_float_round_trip()
    test_search_query_construction()
    test_fetch_paginates_and_applies_issue_type()
    test_fetch_skips_non_issue_nodes_and_dedups()
    test_fetch_warns_when_search_result_cap_truncates()
    test_github_graphql_401_exits_with_actionable_message()
    test_graphql_endpoint_resolution()
    test_forge_links_are_provider_specific()
    test_schema_check_warns_on_unmatched_field_names()
    with tempfile.TemporaryDirectory() as d:
        test_end_to_end_github_render(Path(d))
    print("OK")
