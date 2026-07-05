# Shared base image for Pitmonkey worker images that drive the Claude Agent SDK.
#
# The claude-agent-sdk shells out to a bundled Claude Code CLI (a Node binary),
# so every such image needs: a Python runtime, a Node runtime, the Claude Code
# CLI, and uv. Installing that (especially `npm -g @anthropic-ai/claude-code`)
# produces a large, slow-to-export layer. Baking it into this shared base means
# consumer images only rebuild their own tiny Python layers — the expensive
# layer is built and pushed once here, not on every worker CI run.
#
# Published to ghcr.io/pitmonkey/claude-worker-base by this repo's
# build-claude-worker-base workflow. Consumers use:
#   FROM ghcr.io/pitmonkey/claude-worker-base:latest
#
# Node is copied from the official node:22-trixie-slim image rather than
# `apt-get install nodejs npm` — the Debian metapackage pulls 360+ packages and
# a bloated layer. The Node tag matches python:3.14-slim's Debian release
# (trixie) so glibc is compatible.
FROM node:22-trixie-slim AS node

FROM python:3.14-slim

# ca-certificates: npm/Node need a trust store to fetch over HTTPS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Node runtime: the binary plus its global module tree (npm/npx live there).
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Claude Code CLI driven by the Agent SDK.
RUN npm install -g @anthropic-ai/claude-code \
    && npm cache clean --force

# uv for fast, reproducible Python dependency installs in consumer images.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
