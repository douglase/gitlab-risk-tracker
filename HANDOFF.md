# Handoff — gitlab-risk-tracker session

## Current state

- **Branch**: `claude/stoic-feynman-ZbVZm`. Run `git log --oneline -1` for the
  current head; was `79dde5b` when this section was last refreshed.
- **PRs**:
  - [#2](https://github.com/douglase/gitlab-risk-tracker/pull/2) — original PR
    against `main`. All three Copilot review threads addressed and resolved.
    May be merged or superseded by #13.
  - [#13](https://github.com/douglase/gitlab-risk-tracker/pull/13) — current PR
    for the same branch against a newer `main`. Picked up four Copilot Autofix
    commits and one Copilot-SWE-Agent rename commit; idempotency bug they
    introduced was already fixed in `8924ed5`.
- **Deployed**: live on the team's GitLab Enterprise instance at
  `https://gitlab.sc.ascendingnode.tech:8443/stp/gitlab-risk-tracker` with a
  nightly pipeline schedule. Pulls work-items from the `stp` group recursively;
  publishes a Pages dashboard for members; persists `data/history.ndjson` on a
  separate `risk-history` branch (not `main`).
- **GitHub Actions** (development side): three workflows under
  `.github/workflows/` — `test.yml` (runs both `tests/test_build.py` and
  `tests/test_import_smartsheet.py`), `scancode.yml`, `docs.yml`. Dependabot
  config under `.github/dependabot.yml` watches both `github-actions` and
  `pip`.
- **Docs**: Sphinx site builds from `docs/` and publishes to GitHub Pages on
  push to `main`. A live preview of the example dashboard is embedded in
  `docs/preview.rst` via iframe.
- **Smartsheets → GitLab importer**: implemented at
  `scripts/import_smartsheet.py`. Standalone CLI; run with `--dry-run` first.
  Append-only; never overwrites existing canonical section content. See the
  new "Smartsheets importer" section below.

## What was built this session

Roughly in delivery order:

### Pipeline & deployment
- `.gitlab-ci.yml` written from scratch with `pages` job, `risk-history` branch
  persistence, `[skip ci]` push-back, `PUSH_TOKEN` guard, push-failure
  diagnostics, and `CI_SERVER_PORT` in the push URL.
- Schema-check relaxed from fatal to advisory (some GitLab instances restrict
  introspection on experimental fields while the real query still works).
- Tested end-to-end against the team's GitLab Enterprise instance — surfaced
  and fixed real-world friction: instance runners, protected-branch push
  rejection, masked-vs-protected variable interactions, port-in-URL gotcha.

### Dashboard features
- 5×5 matrix with severity-tier colors, struck-through closed risks
- Filters: Status, Subsystem (multi), Priority, Risk Type, Product
  (combined TO/ESC/WCC with regex shown), **Labels (multi — every label
  in use, auto-populated; no code change to add a new label value)**, and
  click-to-toggle severity-tier chips
- "Filtering actually hides items in cells" (was bold-count-only originally)
- Title cleanup: strips `Risk# <ID>` prefix
- 90-day tier-count trend chart + per-risk score trend chart
- Per-risk chart: bracket grouping for same-score risks, dotted leaders,
  click-to-pin highlight (with transient hover preview)
- Risks table at the bottom with sortable columns, column show/hide
  (persisted in localStorage), CSV export, and three markdown section
  columns (Risk Description, Notes, Mitigation Plan)
- **Unscored risks table** below the main one — every risk lacking C or L
  shown so the team notices and assigns values; respects every filter
  except severity tier
- "See more" modal for full markdown content; edit-pencil deep-links to
  the GitLab heading anchor
- Labels (subsystems, products, other labels) link to group issue search
- Health column from `WorkItemWidgetHealthStatus`
- Refresh-dashboard panel: single button linking to pipeline schedules
- Footer with docs and source links
- `fetch_work_items` now dedupes returned nodes by global id as a
  defensive measure against pagination quirks (logs a warning if it
  ever fires)

### Smartsheets → GitLab importer (`scripts/import_smartsheet.py`)
Standalone CLI that reads an `.xlsx` export and migrates the text columns
into matching GitLab issue descriptions.

- **Never overwrites existing content.** When a row's content differs
  from the issue's existing canonical section body, the importer appends
  a clearly-marked **proposal block** at the end of the description.
  Reviewers manually accept by replacing the canonical section above and
  deleting the proposal.
- **Per-row coexistence**: multiple spreadsheet rows pointing at the same
  GitLab issue each produce their own block; they don't overwrite each
  other. Markers carry a per-row `source_id` derived from the row's
  Unique Risk ID column (or a content hash if absent).
- **Idempotent**: re-running with the same spreadsheet refreshes each
  row's block in place; legacy (no-sid) blocks from earlier versions of
  the script are stripped on the next run for a clean upgrade.
- **Attribution footer** carries the spreadsheet filename, Unique Risk
  ID (if available), Modification Date (if available), and today's date:
  `*(imported from Risk Register - Task Order 5.xlsx, Unique Risk ID: WCC100, Modification Date: 2026-05-15, on 2026-06-08)*`
- **Diff included** when there was prior content; omitted for net-new
  sections (no point in a diff against empty).
- **Move-aware**: detects `moved_to_id` on the GET response and follows
  the chain (up to 5 hops) via `/api/v4/issues/<global-id>` before
  writing. Logs `> followed move chain: src → dest` to stderr.
- **Rename-resilient**: PUTs use the destination's numeric `project_id`
  rather than its URL-encoded path, so a renamed project (where the
  spreadsheet's old URL 301-redirects on GET but not on PUT) still
  works.
- **Backup file** (`backup-YYYYMMDD-HHMMSS.jsonl`) written before any
  PUT, one JSONL row per visited issue with the original description.
- Tests at `tests/test_import_smartsheet.py` cover 24 cases including
  multi-row coexistence, attribution-field permutations, legacy-block
  migration, and full-spreadsheet re-run idempotency.

### Tests
- Mocked GitLab GraphQL; full pipeline runs against fabricated work items
- Coverage for: matrix counts, idempotent re-runs, history-append on every
  `SNAPSHOT_FIELD` change, multi-item simultaneous changes, vanished →
  closed synthesis, section parsing, markdown sanitization (script/iframe/
  `javascript:`), title cleanup, label grouping, filter UI rendering, status
  filter, products list, NASA-fixture-based example output regeneration
- Sample data based on NASA Risk Management Handbook examples #1(a) and #8
- Test now auto-copies the rendered dashboard into
  `docs/_static/example_dashboard.html` so the docs preview stays current

### GPL release prep
- `LICENSE` (GPL-3.0-or-later), SPDX headers on `build.py` and the template
- Sphinx docs: `index`, `preview`, `setup`, `gitlab-setup`, `usage`,
  `deployment`, `contributing`, `license`
- Edit-on-GitHub buttons via `sphinx_rtd_theme` `html_context`
- ScanCode enforcement: `scripts/check_scancode_allowlist.py` with an
  explicit allowlist of acceptable license keys
- GitHub Actions for test, license-scan, docs-deploy
- README badges, Dependabot, `nh3` sanitization on issue-description
  markdown
- All ten `href="${web_url}"` sites in the template now escape

## Decisions made

| Topic | Decision | Why |
|---|---|---|
| History storage | Separate `risk-history` branch, not `main` | Keeps `main` clean from daily churn and sidesteps protected-branch push rules |
| Markdown rendering | Python-side at build time with `nh3` allowlist | Single source of truth for sanitized HTML; no client-side dep |
| Sanitizer | `nh3` (not `bleach`) | Bleach was archived in 2023; nh3 is its actively maintained successor (Rust-backed `ammonia`, MIT) |
| In-dashboard editing | Deep-link to GitLab heading anchor; no inline edit | Lowest blast radius; respects GitLab's existing audit trail |
| Chart highlight | Click-to-pin (with transient hover preview) | Holds for screenshots when generating reports |
| Chart labels | Plain text, no link wrapper | Click-to-pin would have conflicted; navigation lives in the table below |
| Severity legend | Click-to-toggle multi-select chip | Discoverable + matches existing filter idiom |
| Subsystem-style filters | Multi-select dropdowns; OR within filter, AND across filters | Matches user expectation of "show me high OR critical AND optics" |
| Labels in dashboard | Hyperlinked to group issue search | Cheap to wire, expensive to lose |
| License | GPL-3.0-or-later | Modern default, includes patent retaliation |
| Sample data | Paraphrased NASA Risk Handbook examples | Public domain, well-known, real-shape risks |
| `scancode` runner | Direct `scancode-toolkit` CLI in CI | The "official" `aboutcode-org/scancode-action` is actually scancode.io (server-side, pipelines), which complicated the output schema — direct CLI matches the local dry-run |
| Action pinning | Pin to release tag now, plan to upgrade to SHA via Dependabot | "Tag now, SHA later" — user choice from the plan |
| Example dashboard location | `docs/_static/example_dashboard.html` | Single source of truth; Sphinx already bundles `_static/` |
| Documentation example group | Keep `stp` everywhere with substitution notes | User asked: helps the team recognize their own setup, with prominent "swap `stp` for your group" callouts |
| Importer: existing content | Never overwrite; append proposal blocks instead | User directive after seeing the first run. Reviewers manually accept; no silent data loss. |
| Importer: same-issue multi-row | Coexist as separate proposal blocks with per-row markers | The spreadsheet has multiple rows per issue in practice; collapsing them into one would lose data |
| Importer: moved issues | Follow `moved_to_id` (chain of up to 5 hops) | User directive; alternative was to skip with a warning |
| Importer: renamed projects | Use numeric `project_id` from GET response for the PUT | Avoids GitLab's "PUT to old path → 405" rename-redirect surprise |
| Importer: row identifier source | Unique Risk ID column with content-hash fallback | Stable across re-runs when the column is populated; degrades gracefully when not |
| Unscored risks | Surfaced in their own table at the bottom of the dashboard | Otherwise issues without C/L silently disappear from the dashboard; team needs visibility to fix them |

## Deferred work — pick up here next

### High-confidence, ready to implement
1. **Hide moved/duplicate placeholders from the dashboard.** A risk that was
   officially moved in GitLab has `moved_to_id` set on the (closed) source.
   The dashboard could fetch that field and skip those tombstones so the
   destination doesn't appear "twice" when the user views Status = All.
   For risks that were *manually* closed with a "moved to #X" note (no
   `moved_to_id`), a label-based convention would be simpler: anything
   tagged `superseded` or `duplicate` gets hidden by the dashboard.
2. **`--remap` flag for the importer** to handle manually-moved issues that
   GitLab doesn't formally track. ~25 lines; takes a text file mapping
   source URLs/iids to destinations. Recommended only if the team hits more
   than a handful of these cases.
3. **Importer pre-flight: check for closed-issue writes.** Currently the
   importer happily writes to closed issues. Worth a warning ("you're about
   to write to a CLOSED issue — likely stale spreadsheet link") and an
   opt-in flag.
4. **Importer: `--issue-merge`** to consolidate multiple xlsx rows for one
   GitLab issue into a single proposal block per section. Cleaner end-state
   when the spreadsheet legitimately has multiple per-issue rows.
5. **Pin `aboutcode-org/scancode-toolkit` PyPI version via Dependabot.**
   Dependabot is configured to watch pip; the first PR will arrive
   automatically when a newer scancode-toolkit ships. Confirm it merges
   cleanly on first run.
6. **Touch-device pinning.** Click-to-pin already works on touch; verify on a
   real phone — the chart text is small and may need a larger tap target.
7. **Multi-pin / comparison view** on the per-risk chart. The dim/highlight
   machinery generalizes trivially to a `Set<iid>`; UI would need a "compare
   2-3 risks" affordance (Shift-click? a dedicated multi-pin mode?).

### Bigger pieces if/when needed
5. **In-dashboard editing v2.** Plan sketched in earlier conversation: option
   1 (per-user PAT in localStorage, browser-direct API writes) or option 3
   (sidecar service holding one bot token). Currently option 2 (deep-link to
   GitLab's own edit UI via heading anchor) is in place and probably enough.
6. **Epics.** Query is currently `types: [ISSUE]` only. Adding Epics needs
   schema-check updates and a way to mark them visually in the matrix.
7. **History backfill from system notes.** Today the time series starts from
   the first scheduled run. Backfilling would need to parse `note.body` for
   "changed Consequence to X" entries — error-prone, deferred.
8. **Email/Slack alerts** on escalation. Mentioned in the original plan,
   never built. Movement section in the dashboard surfaces this passively.
9. **Live link-check** in the docs CI workflow to catch `docs.gitlab.com`
   URL rot.
10. **Mobile responsiveness.** Dashboard is desktop-first. Charts and table
    scroll horizontally on narrow viewports but are not optimized.

### Likely-not-worth-it
- **Embedding a GitLab trigger token** for one-click pipeline runs from the
  dashboard. Discussed and rejected — any reader of the page could harvest
  the token. The two-click "Run pipeline" link is fine.
- **Replacing the `markdown` Python library with a JS-side renderer** to
  defer rendering until expand. Pre-rendering with sanitization at build
  time is simpler and the snapshot HTML is already safe.

## Caveats / things to keep an eye on

- The `nh3` allowlist is conservative — if you start using markdown extensions
  beyond `fenced_code, tables, nl2br, sane_lists` you may need to add tags.
  Test fixtures include `<strong>`, `<a>`, `<li>`, `<code>`, headings, and
  block code; widen `_HTML_TAGS` if you add more.
- `RISK_PREFIX_RE` (in `build.py`) currently strips `Risk# <ID>` prefixes. If
  your numbering convention changes, edit this regex; the test cases in
  `test_clean_title` document the recognized shapes.
- `PRODUCT_PATTERNS` (`^TO\d`, `^ESC`, `^WCC`) is editable but the test
  fixtures assert on the current shape — if you change it, update the
  fixture assertions too.
- `CANONICAL_SECTIONS` is the one place to add a new section column.
  Template renders all entries automatically via `SECTION_META`.
- The `scancode` workflow ignores `docs/license.rst` and
  `scripts/check_scancode_allowlist.py` because they describe licensing
  meta-textually. If you add real licensed content to those files, remove
  the ignore.
- ScanCode workflow comment used to contain literal license key strings,
  which scancode then matched in the workflow file itself. The current
  comment is worded to avoid license-shaped substrings; don't reintroduce
  them.
- The `risk-history` branch is unprotected by design. If you ever protect
  it, allow the `PUSH_TOKEN` bot user to push.
- `tests/test_build.py` reads/writes the real repo paths
  (`HISTORY_PATH`, `PUBLIC_DIR`) for the main scenario so the example
  dashboard gets refreshed. Two newer tests use a `tmp_path` to isolate;
  follow that pattern for any new test that doesn't need to publish
  artifacts.
- **Copilot Autofix has been a source of regressions.** Two commits on
  this branch (`c444dd0`, `0b68197`) removed a `.rstrip()` that was
  essential for the importer's idempotency, breaking 2 tests. Fix is in
  `8924ed5` with an inline comment explaining why the rstrip must stay.
  If future Autofix passes propose similar "redundant strip" changes,
  decline.
- **The importer's per-row markers are tied to the Unique Risk ID
  column.** If the spreadsheet doesn't have that column populated,
  the importer falls back to a content hash — stable for same content,
  but if a row's content is edited the hash changes and an orphan
  block remains. Tell the team to keep Unique Risk IDs unique and
  populated; otherwise clean orphans manually.
- **`fetch_work_items` dedupes by global id** as a defensive measure.
  If you ever see the "returned N duplicate node(s)" warning in the
  CI log, that's a signal — investigate; it shouldn't normally happen.
- The "Unscored risks" section is computed from items with `c is None
  or l is None` (or out-of-range). If you ever change C/L to a
  different shape (e.g., a text field with values "low"/"medium"/"high"),
  update the unscored guard in `build.py` alongside the matrix-cell
  guard.

## Useful pointers

- `build.py`: GraphQL query, normalize, history append, render entry point.
  `fetch_work_items` does the pagination + dedup; `render` builds every
  JSON payload the template consumes (matrix cells, risks table, unscored
  table, per-risk chart series, label-options, etc.).
- `templates/index.html.j2`: all UI (HTML/CSS/JS in one file by design).
- `scripts/import_smartsheet.py`: standalone xlsx → GitLab issue
  importer. `merge_sections` is the core; `_build_proposal_block`
  formats one block; `_strip_proposals_for_sid` is the per-row strip.
- `scripts/check_scancode_allowlist.py`: allowlist of accepted SPDX-ish
  license keys; add new entries with rationale when a legit detection
  triggers a CI failure.
- `tests/test_build.py`: end-to-end pipeline test + example dashboard
  refresh.
- `tests/test_import_smartsheet.py`: 24 cases covering the importer's
  non-destructive / idempotent / multi-row guarantees.
- `docs/preview.rst`: live iframe of the rendered example dashboard.
- `docs/contributing.rst`: per-workflow purpose table.
