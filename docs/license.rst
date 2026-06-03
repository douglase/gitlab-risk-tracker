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

A GitHub Actions workflow (`.github/workflows/scancode.yml`) runs
`aboutcode-org/scancode-action` on every push and pull request, then
runs ``scripts/check_scancode_allowlist.py`` which fails the build
if any detected license key is outside the project's allowlist.
The allowlist is the dictionary at the top of that script; to add a
new acceptable license, edit the dictionary with a one-line rationale.
