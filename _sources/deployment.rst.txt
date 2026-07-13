Deploying on GitLab
===================

The dashboard is designed to run as a scheduled GitLab CI ``pages``
job that publishes ``public/index.html`` to
`GitLab Pages <https://docs.gitlab.com/user/project/pages/>`_ and
pushes the daily snapshot back to a separate ``risk-history`` branch.

Prerequisites
-------------

Before you start, confirm with your GitLab administrator (or check
yourself if you are one):

- **A runner is available** to the dashboard project and can reach the
  internet to ``pip install`` packages. Without a runner, pipelines
  stay "pending" forever. Settings → CI/CD → Runners shows what is
  available; if the list is empty, enable
  `instance runners <https://docs.gitlab.com/ci/runners/>`_ or
  `register a project runner <https://docs.gitlab.com/runner/register/>`_.
- **GitLab Pages is enabled** on the instance
  (`Pages administration <https://docs.gitlab.com/administration/pages/>`_).
- The source group's
  `custom fields <https://docs.gitlab.com/user/work_items/custom_fields/>`_
  are configured per :doc:`gitlab-setup`.

Project setup
-------------

1. Create a project to host the dashboard (e.g. ``stp/risks-dashboard``).
   This is **not** the group your risks live in — it is a new, separate
   project that holds only this tool.
2. Get this repository's code onto the new project's default branch
   (``main``). From a clone of this repository:

   .. code-block:: bash

      # 'origin' is this repo on GitHub; add your GitLab project as a
      # second remote and push main to it.
      git remote add gitlab https://YOUR-GITLAB-HOST/stp/risks-dashboard.git
      git push gitlab main

   If your GitLab project protects ``main`` and rejects a direct push,
   push to a feature branch instead and open a merge request:

   .. code-block:: bash

      git push gitlab main:import-dashboard
      # then open a merge request import-dashboard -> main in the UI

3. Settings → Pages → Access Control: **Only project members**
   (`Pages access control <https://docs.gitlab.com/user/project/pages/pages_access_control/>`_).

CI/CD variables
---------------

Add these under Settings → CI/CD →
`Variables <https://docs.gitlab.com/ci/variables/>`_. Mark the two
token variables **Masked** (so they are hidden in job logs) and
**Protected** (so they are only exposed to protected branches — see
the next section).

.. list-table::
   :header-rows: 1
   :widths: 22 23 55

   * - Variable
     - What to put in it
     - Description
   * - ``GITLAB_TOKEN``
     - A `group access token <https://docs.gitlab.com/user/group/settings/group_access_tokens/>`_
       on the **source** group
     - ``read_api`` scope. Used by ``build.py`` to query work items.
   * - ``PUSH_TOKEN``
     - A `project access token <https://docs.gitlab.com/user/project/settings/project_access_tokens/>`_
       on the **dashboard** project
     - ``write_repository`` scope, **Maintainer** role. Used by the
       pipeline to commit ``data/history.ndjson`` to the
       ``risk-history`` branch.
   * - ``RISK_GROUP_PATH``
     - The full path of your source group, e.g. ``stp`` or
       ``my-org/risks``
     - Optional but **set it unless your group is literally named**
       ``stp`` (the built-in default). Plain variable; not a secret, so
       leave Masked/Protected off.

.. tip::

   "Masked" and "Protected" interact: a Protected variable is only
   available to pipelines running on a
   `protected branch <https://docs.gitlab.com/user/project/protected_branches/>`_.
   If a pipeline fails with ``GITLAB_TOKEN is not set``, the variable is
   Protected but the branch it ran on is not. See Troubleshooting.

Protected branches
------------------

The ``risk-history`` branch is automatically created by the first
pipeline run. It does not need to be protected. The default branch
(``main``) should be
`protected <https://docs.gitlab.com/user/project/protected_branches/>`_;
the pipeline does **not** push to it.

Schedule
--------

Create a
`pipeline schedule <https://docs.gitlab.com/ci/pipelines/schedules/>`_
under Build → Pipeline schedules → New schedule:

- Description: ``Nightly risk snapshot``
- Interval pattern (cron): ``0 2 * * *`` (or your preference)
- Target branch: ``main``
- Activated: on

To test it without waiting until 02:00, save the schedule and click the
▶ (play) button on its row; that runs it immediately as a ``schedule``
pipeline.

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

After the first successful run, find the published URL under
Deploy → Pages (or Settings → Pages on older versions). Open it in a
private/incognito window to confirm anonymous visitors are blocked, and
in a normal window (signed in as a group member) to confirm you can see
the dashboard.

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

``GitLab rejected GITLAB_TOKEN (401 Unauthorized)``
   The variable *is* populated, but GitLab won't accept the token. In
   practice this almost always means the group access token **expired**
   (they have a mandatory expiry date) or was revoked. Create a new
   token with ``read_api`` scope (Reporter role or higher) on the
   source group, paste it into the ``GITLAB_TOKEN`` variable, and retry
   the pipeline. The error message prints the token length the job saw,
   which also catches stray-whitespace paste accidents.

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
