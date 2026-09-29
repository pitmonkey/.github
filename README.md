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

**Required org secrets:** `OPS_UI_TOKEN` — only when the package has a private git dependency (`[tool.uv.sources] { git = ... }`). Absent is fine: the injection is guarded and public dependencies still resolve. See [Rotating `OPS_UI_TOKEN`](#rotating-ops_ui_token).

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

**Required org secrets:** `OPS_UI_TOKEN` — same as `test-python.yml` above. See [Rotating `OPS_UI_TOKEN`](#rotating-ops_ui_token).

---

### `test-rust.yml` — Run rustfmt, clippy and cargo test (optionally Windows under Wine)

```yaml
jobs:
  test:
    uses: pitmonkey/.github/.github/workflows/test-rust.yml@main
    with:
      extra-cargo-args: -p my-app --no-default-features
      windows: true
```

| Input | Default | Description |
|---|---|---|
| `runner` | `asus-amd64-wine` | Runner label |
| `working-directory` | `.` | Directory holding the Cargo workspace |
| `toolchain` | `stable` | Rust toolchain for `dtolnay/rust-toolchain` |
| `cargo-args` | `--workspace` | Package/feature selection for both `cargo clippy` and `cargo test` |
| `extra-cargo-args` | `""` | More argument sets, one per line, each checked and tested like `cargo-args` (e.g. a `--no-default-features` build) |
| `windows` | `false` | Also run clippy and the tests for `x86_64-pc-windows-gnu`, the tests under Wine |
| `wine` | `wine64` | Wine binary used as cargo's test runner |

The `linux` job runs `cargo fmt --all --check`, then `cargo clippy <args> --all-targets -- -D warnings` and `cargo test <args> --no-fail-fast` for each argument set. The `windows` job repeats clippy and test with `--target x86_64-pc-windows-gnu`, with `CARGO_TARGET_X86_64_PC_WINDOWS_GNU_RUNNER` set to Wine, so each test executable runs as a Windows program. This replaces a GitHub-hosted `windows-latest` job, which private repos pay for at twice the Linux rate. Tests behind `#[cfg(unix)]` or `#[cfg(windows)]` are selected exactly as on a Windows machine. Wine is not Windows, so keep an occasional real-Windows run (for example a `workflow_dispatch` or release-tag job on `windows-latest`) for what Wine cannot show.

Debug info and incremental compilation are turned off (`CARGO_PROFILE_DEV_DEBUG=0`, `CARGO_PROFILE_TEST_DEBUG=0`, `CARGO_INCREMENTAL=0`): they make up most of `target/`, and on the first caller a 19 GB debug `target/` dropped to about 2 GB per target. `Swatinem/rust-cache` keeps dependencies between runs in the Actions cache.

**Runner:** `asus-amd64-wine` is the ARC scale set with mingw-w64, Wine and Xvfb in its image, no DinD, and a work volume sized for Rust. `asus-amd64-dind`'s 4Gi work volume is too small for a Rust workspace (see `docs/arc-runners.md` in `k3s-infra`).

**Required org secrets:** none.

---

### `build-rust.yml` — Build a release binary for one target

```yaml
jobs:
  build:
    needs: [test]
    strategy:
      matrix:
        include:
          - target: x86_64-unknown-linux-gnu.2.17
            zigbuild: true
            artifact: my-app-linux-x86_64
            smoke: '"$BIN" --version'
          - target: x86_64-pc-windows-gnu
            zigbuild: false
            artifact: my-app-windows-x86_64
            smoke: '"$WINE" "$BIN" --version'
    uses: pitmonkey/.github/.github/workflows/build-rust.yml@main
    with:
      package: my-app
      target: ${{ matrix.target }}
      zigbuild: ${{ matrix.zigbuild }}
      smoke-test: ${{ matrix.smoke }}
      artifact-name: ${{ matrix.artifact }}
```

| Input | Default | Description |
|---|---|---|
| `runner` | `asus-amd64-wine` | Runner label |
| `working-directory` | `.` | Directory holding the Cargo workspace |
| `toolchain` | `stable` | Rust toolchain |
| `package` | required | Cargo package to build (`-p`) |
| `binary` | `""` | Binary name without `.exe`; empty = `package` |
| `target` | `x86_64-unknown-linux-gnu` | Target triple; with `zigbuild`, a glibc version may be appended (`x86_64-unknown-linux-gnu.2.17`) |
| `cargo-args` | `""` | More `cargo build` arguments (features) |
| `rustflags` | `""` | `RUSTFLAGS` for the build (e.g. `-C target-feature=+crt-static`) |
| `zigbuild` | `false` | Build with `cargo-zigbuild`, which links against an older glibc |
| `smoke-test` | `""` | Shell commands run after the build, with `$BIN` (binary path) and `$WINE` set |
| `artifact-name` | `""` | Upload the binary under this name; empty = no upload |
| `wine` | `wine64` | Wine binary, as `$WINE` in the smoke test |

Windows targets (`x86_64-pc-windows-gnu`) are cross-compiled with mingw-w64; with `rustflags: -C target-feature=+crt-static` the `.exe` imports only DLLs that ship with Windows. The smoke test runs it under Wine.

**Required org secrets:** none.

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

Image is pushed only on non-PR events. When `platforms` is non-empty, a single buildkit instance on the amd64 runner builds every platform (arm64 via QEMU emulation) and pushes one manifest list atomically; set `native-arm64: true` to fall back to the per-arch native-runner matrix for a compile-heavy image.

**Dependabot pull requests skip the build — except Docker bumps.** All build jobs carry a guard on `github.event.pull_request.user.login`, so a `uv`, `pre-commit` or `github-actions` bump never occupies a runner for a build that pushes nothing. Callers do not need their own `github.actor` guard. The calling job reports `skipped`, which `notify-slack.yml` and the `ci-green` gate both treat as passing.

Branches matching `dependabot/docker/*` **do** build. For a library bump the Dockerfile is unchanged and the build proves nothing; for a base-image bump the Dockerfile *is* the change, and building it is the only test that exists. Without the exception such a PR reports a green `ci-green` having never assembled the image — a green tick that did not test the thing being changed.

Build cache is stored as a registry image on GHCR at `ghcr.io/<owner>/<image-name>:buildcache` (multi-platform builds use a per-platform `:buildcache-<platform>` tag to avoid collisions). Cache is **read on all events, including PRs** — a fresh ephemeral runner pulls the remote cache tag to reuse layers, so PR builds skip work already done on the last push. Cache is **written only on non-PR events** — PRs push no image, and on self-hosted runners exporting a fresh `mode=max` cache per PR dominated wall-clock (it was ~25 min of the old ~28 min PR builds). Pass `no-cache: true` to skip cache entirely.

**Required org secrets:** none for the push itself (uses the auto-provided `GITHUB_TOKEN`). For Docker Hub auth: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`. `OPS_UI_TOKEN` is forwarded as the BuildKit secret `ops_ui_token` for images with a private git dependency, and is inert for Dockerfiles that never mount it — see [Rotating `OPS_UI_TOKEN`](#rotating-ops_ui_token).

**Required caller permissions:** the calling job must declare `permissions: { contents: read, packages: write, actions: write }` — reusable workflows cannot elevate beyond what the caller grants. `packages: write` covers both the image push and the registry build cache; `actions: write` is used by the multi-platform digest artifact upload.

---

### `claude-worker-base` — shared base image for Claude Agent SDK workers

Images that drive the Claude Agent SDK need a Python runtime, a Node runtime, the Claude Code CLI, and `uv`. Installing that (`npm -g @anthropic-ai/claude-code` on a Debian Node install) produces a large, slow-to-export layer — on self-hosted runners it dominated build time. That layer is baked **once** into a shared base image so consumer builds only rebuild their own small Python layers.

- **Definition:** `images/claude-worker-base/Dockerfile` (Node is copied from `node:22-trixie-slim`, matching `python:3.14-slim`'s Debian release, instead of the 360-package `apt-get install nodejs npm`).
- **Published by:** `.github/workflows/build-claude-worker-base.yml` → `ghcr.io/pitmonkey/claude-worker-base:latest`, on changes to the base Dockerfile plus a weekly schedule (to pick up new `@anthropic-ai/claude-code` releases).
- **Package access:** the package stays **private**. Grant each consuming repo pull access under
  Packages → `claude-worker-base` → Package settings → **Manage Actions access** → *Add repository*
  (Read): `github-dispatcher`, `claude-pr-agent`, and any future consumer. `build-docker.yml` logs
  into ghcr on all events — including PRs — so a granted repo's `GITHUB_TOKEN` can pull the base;
  without the grant, other repos 401. (Org-wide `internal` visibility would also work but is
  disabled by the org admins here.)

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

### `dependabot-automerge.yml` — Auto-merge Dependabot dev-tooling PRs

```yaml
# .github/workflows/dependabot-automerge.yml in each consuming repo
name: dependabot-automerge

on: pull_request_target

permissions:
  contents: write
  pull-requests: write

jobs:
  automerge:
    uses: pitmonkey/.github/.github/workflows/dependabot-automerge.yml@main
```

No inputs, no secrets. Permissions must be declared in the **caller** — a reusable workflow's permissions are capped by the caller's grant, so omitting them makes the merge step fail with a 403.

Enables GitHub's native auto-merge (`gh pr merge --auto --squash`) when Dependabot metadata matches any of:

| Condition | Covers |
|---|---|
| `dependency-type == 'direct:development'` | the `uv-dev` group — ruff, mypy, pytest, … |
| `package-ecosystem == 'pre_commit'` | pre-commit hook bumps |
| `package-ecosystem == 'github_actions'` | action version bumps |

Production dependencies (`uv-prod`) and Docker base images (`docker-all`) do **not** match and are left open for review.

Two things this depends on:

- **`ci-green` must be a required status check on the default branch.** `--auto` waits on required checks; with none configured it merges as soon as the PR is mergeable, which defeats the point. The org ruleset `ci-green-required` supplies this.
- **`dependabot.yml` must split `uv` into `uv-dev` and `uv-prod` groups.** Dependabot reports the *most-privileged* dependency type across the whole PR, so a group mixing dev and prod deps always reads as `direct:production` and never qualifies.

Merges enabled with `GITHUB_TOKEN` do not trigger `push`-event workflows, so an auto-merged bump does not rebuild or push images. That is fine for the three eligible ecosystems — none change a runtime image's contents. Adding `docker` or `uv-prod` to the eligible set would require swapping to a PAT.

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

  # The org's single required status check. Job names differ per repo, and a
  # path-filtered job that is skipped emits no check run at all, so a ruleset
  # cannot require them directly. This job always runs, so it always reports.
  # `notify` is excluded: a Slack delivery failure must not block a merge.
  ci-green:
    needs: [test, lint, build]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Fail if any upstream job failed or was cancelled
        if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')
        run: exit 1
```

Every repo must expose a job named exactly `ci-green`, listing all of its test/lint/build jobs in `needs`. The org ruleset `ci-green-required` requires that one context on the default branch, which is what gates Dependabot auto-merge.

---

## Org Setup (one-time)

### Org secrets (Settings → Secrets and variables)

All but `OPS_UI_TOKEN` live only under **Actions**. `OPS_UI_TOKEN` must be set under **Actions** *and* **Dependabot** — see below.

| Secret | Purpose |
|---|---|
| `SLACK_BOT_TOKEN` | Slack bot auth for CI notifications |
| `SLACK_CHANNEL_ID` | Slack channel for CI notifications |
| `PROJECT_PAT` | Classic PAT with `project` scope for org project board |
| `OPS_UI_TOKEN` | Fine-grained PAT, `Contents: Read` on the private repos used as git dependencies (today `pitmonkey/ops-ui`). **Must be set in the Actions *and* Dependabot scopes** — see below |

### Rotating `OPS_UI_TOKEN`

This secret exists **twice** — once in the Actions scope, once in the Dependabot scope — and GitHub does not sync them. A workflow run triggered by a Dependabot pull request reads **only** the Dependabot scope, so updating just the Actions copy leaves push CI green while every Dependabot PR fails. That is what happened on 2026-09-04: the rotation refreshed only the Actions copy, and it surfaced three days later as a `uv-prod` bump PR stuck on a red `ci-green`.

Set both copies, feeding the value on **stdin**. `gh secret set` reads stdin when `--body` is absent, and an empty stdin in a non-interactive shell silently overwrites the secret with an empty string rather than failing:

```bash
tr -d '\r\n' < /path/to/pat | gh secret set OPS_UI_TOKEN --org pitmonkey --app dependabot --visibility all
tr -d '\r\n' < /path/to/pat | gh secret set OPS_UI_TOKEN --org pitmonkey --app actions    --visibility all
```

Piping keeps the value out of `argv` and out of shell history, and `tr` strips the trailing newline that would otherwise become part of the secret.

Verify **both** scopes — a push-triggered rerun does not exercise the Dependabot copy, and vice versa. Rerun a Dependabot PR's failed jobs and a push-triggered run on the default branch, then read `GIT_CONFIG_COUNT` in the `uv sync` step's log:

| Job log | Meaning |
|---|---|
| `GIT_CONFIG_COUNT: 1` | credential injected — this scope is good |
| `GIT_CONFIG_COUNT: 0` + `fatal: could not read Username for 'https://github.com'` | secret **empty or absent** in the scope this run reads |
| `GIT_CONFIG_COUNT: 1` + `remote: Invalid username or token` | secret **present but stale** — the value no longer matches a live PAT |

Two things that mislead while debugging this:

- GitHub's **"Last used"** on the token's own settings page does not reliably register git-over-HTTPS use. A token driving CI daily can read "Never used"; do not use that field to work out which token is live.
- A PAT value is shown **once**, at creation. If it was not saved, the Actions copy cannot be mirrored into the Dependabot copy — use **Regenerate** on the existing token (it keeps the name, permissions and repository selection) and then set both copies.

The org does not require approval for fine-grained PATs, so a newly minted or regenerated token works immediately.

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
