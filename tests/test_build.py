"""End-to-end test for build.py using mocked GitLab responses.

Runs the full main() pipeline against a fabricated GraphQL payload, asserts
on the matrix counts, history-append semantics, vanished->closed handling,
and unscored bucketing. Leaves behind public/index.html as a working
example of the dashboard.

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
    return {
        "id": f"gid://gitlab/WorkItem/{iid}",
        "iid": str(iid),
        "title": title,
        "state": state,
        "webUrl": f"https://gitlab.example.com/stp/sub/-/work_items/{iid}",
        "createdAt": now,
        "updatedAt": now,
        "closedAt": None,
        "widgets": [
            {"type": "LABELS", "labels": {"nodes": [{"title": ln} for ln in labels]}},
            {"type": "CUSTOM_FIELDS", "customFieldValues": cf_values},
        ],
    }


SAMPLE_ITEMS = [
    _item(1, "Coating delamination under thermal cycling", "5", "4", "High", ["Technical"], ["optics", "thermal"]),
    _item(2, "Detector ASIC vendor schedule slip", "4", "5", "High", ["Schedule", "Cost"], ["electrical"]),
    _item(3, "Cryocooler procurement long lead", "5", "3", "High", ["Cost", "Schedule"], ["thermal", "mechanical"]),
    _item(4, "Pointing jitter exceeds budget", "4", "3", "Medium", ["Technical"], ["mechanical", "optics"]),
    _item(5, "FPGA firmware tool obsolescence", "3", "3", "Medium", ["Technical"], ["electrical", "software"]),
    _item(6, "Ground software test bed availability", "2", "4", "Medium", ["Schedule"], ["software"]),
    _item(7, "Documentation backlog", "1", "2", "Low", ["Schedule"], ["software"]),
    _item(8, "Storage capacity margin", "2", "2", "Low", ["Technical"], ["software"]),
    _item(9, "Vibration test fixture rework", "3", "2", "Medium", ["Cost"], ["mechanical"]),
    _item(10, "Optical contamination control", "4", "4", "High", ["Technical"], ["optics"]),
    _item(11, "Unscored placeholder risk", None, None, "Low", [], ["software"]),
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

    # #1 escalated 10 days ago: was C4xL3, now C5xL4
    rows.append(row(60, 1, "Coating delamination under thermal cycling", 4, 3,
                    risk_types=["Technical"], subsystems=["optics", "thermal"]))
    rows.append(row(10, 1, "Coating delamination under thermal cycling", 5, 4,
                    risk_types=["Technical"], subsystems=["optics", "thermal"]))
    # #4 de-escalated 5 days ago: was C5xL3, now C4xL3
    rows.append(row(45, 4, "Pointing jitter exceeds budget", 5, 3, priority="Medium",
                    risk_types=["Technical"], subsystems=["mechanical", "optics"]))
    rows.append(row(5, 4, "Pointing jitter exceeds budget", 4, 3, priority="Medium",
                    risk_types=["Technical"], subsystems=["mechanical", "optics"]))
    # #6 is new 3 days ago
    rows.append(row(3, 6, "Ground software test bed availability", 2, 4, priority="Medium",
                    risk_types=["Schedule"], subsystems=["software"]))
    # #99 closed last week (still in history, won't be in current items -> synthetic closure
    # was already recorded earlier)
    rows.append(row(20, 99, "Retired vendor risk", 3, 3, priority="Low",
                    risk_types=["Cost"], subsystems=["electrical"]))
    rows.append(row(7, 99, "Retired vendor risk", 3, 3, state="closed", priority="Low",
                    risk_types=["Cost"], subsystems=["electrical"]))
    # A second long history for trend variety
    for d, c, l in [(80, 2, 2), (70, 3, 3), (40, 4, 4), (20, 4, 5)]:
        rows.append(row(d, 2, "Detector ASIC vendor schedule slip", c, l,
                        priority="High", risk_types=["Schedule", "Cost"], subsystems=["electrical"]))

    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def _run_main_with_items(items: list[dict]) -> None:
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
    assert "Coating delamination" in html
    # The unscored item must not land in any matrix cell, but may appear in
    # the "new" movement card. Check that #11 is absent from cells_json.
    cells_json = json.loads(html.split("const cells = ", 1)[1].split(";", 1)[0])
    cell_iids = {issue["iid"] for cell in cells_json.values() for issue in cell}
    assert "11" not in cell_iids, "unscored item leaked into a matrix cell"
    # Subsystem bars
    for sub in build.SUBSYSTEMS:
        assert f">{sub}<" in html, f"subsystem {sub} missing from rendered HTML"

    # History: only changed items append new rows. Backdated trail had
    # #1 at C5xL4 already (same as current), #2 at C4xL5 (same as current),
    # #4 at C4xL3 (same as current), #6 at C2xL4 (same as current).
    # Items #3, #5, #7, #8, #9, #10, #11 have no prior history -> new rows.
    rows_after = sum(1 for _ in history_path.open())
    expected_new = 7
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
    print(f"\nWrote example dashboard to: {out}")
    print(f"History rows: {sum(1 for _ in history_path.open())}")


if __name__ == "__main__":
    test_build_dashboard()
    print("OK")
