# gitlab-risk-tracker

[![License: GPL v3+](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Tests](https://github.com/douglase/gitlab-risk-tracker/actions/workflows/test.yml/badge.svg)](https://github.com/douglase/gitlab-risk-tracker/actions/workflows/test.yml)
[![Docs](https://img.shields.io/badge/docs-github%20pages-blue)](https://douglase.github.io/gitlab-risk-tracker/)
[![License scan](https://github.com/douglase/gitlab-risk-tracker/actions/workflows/scancode.yml/badge.svg)](https://github.com/douglase/gitlab-risk-tracker/actions/workflows/scancode.yml)

Pages dashboard for risks in the `stp` group.

Pulls all work-item issues from `stp` (recursive) via GraphQL, snapshots
changed custom-field values to `data/history.ndjson` once per day, and
renders a 5×5 consequence × likelihood matrix at the published Pages URL.

Works against **GitLab** (default) or **GitHub**. Set
`RISK_PROVIDER=github` to read risks from GitHub organization *issue
fields* — the analogue of GitLab work-item custom fields, pinned to a
`Risk` issue type — instead of a GitLab group. See
[docs/github-setup.rst](docs/github-setup.rst). Everything downstream of
the fetch (history, trends, matrix, MSR decks) is provider-agnostic.

## What it shows

- 5×5 risk matrix (Consequence × Likelihood) with current open issues per cell
- Filters: subsystem, priority, risk type
- Click any cell for the full issue list
- 90-day trend chart (issues by severity tier)
- 30-day movement summary (escalated / de-escalated / new / closed)
- Subsystem label-occurrence breakdown
- Pre-generated "Top 5 risks" MSR slide decks per product (PPTX + print-ready PDF)

## Inputs (locked to this group)

- Group: `stp` (override via `RISK_GROUP_PATH` env var)
- Custom fields:
  - `Consequence (C)` — single-select, 1–5
  - `Likelihood (L)` — single-select, 1–5
  - `Priority Level` — single-select High / Medium / Low
  - `Risk Type` — multi-select Technical / Cost / Schedule
- Subsystem labels (plain): `optics`, `thermal`, `software`, `mechanical`,
  `electrical` — edit the `SUBSYSTEMS` list in `build.py` to change.

On GitHub the same four values come from organization **issue fields**
pinned to a `Risk` issue type: `Consequence` and `Likelihood` as Number,
`Priority Level` as single-select, `Risk Type` as multi-select — only
`Risk Type` is multi-valued. Field names
are matched case-insensitively and ignoring a trailing `(C)`-style suffix,
so the defaults above match fields named plainly `Consequence` /
`Likelihood`.

## Setup (GitLab)

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

## Setup (GitHub Actions)

Runs `.github/workflows/dashboard.yml`. Full walk-through in
[docs/github-setup.rst](docs/github-setup.rst).

1. **Create the repository** (e.g. `<org>/risks-dashboard`) and push this
   directory's contents to its default branch.
2. **Define the issue type and fields.** Org Settings → Planning → Issue
   types → add `Risk`. Then Issue fields → add `Consequence` (Number),
   `Likelihood` (Number), `Priority Level` (single select),
   `Risk Type` (multi select), and pin each to the `Risk` type.
3. **Create a PAT** that can read the org's issues — classic with `repo`,
   or fine-grained with *Issues: Read-only*. Add it as repository secret
   `RISK_TOKEN`. A run's built-in `GITHUB_TOKEN` is scoped to its own
   repository and cannot read issues org-wide, so the PAT is required.
4. **Repository variables** (Settings → Secrets and variables → Actions →
   Variables): `RISK_GITHUB_ISSUE_TYPE=Risk`; `RISK_GITHUB_OWNER` if the
   issues live under a different org than the repo; `PUBLISH_PAGES=true`
   to enable the Pages deploy.
5. **Pages.** Settings → Pages → Source: **GitHub Actions**. Note there is
   no equivalent of GitLab's "Only project members" access control on
   github.com — public-repo Pages is world-readable and private-repo Pages
   needs Enterprise Cloud, so keep the repo private or consume the run
   artifact instead.
6. **Schedule.** Already declared in the workflow (`cron: '0 2 * * *'`);
   there is no separate schedule object to create. No branch protection or
   push-token step either — the history snapshot goes to the orphan
   `risk-history` branch with the built-in `GITHUB_TOKEN`, and that branch
   is not a workflow trigger, so no `ci.skip` equivalent is needed.
7. **Trigger the first run** manually (Actions → *Risk dashboard* → Run
   workflow) to seed `risk-history` and publish the initial dashboard.

## Local dry run

Pulls live data but does not commit. `data/history.ndjson` is
created/appended in your working copy.

### GitLab

```bash
export GITLAB_TOKEN=<your token>
export CI_SERVER_URL=https://gitlab.example.com   # your instance URL
pip install -r requirements.txt
python build.py
open public/index.html
```

### GitHub

```bash
export RISK_PROVIDER=github
export GITHUB_TOKEN=<PAT with read access to the org issues>
export RISK_GITHUB_OWNER=<org>
export RISK_GITHUB_ISSUE_TYPE=Risk
pip install -r requirements.txt
python build.py
open public/index.html
```

Watch stderr: the startup probe prints the issue-search query, how many
issues it matched, and the issue-field names found on the first match —
the quickest way to confirm the scan is pointed at the right place.

## Files

- `build.py` — GraphQL fetch (GitLab or GitHub), change-event snapshot, HTML render
- `templates/index.html.j2` — dashboard layout (self-contained HTML/CSS/JS)
- `.gitlab-ci.yml` — GitLab `pages` job, runs on schedule + web triggers
- `.github/workflows/dashboard.yml` — the GitHub Actions equivalent
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
- **GitHub search cap.** The GitHub provider enumerates risks with issue
  search, which limits how deeply results can be paginated. `build.py`
  compares what it retrieved against the reported `issueCount` and warns
  loudly on a shortfall — narrow the scan with `RISK_GITHUB_ISSUE_TYPE` or
  `RISK_GITHUB_SEARCH` if you see it.
- **Blank column on GitHub?** The startup probe prints what each
  configured field name matched; `NOT FOUND` means that column will be
  empty for every risk. If the name *did* match and the column is still
  blank, run `RISK_DEBUG_FIELDS=1 python build.py 2>probe.log` to dump the
  raw values with each field's `dataType`. Note also that an *undefined*
  Actions repository variable interpolates to an empty string, not to
  nothing — `build.py` treats a blank name as unset and `dashboard.yml`
  supplies `|| 'default'`, so keep both if you add more `RISK_FIELD_*`
  wiring.
- **Single- vs multi-select.** `Risk Type` is the only multi-valued
  field. `Consequence`, `Likelihood` and `Priority Level` must be Number /
  Number / single-select; a multi-select declaration is tolerated (first
  option wins, with a warning) but is a misconfiguration.
- **Dormant GitHub schedules.** GitHub disables scheduled workflows in
  repositories with no activity for 60 days, and pushes made with the
  run's own `GITHUB_TOKEN` generally don't reset that clock. If the nightly
  dashboard stops updating, re-enable the workflow in the Actions tab.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE) for the full text.

Copyright (C) 2026 Ewan Douglas and contributors.
largely written with claude code opus 4.7.
Docs: <https://douglase.github.io/gitlab-risk-tracker/> (built via
GitHub Actions; see [`.github/workflows/docs.yml`](.github/workflows/docs.yml)).
