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
  ``^WCC`` labels in your data into one dropdown
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

Risks table
-----------

A flat sortable table at the bottom of the page lists every open
scored risk. Default sort is by score descending. Click any column
header to sort by that column.

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
