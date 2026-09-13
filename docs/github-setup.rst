GitHub setup
============

The dashboard can source risks from GitHub instead of GitLab. Set
``RISK_PROVIDER=github``; everything downstream of the fetch — history,
trend charts, the 5×5 matrix, the risks table, the MSR decks — is
provider-agnostic and behaves identically.

``RISK_PROVIDER`` defaults to ``gitlab``, so existing deployments need no
change.

Where the risk values live
--------------------------

GitHub's analogue of GitLab work-item custom fields is
`issue fields <https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/adding-and-managing-issue-fields>`_:
organization-level typed metadata stored on the issue itself. An
organization admin defines the fields once and *pins* them to
`issue types <https://docs.github.com/en/issues/tracking-your-work-with-issues/configuring-issues/managing-issue-types-in-an-organization>`_,
so a ``Risk`` issue type can carry exactly the risk fields and nothing
else. ``build.py`` reads them from ``Issue.issueFieldValues``.

.. warning::

   Issue fields are **not** the same thing as Projects v2 custom fields.
   Projects v2 fields are scoped to one board and stored on the
   issue-to-board join row, so they are invisible to any issue that has
   not been added to that board. This tool deliberately reads issue
   fields, not project item fields.

   Issue fields reached general availability in July 2026, so the GitHub
   provider requires github.com or a GitHub Enterprise Server release
   that ships them.

Create an issue type (``Risk``) and these organization issue fields,
pinned to it:

.. list-table::
   :header-rows: 1
   :widths: 26 18 56

   * - Field
     - Type
     - Notes
   * - ``Consequence``
     - Number
     - 1–5.
   * - ``Likelihood``
     - Number
     - 1–5.
   * - ``Priority Level``
     - Single select
     - ``High`` / ``Medium`` / ``Low``. Must be single select — the
       dashboard models priority as one value per risk.
   * - ``Risk Type``
     - Multi select
     - ``Technical`` / ``Cost`` / ``Schedule``. Single select also works,
       and then a risk can only carry one type.

Only ``Risk Type`` is multi-valued. If ``Consequence``, ``Likelihood`` or
``Priority Level`` is declared multi-select, ``build.py`` uses the first
selected option and warns — it is tolerated so the value is not lost, but
it is a misconfiguration, not a supported layout.

Subsystem and product labels work exactly as on GitLab: they are plain
issue labels, matched against ``SUBSYSTEMS`` and ``PRODUCT_PATTERNS`` in
``build.py``.

Field names
~~~~~~~~~~~

Field names are matched case-insensitively, ignoring a trailing
parenthetical — so the GitLab-flavoured defaults ``Consequence (C)`` and
``Likelihood (L)`` also match issue fields plainly named ``Consequence``
and ``Likelihood``. The same risk register needs no extra configuration
on either forge.

For anything further from the defaults, name your fields explicitly:

.. code-block:: bash

   export RISK_FIELD_CONSEQUENCE="Impact"
   export RISK_FIELD_RISK_TYPE="Category"

``build.py`` probes the first matching issue on startup and prints the
resolution unconditionally — the fields that issue carries, and what each
configured name matched — so a mismatch shows up as a log line rather than
as a blank column:

.. code-block:: text

   GitHub search 'org:acme is:issue type:"Risk"' matches 34 issue(s).
   Issue fields set on probe issue #212: {'Consequence': 'NUMBER',
     'Likelihood': 'NUMBER', 'Priority Level': 'SINGLE_SELECT'}
     'Consequence (C)' (RISK_FIELD_CONSEQUENCE) -> 'Consequence'
     'Likelihood (L)' (RISK_FIELD_LIKELIHOOD) -> 'Likelihood'
     'Priority Level' (RISK_FIELD_PRIORITY) -> 'Priority Level'
     'Risk Type' (RISK_FIELD_RISK_TYPE) -> NOT FOUND

.. note::

   **A column is blank in the dashboard.** Check that probe output first:
   ``NOT FOUND`` means no issue field matched the configured name, and
   that column will be empty for every risk.

   In GitHub Actions, an *undefined* repository variable interpolates to
   the empty string rather than to nothing, so ``RISK_FIELD_PRIORITY:
   ${{ vars.RISK_FIELD_PRIORITY }}`` with the variable unset hands
   ``build.py`` a blank name that matches nothing. ``build.py`` treats a
   blank value as unset, and ``dashboard.yml`` also supplies ``|| 'Priority
   Level'`` defaults, so both halves are covered — but keep the ``||``
   defaults if you add more ``RISK_FIELD_*`` wiring of your own.

   If a name *did* resolve and the column is still blank, dump the raw
   values:

   .. code-block:: bash

      RISK_DEBUG_FIELDS=1 python build.py 2>probe.log

   That prints every issue's ``issueFieldValues`` nodes, including each
   field's concrete type and ``dataType`` — which is how the
   multi-select Priority Level case above was found.

What gets scanned
-----------------

``IssueType.issues`` requires a repository ID and so cannot span an
organization. The scan therefore goes through issue search:

.. code-block:: text

   org:<RISK_GITHUB_OWNER> is:issue type:"<RISK_GITHUB_ISSUE_TYPE>"

issued as GraphQL ``search(type: ISSUE_ADVANCED, ...)``. Open and closed
issues both come back, which is what the history's closed-risk detection
needs.

Set ``RISK_GITHUB_SEARCH`` to replace that query outright — for a user
account rather than an organization (``user:someone is:issue``), a subset
of repositories, or any other
`advanced search <https://docs.github.com/en/issues/tracking-your-work-with-issues/filtering-and-searching-issues-and-pull-requests>`_
expression, including ``field.<name>:`` qualifiers and AND/OR grouping.

.. warning::

   GitHub caps how deeply an issue search can be paginated. ``build.py``
   compares the number of issues it retrieved against the ``issueCount``
   the search reports and prints a loud warning if they differ, because a
   silently truncated risk register is the worst failure this tool could
   have. If you see that warning, narrow the scan with
   ``RISK_GITHUB_ISSUE_TYPE`` or a more specific ``RISK_GITHUB_SEARCH``.

Token
-----

A token that can read the organization's issues:

- classic PAT: ``repo`` (or ``public_repo`` for public repositories only)
- fine-grained PAT: *Issues: Read-only* on the relevant repositories

Store it as a repository secret named ``RISK_TOKEN``; the workflow passes
it to ``build.py`` as ``GITHUB_TOKEN``. The automatic ``GITHUB_TOKEN`` of
a workflow run is scoped to its own repository, so it cannot read issues
across an organization — a PAT is required for an org-wide scan.

Environment variables
---------------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Variable
     - Meaning
   * - ``RISK_PROVIDER``
     - ``gitlab`` (default) or ``github``.
   * - ``GITHUB_TOKEN``
     - Token, as above.
   * - ``RISK_GITHUB_OWNER``
     - Organization whose issues to scan.
   * - ``RISK_GITHUB_ISSUE_TYPE``
     - Issue-type name to scan, e.g. ``Risk``. Optional; without it every
       issue in the org is fetched and ``RISK_LABEL_FILTER`` does the
       filtering.
   * - ``RISK_GITHUB_SEARCH``
     - Replaces the generated search query outright.
   * - ``RISK_GITHUB_WORKFLOW``
     - Workflow file behind the dashboard's RUN CI button
       (default ``dashboard.yml``).
   * - ``RISK_FIELD_CONSEQUENCE``, ``RISK_FIELD_LIKELIHOOD``,
       ``RISK_FIELD_PRIORITY``, ``RISK_FIELD_RISK_TYPE``
     - Override the expected field names. Honoured on both providers.
   * - ``GITHUB_SERVER_URL``, ``GITHUB_API_URL``, ``GITHUB_REPOSITORY``,
       ``GITHUB_SHA``
     - Set automatically by GitHub Actions. Set ``GITHUB_SERVER_URL`` by
       hand for GitHub Enterprise Server; the GraphQL endpoint is derived
       from it (``https://HOST/api/graphql``).

Local dry run
-------------

.. code-block:: bash

   export RISK_PROVIDER=github
   export GITHUB_TOKEN=<PAT with read access to the org issues>
   export RISK_GITHUB_OWNER=acme
   export RISK_GITHUB_ISSUE_TYPE=Risk
   pip install -r requirements.txt
   python build.py
   open public/index.html

Watch stderr. The startup probe prints the search query, how many issues
it matched, and the issue-field names it found — the fastest way to
confirm the scan is pointed at the right place.

Running in GitHub Actions
-------------------------

``.github/workflows/dashboard.yml`` is a direct port of the
``.gitlab-ci.yml`` ``pages`` job, following the
`manual migration guide <https://docs.github.com/en/actions/tutorials/migrate-to-github-actions/manual-migrations/migrate-from-gitlab-cicd>`_:

.. list-table::
   :header-rows: 1
   :widths: 44 56

   * - GitLab CI
     - GitHub Actions
   * - ``rules: $CI_PIPELINE_SOURCE == "schedule"``
     - ``on: schedule: - cron: '0 2 * * *'``
   * - ``rules: $CI_PIPELINE_SOURCE == "web"``
     - ``on: workflow_dispatch``
   * - ``image: python:3.12-slim``
     - ``runs-on: ubuntu-latest`` + ``actions/setup-python``
   * - ``before_script`` (apt + pip)
     - ``Install LibreOffice`` and ``Install dependencies`` steps
   * - ``artifacts: paths: [public]``
     - ``actions/upload-artifact`` (+ ``upload-pages-artifact``)
   * - GitLab Pages
     - ``actions/deploy-pages``
   * - ``PUSH_TOKEN`` + ``-o ci.skip``
     - built-in ``GITHUB_TOKEN``; the orphan ``risk-history`` branch is
       not a workflow trigger, so no skip flag is needed

Configure the repository with:

- secret ``RISK_TOKEN`` — the PAT described above
- variable ``RISK_GITHUB_ISSUE_TYPE`` (and ``RISK_GITHUB_OWNER`` if the
  issues are not owned by the repository owner)
- variable ``PUBLISH_PAGES=true`` to enable the Pages deploy, plus
  *Settings → Pages → Source: GitHub Actions*

The Pages deploy is gated on ``PUBLISH_PAGES`` because in *this*
repository the Pages site is the Sphinx documentation. Without it the
dashboard is still produced and uploaded as a run artifact.

.. warning::

   **Pages access control.** GitLab's "Only project members" Pages
   setting has no equivalent on github.com — Pages for a public
   repository is world-readable, and private-repository Pages requires
   GitHub Enterprise Cloud. Risk registers are usually not for public
   consumption: keep the repository private and either use Enterprise
   Cloud or consume the run artifact instead of publishing.

Known differences from the GitLab provider
------------------------------------------

- **No health status.** GitHub has no equivalent of GitLab's health
  status, so ``health_status`` is always ``None`` and that column stays
  empty.
- **Scope is a search, not a group tree.** GitLab scans a group
  recursively; GitHub scans whatever the issue search matches, subject to
  the pagination cap described above.
- **The Smartsheet importer is GitLab-only.**
  ``scripts/import_smartsheet.py`` still writes through the GitLab REST
  API; it was out of scope for this change.
