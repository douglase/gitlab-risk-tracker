Deploying on GitLab
===================

The dashboard is designed to run as a scheduled GitLab CI ``pages``
job that publishes ``public/index.html`` to GitLab Pages and pushes
the daily snapshot back to a separate ``risk-history`` branch.

Project setup
-------------

1. Create a project to host the dashboard (e.g. ``stp/risks-dashboard``).
2. Push the repository to its default branch (``main``).
3. Settings → Pages → Access Control: **Only project members**.

CI/CD variables
---------------

Settings → CI/CD → Variables. Both should be **Masked** and
**Protected** (if the default branch is protected, which it should be).

.. list-table::
   :header-rows: 1
   :widths: 20 20 60

   * - Variable
     - Scope
     - Description
   * - ``GITLAB_TOKEN``
     - Group access token on the source group
     - ``read_api`` scope. Used by ``build.py`` to query work items.
   * - ``PUSH_TOKEN``
     - Project access token on the dashboard project
     - ``write_repository`` scope, **Maintainer** role. Used by the
       pipeline to commit ``data/history.ndjson`` to the
       ``risk-history`` branch.

Protected branches
------------------

The ``risk-history`` branch is automatically created by the first
pipeline run. It does not need to be protected. The default branch
(``main``) should be protected; the pipeline does **not** push to it.

Schedule
--------

Build → Pipeline schedules → New schedule:

- Description: ``Nightly risk snapshot``
- Cron: ``0 2 * * *`` (or your preference)
- Target branch: ``main``
- Active: on

Manual trigger
--------------

Build → Pipelines → **New pipeline** → branch ``main`` → Run.

The pipeline:

1. Fetches the existing ``risk-history`` branch (if any) and pulls
   ``data/history.ndjson`` into the working tree.
2. Runs ``build.py``, which queries GitLab GraphQL, appends any
   changed rows to ``data/history.ndjson``, and renders
   ``public/index.html``.
3. If the history changed, commits and pushes it back to
   ``risk-history`` using ``PUSH_TOKEN``.
4. Publishes ``public/`` to GitLab Pages via the ``pages`` job
   artifact.

Behavior summary
----------------

- **History** lives on ``risk-history``, append-only. Daily snapshots
  add only the rows that changed since the last run.
- **Pages** redeploys every pipeline run from the freshly built
  ``public/index.html``.
- **Main** stays clean — only ``.gitlab-ci.yml``, code, templates,
  tests, docs.

Troubleshooting
---------------

``GITLAB_TOKEN is not set``
   The variable is marked **Protected** but the pipeline ran on a
   non-protected branch. Either mark the target branch protected or
   uncheck **Protected** on the variable.

``HTTP Basic: Access denied`` on push
   ``PUSH_TOKEN`` is empty, expired, or its bot user lacks the role
   needed to push to ``risk-history``. Re-issue the token with
   **Maintainer** role on the dashboard project.

``Group.workItems is not available on this GitLab instance``
   The instance restricts GraphQL introspection on experimental
   fields. The build now treats this as a warning and proceeds to the
   real query; if the query then fails with a "field doesn't exist"
   GraphQL error, ask your GitLab admin to enable the
   ``namespace_level_work_items`` feature flag (or equivalent for
   your version).
