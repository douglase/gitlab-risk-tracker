Importing from a spreadsheet
============================

``scripts/import_smartsheet.py`` is a standalone, **non-destructive**
tool for migrating risk text from a Smartsheets / Excel export into the
matching GitLab issue descriptions. It is separate from the dashboard
build: run it by hand when you want to pull spreadsheet content into
GitLab, then let the normal pipeline pick the change up on its next run.

.. important::

   The importer **never overwrites** existing issue content. For each
   row it *appends* a clearly-marked "proposal block" to the bottom of
   the issue description containing the spreadsheet text (and a diff
   against the current section, if one exists). A human reviews each
   proposal in GitLab and decides whether to adopt it. Re-running the
   importer refreshes its own proposal blocks in place rather than
   duplicating them.

Install
-------

The importer reads ``.xlsx`` files with
`openpyxl <https://openpyxl.readthedocs.io/>`_, which is **not** in the
dashboard's ``requirements.txt`` (the dashboard never touches Excel).
Install it into the same conda/mamba environment from :doc:`setup`:

.. code-block:: bash

   conda activate risk-tracker
   pip install -r requirements.txt openpyxl

``openpyxl`` is imported lazily, so the importer's unit tests run
without it; you only need it for a real run against a spreadsheet.

Spreadsheet format
------------------

The importer matches columns by header name (case-insensitive,
surrounding whitespace ignored). Only these are read; every other
column is left alone.

.. list-table::
   :header-rows: 1
   :widths: 30 25 45

   * - Column header
     - Maps to
     - Notes
   * - ``GitLab Link``
     - issue to update
     - Full issue URL, e.g.
       ``https://gitlab.example.com/grp/proj/-/issues/123``. Any column
       whose header contains both "gitlab" and "link" works. **Required
       per row** — rows without one are skipped and reported.
   * - ``Risk Description``
     - ``## Risk Description``
     - Also accepts ``Description``, ``Summary`` headings on the issue
       side.
   * - ``Action Plan/ Notes``
     - ``## Notes``
     - ``Action Plan / Notes``, ``Action Plan/Notes`` and ``Notes`` are
       all accepted.
   * - ``Risk Mitigation Planning``
     - ``## Mitigation Plan``
     - ``Mitigation Plan`` is also accepted.
   * - ``Unique Risk ID``
     - proposal-block identity
     - Optional but recommended. Also accepts ``Risk ID``, ``Risk_ID``,
       ``Risk #``. Tags each proposal block so re-runs update the right
       one and so per-row diagnostics name the row. When absent, a
       stable hash of the row's content is used instead.
   * - ``Modification Date``
     - attribution footer
     - Optional. Also accepts ``Modified Date``, ``Last Modified``,
       ``Modified``, ``Updated``, ``Date Modified``. Date-typed cells
       render as ``YYYY-MM-DD``.

Each appended proposal block carries an italic attribution line, e.g.
``*(imported from Risk Register.xlsx, Unique Risk ID: LPY016,
Modification Date: 2025-07-22, on 2026-06-12)*``.

Usage
-----

Always dry-run first. ``--dry-run`` prints a unified diff per changed
issue and writes nothing.

.. code-block:: bash

   export GITLAB_TOKEN=<token-with-api-scope>

   # Preview a single issue by iid
   python scripts/import_smartsheet.py \
       --xlsx "Risk Register.xlsx" --issue 131 --dry-run

   # Preview the first three matched rows
   python scripts/import_smartsheet.py \
       --xlsx "Risk Register.xlsx" --limit 3 --dry-run

   # Real run (writes proposal blocks back to GitLab)
   python scripts/import_smartsheet.py --xlsx "Risk Register.xlsx"

The token needs ``api`` scope (read **and** write), unlike the
dashboard's read-only ``GITLAB_TOKEN``.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Flag
     - Meaning
   * - ``--xlsx PATH``
     - The spreadsheet export. **Required.**
   * - ``--token`` / ``--token-env``
     - Token value, or the env var to read it from (default
       ``GITLAB_TOKEN``).
   * - ``--server URL``
     - Override the GitLab base URL (default: parsed from each row's
       ``GitLab Link``).
   * - ``--sheet NAME``
     - Worksheet to read (default: the active sheet).
   * - ``--dry-run``
     - Print diffs; make no changes.
   * - ``--print-markdown``
     - Instead of a diff, print the full proposed issue description as
       clean, pasteable markdown; never writes (implies ``--dry-run``).
       See below.
   * - ``--limit N``
     - Process at most N matched rows.
   * - ``--issue IID``
     - Process only the row whose link points at this issue iid.
   * - ``--backup PATH``
     - Where to append the original descriptions before any write
       (default: a timestamped ``backup-*.jsonl`` in the working
       directory). Always written, even on a dry run's matched rows.

Previewing in GitLab
--------------------

``--dry-run`` shows a unified diff, which is great for review but not
something you can paste anywhere. When you'd rather *see* how the
result will render, use ``--print-markdown`` (which implies
``--dry-run`` — it never writes):

.. code-block:: bash

   python scripts/import_smartsheet.py \
       --xlsx "Risk Register.xlsx" --issue 131 --print-markdown

This prints the **complete proposed description** for each changed
issue — exactly what would be written — so you can copy it into the
issue's description box in GitLab and click *Preview* to see the
rendered result before committing to a real run.

Each issue's block is introduced by an HTML-comment delimiter such as
``<!-- ===== LPY016 → grp/proj#131 ... ===== -->``. HTML comments are
invisible in GitLab's rendered markdown, so even if you copy the whole
block (delimiter included) the preview stays clean. Pair the flag with
``--issue <iid>`` to get a single issue's markdown on its own.

How it handles edge cases
-------------------------

- **Renamed projects.** GitLab follows the rename on the read, and the
  importer writes back using the issue's numeric ``project_id`` so the
  ``PUT`` isn't affected by the redirect.
- **Moved issues.** If the spreadsheet URL points at a closed
  placeholder that was moved to another project, the importer follows
  the ``moved_to_id`` chain (up to 5 hops) to the live destination.
  Following a move needs the token to have read access to the
  destination project; if it doesn't, the row fails with a ``403`` and
  is listed in the summary (see below).
- **Bare descriptions.** If an issue's existing Risk Description is
  bare prose with no heading and already matches the spreadsheet, no
  proposal block is added (nothing to propose). Other spreadsheet
  sections on the same row are still appended. This mirrors the
  dashboard's leading-prose fallback (:doc:`gitlab-setup`).

Reading the output
------------------

Every per-row line and error is tagged with the row's Unique Risk ID
(or ``row N`` matching the spreadsheet row number when there's no ID
column), and the run ends with a summary plus an explicit list of any
rows that didn't update and why:

.. code-block:: text

   === Summary ===
     total: 18
     no_link: 1
     ...
     updated: 11
     errors: 6

   === Rows that did not update ===
     - LPY008: move from stp/task-orders#128 → moved_to_id=2620: 403 Forbidden
     - LPY017: no GitLab Link in spreadsheet

Use that list to decide whether to grant the token access to a
destination project or to update the spreadsheet's ``GitLab Link`` to
point straight at the moved issue.

Recovering from a bad run
-------------------------

Before writing anything, the importer appends each issue's original
description as a JSON line to the backup file. To restore an issue,
pull its ``description`` field out of that file and ``PUT`` it back
(or paste it into the issue in GitLab). Because the importer only
*appends* marked proposal blocks, the usual "undo" is simply deleting
the ``<!-- spreadsheet-import:proposal:... -->`` block from the issue
description in GitLab.
