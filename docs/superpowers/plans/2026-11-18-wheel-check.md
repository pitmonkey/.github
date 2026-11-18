# Wheel Check on Dependabot Base-Image PRs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fail a Dependabot `dependabot/docker/*` PR in seconds when a locked runtime dependency has no wheel for the new Python version on amd64 or arm64, before the Docker build runs.

**Architecture:** New reusable workflow `check-wheels.yml` in `pitmonkey/.github`, called as job `wheels` from `build-docker.yml`; build jobs wait on it but are not skipped when it is skipped. Logic is inline shell in workflow steps (a called workflow runs in the caller's checkout, so scripts in `pitmonkey/.github` are not on disk). Then one caller opt-out (agentic-workflow-hub) and four caller fixes.

**Tech Stack:** GitHub Actions reusable workflows, bash, uv (`uv export`, `uv pip compile --no-build --python-platform`), Python `unittest` + PyYAML tests in the existing `tests/` style.

**Spec:** `docs/superpowers/specs/2026-11-18-wheel-check-design.md`.

## Global Constraints

- uv action pin: `astral-sh/setup-uv@v10.3.3` (matches the repo's other workflows).
- Platforms default: `x86_64-manylinux_2_28,aarch64-manylinux_2_28`.
- Runner for `check-wheels.yml`: `pi-arm64`.
- `wheel-check` input on `build-docker.yml`: boolean, default `true`.
- `wheels` job runs only when `inputs.wheel-check && github.event_name == 'pull_request' && github.event.pull_request.user.login == 'dependabot[bot]' && startsWith(github.head_ref, 'dependabot/docker/')`.
- Build jobs keep their existing condition, ANDed with `!cancelled() && needs.wheels.result != 'failure'`.
- No secrets in `check-wheels.yml`. Git and editable requirement lines are dropped before compile.
- Every repo's own `CLAUDE.md`/`AGENTS.md` governs its PR.
- Tests run with: `uv run --with pyyaml python -m unittest discover -s tests -v`.

## Review Focus

1. `FROM --platform=$BUILDPLATFORM python:3.14-slim AS deps` — the `--platform` flag must not break parsing; version is `3.14`.
2. Tags `python:3.15`, `python:3.15.1-slim-trixie`, `python:3.15-slim@sha256:…` all yield `3.15`.
3. A lock with a private git dependency (`ops-ui @ git+https://…`) passes the check with no token (line dropped).
4. Build context in a subdirectory (`hub/`) with `hub/uv.lock` — lock found relative to `build-context`.
5. Non-Python final stage (research-kb: `FROM nginxinc/nginx-unprivileged`, Python only in an earlier stage) — use the last `FROM python:` line anywhere in the file, not the last `FROM` line; skip only when no `FROM python:` exists.

---

### Task 1: `check-wheels.yml` reusable workflow

**Repo:** `pitmonkey/.github` (local clone `~/git/.github`, branch `feat/check-wheels` off fresh `main`).

**Files:**

- Create: `.github/workflows/check-wheels.yml`
- Create: `tests/test_check_wheels.py`
- Create: `docs/superpowers/specs/2026-11-18-wheel-check-design.md`, `docs/superpowers/plans/2026-11-18-wheel-check.md` (the design and this plan)

**Interfaces:**

- Produces: `on: workflow_call` with inputs `dockerfile` (string, default `Dockerfile`), `build-context` (string, default `.`), `platforms` (string, default per Global Constraints). Job `check`. Steps named exactly `Detect Python version` (sets outputs `version`, `skip`), `Check wheels` (runs when `skip != 'true'`). Writes failing package + platform to `$GITHUB_STEP_SUMMARY`.

- [ ] **Step 1: Write failing tests** in `tests/test_check_wheels.py`, reusing the `run_step`/`substitute` helpers pattern from `tests/test_dependabot_uv_relock.py` (copy, do not import across test files). Tests, each writing a temp `Dockerfile`/`uv.lock` and running the step:
  - `test_version_from_last_python_from` — stages `python:3.14-slim AS deps` then `python:3.15-slim` → `version=3.15`, `skip=false`.
  - `test_version_with_platform_flag_and_digest` — `FROM --platform=$BUILDPLATFORM python:3.15.1-slim-trixie@sha256:abc AS b` → `3.15`.
  - `test_python_build_stage_nginx_runtime` — `python:3.12-slim AS build` then `FROM nginxinc/nginx-unprivileged:stable-alpine` → `3.12`.
  - `test_skip_non_python` — only `FROM node:22` → `skip=true`, notice contains `no python base image`.
  - `test_skip_templated_tag` — `FROM python:${PY}-slim` → `skip=true`.
  - `test_skip_no_lock` — Python Dockerfile, no `uv.lock` in `build-context` → `skip=true`, notice contains `no uv.lock`.
  - `test_lock_in_subdir_context` — `build-context=hub`, `hub/uv.lock` present → `skip=false`.
  - `test_check_drops_git_and_editable_lines` — stub `uv` on `path_prefix` whose `export` prints `httpx==0.28.1`, `ops-ui @ git+https://github.com/pitmonkey/ops-ui@abc`, `-e ./contracts`; stub `pip compile` records stdin → recorded stdin is exactly `httpx==0.28.1`.
  - `test_check_runs_each_platform` — stub records `--python-platform` args → both default platforms, each with `--no-build --python-version 3.15`.
  - `test_check_fails_and_summarises` — stub `pip compile` exits 1 on `aarch64-manylinux_2_28` printing `httptools==0.8.0` → step exits non-zero; summary file contains `aarch64-manylinux_2_28` and `httptools`.
  - `test_workflow_has_no_secrets` — parsed YAML has no `secrets` key under `on.workflow_call` and no `secrets.` reference anywhere.

- [ ] **Step 2: Run tests, verify they fail** — `uv run --with pyyaml python -m unittest tests.test_check_wheels -v` → errors, workflow file missing.

- [ ] **Step 3: Implement `.github/workflows/check-wheels.yml`.** Job `check` on `pi-arm64`, `permissions: contents: read`, steps: `actions/checkout` (same pin as `build-docker.yml`), `Detect Python version`, `astral-sh/setup-uv@v10.3.3` (only when not skipped), `Check wheels`. Version regex over lines matching `^FROM\s+(--\S+\s+)*python:`: capture `^\d+\.\d+` from the tag; last match wins. Check step: `uv export --frozen --no-dev --no-hashes --no-emit-project` in `build-context` (captured on its own so a failed export fails the step), `grep -vE '(^-e |@ git\+|^git\+)'`, then loop platforms (comma-split) running `uv pip compile - --no-build --python-version "$version" --python-platform "$p" -q` (no `-o`: uv writes output files atomically beside the target, and `/dev` is not writable); collect failures, append to summary, exit 1 if any.

- [ ] **Step 4: Run tests, verify pass** — same command → all OK. Then whole suite: `uv run --with pyyaml python -m unittest discover -s tests -v` → all OK.

- [ ] **Step 5: Real-world check** of the `Check wheels` command against local clones of the PR heads (`clones/nrlfb_social` expect FAIL httptools both platforms; `clones/nrlteamlist` expect PASS; `clones/kubs-log-analysis` expect FAIL and no git error for `ops-ui`).

- [ ] **Step 6: Commit** — `feat: add check-wheels reusable workflow` (plus spec/plan docs).

### Task 2: Wire `wheels` into `build-docker.yml`

**Repo:** `pitmonkey/.github`, same branch.

**Files:**

- Modify: `.github/workflows/build-docker.yml` (inputs block; jobs `build` L67, `build-multiplatform` L157, `build-native-matrix` L235; `merge` untouched — it already needs `build-native-matrix`)
- Modify: `README.md` (build-docker inputs table; new `check-wheels.yml` section), `CLAUDE.md` (repo layout line; Dependabot convention bullet: base-image PRs run the wheel check before building)
- Test: `tests/test_build_docker_wheels.py`

**Interfaces:**

- Consumes: Task 1 `check-wheels.yml` inputs `dockerfile`, `build-context`.
- Produces: `build-docker.yml` input `wheel-check` (boolean, default `true`); job `wheels` (`uses: pitmonkey/.github/.github/workflows/check-wheels.yml@main` (the same `@main` ref every consumer uses for `build-docker.yml`), passing `dockerfile`, `build-context`).

- [ ] **Step 1: Write failing tests** using the `condition()` evaluator pattern, extended to support `!`, `!=` and `needs.wheels.result`/`cancelled()` stubs:
  - `test_wheel_check_input_default_true`.
  - `test_wheels_runs_on_dependabot_docker_pr` — event `pull_request`, user `dependabot[bot]`, head `dependabot/docker/python-3.15` → true.
  - `test_wheels_skipped_on_uv_dependabot_pr` — head `dependabot/uv/…` → false.
  - `test_wheels_skipped_on_human_pr_and_push` → false for both.
  - `test_wheels_skipped_when_opted_out` — `wheel-check=false` → false.
  - `test_build_jobs_need_wheels` — `build`, `build-multiplatform`, `build-native-matrix` each list `wheels` in `needs`.
  - `test_build_runs_when_wheels_skipped` — `needs.wheels.result=skipped`, human push, `platforms=''` → `build` condition true.
  - `test_build_blocked_when_wheels_failed` — `needs.wheels.result=failure`, dependabot docker PR → all three build conditions false.
  - `test_existing_dependabot_guard_unchanged` — dependabot uv PR → build conditions still false.

- [ ] **Step 2: Run, verify fail** — `uv run --with pyyaml python -m unittest tests.test_build_docker_wheels -v`.

- [ ] **Step 3: Implement** the input, the `wheels` job (condition from Global Constraints), and the `needs`/condition change on the three build jobs. Update README and CLAUDE.md.

- [ ] **Step 4: Run whole suite, verify pass.** Also `actionlint` if available on the machine (else note it was skipped).

- [ ] **Step 5: Commit** — `feat(build-docker): run wheel check before building Dependabot base-image PRs`. Open PR per repo rules; merge when green.

- [ ] **Step 6: End-to-end** — re-run CI on an open Dependabot docker PR that calls `build-docker.yml`: `pitmonkey/happyclap-org-home#10` (`gh run rerun` its latest CI run). Expect `build / wheels / check` success (3.14 lock), then the build job runs. Record the result.

### Task 3: agentic-workflow-hub opt-out

**Repo:** `pitmonkey/agentic-workflow-hub` — read its `CLAUDE.md`/`AGENTS.md` first. Must land after Task 2 merges (unknown input fails the caller).

**Files:** Modify: the CI workflow job that calls `build-docker.yml` for the hub image (`build-hub`) — add `wheel-check: false` with a one-line comment: the hub image installs `build-essential` and compiles dependencies without wheels on purpose.

- [ ] **Step 1:** Edit; `gh workflow view`/push branch; PR CI green (the hub's own `build-hub` path runs on a non-Dependabot PR, so `wheels` is skipped either way — check the input is accepted, no "Invalid input" error).
- [ ] **Step 2:** Merge per repo rules. Commit message: `ci: opt hub image out of the wheel check`.

### Task 4: Restore Dependabot image builds in four repos

**Repos (one PR each):** `kubs-log-analysis`, `nrlfantasy_scraper`, `nrlfb_social`, `nrlteamlist`. Read each repo's `CLAUDE.md` first. Local clones are on stale branches or behind — use clean clones fresh from `main`.

**Files:** Modify `.github/workflows/ci.yml` job `build` in each:

- Delete the caller-level `if: github.actor != 'dependabot[bot]'` (and nrlfantasy_scraper's comment block above it explaining the skip).
- Change `dockerhub-auth: true` to `dockerhub-auth: ${{ github.event.pull_request.user.login != 'dependabot[bot]' }}`.

- [ ] **Step 1:** Apply edit in all four; confirm `ci-green` still `needs` `build` (unchanged).
- [ ] **Step 2:** Open PRs (`ci: build the image on Dependabot base-image PRs`), body explains the skip hid broken base-image bumps and the shared workflow already skips non-docker Dependabot PRs. Verify each PR CI green (human PR: `wheels` skipped, build runs with Docker Hub login).
- [ ] **Step 3:** Merge each per repo rules.
- [ ] **Step 4:** Verify on one repo that a Dependabot run would not hit Docker Hub login: evaluate the expression in the merged file (no Dependabot docker PR is open — python 3.15 is ignored), and note that live proof waits for the next base-image PR.

---

Self-review: spec goals map to Tasks 1–2 (check, reach, summary), Task 4 (gap), Task 3 (opt-out); verification section maps to Task 1 Step 5 and Task 2 Step 6. Review Focus items 1, 2, 5 are covered by Task 1 version tests, 3 by the drop-lines test, 4 by the subdir test.
