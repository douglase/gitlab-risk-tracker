License
=======

This project is licensed under the **GNU General Public License v3.0
or later (GPL-3.0-or-later)**. See the ``LICENSE`` file in the
repository root for the full text.

You are free to use, modify, and redistribute this software, including
for commercial purposes, provided that derivative works are also
distributed under the GPL-3.0-or-later. See
https://www.gnu.org/licenses/gpl-3.0.en.html for details.

Third-party dependencies
------------------------

.. list-table::
   :header-rows: 1

   * - Package
     - License
   * - ``requests``
     - Apache-2.0
   * - ``Jinja2``
     - BSD-3-Clause
   * - ``markdown``
     - BSD-3-Clause
   * - ``nh3``
     - MIT — HTML sanitizer used on rendered issue-description markdown
   * - ``openpyxl`` (importer only)
     - MIT — reads ``.xlsx`` exports in ``scripts/import_smartsheet.py``;
       not required by the dashboard build (see :doc:`importer`)
   * - ``sphinx`` (docs only)
     - BSD-2-Clause
   * - ``sphinx_rtd_theme`` (docs only)
     - MIT
   * - ``myst-parser`` (docs only)
     - MIT

All runtime dependencies use permissive licenses compatible with
GPL-3.0 distribution.

Example data
------------

Sample risks in ``tests/test_build.py`` are paraphrased from
**NASA Risk Management Handbook (NASA/SP-2011-3422, Rev. A)**,
August 2023:
https://www.nasa.gov/wp-content/uploads/2023/08/nasa-risk-mgmt-handbook.pdf

NASA publications authored by US federal employees in the course of
their duties are in the public domain in the United States.

Enforced license scanning
-------------------------

GPL-3.0 imposes obligations on derivative works, and accidentally
pulling in code under a GPL-incompatible license (or unlabeled code of
unknown provenance) would put downstream users in a difficult position.
To make sure that does not happen quietly, every push and pull request
runs an automated license + copyright scan and fails the build if
anything unexpected is found.

The workflow (``.github/workflows/scancode.yml``):

1. Installs a pinned version of
   `scancode-toolkit <https://github.com/aboutcode-org/scancode-toolkit>`_
   from PyPI.
2. Runs ``scancode --license --copyright --info`` over the working
   tree (excluding build artifacts).
3. Hands the JSON report to ``scripts/check_scancode_allowlist.py``,
   which compares every detected license key against an allowlist and
   exits non-zero on any unrecognized key.

The allowlist is the dictionary at the top of
``scripts/check_scancode_allowlist.py``; to add a new acceptable
license, edit the dictionary with a one-line rationale and the
workflow turns green again.
