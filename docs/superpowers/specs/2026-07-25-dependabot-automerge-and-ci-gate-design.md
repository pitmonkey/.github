# Dependabot dev-tooling auto-merge + uniform CI gate

Date: 2026-07-25
Status: approved, not yet implemented

## Goals

1. Dependabot pull requests must not run Docker builds anywhere in the org.
2. Dependabot pull requests that only touch dev tooling must merge themselves once
   CI is green, without human review.

Goal 2 exists to cut the volume of low-value pull requests and to reduce the number
of pull requests the dispatcher's review path has to process.

## In-scope repos

The thirteen repos that have a `.github/dependabot.yml`:

`github-dispatcher`, `nrlfb_social`, `toby-assistant`, `nrl-injury-ward`,
`nrlfantasy_scraper`, `kubs-log-analysis`, `agentic-workflow-hub`, `claude-pr-agent`,
`calendar-sync`, `google-workspace-multiple-mcp`, `local-claude-marketplace`,
`nrl-fantasy-analysis`, `nrlteamlist`.

## Verified current state

Checked live against the GitHub API on 2026-07-25. This supersedes an earlier
handoff document, which was wrong in two material ways (noted inline).

### Docker builds

- The reusable `build-docker.yml` in this repo already sets `push: false` on
  `pull_request` events. A Dependabot pull request therefore burns build time on the
  self-hosted runners but pushes nothing.
- Twelve repos call `build-docker.yml`.
- The `github.actor != 'dependabot[bot]'` guard exists in some callers
  (`nrlfb_social`) and not others (`github-dispatcher`). Drifted, not absent —
  the handoff claimed no guard existed anywhere.

### Auto-merge

- Five repos carry a local `dependabot-automerge.yml`. Four are identical; the copy
  in `nrlfantasy_scraper` is older and lacks the `pre_commit` clause.
- `allow_auto_merge` is `true` on all thirteen repos that have a `dependabot.yml`.
- The org ruleset `global-main-protection` (id `15082599`, active, applies to every
  repo) contains rules for `deletion`, `non_fast_forward`, `pull_request`
  (0 required approvals), `workflows`, and `required_linear_history`. It contains
  **no** `required_status_checks` rule.
- Only `nrlfb_social` and `nrl-injury-ward` require status checks, and they do it
  through *classic* branch protection with the contexts `test / test` and
  `lint / lint`.

The consequence is the central finding, and the handoff missed it: in eleven of
thirteen repos `gh pr merge --auto` has no required check to wait on, so it merges as
soon as the pull request is mergeable. Auto-merge is not gated on tests today.

### Branch naming

Seven repos default to `master`: `toby-assistant`, `nrlfantasy_scraper`,
`kubs-log-analysis`, `calendar-sync`, `local-claude-marketplace`,
`nrl-fantasy-analysis`, `nrlteamlist`. Each one's `ci.yml` correctly filters
`branches: [master]`, so nothing is broken — it is cosmetic drift.

The org already sets `default_repository_branch: main`, so new repos are unaffected.
`k3s-infra` Flux manifests reference only `k3s-infra`'s own `main`; no Flux
`GitRepository` points at any of the seven. Those seven have 19 open pull requests
between them, which GitHub retargets automatically on rename.

### CI job shapes

Two shapes exist across the thirteen in-scope repos:

- **Flat** (eleven repos): jobs `test`, `lint`, `build`, `notify`.
- **Monorepo** (`github-dispatcher`, `agentic-workflow-hub`): a `changes` job running
  `dorny/paths-filter`, then per-component `test-<c>` / `lint-<c>` / `build-<c>` jobs,
  each conditional on its path filter.

## Design

### 1. Skip Docker builds on Dependabot pull requests

Add a guard to each of the four jobs in this repo's `.github/workflows/build-docker.yml`,
appended to that job's existing `if:`:

```yaml
&& !(github.event_name == 'pull_request'
     && github.event.pull_request.user.login == 'dependabot[bot]')
```

Key on `github.event.pull_request.user.login`, not `github.actor`. On a manual re-run
`github.actor` becomes the person who clicked re-run, which would silently re-enable
the build.

Centralising the guard here fixes all twelve callers at once and prevents the drift
that already occurred. Job-level `if:` is evaluated before runner allocation, so a
skipped build costs nothing. Existing per-caller guards become redundant but harmless
and are left in place.

When every job in the reusable workflow is skipped, the calling job reports
`skipped`. Callers that pass `needs.build.result` to `notify-slack.yml` receive the
string `skipped`, which that workflow already handles.

### 2. A uniform required check named `ci-green`

Org rulesets match required status checks by name, and the repos do not agree on
names: flat repos emit `test / test`, `github-dispatcher` emits `test-contracts / test`,
`test-dependabot / test`, and so on. Worse, a path-filtered job that is skipped emits
**no check run at all**, so a required check naming it stays pending forever and the
pull request can never merge.

Each in-scope repo therefore gets one aggregator job with a name that is identical
everywhere:

```yaml
  ci-green:
    needs: [test, lint, build]   # every gating job in that repo
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Fail if any upstream job failed or was cancelled
        if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')
        run: exit 1
```

`skipped` and `success` both pass; `failure` and `cancelled` fail. The job itself is
unconditional, so it always produces a check run.

`needs:` contents per repo shape:

- Flat repos: `[test, lint, build]`. `notify` is excluded — a Slack delivery failure
  must not block a merge.
- `github-dispatcher`: all of `test-contracts`, `lint-contracts`, `test-dependabot`,
  `lint-dependabot`, `build-dependabot`, `test-dispatcher`, `lint-dispatcher`,
  `build-dispatcher`, `test-pr-review`, `lint-pr-review`, `build-pr-review`,
  `test-issue-worker`, `lint-issue-worker`, `build-issue-worker`, `test-pr-fixer`,
  `lint-pr-fixer`, `build-pr-fixer`.
- `agentic-workflow-hub`: all of `test-contracts`, `lint-contracts`, `test-hub`,
  `lint-hub`, `build-hub`, `test-morning-brief`, `lint-morning-brief`,
  `build-morning-brief`, `test-nrl-shorts-script`, `lint-nrl-shorts-script`,
  `build-nrl-shorts-script`, `test-open-models-maintainer`,
  `lint-open-models-maintainer`, `build-open-models-maintainer`.

Including `build-*` jobs is correct: on a Dependabot pull request they are skipped and
the gate passes; on a normal pull request a genuine build failure blocks the merge.

The org ruleset `global-main-protection` then gains one `required_status_checks` rule
with the single context `ci-green`, `strict_required_status_checks_policy: false`.
Strict is off deliberately — requiring the branch to be current forces Dependabot to
rebase every open pull request on each merge, which is exactly the churn this work is
meant to remove. It can be enabled later if merge-order safety becomes a concern.

The classic branch protection on `nrlfb_social` and `nrl-injury-ward` is deleted so
the ruleset is the only source of truth. Left in place, their `test / test` and
`lint / lint` requirements would still apply underneath the ruleset.

### 3. Auto-merge as a reusable workflow

A new `.github/workflows/dependabot-automerge.yml` in this repo, called by a thin
caller in each of the thirteen repos. This removes the `nrlfantasy_scraper` drift and
makes future drift impossible.

Reusable workflow:

```yaml
name: Reusable - Dependabot auto-merge

on:
  workflow_call:

jobs:
  dev-tooling-automerge:
    runs-on: ubuntu-latest
    if: github.event.pull_request.user.login == 'dependabot[bot]'
    steps:
      - id: meta
        uses: dependabot/fetch-metadata@v2

      - name: Enable auto-merge for dev-tooling updates
        if: >-
          steps.meta.outputs.dependency-type == 'direct:development' ||
          steps.meta.outputs.package-ecosystem == 'pre_commit' ||
          steps.meta.outputs.package-ecosystem == 'github_actions'
        run: gh pr merge --auto --squash "${{ github.event.pull_request.html_url }}"
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Caller, identical in all thirteen repos:

```yaml
name: dependabot-automerge

on: pull_request_target

permissions:
  contents: write
  pull-requests: write

jobs:
  automerge:
    uses: pitmonkey/.github/.github/workflows/dependabot-automerge.yml@main
```

Permissions are declared in the caller because a reusable workflow's permissions are
capped by the caller's grant.

Eligible ecosystems, as chosen: development-type dependencies, `pre_commit`, and
`github_actions`. Dependabot has no dev/prod concept for `pre_commit` or
`github_actions` and reports both as `direct:production`, so each needs its own
clause. Docker base images are deliberately excluded — they ship to production.

`dependency-type` resolves to the most-privileged type in the pull request, so a
grouped pull request only reads as `direct:development` when every member is a
development dependency.

### 4. Normalise `dependabot.yml`

Because `dependency-type` resolves to the most-privileged member, a group that mixes
development and production dependencies reads as production and never auto-merges.
Without a dev/prod split, section 3 fires far less often than expected.

Every in-scope repo's `.github/dependabot.yml` is normalised to:

- a `uv` ecosystem with `uv-dev` (`dependency-type: development`) and `uv-prod`
  (`dependency-type: production`) groups,
- a `pre-commit` ecosystem with a single `pre-commit-all` group,
- a `github-actions` ecosystem with a single `actions-all` group,
- a `docker` ecosystem with a single `docker-all` group,
- `schedule: weekly` on Monday, `cooldown.default-days: 7`.

Directory layout stays per-repo: monorepos keep their `directories:` lists,
flat repos keep `directory: /`.

### 5. Rename `master` to `main` on seven repos

Performed with `POST /repos/{owner}/{repo}/branches/master/rename`, which retargets
open pull requests and moves protection rules. Each repo's `ci.yml` push filter
changes from `branches: [master]` to `branches: [main]` in the same rollout pull
request as sections 2–4. Documentation references (for example
`calendar-sync/docs/deployment.md`) are updated in that pull request too.

Local clones are re-pointed by hand:
`git branch -m master main && git fetch origin && git branch -u origin/main main`.

## Rollout order

Order matters. Adding the required check before every repo has the `ci-green` job
would block every open pull request in the repos that lack it.

- **Phase 0** — refresh token scope: `gh auth refresh -h github.com -s admin:org`.
  Required to read and modify org rulesets.
- **Phase 1** — this repo: `build-docker.yml` guard, new reusable
  `dependabot-automerge.yml`, `README.md` documentation for the new workflow and its
  inputs. Merge before anything downstream.
- **Phase 2** — rename `master` to `main` on the seven repos.
- **Phase 3** — one pull request per repo across all thirteen: add `ci-green`,
  replace any local `dependabot-automerge.yml` with the thin caller, normalise
  `dependabot.yml`, and for the renamed seven switch the push filter to `main`.
  All thirteen must be merged before phase 4.
- **Phase 4** — add the `required_status_checks` rule (`ci-green`, non-strict) to the
  org ruleset; delete classic branch protection on `nrlfb_social` and
  `nrl-injury-ward`.
- **Phase 5** — verification, below.

## Verification

Evidence required before this is called done:

1. On a Dependabot pull request in `github-dispatcher`, every `build-*` job reports
   `skipped` and `ci-green` reports success.
2. On a normal pull request in the same repo, `build-*` runs as before.
3. `gh api repos/pitmonkey/<repo>/rules/branches/<default>` lists a
   `required_status_checks` rule containing `ci-green`, for all thirteen repos.
4. At least one real Dependabot dev-tooling pull request reaches merged state with no
   human interaction, and its timeline shows auto-merge waiting on `ci-green`.
5. A Dependabot pull request in the `uv-prod` or `docker-all` group stays open.

## Known consequences

- A merge enabled with `GITHUB_TOKEN` does not trigger `push`-event workflows, so an
  auto-merged bump does not rebuild or push images. This is acceptable for the three
  eligible ecosystems, none of which change a runtime image's contents. It would not
  be acceptable if `docker` or `uv-prod` were ever added to the eligible set — that
  change would require swapping to a PAT.
- `pull_request_target` runs the workflow from the default branch with write
  permissions. The auto-merge workflow never checks out or executes pull request code,
  which is what makes this safe. Any future step added to it must preserve that.
- The `ci-green` gate treats `skipped` as passing. A path filter that wrongly excludes
  a component therefore yields a green gate. This is the same trade-off the existing
  path-filtered CI already makes.

## Out of scope

- The in-repo dispatcher and worker tiering half of issue #99.
- The leftover remote branch `claude/dependabot-checker-behavior-ig1946` in
  `github-dispatcher`, which should be deleted separately.
- Repos with no `dependabot.yml`, and the archived `mysideline-sync` and `dribl-sync`.
