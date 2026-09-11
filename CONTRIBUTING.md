# Contributing

1. Create a focused change that preserves the core boundary.
2. Add or update tests for behavior changes.
3. Run `context-guardian verify examples/conversation.json`.
4. Run `pytest` and `ruff check .`.
5. For Pi changes, run `npm run typecheck` and `npm run smoke` in `adapters/pi`.
6. Before a release, run the interactive `npm run pi-fixture-smoke` check from the
   repository root and manually review the Keep/Drop flow.

The deterministic verifier and RPC smoke test are fast regression checks. The fixture
smoke test is the important end-to-end validation and is intentionally interactive;
it is not run in CI.

Do not add a server, persistent memory database, or replacement summarizer without
first discussing the project scope.
