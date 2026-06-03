Contributing
============

Bug reports, feature requests, and pull requests welcome.

Workflow
--------

1. Open an issue describing the change.
2. Branch from ``main``; make the change locally.
3. Run the test suite: ``python tests/test_build.py``.
4. Push a branch and open a pull request.

Coding conventions
------------------

- Python: prefer standard library; minimize new dependencies.
- Vanilla JS in the template (no framework, no CDN).
- All changes should keep the dashboard self-contained — no external
  network requests at runtime in the published HTML.
- New columns in the risks table should be added to ``COLUMNS`` in
  the template and have their data populated in
  ``risks_table_json`` in ``build.py``.

Tests
-----

The test suite mocks the GitLab GraphQL responses, exercises the full
``main()`` pipeline, and asserts on the rendered HTML, history append
semantics, and section parsing. Sample risks are based on examples
from the NASA Risk Management Handbook (NASA/SP-2011-3422, Rev. A).

Adding a heading synonym
^^^^^^^^^^^^^^^^^^^^^^^^

Edit ``CANONICAL_SECTIONS`` in ``build.py``; add an entry to the
relevant tuple's synonym list. Add a test case in
``test_parse_sections``.

Adding a new section column
^^^^^^^^^^^^^^^^^^^^^^^^^^^

1. Add an entry to ``CANONICAL_SECTIONS`` with a fresh ``key``.
2. The Jinja template renders all sections via ``SECTION_META``
   automatically; no template edits needed.
3. Update ``docs/gitlab-setup.rst`` with the new accepted heading.
