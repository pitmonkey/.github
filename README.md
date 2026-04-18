# pitmonkey-github-repo

Shared GitHub Actions reusable workflows for the Pitmonkey org. Repos call these instead of maintaining their own copies.

## Available Workflows

### `test-python.yml` — Run pytest

```yaml
jobs:
  test:
    uses: pitmonkey/.github/.github/workflows/test-python.yml@main
    secrets: inherit
```

| Input | Default | Description |
|---|---|---|
| `runner` | `pi-arm64` | Runner label |
| `uv-sync-args` | `""` | Extra args to `uv sync` (e.g. `--extra dev`) |
| `test-path` | `tests/` | Path passed to pytest |

---

### `lint-python.yml` — Run ruff + mypy

```yaml
jobs:
  lint:
    uses: pitmonkey/.github/.github/workflows/lint-python.yml@main
    with:
      lint-path: mypackage/
    secrets: inherit
```

| Input | Default | Description |
|---|---|---|
| `runner` | `pi-arm64` | Runner label |
| `uv-sync-args` | `""` | Extra args to `uv sync` |
| `lint-path` | `"."` | Path for `ruff check` and `mypy` |
| `run-mypy` | `true` | Whether to run mypy |

---

### `build-docker.yml` — Build and push Docker image to GHCR

```yaml
jobs:
  build:
    needs: [test]
    uses: pitmonkey/.github/.github/workflows/build-docker.yml@main
    with:
      image-name: my-service
    secrets: inherit
```

| Input | Default | Description |
|---|---|---|
| `runner` | `asus-amd64-dind` | Runner label |
| `image-name` | required | Image name under `ghcr.io/<owner>/` |
| `platforms` | `""` | Multi-platform targets, e.g. `linux/amd64,linux/arm64`. Empty = native arch. |
| `no-cache` | `false` | Pass `no-cache: true` to docker/build-push-action |

Image is pushed only on non-PR events. QEMU is set up automatically when `platforms` is non-empty.

**Required org secrets:** none (uses auto-provided `GITHUB_TOKEN`)

---

### `notify-slack.yml` — Post CI status to Slack

```yaml
jobs:
  notify:
    needs: [test, lint, build]
    if: always() && github.actor != 'dependabot[bot]'
    uses: pitmonkey/.github/.github/workflows/notify-slack.yml@main
    with:
      project-name: my-service
      test-result: ${{ needs.test.result }}
      lint-result: ${{ needs.lint.result }}
      build-result: ${{ needs.build.result }}
    secrets: inherit
```

| Input | Default | Description |
|---|---|---|
| `runner` | `pi-arm64` | Runner label |
| `project-name` | required | Display name in Slack message |
| `test-result` | `""` | Pass `needs.<job>.result` |
| `lint-result` | `""` | Pass `needs.<job>.result` |
| `build-result` | `"skipped"` | Pass `needs.<job>.result`, or omit if no build job |

**Required org secrets:** `SLACK_BOT_TOKEN`, `SLACK_CHANNEL_ID`

---

### `add-issue-to-project.yml` — Add new issues to the org project board

```yaml
# .github/workflows/add-to-project.yml in each consuming repo
name: Add Issue to Project
on:
  issues:
    types: [opened]
jobs:
  add-to-project:
    uses: pitmonkey/.github/.github/workflows/add-issue-to-project.yml@main
    with:
      project-id: ${{ vars.ORG_PROJECT_ID }}
    secrets: inherit
```

| Input | Description |
|---|---|
| `project-id` | Node ID of the org-level ProjectV2 (format: `PVT_kwDO...`) |

**Required org secrets:** `PROJECT_PAT` — classic PAT with `project` scope

---

## Full CI Example

A typical service repo's `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  test:
    uses: pitmonkey/.github/.github/workflows/test-python.yml@main
    secrets: inherit

  lint:
    uses: pitmonkey/.github/.github/workflows/lint-python.yml@main
    with:
      lint-path: mypackage/
    secrets: inherit

  build:
    needs: [test]
    uses: pitmonkey/.github/.github/workflows/build-docker.yml@main
    with:
      image-name: my-service
      platforms: linux/amd64,linux/arm64
    secrets: inherit

  notify:
    needs: [test, lint, build]
    if: always() && github.actor != 'dependabot[bot]'
    uses: pitmonkey/.github/.github/workflows/notify-slack.yml@main
    with:
      project-name: my-service
      test-result: ${{ needs.test.result }}
      lint-result: ${{ needs.lint.result }}
      build-result: ${{ needs.build.result }}
    secrets: inherit
```

---

## Org Setup (one-time)

### Org secrets (Settings → Secrets → Actions)

| Secret | Purpose |
|---|---|
| `SLACK_BOT_TOKEN` | Slack bot auth for CI notifications |
| `SLACK_CHANNEL_ID` | Slack channel for CI notifications |
| `PROJECT_PAT` | Classic PAT with `project` scope for org project board |

### Org variable

| Variable | Purpose |
|---|---|
| `ORG_PROJECT_ID` | ProjectV2 node ID (`PVT_kwDO...`) for the central project board |

Find your project node ID:
```bash
gh api graphql -f query='
  query($org: String!) {
    organization(login: $org) {
      projectsV2(first: 20) {
        nodes { id title }
      }
    }
  }
' -f org="pitmonkey"
```

### Repo access

This repo must be **public** or have "Allow pitmonkey repositories to use workflows from this repository" enabled (Settings → Actions → General).
