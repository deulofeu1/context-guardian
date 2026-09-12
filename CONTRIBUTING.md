# Contributing

1. Create a focused change that preserves the core boundary.
2. Add or update tests for behavior changes.
3. Run `context-guardian verify examples/conversation.json`.
4. Run `pytest` and `ruff check .`.
5. For Pi changes, run `npm run typecheck` and `npm run smoke` in `adapters/pi`.
6. For DeepSeek Harness changes, run `npm run typecheck:dsh`, `npm run test:dsh`,
   and `npm run dsh-fixture-smoke`.
7. Before a release, run the interactive fixture checks from the repository root:
   `npm run pi-fixture-smoke` and `npm run dsh-fixture-smoke`; manually review every
   Keep/Drop flow.

The deterministic verifier, RPC smoke test, and CI fixture jobs are fast regression
checks. The local fixture smoke commands are interactive so a maintainer can verify
the actual review surface before release. Set `CONTEXT_GUARDIAN_REVIEW_MODE=keep` in
automation when no terminal is available.

The manual publish workflow lives in `.github/workflows/release.yml`. Python and npm
publishing use trusted publishing through GitHub Actions OIDC; no long-lived registry
token is required. Each npm package must have a Trusted Publisher configured for
the `deulofeu1/context-guardian` repository and `release.yml` workflow.

Do not add a server, persistent memory database, or replacement summarizer without
first discussing the project scope.
