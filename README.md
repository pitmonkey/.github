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
| `working-directory` | `.` | Directory to run in (monorepo subpackages) |
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
| `working-directory` | `.` | Directory to run in (monorepo subpackages) |
| `uv-sync-args` | `""` | Extra args to `uv sync` |
| `lint-path` | `"."` | Path for `ruff check` (and `mypy`, unless `mypy-path` is set) |
| `mypy-path` | `""` | Separate path for `mypy` (e.g. the package dir, so `ruff` lints tests while `mypy` stays scoped). Empty = use `lint-path` |
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
| `runner` | `asus-amd64-dind` | Runner label for amd64 builds |
| `runner-arm64` | `pi-arm64-dind` | Runner label for native arm64 builds |
| `image-name` | required | Image name under `ghcr.io/<owner>/` |
| `dockerfile` | `Dockerfile` | Path to the Dockerfile (monorepos with subpath Dockerfiles) |
| `build-context` | `.` | Docker build context (default = repo root) |
| `platforms` | `""` | Multi-platform targets, e.g. `linux/amd64,linux/arm64`. Empty = native arch only (single job). |
| `no-cache` | `false` | Pass `no-cache: true` to docker/build-push-action |
| `dockerhub-auth` | `false` | Login to Docker Hub to bypass pull rate limits (requires `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` secrets) |

Image is pushed only on non-PR events. When `platforms` is non-empty, each platform builds natively on its own runner and the manifests are merged — no QEMU emulation.

Build cache is stored as a registry image on GHCR at `ghcr.io/<owner>/<image-name>:buildcache` (multi-platform builds use a per-platform `:buildcache-<platform>` tag to avoid collisions). Cache is read and written **only on non-PR events** — PRs push no image, and on self-hosted runners exporting a fresh `mode=max` cache per PR dominated wall-clock (it was ~25 min of the old ~28 min PR builds). Pass `no-cache: true` to skip cache entirely.

**Required org secrets:** none (uses auto-provided `GITHUB_TOKEN`). For Docker Hub auth: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`.

**Required caller permissions:** the calling job must declare `permissions: { contents: read, packages: write, actions: write }` — reusable workflows cannot elevate beyond what the caller grants. `packages: write` covers both the image push and the registry build cache; `actions: write` is used by the multi-platform digest artifact upload.

---

### `claude-worker-base` — shared base image for Claude Agent SDK workers

Images that drive the Claude Agent SDK need a Python runtime, a Node runtime, the Claude Code CLI, and `uv`. Installing that (`npm -g @anthropic-ai/claude-code` on a Debian Node install) produces a large, slow-to-export layer — on self-hosted runners it dominated build time. That layer is baked **once** into a shared base image so consumer builds only rebuild their own small Python layers.

- **Definition:** `images/claude-worker-base/Dockerfile` (Node is copied from `node:22-trixie-slim`, matching `python:3.14-slim`'s Debian release, instead of the 360-package `apt-get install nodejs npm`).
- **Published by:** `.github/workflows/build-claude-worker-base.yml` → `ghcr.io/pitmonkey/claude-worker-base:latest`, on changes to the base Dockerfile plus a weekly schedule (to pick up new `@anthropic-ai/claude-code` releases).
- **Package visibility:** set the `claude-worker-base` package to **internal** (Packages → package → Settings → Change visibility) so every org repo can pull it. `build-docker.yml` logs into ghcr on all events — including PRs — so consumer PR builds can pull it; a private (repo-scoped) package would 401 from other repos.

Consumer images use it as their base and drop the Node/CLI install entirely:

```dockerfile
FROM ghcr.io/pitmonkey/claude-worker-base:latest
WORKDIR /src/app
COPY app/pyproject.toml app/uv.lock ./
RUN uv sync --no-dev --frozen
COPY app/*.py ./
```

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
    permissions:
      contents: read
      packages: write
      actions: write
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
