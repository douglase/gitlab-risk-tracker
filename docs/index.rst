gitlab-risk-tracker
===================

A members-only GitLab Pages dashboard that renders a 5×5
consequence-by-likelihood risk matrix for issues in a GitLab group,
plus per-risk trend charts, a filterable risks table, and a daily
append-only change-event history.

The tool is designed for engineering organizations that already track
risks as GitLab issues with custom fields and want a single read-only
view of "where do we stand right now and how did we get here."

.. note::

   The examples in this documentation use a group named ``stp`` and a
   dashboard project named ``stp/risks-dashboard``. These are just
   placeholders — **wherever you see** ``stp``\ **, substitute your own
   group path** (for example ``platform/security``). The group to scan
   is controlled by the ``RISK_GROUP_PATH`` setting; see
   :doc:`deployment`.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   preview
   setup
   gitlab-setup
   usage
   importer
   deployment
   contributing
   license

Quick start
-----------

1. Create a GitLab project to host the dashboard (default branch
   protected, `Pages <https://docs.gitlab.com/user/project/pages/>`_
   enabled with "Only project members" access).
2. Set up custom fields and labels on your source group as described in
   :doc:`gitlab-setup`.
3. Copy this repository into that project (see :doc:`deployment`);
   configure CI/CD variables.
4. Trigger the pipeline manually; verify the dashboard URL.
5. Add a daily schedule (02:00 UTC is the suggested default).

See :doc:`deployment` for the full walk-through.

What you need before starting
-----------------------------

This tool relies on several GitLab features. Confirm you have them:

- **A GitLab group whose issues you want to track.** Custom fields are
  a paid-tier feature; see
  `custom fields <https://docs.gitlab.com/user/work_items/custom_fields/>`_
  for current availability.
- **At least one CI/CD runner** available to the dashboard project, with
  outbound HTTPS so it can ``pip install`` dependencies. See
  `GitLab Runner <https://docs.gitlab.com/ci/runners/>`_. Shared
  ("instance") runners are the simplest option if your administrator
  has enabled them.
- **GitLab Pages enabled on your instance.** See
  `GitLab Pages <https://docs.gitlab.com/user/project/pages/>`_.

.. note::

   The documentation links here point to ``docs.gitlab.com`` (GitLab
   SaaS). If you run a self-managed instance, the version-matched copy
   of every page is available on your own server at
   ``https://YOUR-GITLAB-HOST/help`` — prefer that if a feature looks
   different from the screenshots in the public docs.

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
