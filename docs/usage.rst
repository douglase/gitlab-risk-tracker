Using the dashboard
===================

The published dashboard is a single self-contained HTML page. Members
of the source group can view it; anonymous visitors get a 401.

5×5 matrix
----------

The grid is Consequence (Y, top = 5) vs. Likelihood (X, right = 5).
Cell color reflects the severity tier:

- Green: low (score 1–4)
- Yellow: medium (score 5–9)
- Orange: high (score 10–15)
- Red: critical (score 16–25)

Each cell shows up to four matching issues; click any cell to see the
full list in the detail table below.

Closed risks (visible only when the Status filter is set to "Closed"
or "All") appear with their titles struck through and dimmed.

Filters
-------

All filters apply simultaneously and update the matrix, detail table,
per-risk score chart, and bottom risks table.

- **Status** — Open (default), Closed, or All
- **Subsystem** — multi-select; ⌘/Ctrl-click for multiple
- **Priority** — single select
- **Risk Type** — single select
- **Product** — multi-select; combines all ``^TO\d``, ``^ESC``, and
  ``^WCC`` labels in your data into one dropdown. Only appears when at
  least one matching label exists.
- **Labels** — multi-select over *every* label in use across the open
  risks (subsystem, product, and other labels alike). Only appears when
  the data has labels.
- **Severity tier chips** — click any of low/medium/high/critical to
  toggle filter on/off (multi-select)

Click **Clear filters** to reset all of them at once.

Charts
------

Two trend charts at the top:

1. **Issues by severity tier (last 90 days)** — aggregate counts per
   tier, day by day, reconstructed from ``history.ndjson``.
2. **Per-risk score (C×L)** — one line per currently scored risk,
   colored by current tier. Filter-responsive: as you narrow filters,
   non-matching series are hidden.

Both charts label the current value at the right edge so you can read
the present state without inspecting the rightmost data point.

Movement and Subsystem breakdown
--------------------------------

Two summary sections sit between the charts and the risks table, both
**collapsed by default** — click a heading to expand it:

- **Movement (last 30 days)** — four cards listing risks that escalated,
  de-escalated, were newly added, or were closed in the last 30 days
  (up to 10 each), reconstructed from the history log.
- **Subsystem breakdown (label occurrences)** — a bar per subsystem
  label counting open issues carrying it. An issue with two subsystem
  labels counts once under each.

Risks table
-----------

A flat sortable table at the bottom of the page lists every open
scored risk. Default sort is by score descending. Click any column
header to sort by that column.

The **Show** selector in the table toolbar limits the view to the
**Top 5**, **Top 10**, or **Top 25** risks (default: All). "Top" always
means the highest-scored risks after the active filters — regardless of
severity tier and regardless of how the table is currently sorted; the
column sort only changes the display order of those N rows. The row
count in the heading shows ``N of M`` when a limit is active, and the
CSV export respects the same limit.

Columns
^^^^^^^

The Columns dropdown toggles individual columns. Your preference is
remembered in localStorage. Default-hidden columns: Health, Opened,
Closed.

Available columns:

- **ID** — links to the GitLab issue
- **Title** — Risk# prefix stripped
- **Status** — Open / Closed pill
- **Health** — GitLab's HealthStatus value (hidden by default)
- **Opened** / **Closed** — issue dates (hidden by default)
- **C**, **L**, **Score**
- **Priority**, **Risk Type**
- **Subsystems** — label chips, each a link to the group's filtered
  issue search
- **Product** — label chips, same link behavior
- **Owner** — assignee name(s) with profile link
- **Risk Description**, **Notes**, **Mitigation Plan** — section
  content from the issue description, rendered markdown shown in a
  modal via ``see more``. The ✎ pencil opens the issue at the heading
  anchor in GitLab for inline editing.
- **Other labels** — anything not matched by subsystem or product
  patterns

Unscored risks
--------------

Issues that match the risk-label filter but have no valid Consequence ×
Likelihood score (1–5 on each axis) can't be placed on the matrix or
sorted in the main table. They are listed separately in an **Unscored
risks** section beneath the scored table so the team notices them and
assigns values in GitLab. The section is collapsed by default — click
the heading to expand the list — and only appears when at least one
unscored risk exists. The row count next to the heading stays visible
either way and reflects the current filters.

CSV export
----------

The **Export CSV** button downloads the current filtered + sorted view
as a CSV file. The CSV contains the full untruncated section text and
a ``GitLab Link`` column with the issue URL. Excel-readable; UTF-8
BOM is included so Excel recognizes the encoding.

Edit pencils
-------------

Each section cell has a small ✎ icon that opens the issue at the
relevant heading anchor in a new tab. Editing happens in GitLab's
native UI; the dashboard does not edit issues directly.

RUN CI button
-------------

The green **▶ RUN CI** button at the top of the page tees up a
dashboard rebuild: it opens GitLab's *Run pipeline* form in a new tab
with the default branch preselected, so a single click there starts
the pipeline. (A static Pages site can't fire the pipeline directly —
that requires an authenticated POST — so the button takes you to the
one-click form instead.) A run takes 1–3 minutes; reload the dashboard
when it finishes. The button only renders on GitLab-deployed builds,
where the server URL and project path are known.

Version footer
--------------

The page footer shows the short git SHA of the ``build.py`` /
template revision that produced the dashboard, alongside links to this
documentation and the source repository. In a GitLab deployment the SHA
links to the matching commit (using ``CI_PROJECT_URL`` and the CI
commit SHA), so you can always tell exactly which version of the tool
rendered the page you're looking at.
