# pitmonkey/.github — Shared Reusable Workflows

This repo is the single source of truth for all GitHub Actions workflows used across the Pitmonkey org. It contains only reusable workflows — no application code.

## Repo layout

```
.github/workflows/
  test-python.yml              # pytest via uv
  lint-python.yml              # ruff + mypy via uv
  test-rust.yml                # rustfmt + clippy + cargo test, optionally Windows under Wine
  build-rust.yml               # release binary for one target (Linux, musl, Windows via mingw)
  build-docker.yml             # Docker build + push to ghcr.io
  build-claude-worker-base.yml # Build + push the shared claude-worker-base image
  notify-slack.yml             # Slack CI status notification
  add-issue-to-project.yml     # Add new GitHub issue to org project board
  dependabot-automerge.yml     # Auto-merge Dependabot dev-tooling PRs on green
  dependabot-uv-relock.yml     # Re-lock every uv project on Dependabot uv PRs and push the locks back
```

## How consuming repos use these

Each workflow is called individually so repos can pick only what they need:

```yaml
jobs:
  test:
    uses: pitmonkey/.github/.github/workflows/test-python.yml@main
    secrets: inherit
```

Most callers use `secrets: inherit`. Dependabot auto-merge instead maps the App private key explicitly, as shown in README.md.

## Adding or modifying a workflow

- All inputs must have sensible defaults so callers only specify overrides
- Keep jobs to one concern per file (test, lint, build, notify are separate)
- Document every input in README.md when adding or changing one
- The standard runners are `pi-arm64` (test/lint/notify and arm64 Docker builds), `asus-amd64-dind` (amd64 Docker builds) and `asus-amd64-wine` (Rust test and build jobs, Windows under Wine; no DinD)

## Org CI conventions

- Every consuming repo exposes a job named exactly **`ci-green`** that `needs:` all of its test/lint/build jobs, runs `if: always()`, and fails only on `failure`/`cancelled`. It is the single required status check across the org, supplied by the org ruleset `ci-green-required`. Job names differ per repo and a skipped path-filtered job emits no check run, so individual job names can never be required directly.
- Dependabot pull requests skip Docker builds automatically — the guard lives in `build-docker.yml`, not in callers. Branches matching `dependabot/docker/*` are the exception and still build, because a base-image bump can only be validated by building it.
- Dependabot dev-tooling updates auto-merge on green via `dependabot-automerge.yml`. Callers pass `app-client-id` from `PITMONKEY_CODER_CLIENT_ID` and map `PITMONKEY_CODER_PRIVATE_KEY` to `app-private-key` so App-attributed merges trigger push CI. Omitting the input retains legacy `GITHUB_TOKEN` behavior with no push run. The App must never bypass required checks. This only works when the repo's `dependabot.yml` splits `uv` into `uv-dev`/`uv-prod` groups; a mixed group reports as `direct:production` and never qualifies.
- Dependabot re-locks only the directory it bumps. A repo whose uv projects depend on each other through path sources calls `dependabot-uv-relock.yml` (from `pull_request_target`, with the same App credentials as auto-merge) and passes `uv-sync-args: --locked` to `test-python.yml` / `lint-python.yml`, so a stale lock fails CI and is re-locked automatically. Its `relock` job runs PR code without a write credential; its `push` job holds the App token and runs no PR code. Keep that split.
- Never add a `pre-commit` Dependabot ecosystem to a repo with no `.pre-commit-config.yaml` — Dependabot errors on it.
- `OPS_UI_TOKEN` is held in two org secret scopes, Actions and Dependabot, which GitHub does not sync. A Dependabot-triggered run reads only the Dependabot copy, so rotating the PAT and updating only Actions breaks every Dependabot PR while push CI stays green. Rotation procedure and the diagnosis table: "Rotating `OPS_UI_TOKEN`" in README.md.

## Org setup required

| Secret | Purpose |
|---|---|
| `SLACK_BOT_TOKEN` | Slack notifications |
| `SLACK_CHANNEL_ID` | Slack channel |
| `PROJECT_PAT` | Classic PAT with `project` scope for org project board |
| `PITMONKEY_CODER_PRIVATE_KEY` | Actions PEM key for App-authenticated Dependabot auto-merge |
| `DOCKERHUB_USERNAME` | Docker Hub login — avoids pull rate limits (optional, used when `dockerhub-auth: true`) |
| `DOCKERHUB_TOKEN` | Docker Hub access token (pair with `DOCKERHUB_USERNAME`) |
| `OPS_UI_TOKEN` | Fine-grained PAT, `Contents: Read` on private repos used as uv git dependencies (today `pitmonkey/ops-ui`). Set in **both** the Actions and Dependabot scopes — see "Rotating `OPS_UI_TOKEN`" in README.md |

| Variable | Purpose |
|---|---|
| `ORG_PROJECT_ID` | ProjectV2 node ID (`PVT_kwDO...`) for the central project board |
| `PITMONKEY_CODER_CLIENT_ID` | `pitmonkey-coder` client ID (`Iv23liyMdjpPInjnQcVD`) for auto-merge |
