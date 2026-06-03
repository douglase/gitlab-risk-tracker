gitlab-risk-tracker
===================

A members-only GitLab Pages dashboard that renders a 5×5
consequence-by-likelihood risk matrix for issues in a GitLab group,
plus per-risk trend charts, a filterable risks table, and a daily
append-only change-event history.

The tool is designed for engineering organizations that already track
risks as GitLab issues with custom fields and want a single read-only
view of "where do we stand right now and how did we get here."

.. toctree::
   :maxdepth: 2
   :caption: Contents

   setup
   gitlab-setup
   usage
   deployment
   contributing
   license

Quick start
-----------

1. Create a GitLab project to host the dashboard (default branch
   protected, Pages enabled with "Only project members" access).
2. Set up custom fields and labels on your source group as described in
   :doc:`gitlab-setup`.
3. Mirror this repository into that project; configure CI/CD variables.
4. Trigger the pipeline manually; verify the dashboard URL.
5. Add a daily schedule (02:00 UTC is the suggested default).

See :doc:`deployment` for the full walk-through.

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
