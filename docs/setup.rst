Local setup
===========

This page covers running ``build.py`` on your own machine to preview
the dashboard. To run it as an automated GitLab pipeline instead, see
:doc:`deployment`.

Prerequisites
-------------

- Python 3.12+
- A GitLab access token with ``read_api`` scope that can read the
  source group's issues. A
  `personal access token <https://docs.gitlab.com/user/profile/personal_access_tokens/>`_
  is easiest for local use; a
  `group access token <https://docs.gitlab.com/user/group/settings/group_access_tokens/>`_
  is better for the pipeline.
- ``git`` installed if you intend to push changes.

Install
-------

.. code-block:: bash

   git clone https://github.com/douglase/gitlab-risk-tracker.git
   cd gitlab-risk-tracker
   python -m venv .venv && source .venv/bin/activate   # recommended
   pip install -r requirements.txt

Dry run
-------

Set the environment variables below, then run ``build.py`` directly.
It writes ``public/index.html`` and appends to ``data/history.ndjson``
in your working copy; it does **not** commit or push anything.

.. code-block:: bash

   export GITLAB_TOKEN=<your-token>
   export CI_SERVER_URL=https://gitlab.example.com   # your GitLab host
   export RISK_GROUP_PATH=stp                         # change to your group
   python build.py
   xdg-open public/index.html        # or: open public/index.html (macOS)

The examples throughout this documentation use ``stp`` as the group
name. **Wherever you see** ``stp``\ **, substitute the full path of your
own group** (e.g. ``platform/security`` or ``my-org/risks``).

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Variable
     - Meaning
   * - ``GITLAB_TOKEN``
     - Access token with ``read_api`` scope. **Required.**
   * - ``CI_SERVER_URL``
     - Base URL of your GitLab instance, e.g.
       ``https://gitlab.example.com``. (Inside a GitLab pipeline this is
       set automatically; you only set it for local runs. ``GITLAB_URL``
       is accepted as an alias.)
   * - ``RISK_GROUP_PATH``
     - Full path of the group to scan, e.g. ``stp`` or
       ``my-org/risks``. Defaults to ``stp`` if unset, so set it unless
       your group really is named ``stp``.

Running the tests
-----------------

Tests are self-contained (no GitLab connection required) and assert on
matrix counts, history append semantics, section parsing, and the
generated HTML.

.. code-block:: bash

   python tests/test_build.py
