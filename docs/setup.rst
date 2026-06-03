Local setup
===========

Prerequisites
-------------

- Python 3.12+
- A GitLab personal or group access token with ``read_api`` scope on
  the source group.
- ``git`` installed if you intend to push changes.

Install
-------

.. code-block:: bash

   git clone https://github.com/douglase/gitlab-risk-tracker.git
   cd gitlab-risk-tracker
   pip install -r requirements.txt

Dry run
-------

Set ``GITLAB_TOKEN`` and ``CI_SERVER_URL`` (or ``GITLAB_URL``), then
run ``build.py`` directly. ``build.py`` writes ``public/index.html``
and appends to ``data/history.ndjson`` in your working copy; it does
not commit anything.

.. code-block:: bash

   export GITLAB_TOKEN=<your-token>
   export CI_SERVER_URL=https://gitlab.example.com
   export RISK_GROUP_PATH=stp           # optional, defaults to "stp"
   python build.py
   open public/index.html

Running the tests
-----------------

Tests are self-contained (no GitLab connection required) and assert on
matrix counts, history append semantics, section parsing, and the
generated HTML.

.. code-block:: bash

   python tests/test_build.py
