GitLab project setup
====================

The dashboard reads from work-item issues across a GitLab group
(recursively). To make your issues compatible with the dashboard,
configure the following on your **source** group (the group that owns
the risks), not on the dashboard project itself.

The term "source group" means the GitLab group whose issues are your
risks. The "dashboard project" (set up in :doc:`deployment`) is a
separate project that only holds this tool's code and publishes the
rendered page.

Custom fields
-------------

Create these custom fields on the source group, under
**Settings → Issues → Custom fields**. Field names must match exactly.

See GitLab's
`custom fields documentation <https://docs.gitlab.com/user/work_items/custom_fields/>`_
for how to create them and which subscription tier is required.

.. list-table::
   :header-rows: 1
   :widths: 25 15 30 30

   * - Field name
     - Type
     - Allowed values
     - Used for
   * - ``Consequence (C)``
     - Single select
     - ``1``, ``2``, ``3``, ``4``, ``5``
     - Matrix Y axis
   * - ``Likelihood (L)``
     - Single select
     - ``1``, ``2``, ``3``, ``4``, ``5``
     - Matrix X axis
   * - ``Priority Level``
     - Single select
     - ``High``, ``Medium``, ``Low``
     - Filter chip
   * - ``Risk Type``
     - Multi select
     - ``Technical``, ``Cost``, ``Schedule``
     - Filter + table column

Labels
------

Create these labels at the **group** level so they propagate to all
subprojects (see
`labels <https://docs.gitlab.com/user/project/labels/>`_).
The dashboard categorizes labels into three groups:

**Subsystems** (plain labels). Edit ``SUBSYSTEMS`` in ``build.py`` if
your subsystem set differs:

- ``optics``
- ``thermal``
- ``software``
- ``mechanical``
- ``electrical``

**Products** (anything matching the regex patterns ``^TO\d``, ``^ESC``,
``^WCC`` becomes a Product filter option in the dashboard). Edit
``PRODUCT_PATTERNS`` in ``build.py`` to change the rules.

Examples:

- ``TO6- WCC Pre-SRR``
- ``TO12- Planet X EDL``
- ``ESC033``
- ``WCC100``

**Other labels**: anything else attached to a risk issue shows under
the "Other labels" column in the table.

Issue description template
---------------------------

The dashboard pulls structured content from sections of the issue
description body. Create a
`description template <https://docs.gitlab.com/user/project/description_templates/>`_
(e.g. ``.gitlab/issue_templates/Risk.md`` in your source project) with
the following canonical headings:

.. code-block:: markdown

   ## Risk Description

   Given that [CONDITION], there is a possibility of [DEPARTURE]
   adversely impacting [ASSET], thereby resulting in [CONSEQUENCE].

   ## Notes

   - Action items, status notes, links to related work.

   ## Mitigation Plan

   What we will do if the risk materializes, including schedule and
   cost impact estimates.

Accepted heading synonyms (case-insensitive, trailing colon optional):

.. list-table::
   :header-rows: 1

   * - Canonical column
     - Heading text accepted
   * - Risk Description
     - ``Risk Description``, ``Description``, ``Summary``
   * - Notes
     - ``Notes``
   * - Mitigation Plan
     - ``Mitigation Plan``, ``Plan``, ``Planning``, ``Mitigation``,
       ``Risk Mitigation``, ``Risk Mitigation Planning``

Title convention
----------------

The dashboard strips a leading ``Risk# <ID>`` prefix from issue titles
before display (case-insensitive). Example titles that are recognized:

- ``Risk# 1A Planetary contamination from aerocapture breakup``
- ``Risk#WCC100 Coating delamination``
- ``RISK# ESC046 — ARB 350 thermal limit``

If your numbering scheme differs, edit ``RISK_PREFIX_RE`` in
``build.py``.

Health status (optional)
-------------------------

GitLab's built-in
`health status <https://docs.gitlab.com/user/project/issues/managing_issues/>`_
field is read into a hidden "Health" column (toggle on via the Columns
dropdown). Values map to:

- ``onTrack`` → green "On track"
- ``needsAttention`` → amber "Needs attention"
- ``atRisk`` → red "At risk"
