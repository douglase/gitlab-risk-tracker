Contributing
============

Bug reports, feature requests, and pull requests welcome.

Workflow
--------

1. Open an issue describing the change.
2. Branch from ``main``; make the change locally.
3. Run the test suites: ``python tests/test_build.py`` and
   ``python tests/test_import_smartsheet.py`` (or ``pytest tests/`` to
   run both).
4. Push a branch and open a pull request.

Coding conventions
------------------

- Python: prefer standard library; minimize new dependencies.
- Vanilla JS in the template (no framework, no CDN).
- All changes should keep the dashboard self-contained — no external
  network requests at runtime in the published HTML.
- New columns in the risks table should be added to ``COLUMNS`` in
  the template and have their data populated in
  ``risks_table_json`` in ``build.py``.

Tests
-----

``tests/test_build.py`` mocks the GitLab GraphQL responses, exercises
the full ``main()`` pipeline, and asserts on the rendered HTML, history
append semantics, and section parsing. Sample risks are based on
examples from the NASA Risk Management Handbook (NASA/SP-2011-3422,
Rev. A).

``tests/test_build_github.py`` covers the GitHub provider: that both
providers normalize to the same item dict, that risk values are read
from ``Issue.issueFieldValues`` (organization issue fields, not
Projects v2 board fields), issue-search pagination and its result cap,
and field-name matching. It mocks every response, so it runs without a
GitHub connection.

``tests/test_import_smartsheet.py`` covers the spreadsheet importer
(see :doc:`importer`): the non-destructive proposal-block behavior,
idempotent re-runs, heading-synonym matching, the bare-body fallback,
and the per-row failure diagnostics. Its helpers are pure-Python, so
the suite runs without a GitLab connection or an ``.xlsx`` file.

Continuous integration
----------------------

Four GitHub Actions workflows live in this repository. Three support
development of the tool; ``dashboard.yml`` is a deployment pipeline and
runs only for dashboards hosted on GitHub. The reference deployment
still runs on **GitLab CI** via ``.gitlab-ci.yml`` (see
:doc:`deployment`); the GitHub equivalent is described in
:doc:`github-setup`.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Workflow
     - Purpose
   * - ``.github/workflows/test.yml``
     - Runs ``python tests/test_build.py``,
       ``python tests/test_build_github.py`` and
       ``python tests/test_import_smartsheet.py`` on every push and
       pull request. Exercises the full ``build.py`` pipeline against
       mocked GitLab and GitHub data (matrix counts, history append
       semantics, section parsing, markdown sanitization, the rendered
       HTML, provider parity) and the importer's pure-Python helpers.
   * - ``.github/workflows/scancode.yml``
     - License-scan gate. Runs
       `scancode-toolkit <https://github.com/aboutcode-org/scancode-toolkit>`_
       on every push and pull request and fails the build if any
       detected license is outside the allowlist in
       ``scripts/check_scancode_allowlist.py``. Protects the GPL-3.0
       release from accidentally absorbing incompatibly-licensed code;
       see :doc:`license` for details and how to extend the allowlist.
   * - ``.github/workflows/dashboard.yml``
     - Deployment pipeline, not development support: the GitHub
       Actions port of the ``.gitlab-ci.yml`` ``pages`` job. Builds the
       dashboard on a daily schedule (or on demand), round-trips
       ``data/history.ndjson`` through the orphan ``risk-history``
       branch, and uploads ``public/``. The Pages deploy is gated on a
       ``PUBLISH_PAGES`` repository variable, so it stays inert in this
       repository, whose Pages site is this documentation. Requires
       ``RISK_PROVIDER=github`` and the configuration in
       :doc:`github-setup`.
   * - ``.github/workflows/docs.yml``
     - Documentation publisher. On push to ``main``, builds this
       Sphinx site under ``docs/`` and deploys the HTML to the
       ``gh-pages`` branch, which GitHub Pages then serves at the
       project's docs URL. Builds run with ``-W`` (warnings treated
       as errors) so doc-syntax regressions block the deploy.

Dependency updates for both workflows (and for ``requirements.txt``)
arrive as PRs via ``.github/dependabot.yml``.

Adding a heading synonym
^^^^^^^^^^^^^^^^^^^^^^^^

Edit ``CANONICAL_SECTIONS`` in ``build.py``; add an entry to the
relevant tuple's synonym list. Add a test case in
``test_parse_sections``.

Adding a new section column
^^^^^^^^^^^^^^^^^^^^^^^^^^^

1. Add an entry to ``CANONICAL_SECTIONS`` with a fresh ``key``.
2. The Jinja template renders all sections via ``SECTION_META``
   automatically; no template edits needed.
3. Update ``docs/gitlab-setup.rst`` with the new accepted heading.
