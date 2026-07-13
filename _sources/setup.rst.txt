Local setup
===========

This page covers running ``build.py`` on your own machine to preview
the dashboard. To run it as an automated GitLab pipeline instead, see
:doc:`deployment`.

Prerequisites
-------------

- Python 3.10 or newer (continuous integration runs on 3.12).
- A GitLab access token with ``read_api`` scope that can read the
  source group's issues. A
  `personal access token <https://docs.gitlab.com/user/profile/personal_access_tokens/>`_
  is easiest for local use; a
  `group access token <https://docs.gitlab.com/user/group/settings/group_access_tokens/>`_
  is better for the pipeline.
- ``git`` installed if you intend to push changes.

Install
-------

A dedicated environment is recommended. Using
`conda <https://docs.conda.io/>`_ (or the faster, drop-in
`mamba <https://mamba.readthedocs.io/>`_ — swap ``conda`` for ``mamba``
in any command below):

.. code-block:: bash

   git clone https://github.com/douglase/gitlab-risk-tracker.git
   cd gitlab-risk-tracker
   conda create -n risk-tracker python=3.12
   conda activate risk-tracker
   pip install -r requirements.txt

The runtime dependencies are pure-Python wheels, so ``pip`` inside the
conda environment is the simplest way to install them. If you prefer to
pull everything from conda-forge instead, the equivalent is
``conda install -c conda-forge requests jinja2 markdown nh3``.

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
   * - ``RISK_LABEL_FILTER``
     - Substring (case-insensitive) that must appear in at least one of
       an issue's labels for it to be included on the dashboard.
       Defaults to ``"risk"`` so general bug-reports / feature-requests
       living alongside your risks don't clutter the matrix. Set to the
       empty string to disable the filter and include every work item.

Running the tests
-----------------

Tests are self-contained (no GitLab connection required) and assert on
matrix counts, history append semantics, section parsing, and the
generated HTML.

.. code-block:: bash

   python tests/test_build.py            # dashboard build pipeline
   python tests/test_import_smartsheet.py  # spreadsheet importer

Both run under ``pytest`` as well (``pytest tests/``) if you prefer.
