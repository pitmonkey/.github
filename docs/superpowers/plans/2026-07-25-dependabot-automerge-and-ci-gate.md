# Dependabot Auto-Merge and CI Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Dependabot pull requests from running Docker builds anywhere in the
pitmonkey org, and auto-merge Dependabot dev-tooling updates once CI is green.

**Architecture:** The Docker skip is centralised in this repo's reusable
`build-docker.yml`, so all twelve callers are fixed by one edit. Auto-merge becomes a
reusable workflow here plus a thin caller in each of thirteen repos, replacing five
drifted local copies. A uniform aggregator job named `ci-green` is added to each
repo's CI so a single org ruleset can require one check name everywhere, which is what
gives `gh pr merge --auto` something to wait on.

**Tech Stack:** GitHub Actions reusable workflows, GitHub rulesets REST API,
`dependabot/fetch-metadata@v2`, `gh` CLI, Dependabot `dependabot.yml` v2.

**Spec:** `docs/superpowers/specs/2026-07-25-dependabot-automerge-and-ci-gate-design.md`

## Global Constraints

- The thirteen in-scope repos are: `github-dispatcher`, `nrlfb_social`,
  `toby-assistant`, `nrl-injury-ward`, `nrlfantasy_scraper`, `kubs-log-analysis`,
  `agentic-workflow-hub`, `claude-pr-agent`, `calendar-sync`,
  `google-workspace-multiple-mcp`, `local-claude-marketplace`, `nrl-fantasy-analysis`,
  `nrlteamlist`.
- Never clone another repo into `/home/palee/git/pitmonkey-github-repo`. All clones go
  under the session scratchpad directory.
- Do not use git worktrees.
- No AI attribution trailers in commit messages.
- The required status check context is exactly `ci-green` in every repo.
- `strict_required_status_checks_policy` is `false`.
- Eligible auto-merge conditions are exactly: `dependency-type == 'direct:development'`,
  `package-ecosystem == 'pre_commit'`, `package-ecosystem == 'github_actions'`.
- Guard on `github.event.pull_request.user.login`, never `github.actor`.
- Never add a `pre-commit` Dependabot ecosystem to a repo with no
  `.pre-commit-config.yaml`.
- Phase order is load-bearing: no ruleset change until all thirteen repo pull requests
  are merged.

---

## Reference: per-repo facts

Gathered live on 2026-07-25. Task 6 depends on these.

| Repo | default branch | CI file | `ci-green` needs | uv groups today | `.pre-commit-config.yaml` | local automerge file |
|---|---|---|---|---|---|---|
| github-dispatcher | main | ci.yaml | monorepo list A | uv-dev/uv-prod | no | yes |
| nrlfb_social | main | ci.yml | test, lint, build | uv-dev/uv-prod | yes | yes |
| toby-assistant | master | ci.yml | test, lint, build | uv-dev/uv-prod | yes | yes |
| nrl-injury-ward | main | ci.yml | test, lint, build | uv-dev/uv-prod | yes | yes |
| nrlfantasy_scraper | master | ci.yml | test, lint, build | uv-dev/uv-prod | no | yes (old variant) |
| kubs-log-analysis | master | ci.yml | test, lint, build | uv-all | yes | no |
| agentic-workflow-hub | main | ci.yaml | monorepo list B | uv-all | no | no |
| claude-pr-agent | main | ci.yml | test, lint, build | uv-all | no | no |
| calendar-sync | master | ci.yml | test, lint, build | uv-all | yes | no |
| google-workspace-multiple-mcp | main | ci.yml | test, lint, build | uv-all | no | no |
| local-claude-marketplace | master | ci.yml | test, lint, build | multi-ecosystem-group | yes | no |
| nrl-fantasy-analysis | master | ci.yml | test, lint, build | uv-all | yes | no |
| nrlteamlist | master | ci.yml | test, lint, build | uv-all | no | no |

**Monorepo list A** (`github-dispatcher`): `test-contracts`, `lint-contracts`,
`test-dependabot`, `lint-dependabot`, `build-dependabot`, `test-dispatcher`,
`lint-dispatcher`, `build-dispatcher`, `test-pr-review`, `lint-pr-review`,
`build-pr-review`, `test-issue-worker`, `lint-issue-worker`, `build-issue-worker`,
`test-pr-fixer`, `lint-pr-fixer`, `build-pr-fixer`.

**Monorepo list B** (`agentic-workflow-hub`): `test-contracts`, `lint-contracts`,
`test-hub`, `lint-hub`, `build-hub`, `test-morning-brief`, `lint-morning-brief`,
`build-morning-brief`, `test-nrl-shorts-script`, `lint-nrl-shorts-script`,
`build-nrl-shorts-script`, `test-open-models-maintainer`,
`lint-open-models-maintainer`, `build-open-models-maintainer`.

Repos defaulting to `master` (rename in Task 5): `toby-assistant`,
`nrlfantasy_scraper`, `kubs-log-analysis`, `calendar-sync`, `local-claude-marketplace`,
`nrl-fantasy-analysis`, `nrlteamlist`.

---

## Task 1: Refresh token scope

**Files:** none.

**Interfaces:**
- Consumes: nothing.
- Produces: a `gh` token carrying `admin:org`, required by Tasks 5, 10, and 11.

- [ ] **Step 1: Confirm the scope is currently missing**

Run: `gh api orgs/pitmonkey/rulesets`
Expected: FAIL with `Not Found (HTTP 404)` and a message about the `admin:org` scope.

- [ ] **Step 2: Ask the user to refresh the token**

This is interactive and cannot be run by an agent. Ask the user to run, in the session:

```
! gh auth refresh -h github.com -s admin:org
```

- [ ] **Step 3: Verify the scope now works**

Run: `gh api orgs/pitmonkey/rulesets --jq '.[]|[.id,.name,.target,.enforcement]|@tsv'`
Expected: PASS, listing at least `15082599  global-main-protection  branch  active`.

- [ ] **Step 4: Record what global-main-protection actually targets**

Run: `gh api orgs/pitmonkey/rulesets/15082599 --jq '.conditions'`
Expected: PASS. Note the output. If `repository_name.include` is `["~ALL"]`, the
spec's reasoning for a separate ruleset is confirmed. If it already targets a subset,
re-read it before Task 11 and adjust the new ruleset's conditions to match style.

No commit — this task changes no files.

---

## Task 2: Skip Docker builds on Dependabot pull requests

**Files:**
- Modify: `.github/workflows/build-docker.yml` (jobs `build`, `build-multiplatform`,
  `build-native-matrix`, `merge`)

**Interfaces:**
- Consumes: nothing.
- Produces: build jobs that report `skipped` on Dependabot pull requests. Task 6's
  `ci-green` job relies on `skipped` being a passing state.

- [ ] **Step 1: Add a reusable YAML anchor comment and the guard to the `build` job**

In `.github/workflows/build-docker.yml`, change the `build` job's condition from:

```yaml
  build:
    if: inputs.platforms == ''
```

to:

```yaml
  # A Dependabot pull request never pushes an image (push is already false on
  # pull_request events), so building one only burns time on the self-hosted
  # runners. Key on pull_request.user.login rather than github.actor: on a manual
  # re-run github.actor becomes whoever clicked re-run, which would silently
  # re-enable the build.
  build:
    if: >-
      inputs.platforms == ''
      && !(github.event_name == 'pull_request'
           && github.event.pull_request.user.login == 'dependabot[bot]')
```

- [ ] **Step 2: Add the guard to `build-multiplatform`**

Change:

```yaml
  build-multiplatform:
    if: inputs.platforms != '' && !inputs.native-arm64
```

to:

```yaml
  build-multiplatform:
    if: >-
      inputs.platforms != '' && !inputs.native-arm64
      && !(github.event_name == 'pull_request'
           && github.event.pull_request.user.login == 'dependabot[bot]')
```

- [ ] **Step 3: Add the guard to `build-native-matrix`**

Change:

```yaml
  build-native-matrix:
    if: inputs.platforms != '' && inputs.native-arm64
```

to:

```yaml
  build-native-matrix:
    if: >-
      inputs.platforms != '' && inputs.native-arm64
      && !(github.event_name == 'pull_request'
           && github.event.pull_request.user.login == 'dependabot[bot]')
```

- [ ] **Step 4: Leave the `merge` job alone**

`merge` already carries `github.event_name != 'pull_request'`, so it never runs on any
pull request. Adding the guard there would be dead logic. Confirm the condition still
reads:

```yaml
  merge:
    if: inputs.platforms != '' && inputs.native-arm64 && github.event_name != 'pull_request'
```

- [ ] **Step 5: Verify the file is still valid YAML**

Run:

```bash
python3 -c "import yaml,sys; d=yaml.safe_load(open('.github/workflows/build-docker.yml')); print(sorted(d['jobs']))"
```

Expected: PASS, printing
`['build', 'build-multiplatform', 'build-native-matrix', 'merge']`.

- [ ] **Step 6: Verify each guard is present exactly once**

Run:

```bash
grep -c "dependabot\[bot\]" .github/workflows/build-docker.yml
```

Expected: `3`.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/build-docker.yml
git commit -m "ci(build-docker): skip builds on Dependabot pull requests

Docker builds already push nothing on pull_request events, so building a
Dependabot bump only consumes self-hosted runner time. Guard on
pull_request.user.login rather than github.actor, which becomes the
re-running user on a manual re-run.

Refs #99"
```

---

## Task 3: Add the reusable auto-merge workflow

**Files:**
- Create: `.github/workflows/dependabot-automerge.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: reusable workflow `pitmonkey/.github/.github/workflows/dependabot-automerge.yml@main`,
  called with no inputs and no secrets. Task 6's caller depends on this exact path.

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/dependabot-automerge.yml`:

```yaml
name: Reusable - Dependabot auto-merge

# Enables GitHub's native auto-merge on Dependabot pull requests that only touch
# dev tooling. `--auto` holds the merge until the branch's required status checks
# pass, which across this org is the single `ci-green` context. Runtime/production
# dependencies do not match the filter and fall through untouched.
#
# SECURITY: callers invoke this from `pull_request_target`, which runs with write
# permissions against the base repo. This workflow must never check out or execute
# pull request code. Do not add a checkout step.

on:
  workflow_call:

jobs:
  dev-tooling-automerge:
    runs-on: ubuntu-latest
    if: github.event.pull_request.user.login == 'dependabot[bot]'
    steps:
      - name: Fetch Dependabot metadata
        id: meta
        uses: dependabot/fetch-metadata@v2

      # dependency-type resolves to the most-privileged type in the pull request,
      # so a grouped PR only reads as development when every member is a dev dep.
      # Dependabot has no dev/prod concept for pre-commit or github-actions and
      # reports both as direct:production, hence the explicit ecosystem clauses.
      - name: Enable auto-merge for dev-tooling updates
        if: >-
          steps.meta.outputs.dependency-type == 'direct:development' ||
          steps.meta.outputs.package-ecosystem == 'pre_commit' ||
          steps.meta.outputs.package-ecosystem == 'github_actions'
        run: gh pr merge --auto --squash "${{ github.event.pull_request.html_url }}"
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 2: Verify it parses and declares no required inputs**

Run:

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('.github/workflows/dependabot-automerge.yml'))
wc = d[True]['workflow_call']
assert wc is None or not wc.get('inputs'), wc
assert 'checkout' not in open('.github/workflows/dependabot-automerge.yml').read()
print('ok', sorted(d['jobs']))
"
```

Expected: PASS, printing `ok ['dev-tooling-automerge']`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/dependabot-automerge.yml
git commit -m "feat(dependabot): add reusable dev-tooling auto-merge workflow

Five repos carried drifted local copies of this logic; one was missing the
pre_commit clause entirely. Centralising it here makes future drift
impossible and adds github_actions to the eligible set.

Refs #99"
```

---

## Task 4: Document both workflows and open the phase-1 pull request

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces: `main` of this repo carrying both changes, which every caller in Task 6
  references via `@main`.

- [ ] **Step 1: Read the README to find the workflow list and table conventions**

Run: `grep -n "build-docker\|^## \|^### " README.md`

- [ ] **Step 2: Add a `dependabot-automerge.yml` section to README.md**

Match the surrounding heading level and table style. The section must state:

- Purpose: enables native auto-merge on Dependabot dev-tooling pull requests.
- No inputs, no secrets required.
- Caller must use `on: pull_request_target` and set
  `permissions: {contents: write, pull-requests: write}` at workflow level, because a
  reusable workflow's permissions are capped by the caller's grant.
- Eligible: `direct:development` dependencies, the `pre_commit` ecosystem, the
  `github_actions` ecosystem. Docker base images and production dependencies are not.
- Requires `ci-green` to be a required status check on the default branch, otherwise
  `--auto` has nothing to wait on and merges immediately.
- The caller snippet:

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

- [ ] **Step 3: Note the Dependabot skip in the `build-docker.yml` README section**

Add one line to that section: build jobs are skipped automatically on pull requests
opened by `dependabot[bot]`; callers do not need their own guard.

- [ ] **Step 4: Add `dependabot-automerge.yml` to the repo layout block in CLAUDE.md**

The block currently lists five workflows. Add:

```
  dependabot-automerge.yml   # Auto-merge Dependabot dev-tooling PRs on green
```

Note that `build-claude-worker-base.yml` is also missing from that block; add it in
the same edit:

```
  build-claude-worker-base.yml  # Build+push the claude-worker-base image
```

- [ ] **Step 5: Verify no stale claim survives in the docs**

Run: `grep -rn "dependabot" README.md CLAUDE.md`
Expected: hits describe the new workflow and the build skip; nothing claims callers
must add their own `github.actor` guard.

- [ ] **Step 6: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document dependabot-automerge and the build-docker Dependabot skip"
```

- [ ] **Step 7: Push and open the pull request**

```bash
git push -u origin feat/dependabot-automerge-ci-gate
gh pr create --fill --base main
```

- [ ] **Step 8: Merge it**

```bash
gh pr merge --squash --delete-branch
git checkout main && git pull
```

Expected: `main` now contains `dependabot-automerge.yml` and the guarded
`build-docker.yml`.

- [ ] **Step 9: Verify the reusable workflow is resolvable at `@main`**

Run:

```bash
gh api repos/pitmonkey/.github/contents/.github/workflows/dependabot-automerge.yml?ref=main --jq '.name'
```

Expected: `dependabot-automerge.yml`.

---

## Task 5: Rename `master` to `main` on seven repos

**Files:** none locally — this is a GitHub API operation.

**Interfaces:**
- Consumes: Task 1's `admin:org` token.
- Produces: all thirteen in-scope repos default to `main`, so Task 6 and Task 11 can
  assume that branch name.

- [ ] **Step 1: Record the current state so the change is verifiable**

```bash
for r in toby-assistant nrlfantasy_scraper kubs-log-analysis calendar-sync \
         local-claude-marketplace nrl-fantasy-analysis nrlteamlist; do
  printf "%-26s %s\n" "$r" "$(gh api repos/pitmonkey/$r --jq .default_branch)"
done
```

Expected: seven lines, all `master`.

- [ ] **Step 2: Rename each**

```bash
for r in toby-assistant nrlfantasy_scraper kubs-log-analysis calendar-sync \
         local-claude-marketplace nrl-fantasy-analysis nrlteamlist; do
  echo "== $r"
  gh api -X POST "repos/pitmonkey/$r/branches/master/rename" -f new_name=main --jq '.name'
done
```

Expected: seven lines reading `main`.

GitHub retargets the 19 open pull requests across these repos automatically and moves
branch protection rules. It does not update workflow `branches:` filters — Task 6 does
that.

- [ ] **Step 3: Verify**

```bash
for r in toby-assistant nrlfantasy_scraper kubs-log-analysis calendar-sync \
         local-claude-marketplace nrl-fantasy-analysis nrlteamlist; do
  printf "%-26s default=%s openPRs=%s\n" "$r" \
    "$(gh api repos/pitmonkey/$r --jq .default_branch)" \
    "$(gh pr list -R pitmonkey/$r --state open --json baseRefName --jq '[.[]|select(.baseRefName=="main")]|length')"
done
```

Expected: every line `default=main`, and the open-pull-request count matching the
pre-rename count for that repo (`toby-assistant` 5, `nrlfantasy_scraper` 4,
`kubs-log-analysis` 2, `calendar-sync` 2, `local-claude-marketplace` 0,
`nrl-fantasy-analysis` 4, `nrlteamlist` 2).

- [ ] **Step 4: Tell the user to re-point any local clones**

For each renamed repo they have cloned locally:

```bash
git branch -m master main
git fetch origin
git branch -u origin/main main
git remote set-head origin -a
```

---

## Task 6: Roll out `ci-green`, the auto-merge caller, and normalised Dependabot config

**Files (per repo, thirteen times):**
- Modify: `.github/workflows/ci.yml` or `.github/workflows/ci.yaml`
- Create or replace: `.github/workflows/dependabot-automerge.yml`
- Modify: `.github/dependabot.yml`

**Interfaces:**
- Consumes: Task 3's reusable workflow at `@main`; Task 5's renamed branches.
- Produces: a check run named exactly `ci-green` on every pull request in all thirteen
  repos. Task 11's ruleset requires that exact string.

Work one repo at a time. Do not batch — a broken `ci.yml` in one repo is easy to spot
and revert on its own.

- [ ] **Step 1: Set up the scratchpad working directory**

```bash
WORK="$(mktemp -d /tmp/pitmonkey-rollout-XXXXXX)"
echo "$WORK"
```

Never clone into `/home/palee/git/pitmonkey-github-repo`.

- [ ] **Step 2: For each repo, clone and branch**

```bash
REPO=nrlfb_social   # substitute each of the thirteen in turn
git clone "https://github.com/pitmonkey/$REPO.git" "$WORK/$REPO"
cd "$WORK/$REPO"
git checkout -b ci/dependabot-automerge-and-ci-gate
```

- [ ] **Step 3: Add the `ci-green` job to the CI workflow**

For the eleven flat repos, append this job to `.github/workflows/ci.yml`:

```yaml
  # Single uniform required status check for the whole org. Job names differ per
  # repo (and a path-filtered job that is skipped emits no check run at all), so a
  # ruleset cannot require them directly. This job always runs, so it always
  # reports. `notify` is excluded deliberately: a Slack delivery failure must not
  # block a merge.
  ci-green:
    needs: [test, lint, build]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Fail if any upstream job failed or was cancelled
        if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')
        run: exit 1
```

For `github-dispatcher`, append to `.github/workflows/ci.yaml` with the same comment
and body but this `needs:` list:

```yaml
    needs: [test-contracts, lint-contracts,
            test-dependabot, lint-dependabot, build-dependabot,
            test-dispatcher, lint-dispatcher, build-dispatcher,
            test-pr-review, lint-pr-review, build-pr-review,
            test-issue-worker, lint-issue-worker, build-issue-worker,
            test-pr-fixer, lint-pr-fixer, build-pr-fixer]
```

For `agentic-workflow-hub`, append to `.github/workflows/ci.yaml` with this `needs:`
list:

```yaml
    needs: [test-contracts, lint-contracts,
            test-hub, lint-hub, build-hub,
            test-morning-brief, lint-morning-brief, build-morning-brief,
            test-nrl-shorts-script, lint-nrl-shorts-script, build-nrl-shorts-script,
            test-open-models-maintainer, lint-open-models-maintainer,
            build-open-models-maintainer]
```

- [ ] **Step 4: For the seven renamed repos only, fix the push filter**

In `toby-assistant`, `nrlfantasy_scraper`, `kubs-log-analysis`, `calendar-sync`,
`local-claude-marketplace`, `nrl-fantasy-analysis`, `nrlteamlist`, change:

```yaml
  push:
    branches: [master]
```

to:

```yaml
  push:
    branches: [main]
```

Then grep that repo for other `master` references and update any that refer to this
repo's own branch:

```bash
grep -rn "master" --include="*.md" --include="*.yml" --include="*.yaml" . | grep -v node_modules
```

`calendar-sync/docs/deployment.md` is known to contain one.

- [ ] **Step 5: Write the auto-merge caller**

Overwrite `.github/workflows/dependabot-automerge.yml` (create it where absent —
eight repos have none, five have a local copy to replace):

```yaml
name: dependabot-automerge

# Thin caller. All logic lives in the org reusable workflow so it cannot drift.
# Permissions must be granted here: a reusable workflow's permissions are capped
# by the caller's grant.

on: pull_request_target

permissions:
  contents: write
  pull-requests: write

jobs:
  automerge:
    uses: pitmonkey/.github/.github/workflows/dependabot-automerge.yml@main
```

- [ ] **Step 6: Normalise `.github/dependabot.yml`**

Only the `uv` ecosystem's groups change. Leave `directory:`/`directories:`,
`versioning-strategy`, `cooldown`, and `open-pull-requests-limit` exactly as they are.
Never add a `pre-commit` ecosystem — the seven repos that need one already have it,
and the other six have no `.pre-commit-config.yaml`.

Repos already correct, needing **no** `dependabot.yml` change: `github-dispatcher`,
`nrlfb_social`, `toby-assistant`, `nrl-injury-ward`, `nrlfantasy_scraper`.

For the seven repos whose `uv` ecosystem has a single `uv-all` group
(`kubs-log-analysis`, `agentic-workflow-hub`, `claude-pr-agent`, `calendar-sync`,
`google-workspace-multiple-mcp`, `nrl-fantasy-analysis`, `nrlteamlist`), replace that
group block:

```yaml
    groups:
      uv-all:
        patterns:
          - "*"
        update-types:
          - major
          - minor
          - patch
```

with:

```yaml
    # Split dev from prod: fetch-metadata reports the most-privileged type across
    # the whole PR, so a mixed group always reads as direct:production and never
    # qualifies for auto-merge.
    groups:
      uv-dev:
        dependency-type: development
        patterns:
          - "*"
      uv-prod:
        dependency-type: production
        patterns:
          - "*"
```

For `local-claude-marketplace` only, replace the entire file. Its
`multi-ecosystem-groups: weekly-deps` config puts every ecosystem into one pull
request, which can never read as dev-only:

```yaml
version: 2
updates:
  - package-ecosystem: uv
    directory: /
    schedule:
      interval: weekly
      day: monday
    groups:
      uv-dev:
        dependency-type: development
        patterns:
          - "*"
      uv-prod:
        dependency-type: production
        patterns:
          - "*"
    open-pull-requests-limit: 10

  - package-ecosystem: docker
    directory: /
    schedule:
      interval: weekly
      day: monday
    groups:
      docker-all:
        patterns:
          - "*"
        update-types:
          - major
          - minor
          - patch
    open-pull-requests-limit: 10

  - package-ecosystem: pre-commit
    directory: /
    schedule:
      interval: weekly
      day: monday
    groups:
      pre-commit-all:
        patterns:
          - "*"
        update-types:
          - major
          - minor
          - patch
    open-pull-requests-limit: 10

  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
      day: monday
    groups:
      actions-all:
        patterns:
          - "*"
        update-types:
          - major
          - minor
          - patch
    open-pull-requests-limit: 10
```

- [ ] **Step 7: Verify the edits before pushing**

```bash
python3 - <<'PY'
import glob, sys, yaml
ci = glob.glob('.github/workflows/ci.y*ml')[0]
d = yaml.safe_load(open(ci))
jobs = d['jobs']
assert 'ci-green' in jobs, 'ci-green job missing'
g = jobs['ci-green']
assert g['if'] == 'always()', g.get('if')
missing = [n for n in g['needs'] if n not in jobs]
assert not missing, f'ci-green needs unknown jobs: {missing}'
assert 'notify' not in g['needs'], 'notify must not gate the merge'
am = yaml.safe_load(open('.github/workflows/dependabot-automerge.yml'))
assert list(am[True]) == ['pull_request_target'], am[True]
assert am['permissions'] == {'contents': 'write', 'pull-requests': 'write'}
assert am['jobs']['automerge']['uses'].startswith('pitmonkey/.github/')
db = yaml.safe_load(open('.github/dependabot.yml'))
for u in db['updates']:
    if u['package-ecosystem'] == 'uv':
        assert set(u['groups']) == {'uv-dev', 'uv-prod'}, u['groups']
print('ok', ci, len(g['needs']), 'needs')
PY
```

Expected: PASS. For the two monorepos the `needs` count is 17 and 14 respectively; for
flat repos it is 3.

- [ ] **Step 8: Confirm no `master` reference remains in the seven renamed repos**

```bash
grep -rn "branches: \[master\]" .github/ || echo "clean"
```

Expected: `clean`.

- [ ] **Step 9: Commit and open the pull request**

```bash
git add .github/
git commit -m "ci: add ci-green gate and org dependabot auto-merge caller

ci-green is one aggregator job with an identical name in every repo, so a
single org ruleset can require one check context. Path-filtered jobs that
are skipped emit no check run, which is why their names cannot be required
directly; ci-green always runs and treats skipped as passing.

The auto-merge workflow moves to the org reusable workflow so the five
drifted local copies cannot diverge again.

Refs #99"
git push -u origin ci/dependabot-automerge-and-ci-gate
gh pr create --fill --base main
```

Adjust the commit body per repo: drop the auto-merge paragraph for the eight repos
that had no local copy, and mention the `master`-to-`main` push-filter change and the
`uv-dev`/`uv-prod` split where they apply.

- [ ] **Step 10: Confirm `ci-green` actually reports on that pull request**

```bash
gh pr checks --watch
```

Expected: a check named `ci-green` appears and concludes. Its result may be a failure
if the repo's CI is already red — that is information, not a blocker for this task, but
note it. What matters is that the check *reports*.

- [ ] **Step 11: Merge**

```bash
gh pr merge --squash --delete-branch
```

- [ ] **Step 12: Repeat Steps 2 to 11 for the remaining repos**

Track completion explicitly:

- [ ] github-dispatcher
- [ ] nrlfb_social
- [ ] toby-assistant
- [ ] nrl-injury-ward
- [ ] nrlfantasy_scraper
- [ ] kubs-log-analysis
- [ ] agentic-workflow-hub
- [ ] claude-pr-agent
- [ ] calendar-sync
- [ ] google-workspace-multiple-mcp
- [ ] local-claude-marketplace
- [ ] nrl-fantasy-analysis
- [ ] nrlteamlist

---

## Task 7: Confirm every repo emits `ci-green` before touching rulesets

**Files:** none.

**Interfaces:**
- Consumes: Task 6.
- Produces: the go/no-go signal for Task 11. Requiring `ci-green` before this passes
  would permanently block every open pull request in any repo still missing it.

- [ ] **Step 1: Check the merged default branch of all thirteen**

```bash
for r in github-dispatcher nrlfb_social toby-assistant nrl-injury-ward \
         nrlfantasy_scraper kubs-log-analysis agentic-workflow-hub claude-pr-agent \
         calendar-sync google-workspace-multiple-mcp local-claude-marketplace \
         nrl-fantasy-analysis nrlteamlist; do
  f=$(gh api "repos/pitmonkey/$r/contents/.github/workflows" --jq \
      '[.[].name]|map(select(test("^ci\\.ya?ml$")))[0]')
  has_gate=$(gh api "repos/pitmonkey/$r/contents/.github/workflows/$f" --jq .content \
             | base64 -d | grep -c '^  ci-green:')
  has_am=$(gh api "repos/pitmonkey/$r/contents/.github/workflows/dependabot-automerge.yml" \
           --jq .content 2>/dev/null | base64 -d | grep -c 'pitmonkey/.github/')
  printf "%-30s ci-green=%s automerge-caller=%s\n" "$r" "$has_gate" "$has_am"
done
```

Expected: thirteen lines, every one `ci-green=1 automerge-caller=1`.

- [ ] **Step 2: Stop if any line disagrees**

Any repo showing `0` must go back through Task 6 before Task 11 runs. Do not proceed
on a partial result.

---

## Task 8: Create the `ci-green-required` org ruleset

**Files:** none locally. Creates `/tmp/...`-scoped JSON payload in the scratchpad.

**Interfaces:**
- Consumes: Task 1's `admin:org` scope; Task 7's all-green confirmation.
- Produces: `ci-green` enforced as a required status check on the default branch of
  the thirteen repos, which is what `gh pr merge --auto` waits on.

- [ ] **Step 1: Write the ruleset payload**

`$WORK` may not be set if this task runs in a different shell from Task 6:

```bash
WORK="${WORK:-$(mktemp -d /tmp/pitmonkey-rollout-XXXXXX)}"
cat > "$WORK/ci-green-ruleset.json" <<'JSON'
{
  "name": "ci-green-required",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] },
    "repository_name": {
      "include": [
        "github-dispatcher", "nrlfb_social", "toby-assistant", "nrl-injury-ward",
        "nrlfantasy_scraper", "kubs-log-analysis", "agentic-workflow-hub",
        "claude-pr-agent", "calendar-sync", "google-workspace-multiple-mcp",
        "local-claude-marketplace", "nrl-fantasy-analysis", "nrlteamlist"
      ],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "do_not_enforce_on_create": false,
        "required_status_checks": [ { "context": "ci-green" } ]
      }
    }
  ]
}
JSON
python3 -c "import json;print(json.load(open('$WORK/ci-green-ruleset.json'))['name'])"
```

Expected: `ci-green-required`.

`strict_required_status_checks_policy` is `false` on purpose: strict mode forces
Dependabot to rebase every open pull request after each merge, which is precisely the
churn this work removes.

- [ ] **Step 2: Create it**

```bash
gh api -X POST orgs/pitmonkey/rulesets --input "$WORK/ci-green-ruleset.json" \
  --jq '[.id,.name,.enforcement]|@tsv'
```

Expected: one line, e.g. `12345678  ci-green-required  active`. Record the id.

- [ ] **Step 3: Verify it lands on an in-scope repo**

```bash
gh api repos/pitmonkey/nrlfb_social/rules/branches/main \
  --jq '[.[]|select(.type=="required_status_checks")]'
```

Expected: one rule whose `parameters.required_status_checks` contains
`{"context": "ci-green"}`.

- [ ] **Step 4: Verify it does NOT land on an out-of-scope repo**

```bash
gh api repos/pitmonkey/second-brain/rules/branches/main \
  --jq '[.[]|select(.type=="required_status_checks")]|length'
```

Expected: `0`. A non-zero result means the repository condition is wrong and every
pull request in ~30 CI-less repos is now blocked — delete the ruleset immediately with
`gh api -X DELETE orgs/pitmonkey/rulesets/<id>` and fix the conditions.

---

## Task 9: Remove the redundant classic branch protection

**Files:** none.

**Interfaces:**
- Consumes: Task 8.
- Produces: the new ruleset as the only source of required checks, so the old
  `test / test` and `lint / lint` contexts stop applying underneath it.

- [ ] **Step 1: Record what is there now**

```bash
for r in nrlfb_social nrl-injury-ward; do
  printf "%-20s %s\n" "$r" \
    "$(gh api repos/pitmonkey/$r/branches/main/protection --jq '.required_status_checks.contexts|join(",")')"
done
```

Expected: both lines `test / test,lint / lint`.

- [ ] **Step 2: Delete the classic protection**

```bash
for r in nrlfb_social nrl-injury-ward; do
  gh api -X DELETE "repos/pitmonkey/$r/branches/main/protection" && echo "$r deleted"
done
```

- [ ] **Step 3: Verify the ruleset still applies**

```bash
for r in nrlfb_social nrl-injury-ward; do
  echo "== $r"
  gh api repos/pitmonkey/$r/branches/main/protection --jq '.required_status_checks.contexts' 2>&1 | head -1
  gh api repos/pitmonkey/$r/rules/branches/main --jq '[.[].type]|join(",")'
done
```

Expected: the protection call returns `Branch not protected (HTTP 404)`, and the rules
call still lists `required_status_checks` alongside the `global-main-protection` rule
types.

---

## Task 10: End-to-end verification

**Files:** none.

**Interfaces:**
- Consumes: every prior task.
- Produces: the evidence the spec requires before this work is called done.

- [ ] **Step 1: Confirm the required check is live in all thirteen**

```bash
for r in github-dispatcher nrlfb_social toby-assistant nrl-injury-ward \
         nrlfantasy_scraper kubs-log-analysis agentic-workflow-hub claude-pr-agent \
         calendar-sync google-workspace-multiple-mcp local-claude-marketplace \
         nrl-fantasy-analysis nrlteamlist; do
  printf "%-30s %s\n" "$r" \
    "$(gh api "repos/pitmonkey/$r/rules/branches/main" \
       --jq '[.[]|select(.type=="required_status_checks")
              |.parameters.required_status_checks[].context]|join(",")')"
done
```

Expected: thirteen lines, every one `ci-green`.

- [ ] **Step 2: Confirm builds are skipped on a Dependabot pull request**

Find an open Dependabot pull request in a repo that builds images:

```bash
gh pr list -R pitmonkey/github-dispatcher --author "app/dependabot" \
  --json number,title,headRefName
```

Pick one, then:

```bash
gh pr checks <number> -R pitmonkey/github-dispatcher
```

Expected: every `build-*` check is absent or `skipped`; `ci-green` reports.

If no Dependabot pull request is open, close and reopen one, or wait for the Monday
schedule. Do not fabricate a pull request from a non-Dependabot account — the guard
keys on the author and would not trigger.

- [ ] **Step 3: Confirm builds still run on a normal pull request**

Open a trivial pull request in `github-dispatcher` touching one component, then:

```bash
gh pr checks <number> -R pitmonkey/github-dispatcher
```

Expected: the matching `build-*` check runs. Close the pull request afterwards.

- [ ] **Step 4: Confirm a real dev-tooling pull request auto-merges**

For an open Dependabot pull request in the `uv-dev`, `pre-commit-all`, or
`actions-all` group:

```bash
gh pr view <number> -R pitmonkey/<repo> --json autoMergeRequest,state,mergedAt
```

Expected: `autoMergeRequest` is non-null while checks run, then `state` becomes
`MERGED` with no human action.

- [ ] **Step 5: Confirm a production pull request does NOT auto-merge**

For an open Dependabot pull request in the `uv-prod` or `docker-all` group:

```bash
gh pr view <number> -R pitmonkey/<repo> --json autoMergeRequest,state
```

Expected: `autoMergeRequest` is `null` and `state` is `OPEN`.

- [ ] **Step 6: Record the results in the spec**

Append a short "Verification results" section to
`docs/superpowers/specs/2026-07-25-dependabot-automerge-and-ci-gate-design.md` with the
actual pull request numbers and outcomes observed. State plainly if any check could not
be run yet — for example if no `uv-prod` pull request was open to test Step 5.

- [ ] **Step 7: Commit**

```bash
cd /home/palee/git/pitmonkey-github-repo
git checkout -b docs/dependabot-rollout-verification
git add docs/superpowers/specs/2026-07-25-dependabot-automerge-and-ci-gate-design.md
git commit -m "docs: record verification results for the dependabot rollout"
git push -u origin docs/dependabot-rollout-verification
gh pr create --fill --base main && gh pr merge --squash --delete-branch
```

---

## Task 11: Clean up the leftover remote branch

**Files:** none.

**Interfaces:**
- Consumes: nothing.
- Produces: nothing downstream. Independent cleanup carried over from the previous
  session.

- [ ] **Step 1: Confirm it still exists**

```bash
gh api repos/pitmonkey/github-dispatcher/branches/claude/dependabot-checker-behavior-ig1946 \
  --jq '.name' 2>&1 | head -1
```

Expected: either the branch name, or `Branch not found (HTTP 404)` — in which case
this task is already done, so skip the rest.

- [ ] **Step 2: Confirm nothing depends on it**

```bash
gh pr list -R pitmonkey/github-dispatcher --state all \
  --head claude/dependabot-checker-behavior-ig1946 --json number,state
```

Expected: no open pull request. If one is open, ask the user before deleting.

- [ ] **Step 3: Delete it**

```bash
gh api -X DELETE repos/pitmonkey/github-dispatcher/git/refs/heads/claude/dependabot-checker-behavior-ig1946
```

- [ ] **Step 4: Verify**

```bash
gh api repos/pitmonkey/github-dispatcher/branches/claude/dependabot-checker-behavior-ig1946 2>&1 | head -1
```

Expected: `Branch not found (HTTP 404)`.

---

## Rollback

Each phase reverses independently:

- **Task 8** — `gh api -X DELETE orgs/pitmonkey/rulesets/<id>`. Do this first if
  pull requests start hanging; it is the only change that can block merges.
- **Task 9** — recreate classic protection via
  `PUT repos/pitmonkey/<repo>/branches/main/protection`, though the ruleset makes it
  redundant.
- **Task 6** — revert the per-repo squash merge with
  `gh pr create` off a `git revert <sha>` branch.
- **Tasks 2 to 4** — revert the squash merge on this repo. All twelve callers pick the
  revert up immediately, since they reference `@main`.
- **Task 5** — rename back with
  `POST repos/pitmonkey/<repo>/branches/main/rename -f new_name=master`.
