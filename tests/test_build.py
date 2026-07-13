"""End-to-end test for build.py using mocked GitLab responses.

Runs the full main() pipeline against a fabricated GraphQL payload, asserts
on the matrix counts, history-append semantics, vanished->closed handling,
and unscored bucketing. Leaves behind public/index.html as a working
example of the dashboard.

Sample risks are loosely based on examples from the NASA Risk Management
Handbook (NASA/SP-2011-3422, Rev. A, 2023):
https://www.nasa.gov/wp-content/uploads/2023/08/nasa-risk-mgmt-handbook.pdf
Risk #1(a) Planetary Contamination and Risk #8 Staffing for Legacy
Software are paraphrased from the handbook; the remaining items are
synthetic variations in similar style for matrix-population purposes.

Run:
    python -m pytest tests/test_build.py -v
or directly:
    python tests/test_build.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build  # noqa: E402


def _item(
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
    """Build a raw GraphQL work-item node matching what build.fetch_work_items returns."""
    cf_values: list[dict] = []
    if c is not None:
        cf_values.append(
            {
                "customField": {"id": "gid://1", "name": build.CF_CONSEQUENCE, "fieldType": "SINGLE_SELECT"},
                "selectedOptions": [{"id": f"gid://opt/c{c}", "value": c}],
            }
        )
    if l is not None:
        cf_values.append(
            {
                "customField": {"id": "gid://2", "name": build.CF_LIKELIHOOD, "fieldType": "SINGLE_SELECT"},
                "selectedOptions": [{"id": f"gid://opt/l{l}", "value": l}],
            }
        )
    if priority is not None:
        cf_values.append(
            {
                "customField": {"id": "gid://3", "name": build.CF_PRIORITY, "fieldType": "SINGLE_SELECT"},
                "selectedOptions": [{"id": f"gid://opt/p{priority}", "value": priority}],
            }
        )
    if risk_types:
        cf_values.append(
            {
                "customField": {"id": "gid://4", "name": build.CF_RISK_TYPE, "fieldType": "MULTI_SELECT"},
                "selectedOptions": [{"id": f"gid://opt/rt{rt}", "value": rt} for rt in risk_types],
            }
        )
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    widgets: list[dict] = [
        {"type": "LABELS", "labels": {"nodes": [{"title": ln} for ln in labels]}},
        {"type": "CUSTOM_FIELDS", "customFieldValues": cf_values},
    ]
    if description:
        widgets.append({"type": "DESCRIPTION", "description": description})
    if assignees:
        widgets.append({
            "type": "ASSIGNEES",
            "assignees": {"nodes": [
                {"id": f"gid://user/{a['username']}", "username": a["username"],
                 "name": a.get("name", a["username"]),
                 "webUrl": f"https://gitlab.example.com/{a['username']}"}
                for a in assignees
            ]},
        })
    return {
        "id": f"gid://gitlab/WorkItem/{iid}",
        "iid": str(iid),
        "title": title,
        "state": state,
        "webUrl": f"https://gitlab.example.com/stp/sub/-/work_items/{iid}",
        "createdAt": now,
        "updatedAt": now,
        "closedAt": None,
        "widgets": widgets,
    }


SAMPLE_DESC_PLANETARY = """## Risk Description

Given that the state of knowledge of Planet X's atmosphere is **limited**, that it is
difficult to ascertain more information about Planet X's atmosphere from Earth, and that
the spacecraft contains radioactive material, there is a possibility of unanticipated
atmospheric characteristics during the aerocapture maneuver at Planet X leading to a
less-than-optimal trajectory adversely impacting the spacecraft, thereby resulting in
spacecraft breakup and radioactive contamination of Planet X.

### Narrative

The atmosphere of Planet X has been observed with ground-based and Earth-orbital
telescopes, including during eclipses, and spectral analysis of the data has been
performed. There have also been flybys to observe atmosphere thickness, species, and
density. Uncertainties in the results are large because of inherent variability in the
atmosphere, both spatially and timewise. Additionally there is considerable inherent
uncertainty in the heat-shield thermal-response models, which are based on assumptions
about the effects of ionizing radiation on heat transfer and the condition of the
vehicle surface as it affects boundary-layer transition.

## Notes

- Refine atmospheric uncertainty model with the latest flyby data.
- Add margin to heat-shield ablation analysis for upper-bound density.
- Coordinate with the planetary protection office on contamination scenarios.

## Mitigation Plan

If shield margin remains below 30% after the refined analysis, expand the aerocapture
corridor or switch to a propulsive orbit-insertion strategy. Estimated schedule impact
~6 months; cost impact ~$45M.

*Source: NASA Risk Management Handbook (NASA/SP-2011-3422, Rev. A), Example 1(a).*
"""

SAMPLE_DESC_STAFFING = """## Risk Description

Given that the decision has been made to adapt legacy software for this mission and the
Agency projects a scarcity of qualified programmers familiar with the legacy language,
there is a possibility that there may be **insufficient staffing at the high labor
categories** adversely impacting the control software, which could result in delays in
the delivery of the software and/or software reliability issues.

### Narrative

NASA's budget for future years reflects reduced funding for certain legacy programs and
in some cases outright termination of the program. It is anticipated that this will lead
to retirements and/or resignations as qualified staff review their options. In
particular, a predominance of the staff departures may be in the higher labor categories
among people who have experience using the programming languages associated with the
legacy software.

## Notes

- Survey current legacy-language staff for retirement intent within the next 24 months.
- Begin knowledge-capture sprints with senior engineers.
- Open requisitions for two senior engineers familiar with the legacy stack.

## Mitigation Plan

If the staffing gap exceeds 2 FTE at the high labor categories, accelerate the porting
effort to the modern language and accept an ~9-month schedule slip.

*Source: NASA Risk Management Handbook (NASA/SP-2011-3422, Rev. A), Example 8.*
"""

SAMPLE_ITEMS = [
    _item(1, "Risk# 1A Planetary contamination from aerocapture breakup",
          "5", "3", "High", ["Technical"],
          ["thermal", "mechanical", "TO12- Planet X EDL", "WCC100"],
          description=SAMPLE_DESC_PLANETARY,
          assignees=[{"username": "sride", "name": "Sally Ride"}]),
    _item(2, "Risk# 8 Staffing for legacy software",
          "4", "4", "High", ["Schedule", "Cost"],
          ["software", "TO8- Software Dev", "WCC078"],
          description=SAMPLE_DESC_STAFFING,
          assignees=[{"username": "mjemison", "name": "Mae Jemison"}]),
    _item(3, "Cryocooler procurement long lead", "5", "2", "High", ["Cost", "Schedule"],
          ["thermal", "mechanical", "TO6- WCC Pre-SRR"]),
    _item(4, "Spacecraft Pu power source thermal loading",
          "4", "3", "High", ["Technical"], ["thermal", "TO12- Planet X EDL"]),
    _item(5, "FPGA single-event upset susceptibility",
          "3", "3", "Medium", ["Technical"], ["electrical", "software", "TO8- Software Dev"]),
    _item(6, "Ground software test bed availability", "2", "4", "Medium", ["Schedule"],
          ["software", "TO8- Software Dev"]),
    _item(7, "Documentation backlog for closeout package",
          "1", "2", "Low", ["Schedule"], ["software"]),
    _item(8, "On-board storage margin below 20%", "2", "2", "Low", ["Technical"],
          ["software", "WCC078"]),
    _item(9, "Vibration test fixture rework", "3", "2", "Medium", ["Cost"],
          ["mechanical", "TO6- WCC Pre-SRR"]),
    _item(10, "Optical contamination during integration",
          "4", "4", "High", ["Technical"], ["optics", "WCC100", "ESC033"]),
    _item(11, "Unscored placeholder pending review",
          None, None, "Low", [], ["software"]),
]


def _backdate_history(history_path: Path) -> None:
    """Pre-populate history.ndjson with a small backdated trail so the
    90-day trend chart and 30-day movement section render something
    meaningful in the example output."""
    rows: list[dict] = []
    now = datetime.now(timezone.utc)

    def row(days_ago: int, iid: int, title: str, c, l, state="open", priority="High",
            risk_types=None, subsystems=None) -> dict:
        ts = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
        return {
            "ts": ts,
            "id": f"gid://gitlab/WorkItem/{iid}",
            "iid": str(iid),
            "title": title,
            "state": state,
            "consequence": c,
            "likelihood": l,
            "priority": priority,
            "risk_types": risk_types or [],
            "subsystems": subsystems or [],
            "web_url": f"https://gitlab.example.com/stp/sub/-/work_items/{iid}",
        }

    # #1 escalated 10 days ago: was C4xL2, now C5xL3
    rows.append(row(60, 1, "Planetary contamination", 4, 2, priority="High",
                    risk_types=["Technical"], subsystems=["mechanical", "thermal"]))
    rows.append(row(10, 1, "Planetary contamination", 5, 3, priority="High",
                    risk_types=["Technical"], subsystems=["mechanical", "thermal"]))
    # #4 de-escalated 5 days ago: was C5xL3, now C4xL3
    rows.append(row(45, 4, "Pu thermal loading", 5, 3, priority="High",
                    risk_types=["Technical"], subsystems=["thermal"]))
    rows.append(row(5, 4, "Pu thermal loading", 4, 3, priority="High",
                    risk_types=["Technical"], subsystems=["thermal"]))
    # #6 is new 3 days ago
    rows.append(row(3, 6, "Ground software test bed availability", 2, 4, priority="Medium",
                    risk_types=["Schedule"], subsystems=["software"]))
    # #99 closed last week (still in history, won't be in current items -> synthetic closure
    # was already recorded earlier)
    rows.append(row(20, 99, "Retired vendor risk", 3, 3, priority="Low",
                    risk_types=["Cost"], subsystems=["electrical"]))
    rows.append(row(7, 99, "Retired vendor risk", 3, 3, state="closed", priority="Low",
                    risk_types=["Cost"], subsystems=["electrical"]))
    # A second long history for trend variety on #2
    for d, c, l in [(80, 2, 2), (70, 3, 3), (40, 4, 3), (20, 4, 4)]:
        rows.append(row(d, 2, "Legacy software staffing", c, l, priority="High",
                        risk_types=["Schedule", "Cost"], subsystems=["software"]))
    # History for #10 so it co-renders on the per-risk chart with #2 (both score 16)
    # and the bracket logic in drawRiskTrends has a multi-item group to draw.
    for d, c, l in [(60, 3, 3), (30, 3, 4), (10, 4, 4)]:
        rows.append(row(d, 10, "Optical contamination during integration", c, l,
                        priority="High", risk_types=["Technical"], subsystems=["optics"]))

    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def _run_main_with_items(items: list[dict]) -> None:
    os.environ.setdefault("CI_SERVER_URL", "https://gitlab.example.com")
    os.environ.setdefault("CI_PROJECT_PATH", "stp/gitlab-risk-tracker")
    # Disable the production RISK_LABEL_FILTER for these fixtures
    # (which use labels like 'thermal' / 'optics' / 'TO12- ...' that
    # don't contain "risk"). The filter itself has its own unit test.
    os.environ.setdefault("RISK_LABEL_FILTER", "")
    with patch.object(build, "schema_check", lambda: None), \
         patch.object(build, "fetch_work_items", lambda: items):
        build.main()


def test_build_dashboard(tmp_path_factory=None) -> None:
    # Use the real repo paths (not a tmpdir) so the rendered output is
    # left behind as an example.
    history_path = build.HISTORY_PATH
    public_dir = build.PUBLIC_DIR
    if history_path.exists():
        history_path.unlink()
    if public_dir.exists():
        shutil.rmtree(public_dir)

    _backdate_history(history_path)
    rows_before = sum(1 for _ in history_path.open())

    _run_main_with_items(SAMPLE_ITEMS)

    # public/index.html exists and contains the dashboard skeleton.
    out = public_dir / "index.html"
    assert out.exists(), "public/index.html was not generated"
    html = out.read_text()
    assert "Risk Dashboard" in html
    assert "Consequence" in html and "Likelihood" in html
    # All sample issue titles end up in the rendered page (matrix cell lists
    # truncate to 28 chars, so match a stem).
    assert "Planetary contamination" in html
    # The unscored item must not land in any matrix cell, but may appear in
    # the "new" movement card. Check that #11 is absent from cells_json.
    cells_json = json.loads(html.split("const cells = ", 1)[1].split(";", 1)[0])
    cell_iids = {issue["iid"] for cell in cells_json.values() for issue in cell}
    assert "11" not in cell_iids, "unscored item leaked into a matrix cell"
    # Every cell item must carry a display_title and products for the JS to render & filter.
    for cell in cells_json.values():
        for issue in cell:
            assert "display_title" in issue, "display_title missing from cells JSON"
            assert "products" in issue, "products missing from cells JSON"

    # Items with the labels we seeded must land in the combined products list.
    item1 = next(i for cell in cells_json.values() for i in cell if i["iid"] == "1")
    assert "TO12- Planet X EDL" in item1["products"]
    assert "WCC100" in item1["products"]
    item10 = next(i for cell in cells_json.values() for i in cell if i["iid"] == "10")
    assert "ESC033" in item10["products"]

    # Filter UI: all product label values must appear in the single combined dropdown.
    for v in ("TO6- WCC Pre-SRR", "TO8- Software Dev", "TO12- Planet X EDL",
              "ESC033", "WCC078", "WCC100"):
        assert v in html, f"expected filter option {v!r} not rendered"
    # Patterns string is rendered for the user.
    for p in build.PRODUCT_PATTERNS:
        assert p in html, f"product pattern {p!r} not displayed"

    # Subsystem select is now multi-select.
    assert 'id="f-subsystem" multiple' in html
    # Status filter present with Open default.
    assert 'id="f-status"' in html
    assert '<option value="open" selected>Open</option>' in html

    # Risk# prefix gets stripped from #1's title.
    assert item1["display_title"] == "Planetary contamination from aerocapture breakup"

    # Risks table: must contain item #1 with rendered section HTML and the assignee.
    risks_json_str = html.split("const risks = ", 1)[1].split(";\nconst SECTION_META", 1)[0]
    risks_json = json.loads(risks_json_str)
    row1 = next(r for r in risks_json if r["iid"] == "1")
    assert row1["assignees"] and row1["assignees"][0]["name"] == "Sally Ride"
    rd = row1["sections"]["risk_description"]
    assert "<strong>limited</strong>" in rd["html"], "markdown bold not rendered to HTML"
    assert "atmosphere" in rd["preview"]
    ap = row1["sections"]["notes"]
    assert "<li>" in ap["html"], "markdown list not rendered to HTML"
    assert row1["sections"]["mitigation_plan"]["full_text"].startswith("If shield margin")
    # Score is computed.
    assert row1["score"] == 15

    # The table section is rendered with toolbar + export button.
    assert 'id="risks-table"' in html
    assert 'id="export-csv"' in html
    assert 'id="col-toggles"' in html
    # Subsystem bars
    for sub in build.SUBSYSTEMS:
        assert f">{sub}<" in html, f"subsystem {sub} missing from rendered HTML"

    # History: only changed items append new rows. Backdated trail had
    # #1 at C5xL4 already (same as current), #2 at C4xL5 (same as current),
    # #4 at C4xL3 (same as current), #6 at C2xL4 (same as current).
    # Items #3, #5, #7, #8, #9, #11 have no prior history -> new rows.
    # (#10 has backdated history matching its current state so no new row.)
    rows_after = sum(1 for _ in history_path.open())
    expected_new = 6
    assert rows_after - rows_before == expected_new, (
        f"expected {expected_new} new history rows, got {rows_after - rows_before}"
    )

    # Re-running with the same items is idempotent.
    _run_main_with_items(SAMPLE_ITEMS)
    rows_after_2 = sum(1 for _ in history_path.open())
    assert rows_after_2 == rows_after, "re-run with no changes should not append"

    # Mutate item #5 (escalate C 3->4) and drop item #10 (vanished -> closed).
    mutated = []
    for it in SAMPLE_ITEMS:
        if it["iid"] == "10":
            continue
        if it["iid"] == "5":
            it = json.loads(json.dumps(it))  # deepcopy via json
            for w in it["widgets"]:
                if w["type"] == "CUSTOM_FIELDS":
                    for cf in w["customFieldValues"]:
                        if cf["customField"]["name"] == build.CF_CONSEQUENCE:
                            cf["selectedOptions"] = [{"id": "gid://opt/c4", "value": "4"}]
        mutated.append(it)
    _run_main_with_items(mutated)
    rows_after_3 = sum(1 for _ in history_path.open())
    assert rows_after_3 == rows_after_2 + 2, (
        "expected exactly 2 new rows (mutation of #5, synthetic close of #10), "
        f"got {rows_after_3 - rows_after_2}"
    )

    # Verify the synthetic close row.
    last_lines = history_path.read_text().splitlines()[-2:]
    parsed = [json.loads(line) for line in last_lines]
    closed = [r for r in parsed if r["state"] == "closed" and r["iid"] == "10"]
    assert closed, "expected a synthetic closed row for vanished item #10"
    escalated = [r for r in parsed if r["iid"] == "5"]
    assert escalated and escalated[0]["consequence"] == 4

    # Restore the canonical state for the example: re-render against the
    # original SAMPLE_ITEMS so the published public/index.html shows the
    # full 10-item matrix.
    _run_main_with_items(SAMPLE_ITEMS)
    # Promote the freshly-rendered dashboard to the docs static directory
    # so it ships with the published Sphinx site as a live preview.
    example_target = build.ROOT / "docs" / "_static" / "example_dashboard.html"
    example_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out, example_target)
    print(f"\nWrote example dashboard to: {out}")
    print(f"Copied to docs/_static for the published preview: {example_target}")
    print(f"History rows: {sum(1 for _ in history_path.open())}")


def test_every_snapshot_field_change_is_retained(tmp_path) -> None:
    """For each field in SNAPSHOT_FIELDS, mutate it across successive runs
    and confirm history.ndjson grows by exactly one row per change with
    the new value persisted."""
    history_path = tmp_path / "history.ndjson"
    saved_history = build.HISTORY_PATH
    saved_public = build.PUBLIC_DIR
    build.HISTORY_PATH = history_path
    build.PUBLIC_DIR = tmp_path / "public"
    try:
        baseline = [_item(
            42, "Baseline risk", "3", "3", "Medium", ["Technical"],
            ["software", "TO6- WCC Pre-SRR"],
        )]
        # First run seeds one row.
        _run_main_with_items(baseline)
        assert _count_lines(history_path) == 1

        # Re-running identical input must not append.
        _run_main_with_items(baseline)
        assert _count_lines(history_path) == 1, "idempotent re-run failed"

        # Sequence of single-field mutations. Each must add exactly 1 row.
        mutations = [
            # (description, mutator, expected snapshot-field, expected new value)
            ("change consequence 3->4",
             _set_cf(build.CF_CONSEQUENCE, "4"),
             "consequence", 4),
            ("change likelihood 3->5",
             _set_cf(build.CF_LIKELIHOOD, "5"),
             "likelihood", 5),
            ("change priority Medium->High",
             _set_cf(build.CF_PRIORITY, "High"),
             "priority", "High"),
            ("change risk_types Technical->[Cost, Schedule]",
             _set_multi(build.CF_RISK_TYPE, ["Cost", "Schedule"]),
             "risk_types", ["Cost", "Schedule"]),
            ("add subsystem optics",
             _set_labels(["software", "optics", "TO6- WCC Pre-SRR"]),
             "subsystems", ["optics", "software"]),
            ("close the issue",
             _set_state("CLOSED"),
             "state", "closed"),
        ]
        prev_count = _count_lines(history_path)
        for desc, mutate, field, expected in mutations:
            items = [mutate(json.loads(json.dumps(baseline[0])))]
            # Each step builds on the previous step's accumulated state, so
            # update baseline to carry forward.
            baseline = items
            _run_main_with_items(items)
            cur = _count_lines(history_path)
            assert cur == prev_count + 1, (
                f"{desc}: expected exactly 1 new row, got {cur - prev_count}"
            )
            last = json.loads(history_path.read_text().splitlines()[-1])
            assert last[field] == expected, (
                f"{desc}: last row's {field} = {last[field]!r}, expected {expected!r}"
            )
            prev_count = cur
    finally:
        build.HISTORY_PATH = saved_history
        build.PUBLIC_DIR = saved_public


def test_multiple_items_changing_in_one_run(tmp_path) -> None:
    """Several items changing in the same run all get individual rows."""
    history_path = tmp_path / "history.ndjson"
    saved_history = build.HISTORY_PATH
    saved_public = build.PUBLIC_DIR
    build.HISTORY_PATH = history_path
    build.PUBLIC_DIR = tmp_path / "public"
    try:
        items = [
            _item(101, "Risk A", "2", "2", "Low",  ["Technical"], ["software"]),
            _item(102, "Risk B", "3", "3", "Medium", ["Cost"],     ["thermal"]),
            _item(103, "Risk C", "4", "4", "High",   ["Schedule"], ["optics"]),
        ]
        _run_main_with_items(items)
        assert _count_lines(history_path) == 3  # 3 first-seen rows

        # Change C on A, L on B, leave C unchanged.
        mutated = [
            _set_cf(build.CF_CONSEQUENCE, "4")(json.loads(json.dumps(items[0]))),
            _set_cf(build.CF_LIKELIHOOD,  "5")(json.loads(json.dumps(items[1]))),
            json.loads(json.dumps(items[2])),
        ]
        _run_main_with_items(mutated)
        assert _count_lines(history_path) == 5, (
            "expected 2 new rows (A and B changed, C unchanged)"
        )
    finally:
        build.HISTORY_PATH = saved_history
        build.PUBLIC_DIR = saved_public


def _count_lines(p: Path) -> int:
    return sum(1 for _ in p.open()) if p.exists() else 0


def _set_cf(field_name: str, value: str):
    def mutate(it):
        for w in it["widgets"]:
            if w["type"] == "CUSTOM_FIELDS":
                found = False
                for cf in w["customFieldValues"]:
                    if cf["customField"]["name"] == field_name:
                        cf["selectedOptions"] = [{"id": f"gid://opt/{value}", "value": value}]
                        found = True
                if not found:
                    w["customFieldValues"].append({
                        "customField": {"id": "gid://", "name": field_name, "fieldType": "SINGLE_SELECT"},
                        "selectedOptions": [{"id": f"gid://opt/{value}", "value": value}],
                    })
        return it
    return mutate


def _set_multi(field_name: str, values: list[str]):
    def mutate(it):
        for w in it["widgets"]:
            if w["type"] == "CUSTOM_FIELDS":
                for cf in w["customFieldValues"]:
                    if cf["customField"]["name"] == field_name:
                        cf["selectedOptions"] = [
                            {"id": f"gid://opt/{v}", "value": v} for v in values
                        ]
                        return it
                w["customFieldValues"].append({
                    "customField": {"id": "gid://", "name": field_name, "fieldType": "MULTI_SELECT"},
                    "selectedOptions": [{"id": f"gid://opt/{v}", "value": v} for v in values],
                })
        return it
    return mutate


def _set_labels(labels: list[str]):
    def mutate(it):
        for w in it["widgets"]:
            if w["type"] == "LABELS":
                w["labels"] = {"nodes": [{"title": l} for l in labels]}
        return it
    return mutate


def _set_state(state: str):
    def mutate(it):
        it["state"] = state
        return it
    return mutate


def test_graphql_401_exits_with_actionable_message() -> None:
    """A 401 from GitLab (expired/revoked token) must exit with a clear
    diagnosis instead of an HTTPError traceback — this is the most common
    production failure once a group access token hits its expiry date."""
    class _Resp401:
        status_code = 401
        def raise_for_status(self):
            raise AssertionError("401 branch should exit before raise_for_status")
        def json(self):
            return {}

    env = {"GITLAB_TOKEN": "expired-token-value", "CI_SERVER_URL": "https://gl.example.com"}
    with patch.dict(os.environ, env), \
         patch.object(build.requests, "post", return_value=_Resp401()):
        try:
            build.graphql("query {}", {})
            raise AssertionError("expected SystemExit on 401")
        except SystemExit as e:
            msg = str(e)
            assert "401" in msg
            assert "EXPIRED" in msg, "message should point at token expiry"
            assert "read_api" in msg, "message should say how to fix it"
            assert str(len("expired-token-value")) in msg, \
                "message should include the observed token length"


def test_render_markdown_sanitization() -> None:
    """User-controlled issue descriptions get HTML-injected into the
    modal via innerHTML. render_markdown() must strip script tags,
    iframes, and javascript: URLs while keeping legitimate markdown
    output (bold, links, lists, code, headings)."""
    hostile = (
        "# Heading\n\n"
        "**bold** and a [bad link](javascript:alert(1)) "
        "and a [good link](https://example.com).\n\n"
        "<script>alert('xss')</script>\n"
        "<iframe src='https://evil.example/'></iframe>\n\n"
        "- item one\n"
        "- item two\n\n"
        "```\nsome code\n```\n"
    )
    out = build.render_markdown(hostile)
    # Dangerous markup is gone.
    assert "<script" not in out.lower(), f"script tag not stripped: {out!r}"
    assert "<iframe" not in out.lower(), f"iframe not stripped: {out!r}"
    assert "javascript:" not in out.lower(), (
        f"javascript: URL not stripped: {out!r}"
    )
    # Legitimate content survives.
    assert "<strong>bold</strong>" in out
    assert 'href="https://example.com"' in out
    assert "<h1>" in out
    assert "<li>" in out
    assert "<code>" in out
    # Empty / None handled.
    assert build.render_markdown(None) == ""
    assert build.render_markdown("") == ""


def test_parse_sections() -> None:
    md = """
Stuff before any heading is ignored.

## Risk Description

Body of description.
Multiple lines.

### Subheading inside still counts as boundary
Other content.

## Notes
- Do thing
- Do other thing

### Random unrelated heading
Filler.

# Plan:
Mitigation body.
"""
    out = build.parse_sections(md)
    assert "risk_description" in out
    assert out["risk_description"].startswith("Body of description.")
    assert "notes" in out
    assert "- Do thing" in out["notes"]
    assert "mitigation_plan" in out
    assert out["mitigation_plan"].startswith("Mitigation body.")
    # "Mitigation Plan" canonical heading also resolves.
    assert "mitigation_plan" in build.parse_sections("## Mitigation Plan\nbody")

    # Missing description / unknown heading -> not present, no crash.
    assert build.parse_sections(None) == {}
    assert build.parse_sections("") == {}
    # Non-canonical heading with no leading prose -> still empty.
    assert build.parse_sections("## Unknown\nbody") == {}


def test_parse_sections_bare_body_fallback() -> None:
    """A description with no canonical Risk Description heading falls
    back to using the leading prose (text before the first heading, or
    the whole body if there are no headings) as the Risk Description.
    """
    # Whole body is bare prose -> all of it becomes risk_description.
    bare = "If fixture does not fit on the air cart, then we cannot move within the facility."
    out = build.parse_sections(bare)
    assert out.get("risk_description") == bare

    # Leading prose followed by an unrelated heading -> prose still
    # becomes risk_description (the unrelated heading is ignored).
    mixed = (
        "Bare prose risk statement here.\n\n"
        "## Unknown\n"
        "other content\n"
    )
    out = build.parse_sections(mixed)
    assert out.get("risk_description", "").startswith("Bare prose risk statement here.")

    # Leading prose + an explicit ## Notes heading -> Notes wins for
    # notes, leading prose becomes risk_description.
    mixed_notes = (
        "Bare description.\n\n"
        "## Notes\n"
        "- a note\n"
    )
    out = build.parse_sections(mixed_notes)
    assert out.get("risk_description") == "Bare description."
    assert out.get("notes") == "- a note"

    # An explicit ## Risk Description heading wins over leading prose:
    # leading prose is NOT used as a fallback when the canonical
    # heading is present.
    with_header = (
        "Leading prose that should be ignored.\n\n"
        "## Risk Description\n\n"
        "Actual described risk.\n"
    )
    out = build.parse_sections(with_header)
    assert out["risk_description"] == "Actual described risk."

    # Whitespace-only leading prose -> no fallback, risk_description absent.
    assert "risk_description" not in build.parse_sections(
        "   \n\n## Unknown\nbody"
    )


def test_clean_title() -> None:
    cases = [
        ("Risk# WCC100 - NSV mount drift", "NSV mount drift"),
        ("RISK# ESC046 ARB 350 thermal limit", "ARB 350 thermal limit"),
        ("Risk#ESC033: DM Cable harness", "DM Cable harness"),
        ("Risk#WCC078: Tool obsolescence", "Tool obsolescence"),
        ("Coating delamination under thermal cycling", "Coating delamination under thermal cycling"),
        ("  risk # ABC123 — Detail", "Detail"),
        ("Risk#XYZ999", "Risk#XYZ999"),  # nothing after the prefix -> fall back to original
        ("", ""),
        (None, ""),
    ]
    for raw, expected in cases:
        got = build.clean_title(raw)
        assert got == expected, f"clean_title({raw!r}) -> {got!r}, expected {expected!r}"


def test_risk_label_filter_case_insensitive_substring() -> None:
    """``is_risk_labelled`` matches the configured needle anywhere in any
    label, case-insensitively. Empty filter is a pass-through."""
    saved = os.environ.get("RISK_LABEL_FILTER")
    try:
        os.environ["RISK_LABEL_FILTER"] = "risk"
        cases = [
            ({"labels": ["risk"]},                          True),
            ({"labels": ["RISK"]},                          True),
            ({"labels": ["Risk"]},                          True),
            ({"labels": ["risk-register"]},                 True),
            ({"labels": ["RISK#WCC100"]},                   True),
            ({"labels": ["some-label-with-risk-in-it"]},    True),
            ({"labels": ["thermal", "Risk#ESC042"]},        True),  # any one matches
            ({"labels": ["thermal", "optics"]},             False),
            ({"labels": []},                                False),
            ({},                                            False),  # missing 'labels'
        ]
        for item, expected in cases:
            got = build.is_risk_labelled(item)
            assert got == expected, (
                f"is_risk_labelled({item}) -> {got}, expected {expected}"
            )

        # Empty filter → pass-through.
        os.environ["RISK_LABEL_FILTER"] = ""
        assert build.is_risk_labelled({"labels": ["thermal"]})
        assert build.is_risk_labelled({"labels": []})

        # Different needle.
        os.environ["RISK_LABEL_FILTER"] = "hazard"
        assert build.is_risk_labelled({"labels": ["safety-hazard"]})
        assert not build.is_risk_labelled({"labels": ["risk"]})
    finally:
        if saved is None:
            os.environ.pop("RISK_LABEL_FILTER", None)
        else:
            os.environ["RISK_LABEL_FILTER"] = saved


if __name__ == "__main__":
    import tempfile
    test_risk_label_filter_case_insensitive_substring()
    test_graphql_401_exits_with_actionable_message()
    test_render_markdown_sanitization()
    test_parse_sections()
    test_parse_sections_bare_body_fallback()
    test_clean_title()
    with tempfile.TemporaryDirectory() as d:
        test_every_snapshot_field_change_is_retained(Path(d))
    with tempfile.TemporaryDirectory() as d:
        test_multiple_items_changing_in_one_run(Path(d))
    test_build_dashboard()
    print("OK")
