# pitmonkey/.github — Shared Reusable Workflows

This repo is the single source of truth for all GitHub Actions workflows used across the Pitmonkey org. It contains only reusable workflows — no application code.

## Repo layout

```
.github/workflows/
  test-python.yml           # pytest via uv
  lint-python.yml           # ruff + mypy via uv
  build-docker.yml          # Docker build + push to ghcr.io
  notify-slack.yml          # Slack CI status notification
  add-issue-to-project.yml  # Add new GitHub issue to org project board
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
- The standard runners are `pi-arm64` (test/lint/notify) and `asus-amd64-dind` (Docker build)

## Org setup required

| Secret | Purpose |
|---|---|
| `SLACK_BOT_TOKEN` | Slack notifications |
| `SLACK_CHANNEL_ID` | Slack channel |
| `PROJECT_PAT` | Classic PAT with `project` scope for org project board |

| Variable | Purpose |
|---|---|
| `ORG_PROJECT_ID` | ProjectV2 node ID (`PVT_kwDO...`) for the central project board |
