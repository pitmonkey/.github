# Wheel check on Dependabot base-image PRs — design

Status: approved 2026-11-18.

## Intent

Dependabot keeps opening `python:3.X-slim` base-image bumps before the ecosystem ships wheels for that version. The image build eventually fails deep in `uv sync` (no gcc in slim), the failure is slow and buried, and in four repos it is never run at all. We want a fast, plain answer on every such PR: do all runtime dependencies have wheels for the new Python version on amd64 and arm64?

## Goals

- Fail a `dependabot/docker/*` PR within seconds when any locked runtime dependency lacks a wheel for the target Python on `x86_64-manylinux_2_28` or `aarch64-manylinux_2_28`, naming the package.
- Reach every repo that already calls `build-docker.yml` with no caller change.
- Close the gap in the four repos that skip the shared build on Dependabot PRs.

## Non-goals

- Replacing the Docker build. The build still runs after the check passes (user decision: check, then build).
- Checking git dependencies (e.g. `ops-ui`); they are filtered out.
- Running on non-Dependabot PRs or pushes.

## Anti-goals

- A false failure blocking a repo that compiles on purpose, with no way out.
- Any new secret requirement on Dependabot runs.

## Approaches considered

1. **Separate `check-wheels.yml`, called as a job from `build-docker.yml`** — chosen. One concern per file (repo rule), zero caller edits for the ~21 consumers, no `ci-green` changes. Cost: one more level of reusable-workflow nesting.
2. Separate workflow called by each repo — explicit, but ~25 caller PRs plus `ci-green` edits; slow and drifts.
3. Steps inlined in `build-docker.yml` jobs — least code, but mixes concerns against the repo rule and is harder to opt out of.

## Design

**`check-wheels.yml` (new reusable workflow).** Inputs: `dockerfile` (default `Dockerfile`), `build-context` (default `.`), `platforms` (default `x86_64-manylinux_2_28,aarch64-manylinux_2_28`). Runs on `pi-arm64`. Steps:

1. Read the Python version from the last `FROM python:<X.Y>[-…]` line of the Dockerfile (my call: last line is the runtime stage; all stages share a version in every repo today). No match (non-Python base, or an `ARG`-templated tag) — skip with a notice, pass.
2. No `uv.lock` in `build-context` — skip with a notice, pass.
3. `uv export --frozen --no-dev --no-hashes --no-emit-project`, drop git and editable lines, then per platform `uv pip compile - --no-build --python-version <X.Y> --python-platform <p>`. Any failure fails the job; write the offending package and platform to the job summary.

uv installed with a pinned `astral-sh/setup-uv` (my call). No secrets.

**`build-docker.yml` changes.**

- New input `wheel-check` (boolean, default `true`).
- New job `wheels`, `uses: ./.github/workflows/check-wheels.yml`, runs only when `inputs.wheel-check` and the PR is a Dependabot PR on a `dependabot/docker/*` branch (same expression shape as the existing guard).
- Each build job gains `needs: wheels` and keeps its existing condition, ANDed with `!cancelled() && needs.wheels.result != 'failure'`, so a skipped check does not skip the build (a plain `needs:` on a skipped job would).
- README documents the new input and behaviour; CLAUDE.md's Dependabot convention line mentions the check.

**Opt-out.** `agentic-workflow-hub` sets `wheel-check: false` on its hub build (it installs `build-essential` and compiles on purpose).

**The four gap repos** (kubs-log-analysis, nrlfantasy_scraper, nrlfb_social, nrlteamlist): remove the caller-level `if: github.actor != 'dependabot[bot]'` on `build`, and pass `dockerhub-auth: ${{ github.event.pull_request.user.login != 'dependabot[bot]' }}` so the Docker Hub login (no Dependabot secret) is skipped on Dependabot runs. This also restores their image build on base-image PRs, matching the org convention. Each change goes through that repo's own rules (kubs-log-analysis and nrlfb_social route code through their `python-pro` agent; these are YAML-only).

## Verification

- `check-wheels.yml` exercised from a test branch against known cases: nrlfb_social lock fails (httptools), nrlteamlist passes, a non-Python Dockerfile skips.
- After merge, re-run CI on one open `dependabot/docker/*` PR (or `@dependabot recreate` a closed one) and confirm `wheels` runs then the build runs.

## Left to the builder

Exact job names and summary formatting; whether the check is a shell step or a small script under `.github/scripts/`; test layout under `tests/`, following what the repo already does.
