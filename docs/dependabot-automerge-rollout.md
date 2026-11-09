# Dependabot App authentication rollout

Inventory inspected every workflow in 59 active org repositories on 2026-11-09;
21 callers reference the reusable workflow, including this repository.

## Prepared state

The client-ID variable and private-key Actions secret are configured with selected-
repository access for all 21 callers. The key successfully authenticated as
`pitmonkey-coder` and minted a token restricted to kubs-log-analysis with Contents,
Pull requests and Workflows write permissions; the validation token was revoked.
The live Dependabot merge pilot remains pending. The shared branch
contains the self-caller migration. Twenty external caller patches are prepared
under `/tmp/issue45-rollout/` in the implementation workspace; each repository has
its changed workflow and a separate `.patch` file. These are preparation artifacts,
not published caller changes.

## Release order

1. Make the existing App key available as Actions secret `PITMONKEY_CODER_PRIVATE_KEY`
   and its client ID as variable `PITMONKEY_CODER_CLIENT_ID`. Verify caller access.
2. Merge the shared workflow change before any external caller migration.
3. Migrate kubs-log-analysis and observe a genuine eligible Dependabot merge:
   required checks gate it, the actor is `pitmonkey-coder`, push CI references the
   merge SHA, and the image is published from that SHA.
4. Migrate the remaining callers, preserving caller permissions and other jobs.
   Replace any `secrets: inherit` on this job with the explicit secret mapping below.
5. Validate post-merge CI and image publication for each image-producing caller.

```yaml
    with:
      app-client-id: ${{ vars.PITMONKEY_CODER_CLIENT_ID }}
    secrets:
      app-private-key: ${{ secrets.PITMONKEY_CODER_PRIVATE_KEY }}
```

The self caller is updated in the shared change. External caller patches must
remain pending until the shared interface is available on `main`. Remove the
input and secret mapping to roll a caller back to legacy authentication.

## Caller checklist

All external callers use `.github/workflows/dependabot-automerge.yml`; the self
caller uses `.github/workflows/dependabot-automerge-self.yml`.

- [ ] `pitmonkey/nrlfantasy_scraper`
- [ ] `pitmonkey/product-safety-rss`
- [ ] `pitmonkey/toby-assistant`
- [ ] `pitmonkey/nrlteamlist`
- [ ] `pitmonkey/nrlfb_social`
- [ ] `pitmonkey/kubs-log-analysis` — pilot
- [ ] `pitmonkey/nrl-fantasy-analysis`
- [ ] `pitmonkey/.github`
- [ ] `pitmonkey/calendar-sync`
- [ ] `pitmonkey/nrl-injury-ward`
- [ ] `pitmonkey/local-claude-marketplace`
- [ ] `pitmonkey/shopify-product-catalogue`
- [ ] `pitmonkey/international-product-recalls`
- [ ] `pitmonkey/game-dev-research`
- [ ] `pitmonkey/github-dispatcher`
- [ ] `pitmonkey/google-workspace-multiple-mcp`
- [ ] `pitmonkey/agentic-workflow-hub`
- [ ] `pitmonkey/sluice`
- [ ] `pitmonkey/fed-gov-tracker`
- [ ] `pitmonkey/toby-chat-worker`
- [ ] `pitmonkey/nrl-official`

## Verification limits

Local tests exercise merge commands, authentication selection and eligibility;
`actionlint` checks workflow expressions. Only a live merge can establish that
post-merge push CI and image publication work with the installation and rulesets.
Do not close #45 until rollout and live verification are complete.

The separate refresh-automerge workflow in fed-gov-tracker belongs to #211; it
can reuse these credentials but is not changed by this migration.
