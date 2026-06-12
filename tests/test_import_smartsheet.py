"""Tests for scripts/import_smartsheet.py.

Focus areas (the user-facing guarantees the importer makes):
- **Non-destructive**: existing canonical section bodies are NEVER
  modified. Spreadsheet content that differs is appended as a clearly-
  marked proposal block; the user reviews and accepts manually.
- **Preserves existing and non-canonical content**: intro prose,
  `## See also`-style headings, and untouched canonical sections all
  survive a run unchanged.
- **Idempotent**: running the importer twice with the same spreadsheet
  data leaves the description in a stable state — proposal blocks are
  refreshed in place via HTML markers, not duplicated.

Run::

    python tests/test_import_smartsheet.py
    # or
    python -m pytest tests/test_import_smartsheet.py -v

The tests target the pure-Python helpers (merge_sections,
parse_issue_url, canonical_key, extract_sections, find_link). The
network and Excel I/O paths are not exercised here — they're thin
wrappers and the user verifies them via ``--dry-run`` before any real
run.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import import_smartsheet as imp  # noqa: E402


# ---------------------------------------------------------------------------
# Non-destructive guarantees
# ---------------------------------------------------------------------------

def test_match_is_noop() -> None:
    """Existing body matches spreadsheet → no proposal block emitted."""
    existing = "## Risk Description\n\nSame content.\n"
    out = imp.merge_sections(
        existing, {"risk_description": "Same content."}, today="2026-06-04"
    )
    assert "spreadsheet-import:proposal" not in out, \
        f"unexpected proposal block:\n{out}"
    assert out.strip() == existing.strip(), \
        f"existing description was modified:\n{out}"


def test_match_tolerates_whitespace_differences() -> None:
    """Trailing whitespace and blank-line runs are normalized for comparison."""
    existing = "## Notes\n\nLine one.\n   \n\nLine two.\n"
    spreadsheet = "Line one.\n\nLine two."
    out = imp.merge_sections(
        existing, {"notes": spreadsheet}, today="2026-06-04"
    )
    assert "spreadsheet-import:proposal" not in out, \
        f"whitespace-only difference triggered a proposal:\n{out}"


def test_differ_appends_proposal_existing_preserved() -> None:
    """Different body → existing untouched; proposal appended after it."""
    existing = "## Risk Description\n\nOld assessment.\n"
    out = imp.merge_sections(
        existing, {"risk_description": "New assessment."}, today="2026-06-04"
    )
    assert "## Risk Description\n\nOld assessment." in out, \
        "existing canonical section was modified"
    assert "spreadsheet-import:proposal:risk_description" in out, \
        "proposal marker missing"
    assert "New assessment." in out, "proposed content missing"
    assert out.index("Old assessment.") < out.index("New assessment."), \
        "proposal not appended after existing section"


def test_bare_body_matches_spreadsheet_risk_description() -> None:
    """A description with no canonical heading but whose entire body
    matches the spreadsheet's Risk Description should NOT trigger a
    proposal block — the bare prose is treated as the existing
    canonical content (the dashboard surfaces it via the same leading-
    prose fallback). Avoids polluting the issue with a duplicate."""
    existing = "If fixture does not fit on the air cart, then we cannot move within the facility."
    out = imp.merge_sections(
        existing,
        {"risk_description": existing},
        today="2026-06-04",
        source_id="LPY016",
    )
    assert "spreadsheet-import:proposal:risk_description" not in out, (
        f"bare matching body triggered a duplicate proposal block:\n{out}"
    )
    assert out.strip() == existing.strip(), \
        f"bare body was modified:\n{out}"


def test_bare_body_differs_still_proposes() -> None:
    """Bare body that DOESN'T match the spreadsheet still gets a
    proposal block — the bare prose is the existing content, and the
    diff in the proposal shows what changed."""
    existing = "Old free-form text."
    out = imp.merge_sections(
        existing,
        {"risk_description": "New canonical text from the spreadsheet."},
        today="2026-06-04",
        source_id="LPY016",
    )
    assert "spreadsheet-import:proposal:risk_description" in out
    assert "New canonical text from the spreadsheet." in out
    # The diff block should be present (since "existing_body" is now the
    # bare prose, not "").
    assert "```diff" in out, \
        "expected a diff block comparing bare body to spreadsheet text"
    assert "-Old free-form text." in out


def test_bare_body_only_blocks_risk_description_fallback() -> None:
    """The bare-body fallback covers risk_description only — Notes and
    Mitigation Plan still require explicit headings to match."""
    existing = "Free-form risk text."
    out = imp.merge_sections(
        existing,
        {"notes": "Free-form risk text."},  # same string, but for Notes
        today="2026-06-04",
        source_id="LPY016",
    )
    # Notes still differs (no canonical Notes section in existing) → proposal added.
    assert "spreadsheet-import:proposal:notes" in out


def test_bare_body_matches_rd_other_sections_still_proposed() -> None:
    """Even when the bare body matches the spreadsheet's Risk
    Description (so no risk_description proposal is needed), any
    *other* sections present only in the spreadsheet still produce
    proposal blocks. The bare-body fallback only short-circuits
    risk_description, never the other canonical sections."""
    existing = "If fixture does not fit on the air cart, then we cannot move within the facility."
    out = imp.merge_sections(
        existing,
        {
            "risk_description": existing,                          # match → no proposal
            "notes": "Verify cart load every shift.",              # missing → proposal
            "mitigation_plan": "Order an oversize-fixture cart.",  # missing → proposal
        },
        today="2026-06-04",
        source_id="LPY016",
    )
    assert "spreadsheet-import:proposal:risk_description" not in out, \
        "matching risk_description should not trigger a proposal"
    assert "spreadsheet-import:proposal:notes" in out, \
        "notes proposal missing — bare-body fallback swallowed it"
    assert "Verify cart load every shift." in out
    assert "spreadsheet-import:proposal:mitigation_plan" in out, \
        "mitigation_plan proposal missing — bare-body fallback swallowed it"
    assert "Order an oversize-fixture cart." in out
    # And the original bare body is preserved verbatim at the top.
    assert out.startswith(existing)


def test_missing_section_appends_proposal_not_canonical_heading() -> None:
    """Issue has no matching canonical heading → proposal block, NOT a
    bare canonical section. The user must still review before adopting."""
    existing = "Some intro paragraph, no headings.\n"
    out = imp.merge_sections(
        existing, {"notes": "Spreadsheet notes."}, today="2026-06-04"
    )
    assert "Some intro paragraph, no headings." in out, \
        "intro text was lost"
    assert "spreadsheet-import:proposal:notes" in out, \
        "missing-section path did not produce a proposal block"
    # Check for actual H2 heading lines, not substring match — "### Notes"
    # in the proposal block contains "## Notes" as a substring.
    h2_notes_lines = [
        line for line in out.splitlines() if line.strip() == "## Notes"
    ]
    assert h2_notes_lines == [], \
        "missing-section path silently added a canonical H2 section"


def test_existing_rd_no_notes_spreadsheet_notes_get_appended() -> None:
    """Issue has an explicit ## Risk Description heading but NO ## Notes
    section at all. Spreadsheet supplies a Notes value. The importer
    must append a Notes proposal block — and leave the existing Risk
    Description heading & body untouched."""
    existing = "## Risk Description\n\nSome existing risk text.\n"
    out = imp.merge_sections(
        existing,
        {"notes": "These notes from the spreadsheet should appear."},
        today="2026-06-04",
        source_id="LPY042",
    )
    # Existing canonical section is preserved verbatim.
    assert "## Risk Description\n\nSome existing risk text." in out, \
        "existing Risk Description section was modified"
    # Notes proposal block added.
    assert "spreadsheet-import:proposal:notes:lpy042" in out, \
        "notes proposal block missing for issue with no existing Notes section"
    assert "These notes from the spreadsheet should appear." in out
    # Nothing about risk_description in the diff stream (it wasn't in the
    # spreadsheet for this row).
    assert "spreadsheet-import:proposal:risk_description" not in out


def test_empty_existing_description_only_appends_proposals() -> None:
    """Empty starting description → every spreadsheet section becomes a
    proposal block. Nothing is written as canonical content directly,
    so the dashboard parser will not surface it until the user accepts."""
    out = imp.merge_sections(
        "",
        {"risk_description": "RD body.", "notes": "Notes body."},
        today="2026-06-04",
    )
    assert "spreadsheet-import:proposal:risk_description" in out
    assert "spreadsheet-import:proposal:notes" in out
    # Inspect the actual heading lines (not substrings) — none of them
    # should be H2 canonical sections. Proposal headings are H3.
    h2_headings = [
        line for line in out.splitlines()
        if line.startswith("## ") and not line.startswith("### ")
    ]
    canonical_h2 = [
        h for h in h2_headings
        if imp.canonical_key(h.removeprefix("## ").strip()) is not None
    ]
    assert canonical_h2 == [], (
        f"expected no canonical H2 sections in append-only output, got: "
        f"{canonical_h2!r}"
    )


# ---------------------------------------------------------------------------
# Preserving non-canonical content
# ---------------------------------------------------------------------------

def test_non_canonical_headings_preserved() -> None:
    """Headings the dashboard doesn't recognize survive unchanged."""
    existing = (
        "Top intro.\n\n"
        "## Risk Description\n\nOriginal body.\n\n"
        "## See also\n\n"
        "- Link to doc A\n"
        "- Link to doc B\n\n"
        "## Mitigation Plan\n\nOriginal plan.\n"
    )
    out = imp.merge_sections(
        existing,
        {"risk_description": "Updated description."},
        today="2026-06-04",
    )
    assert "Top intro." in out, "intro lost"
    assert "## See also\n\n- Link to doc A\n- Link to doc B" in out, \
        "non-canonical heading body lost"
    assert "## Risk Description\n\nOriginal body." in out, \
        "canonical section we're updating was modified"
    assert "## Mitigation Plan\n\nOriginal plan." in out, \
        "untouched canonical section was modified"
    assert "spreadsheet-import:proposal:risk_description" in out, \
        "no proposal for updated section"
    assert "spreadsheet-import:proposal:mitigation_plan" not in out, \
        "untouched section got a spurious proposal block"


def test_legacy_heading_preserved_and_matched() -> None:
    """Legacy ``## Action Plan / Notes`` heading maps to the ``notes``
    canonical key for comparison, so matching content stays a no-op AND
    the legacy heading text is preserved (no overwrite of any kind)."""
    existing = "## Action Plan / Notes\n\nShared content.\n"
    out = imp.merge_sections(
        existing, {"notes": "Shared content."}, today="2026-06-04"
    )
    assert "spreadsheet-import:proposal" not in out, \
        "match path incorrectly emitted a proposal block"
    assert "## Action Plan / Notes" in out, \
        "legacy heading text was modified"


def test_legacy_heading_emits_proposal_when_body_differs() -> None:
    """Legacy heading + body differs → proposal block appended;
    legacy heading is still NOT renamed."""
    existing = "## Action Plan / Notes\n\nOld notes.\n"
    out = imp.merge_sections(
        existing, {"notes": "Spreadsheet notes."}, today="2026-06-04"
    )
    assert "## Action Plan / Notes\n\nOld notes." in out, \
        "legacy section body was modified"
    assert "spreadsheet-import:proposal:notes" in out
    assert "Spreadsheet notes." in out


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_idempotent_same_data_byte_for_byte() -> None:
    """Same spreadsheet input twice → identical output."""
    existing = "## Risk Description\n\nOriginal body.\n"
    once = imp.merge_sections(
        existing, {"risk_description": "Updated."}, today="2026-06-04"
    )
    twice = imp.merge_sections(
        once, {"risk_description": "Updated."}, today="2026-06-04"
    )
    assert once == twice, (
        f"NOT idempotent:\n--once--\n{once!r}\n--twice--\n{twice!r}"
    )


def test_proposal_refreshes_when_spreadsheet_changes() -> None:
    """Spreadsheet text changes between runs → previous block stripped,
    new block written in its place (NOT duplicated). Requires a stable
    source_id — in production, that's the row's Unique Risk ID column."""
    existing = "## Risk Description\n\nOriginal body.\n"
    first = imp.merge_sections(
        existing, {"risk_description": "First proposal."},
        today="2026-06-04", source_id="WCC123",
    )
    second = imp.merge_sections(
        first, {"risk_description": "Second proposal."},
        today="2026-06-04", source_id="WCC123",
    )
    open_markers = second.count(
        "<!-- spreadsheet-import:proposal:risk_description:wcc123 -->"
    )
    close_markers = second.count(
        "<!-- /spreadsheet-import:proposal:risk_description:wcc123 -->"
    )
    assert open_markers == 1, f"open markers: {open_markers}, expected 1"
    assert close_markers == 1, f"close markers: {close_markers}, expected 1"
    assert "First proposal." not in second, \
        "stale proposal text from prior run was not stripped"
    assert "Second proposal." in second


def test_acceptance_workflow_clears_proposal_on_next_run() -> None:
    """If the user manually accepts a proposal — i.e., updates the
    canonical section above to match the spreadsheet content and deletes
    the proposal block — the next run should leave a clean description."""
    accepted = "## Risk Description\n\nAccepted content.\n"
    out = imp.merge_sections(
        accepted, {"risk_description": "Accepted content."}, today="2026-06-04"
    )
    assert "spreadsheet-import:proposal" not in out, \
        "user-accepted change triggered a new proposal block"
    assert out.strip() == accepted.strip()


def test_idempotency_across_multiple_sections() -> None:
    """All three canonical sections; mix of match/differ/missing must
    re-run cleanly. Uses an explicit source_id so the second call
    refreshes the same proposal blocks instead of appending new ones."""
    existing = (
        "## Risk Description\n\nDesc body unchanged.\n\n"
        "## Notes\n\nOld notes.\n"
    )
    sections = {
        "risk_description": "Desc body unchanged.",     # match  → no proposal
        "notes": "New notes.",                          # differ → proposal
        "mitigation_plan": "Plan body.",                # missing → proposal
    }
    once = imp.merge_sections(existing, sections, today="2026-06-04",
                              source_id="WCC123")
    twice = imp.merge_sections(once, sections, today="2026-06-04",
                               source_id="WCC123")
    assert once == twice, "not idempotent across mixed match/differ/missing"
    # Sanity: exactly the two expected proposals, no more.
    assert once.count("<!-- spreadsheet-import:proposal:notes:wcc123 -->") == 1
    assert once.count("<!-- spreadsheet-import:proposal:mitigation_plan:wcc123 -->") == 1
    assert "<!-- spreadsheet-import:proposal:risk_description:wcc123 -->" not in once


# ---------------------------------------------------------------------------
# Lower-level helpers
# ---------------------------------------------------------------------------

def test_multi_row_same_issue_appends_distinct_blocks() -> None:
    """Two spreadsheet rows targeting the same issue with different
    source_ids each produce their own proposal block; neither is
    overwritten by the other."""
    existing = "## Risk Description\n\nIssue body.\n"
    first = imp.merge_sections(
        existing, {"risk_description": "Row A content."},
        today="2026-06-04", source_id="WCC100",
    )
    both = imp.merge_sections(
        first, {"risk_description": "Row B content."},
        today="2026-06-04", source_id="ESC042",
    )
    assert "Row A content." in both, "first row's block was overwritten"
    assert "Row B content." in both, "second row's block missing"
    assert both.count(
        "<!-- spreadsheet-import:proposal:risk_description:wcc100 -->"
    ) == 1
    assert both.count(
        "<!-- spreadsheet-import:proposal:risk_description:esc042 -->"
    ) == 1
    # Idempotent: re-running the WHOLE spreadsheet in the same row
    # order produces a byte-identical description. (Re-running a single
    # row in isolation can move its block to the end of the list — only
    # the full-pass ordering is guaranteed.)
    second_pass = imp.merge_sections(
        both, {"risk_description": "Row A content."},
        today="2026-06-04", source_id="WCC100",
    )
    second_pass = imp.merge_sections(
        second_pass, {"risk_description": "Row B content."},
        today="2026-06-04", source_id="ESC042",
    )
    assert second_pass == both, "full re-run drifted the description"


def test_attribution_includes_unique_id_and_modification_date() -> None:
    """The italic attribution footer carries optional fields when given."""
    out = imp.merge_sections(
        "", {"risk_description": "Body."},
        today="2026-06-04",
        source_label="Risk Register.xlsx",
        source_id="WCC100",
        unique_id="WCC100",
        modification_date="2026-05-15",
    )
    assert (
        "*(imported from Risk Register.xlsx, "
        "Unique Risk ID: WCC100, "
        "Modification Date: 2026-05-15, "
        "on 2026-06-04)*"
    ) in out


def test_attribution_omits_missing_optional_fields() -> None:
    """Attribution gracefully drops Unique Risk ID / Modification Date
    bits when they're not provided."""
    out = imp.merge_sections(
        "", {"risk_description": "Body."},
        today="2026-06-04",
        source_label="X.xlsx",
        source_id="abc",
    )
    assert "*(imported from X.xlsx, on 2026-06-04)*" in out
    assert "Unique Risk ID" not in out
    assert "Modification Date" not in out


def test_legacy_blocks_stripped_on_upgrade() -> None:
    """Issues that still contain old-format (no-sid) proposal blocks
    from an earlier version of the script get migrated cleanly: the
    legacy block disappears and a new sid-tagged block takes its place."""
    legacy_existing = (
        "## Risk Description\n\nReal content.\n\n"
        "<!-- spreadsheet-import:proposal:risk_description -->\n"
        "### Risk Description\n\nOld proposal content.\n"
        "<!-- /spreadsheet-import:proposal:risk_description -->\n"
    )
    out = imp.merge_sections(
        legacy_existing, {"risk_description": "Fresh content."},
        today="2026-06-04", source_id="WCC123",
    )
    assert "Old proposal content." not in out, \
        "legacy proposal block was not stripped"
    assert "Fresh content." in out
    # New marker present.
    assert "spreadsheet-import:proposal:risk_description:wcc123" in out


def test_find_unique_id_and_modification_date() -> None:
    """Header lookup is case-insensitive and tolerates extra whitespace."""
    row = {
        "GitLab Link": "https://...",
        "Unique Risk ID": "WCC100",
        "Modification Date": "2026-05-15",
        "Risk Description": "Body.",
    }
    assert imp.find_unique_id(row) == "WCC100"
    assert imp.find_modification_date(row) == "2026-05-15"

    row2 = {"  risk id  ": "X-9", "modified": "2026-01-02"}
    assert imp.find_unique_id(row2) == "X-9"
    assert imp.find_modification_date(row2) == "2026-01-02"

    # Datetime cell → YYYY-MM-DD string.
    from datetime import datetime
    row3 = {"Modification Date": datetime(2026, 7, 4, 12, 30)}
    assert imp.find_modification_date(row3) == "2026-07-04"

    # No relevant columns → None.
    assert imp.find_unique_id({"Other": "x"}) is None
    assert imp.find_modification_date({"Other": "x"}) is None


def test_strip_proposals_removes_complete_block() -> None:
    text = (
        "## Risk Description\n\nBody.\n\n"
        "<!-- spreadsheet-import:proposal:risk_description -->\n"
        "### Proposed update\nContent here.\n"
        "<!-- /spreadsheet-import:proposal:risk_description -->\n"
    )
    out = imp._strip_proposals(text)
    assert "spreadsheet-import:proposal" not in out
    assert "## Risk Description\n\nBody." in out


def test_strip_proposals_handles_multiple_blocks() -> None:
    text = (
        "<!-- spreadsheet-import:proposal:risk_description -->\nA\n"
        "<!-- /spreadsheet-import:proposal:risk_description -->\n"
        "Middle text.\n"
        "<!-- spreadsheet-import:proposal:notes -->\nB\n"
        "<!-- /spreadsheet-import:proposal:notes -->\n"
    )
    out = imp._strip_proposals(text)
    assert "spreadsheet-import:proposal" not in out
    assert "Middle text." in out


def test_canonical_key_synonyms() -> None:
    cases = [
        ("Risk Description", "risk_description"),
        ("description", "risk_description"),
        ("Summary", "risk_description"),
        ("Notes", "notes"),
        ("Action Plan / Notes", "notes"),
        ("Action Plan/Notes", "notes"),
        ("Action Plan", "notes"),
        ("Mitigation Plan", "mitigation_plan"),
        ("Risk Mitigation Planning", "mitigation_plan"),
        ("Mitigation", "mitigation_plan"),
        ("Some Random Heading", None),
        ("", None),
    ]
    for heading, expected in cases:
        got = imp.canonical_key(heading)
        assert got == expected, (
            f"canonical_key({heading!r}) -> {got!r}, expected {expected!r}"
        )


def test_parse_issue_url() -> None:
    cases = [
        (
            "https://gitlab.example.com/stp/risks/-/issues/123",
            {"server": "https://gitlab.example.com",
             "project_path": "stp/risks", "iid": 123},
        ),
        (
            "https://gitlab.sc.ascendingnode.tech:8443/stp/sub/proj/-/work_items/42",
            {"server": "https://gitlab.sc.ascendingnode.tech:8443",
             "project_path": "stp/sub/proj", "iid": 42},
        ),
        ("not a url", None),
        ("https://example.com/no/issue/segment", None),
    ]
    for url, expected in cases:
        got = imp.parse_issue_url(url)
        assert got == expected, f"parse_issue_url({url!r}) -> {got!r}"


def test_extract_sections_from_row() -> None:
    row = {
        "Risk Description": "Body of risk.",
        "Action Plan/ Notes": "Notes body.",
        "Risk Mitigation Planning": "Plan body.",
        "Some Other Column": "Ignored.",
    }
    out = imp.extract_sections(row)
    assert out == {
        "risk_description": "Body of risk.",
        "notes": "Notes body.",
        "mitigation_plan": "Plan body.",
    }, f"unexpected: {out}"


def test_extract_sections_skips_empty_cells() -> None:
    row = {
        "Risk Description": "  ",       # whitespace only
        "Action Plan/ Notes": None,
        "Risk Mitigation Planning": "Plan body.",
    }
    out = imp.extract_sections(row)
    assert out == {"mitigation_plan": "Plan body."}, f"unexpected: {out}"


def test_find_link_picks_gitlab_link_column() -> None:
    assert imp.find_link({
        "GitLab Link": "https://example.com/x/y/-/issues/1",
        "Other": "no",
    }) == "https://example.com/x/y/-/issues/1"
    # Case-insensitive header match.
    assert imp.find_link({"gitlab link ": "url-2", "Random": "x"}) == "url-2"
    # No matching column.
    assert imp.find_link({"Foo": "bar"}) is None


# ---------------------------------------------------------------------------
# main() per-row diagnostics
# ---------------------------------------------------------------------------

def test_main_tags_failures_with_unique_risk_id(tmp_path=None, capsys=None) -> None:
    """When a spreadsheet row fails (no link, unparseable URL, move-follow
    403, PUT 403), the final '=== Rows that did not update ===' summary
    must list the row's Unique Risk ID so the user knows which
    spreadsheet row to fix — not just the GitLab iid."""
    import io
    import sys as _sys
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    import requests

    rows = [
        # LPY001: valid, will succeed with a proposal block.
        {"GitLab Link": "https://gl.example.com/p/-/issues/1",
         "Unique Risk ID": "LPY001",
         "Risk Description": "Body 1."},
        # LPY008: spreadsheet GitLab Link points at an issue that is moved,
        # and following the move 403s. This is the user's reported bug.
        {"GitLab Link": "https://gl.example.com/p/-/issues/2",
         "Unique Risk ID": "LPY008",
         "Risk Description": "Body 8.",
         "Action Plan/ Notes": "Important notes that aren't showing up."},
        # LPY099: no GitLab Link at all in the row.
        {"Unique Risk ID": "LPY099",
         "Risk Description": "Body 99."},
        # No Unique Risk ID: falls back to "row N" label.
        {"GitLab Link": "not a real url",
         "Risk Description": "Body unparseable."},
    ]

    class _FakeResp:
        def __init__(self, status, body):
            self.status_code = status
            self._body = body
        def json(self): return self._body
        def raise_for_status(self):
            if self.status_code >= 400:
                err = requests.HTTPError(f"{self.status_code} error")
                err.response = self
                raise err

    def fake_get(url, timeout=30):
        # GET on the project-scoped issue endpoint.
        if "/issues/1" in url and "projects" in url:
            return _FakeResp(200, {
                "iid": 1, "project_id": 100,
                "web_url": "https://gl.example.com/p/-/issues/1",
                "description": "Old desc 1.",
            })
        if "/issues/2" in url and "projects" in url:
            # Issue #2 was moved.
            return _FakeResp(200, {
                "iid": 2, "project_id": 100,
                "web_url": "https://gl.example.com/p/-/issues/2",
                "description": "Old desc 2.",
                "moved_to_id": 9999,
            })
        # GET on the global-issues endpoint — destination project blocks us.
        if url.endswith("/issues/9999"):
            return _FakeResp(403, {})
        return _FakeResp(404, {})

    def fake_put(url, json=None, timeout=30):
        return _FakeResp(200, {})

    with tempfile.TemporaryDirectory() as d:
        xlsx_path = Path(d) / "Risk Register - Task Order 5.xlsx"
        xlsx_path.write_bytes(b"")  # contents irrelevant; we mock read_xlsx
        backup_path = Path(d) / "backup.jsonl"
        argv = ["import_smartsheet.py", "--xlsx", str(xlsx_path),
                "--token", "fake-token", "--dry-run",
                "--backup", str(backup_path)]
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with patch.object(imp, "read_xlsx", return_value=rows), \
             patch.object(imp, "requests") as mock_requests, \
             patch.object(_sys, "argv", argv), \
             patch.object(_sys, "stdout", buf_out), \
             patch.object(_sys, "stderr", buf_err):
            sess = mock_requests.Session.return_value
            sess.headers = {}
            sess.get.side_effect = fake_get
            sess.put.side_effect = fake_put
            mock_requests.HTTPError = requests.HTTPError
            rc = imp.main()

    out = buf_out.getvalue() + "\n" + buf_err.getvalue()

    # Per-row tagging is present in error/info lines.
    assert "LPY008" in out, "LPY008 row tag should appear in output"
    assert "LPY099" in out, "LPY099 (no link) row tag should appear"

    # The final failures summary lists each bad row with its Unique Risk
    # ID + reason, so the user can scan it.
    assert "=== Rows that did not update ===" in out, \
        "missing final failure summary"
    assert "LPY008" in out.split("=== Rows that did not update ===")[1], \
        "LPY008 (move-follow 403) should appear in the failure summary"
    assert "LPY099" in out.split("=== Rows that did not update ===")[1], \
        "LPY099 (no GitLab Link) should appear in the failure summary"
    # Exit non-zero because there were errors.
    assert rc != 0, "main() should return non-zero when errors > 0"


def test_main_print_markdown_emits_clean_pasteable_description() -> None:
    """--print-markdown prints the full proposed description verbatim
    (pasteable into GitLab), never PUTs, and delimits issues with an
    HTML comment (invisible in GitLab's rendered preview)."""
    import io
    import sys as _sys
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    import requests

    rows = [
        {"GitLab Link": "https://gl.example.com/p/-/issues/2",
         "Unique Risk ID": "LPY016",
         "Risk Description": "Bare risk statement.",
         "Action Plan/ Notes": "Verify cart load every shift."},
    ]

    class _FakeResp:
        def __init__(self, status, body):
            self.status_code = status
            self._body = body
        def json(self): return self._body
        def raise_for_status(self):
            if self.status_code >= 400:
                err = requests.HTTPError(f"{self.status_code} error")
                err.response = self
                raise err

    def fake_get(url, timeout=30):
        if "/issues/2" in url and "projects" in url:
            return _FakeResp(200, {
                "iid": 2, "project_id": 100,
                "web_url": "https://gl.example.com/p/-/issues/2",
                "description": "Bare risk statement.",
            })
        return _FakeResp(404, {})

    def fake_put(url, json=None, timeout=30):
        raise AssertionError("--print-markdown must never PUT")

    with tempfile.TemporaryDirectory() as d:
        xlsx_path = Path(d) / "Risk Register.xlsx"
        xlsx_path.write_bytes(b"")
        backup_path = Path(d) / "backup.jsonl"
        # Note: deliberately NOT passing --dry-run; --print-markdown must
        # imply it on its own.
        argv = ["import_smartsheet.py", "--xlsx", str(xlsx_path),
                "--token", "fake-token", "--print-markdown",
                "--backup", str(backup_path)]
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with patch.object(imp, "read_xlsx", return_value=rows), \
             patch.object(imp, "requests") as mock_requests, \
             patch.object(_sys, "argv", argv), \
             patch.object(_sys, "stdout", buf_out), \
             patch.object(_sys, "stderr", buf_err):
            sess = mock_requests.Session.return_value
            sess.headers = {}
            sess.get.side_effect = fake_get
            sess.put.side_effect = fake_put
            mock_requests.HTTPError = requests.HTTPError
            rc = imp.main()
            put_calls = sess.put.call_count

    out = buf_out.getvalue()

    # Never wrote.
    assert put_calls == 0, "--print-markdown issued a PUT"
    assert rc == 0
    # The clean proposal markdown is present, not a unified diff.
    assert "### Notes" in out
    assert "Verify cart load every shift." in out
    assert "--- current" not in out and "+++ new" not in out, \
        "print-markdown should not emit a unified diff"
    assert "@@" not in out, "print-markdown should not emit diff hunk headers"
    # Issue delimiter is an HTML comment (invisible in GitLab preview).
    assert "<!-- ===== LPY016 →" in out, \
        "missing HTML-comment issue delimiter"


# ---------------------------------------------------------------------------
# Runner (so `python tests/test_import_smartsheet.py` works alongside pytest)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = sorted(
        ((name, fn) for name, fn in globals().items()
         if name.startswith("test_") and callable(fn)),
        key=lambda t: t[0],
    )
    print(f"Running {len(tests)} tests from {__file__}")
    failures: list[tuple[str, str]] = []
    for name, fn in tests:
        try:
            fn()
            print(f"  ok  {name}")
        except AssertionError as e:
            print(f"  FAIL {name}: {e}")
            failures.append((name, str(e)))
        except Exception as e:
            print(f"  ERR  {name}: {type(e).__name__}: {e}")
            failures.append((name, f"{type(e).__name__}: {e}"))
    if failures:
        print(f"\n{len(failures)} failed:")
        for n, msg in failures:
            print(f"  - {n}: {msg}")
        sys.exit(1)
    print(f"\n{len(tests)} passed")
