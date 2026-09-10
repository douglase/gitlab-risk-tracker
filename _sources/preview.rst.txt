Example dashboard
=================

The example below is the actual dashboard HTML produced by
``tests/test_build.py`` against the synthetic NASA-Handbook–style
fixture. It is interactive — try the filters, click cells, sort
columns, and open the modal — and updates each time the test suite
runs against the latest ``build.py`` and ``templates/index.html.j2``.

The example is for preview only:

- All issue links point at ``https://gitlab.example.com/...`` URLs
  that do not exist.
- The "Refresh this dashboard" button at the bottom would, in a
  real deployment, link to your GitLab project's pipeline schedules
  page.

.. raw:: html

   <p style="margin: .5rem 0 1rem;">
     <a class="reference external"
        href="_static/example_dashboard.html"
        target="_blank" rel="noopener">
       ↗ Open the example in its own tab
     </a>
   </p>
   <iframe src="_static/example_dashboard.html"
           title="Example gitlab-risk-tracker dashboard"
           style="width: 100%; height: 80vh; border: 1px solid #ddd; border-radius: 4px;"
           loading="lazy">
   </iframe>

Where the fixture data comes from
---------------------------------

Sample risks #1 and #2 paraphrase examples from the NASA Risk
Management Handbook (NASA/SP-2011-3422, Rev. A, 2023):
https://www.nasa.gov/wp-content/uploads/2023/08/nasa-risk-mgmt-handbook.pdf

The remaining items are synthetic variations to populate the matrix
across all severity tiers and exercise the per-risk score chart,
filters, history-replay, and section-rendering code paths. See
``tests/test_build.py`` for the full fixture.

Regenerating the preview
------------------------

The Sphinx site bundles whatever ``docs/_static/example_dashboard.html``
contains at build time. To refresh it locally:

.. code-block:: bash

   pip install -r requirements.txt
   python tests/test_build.py
   # writes docs/_static/example_dashboard.html alongside public/index.html

Commit the updated file to land the new preview on the next docs
publish.