# gitlab-risk-tracker

[![License: GPL v3+](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Tests](https://github.com/douglase/gitlab-risk-tracker/actions/workflows/test.yml/badge.svg)](https://github.com/douglase/gitlab-risk-tracker/actions/workflows/test.yml)
[![Docs](https://img.shields.io/badge/docs-github%20pages-blue)](https://douglase.github.io/gitlab-risk-tracker/)
[![License scan](https://github.com/douglase/gitlab-risk-tracker/actions/workflows/scancode.yml/badge.svg)](https://github.com/douglase/gitlab-risk-tracker/actions/workflows/scancode.yml)

GitLab Pages dashboard for risks in the `stp` group.

Pulls all work-item issues from `stp` (recursive) via GraphQL, snapshots
changed custom-field values to `data/history.ndjson` once per day, and
renders a 5×5 consequence × likelihood matrix at the published Pages URL.

## What it shows

- 5×5 risk matrix (Consequence × Likelihood) with current open issues per cell
- Filters: subsystem, priority, risk type
- Click any cell for the full issue list
- 90-day trend chart (issues by severity tier)
- 30-day movement summary (escalated / de-escalated / new / closed)
- Subsystem label-occurrence breakdown

## Inputs (locked to this group)

- Group: `stp` (override via `RISK_GROUP_PATH` env var)
- Custom fields:
  - `Consequence (C)` — single-select, 1–5
  - `Likelihood (L)` — single-select, 1–5
  - `Priority Level` — single-select High / Medium / Low
  - `Risk Type` — multi-select Technical / Cost / Schedule
- Subsystem labels (plain): `optics`, `thermal`, `software`, `mechanical`,
  `electrical` — edit the `SUBSYSTEMS` list in `build.py` to change.

## Setup

1. **Create the project** `stp/risks-dashboard` on the GitLab instance.
   Push this directory's contents to its default branch.
2. **Create a group access token** on `stp` with scope `read_api`. Add as
   masked, protected CI/CD variable `GITLAB_TOKEN` on the project.
3. **Create a project access token** on `risks-dashboard` with scope
   `write_repository` and role **Maintainer**. Add as masked, protected
   CI/CD variable `PUSH_TOKEN`.
4. **Branch protection.** Default branch must allow Maintainers to push
   (Settings → Repository → Protected branches). The pipeline pushes
   the daily snapshot back with `-o ci.skip` to avoid re-triggering.
5. **Pages access control.** Settings → Pages → set Access Control to
   "Only project members".
6. **Pipeline schedule.** Build → Pipeline schedules → New schedule.
   Cron `0 2 * * *` (daily, 02:00 UTC), target the default branch.
7. **Trigger the first run** manually (Pipelines → Run pipeline) to seed
   `data/history.ndjson` and publish the initial dashboard.

## Local dry run

```bash
export GITLAB_TOKEN=<your token>
export CI_SERVER_URL=https://gitlab.example.com   # your instance URL
pip install -r requirements.txt
python build.py
open public/index.html
```

This pulls live data but does not commit. `data/history.ndjson` will be
created/appended in your working copy.

## Files

- `build.py` — GraphQL fetch, change-event snapshot, HTML render
- `templates/index.html.j2` — dashboard layout (self-contained HTML/CSS/JS)
- `.gitlab-ci.yml` — `pages` job, runs on schedule + web triggers
- `data/history.ndjson` — append-only change log (committed each run)
- `public/index.html` — generated artifact published by Pages

## Pitfalls / future work

- **Pipeline loop.** Snapshot commit uses `[skip ci]` + `-o ci.skip` to
  prevent re-triggering. If you change the CI config, keep that.
- **Closed risks.** Captured via "vanished from query" detection — when
  an issue stops appearing, a synthetic `state=closed` row is appended.
- **Multi-subsystem issues.** Counted under each subsystem they label.
  The breakdown bar reports *label occurrences*, not unique issues.
- **Air-gapped runners.** The job needs outbound HTTPS for `pip
  install`. Switch to a pre-baked image or internal PyPI mirror if your
  runner is restricted.
- **Epics.** Not included in v1 (`types: [ISSUE]` only).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE) for the full text.

Copyright (C) 2026 Ewan Douglas and contributors.

Docs: <https://douglase.github.io/gitlab-risk-tracker/> (built via
GitHub Actions; see [`.github/workflows/docs.yml`](.github/workflows/docs.yml)).
