# pitmonkey/.github — Shared Reusable Workflows

This repo is the single source of truth for all GitHub Actions workflows used across the Pitmonkey org. It contains only reusable workflows — no application code.

## Repo layout

```
.github/workflows/
  test-python.yml              # pytest via uv
  lint-python.yml              # ruff + mypy via uv
  build-docker.yml             # Docker build + push to ghcr.io
  build-claude-worker-base.yml # Build + push the shared claude-worker-base image
  notify-slack.yml             # Slack CI status notification
  add-issue-to-project.yml     # Add new GitHub issue to org project board
  dependabot-automerge.yml     # Auto-merge Dependabot dev-tooling PRs on green
```

## How consuming repos use these

Each workflow is called individually so repos can pick only what they need:

```yaml
jobs:
  test:
    uses: pitmonkey/.github/.github/workflows/test-python.yml@main
    secrets: inherit
```

All callers use `secrets: inherit` — no secret forwarding needed in the caller file.

## Adding or modifying a workflow

- All inputs must have sensible defaults so callers only specify overrides
- Keep jobs to one concern per file (test, lint, build, notify are separate)
- Document every input in README.md when adding or changing one
- The standard runners are `pi-arm64` (test/lint/notify and arm64 Docker builds) and `asus-amd64-dind` (amd64 Docker builds)

## Org CI conventions

- Every consuming repo exposes a job named exactly **`ci-green`** that `needs:` all of its test/lint/build jobs, runs `if: always()`, and fails only on `failure`/`cancelled`. It is the single required status check across the org, supplied by the org ruleset `ci-green-required`. Job names differ per repo and a skipped path-filtered job emits no check run, so individual job names can never be required directly.
- Dependabot pull requests skip Docker builds automatically — the guard lives in `build-docker.yml`, not in callers. Branches matching `dependabot/docker/*` are the exception and still build, because a base-image bump can only be validated by building it.
- Dependabot dev-tooling updates auto-merge on green via `dependabot-automerge.yml`. This only works when the repo's `dependabot.yml` splits `uv` into `uv-dev`/`uv-prod` groups; a mixed group reports as `direct:production` and never qualifies.
- Never add a `pre-commit` Dependabot ecosystem to a repo with no `.pre-commit-config.yaml` — Dependabot errors on it.

## Org setup required

| Secret | Purpose |
|---|---|
| `SLACK_BOT_TOKEN` | Slack notifications |
| `SLACK_CHANNEL_ID` | Slack channel |
| `PROJECT_PAT` | Classic PAT with `project` scope for org project board |
| `DOCKERHUB_USERNAME` | Docker Hub login — avoids pull rate limits (optional, used when `dockerhub-auth: true`) |
| `DOCKERHUB_TOKEN` | Docker Hub access token (pair with `DOCKERHUB_USERNAME`) |

| Variable | Purpose |
|---|---|
| `ORG_PROJECT_ID` | ProjectV2 node ID (`PVT_kwDO...`) for the central project board |
