# Progress

## M0 — local foundation and hosted deployment verified

2026-10-11. Work is on `feat/m0`, based on upstream vibetest-use commit
`fe0b90ac9d6a129ce06f5b53074241a9f205015b`; history and attribution are retained.
Package renamed to `ux_guardian`; browser-use, Google LLM bindings, screeninfo
and upstream generated egg metadata removed. The optional MCP interface now
replays fixtures only. The bounded asyncio swarm uses the BrowserAgent protocol.

Verified on Windows Server with Python 3.12 and Node 24:

- `uv sync --locked`: succeeds with uv.lock; no browser-use dependency.
- `uv run pytest`: 21 passed, 11 browser tests explicitly skipped unless the
  local demo harness is running. Judge tests cover all four truth-table rows,
  earlier-step retry confirmation, deterministic confirmation and severity rules.
- `uv run ruff check .`: passes. `uv run pyright`: zero errors.
- `pnpm build` and `pnpm typecheck` in demo-app: pass.
- `uv run ux-guardian demo smoke`: 31 passed, one unseeded-only test skipped;
  desktop/mobile seeded sign-in, rejected login,
  forged session, search/product/cart persistence, checkout to disabled payment,
  404 product route and foreign-origin rejection verified. Screenshots are saved
  locally under artifacts/demo without credential fields or captions.
- `uv run ux-guardian demo smoke --unseeded`: missing seeded credentials return
  503 and no session cookie; account route redirects to login.
- Fixture dry-run writes report.json and report.md without network or SDK calls.
  It replays the protocol/swarm and judge, including a recorded synthetic retry;
  removing confirmation evidence produces a flaky candidate, not a finding.
- FR10 layout is covered by a markdown snapshot against a synthetic report.json.
  Redaction is tested before JSON encoding and Markdown escaping, including
  quotes, apostrophes, ampersands, pipes and newlines in credential values.
  Both saved reports and MCP output require the redaction marker.
- `uv build`: source distribution and wheel build; fixture JSON and NOTICE are
  included. A direct MCP start/results fixture smoke check passes.

The initial browser tests exposed NextURL's loopback-host normalization; using
the browser's Host authority fixed same-origin login. The wrong-login assertion
was scoped to the app's alert to avoid Next.js's route-announcer alert.

A GitHub Actions quality matrix for Windows and Ubuntu is included. Linux has
not been executed on this Windows box; the matrix must pass after repository push.
No WSL, Docker, live TinyFish call, or billable agent run was used.

Read-only review found one Important issue: Markdown escaping could prevent
post-render secret redaction. A stronger test reproduced it; shared pre-render
model redaction fixes both report files and MCP output. The full foundation suite,
Ruff and Pyright pass after that fix. No additional review findings remain.

### Hosted deployment verification — 2026-10-11

- Vercel CLI 63.1.2 authenticated as `abhinav-ranish`; created and linked
  `aranish-uk/ux-guardian-demo`, root directory `demo-app`, Next.js preset.
- Production: https://ux-guardian-demo.vercel.app
- Preview: https://ux-guardian-demo-f4vlvs23b-aranish-uk.vercel.app
- Both deployments reached READY. Disabled SSO/Vercel Authentication on this
  project only; unauthenticated HTTP requests returned 200 without redirects for
  `/`, `/login`, and `/search` on both URLs, without bypass headers or tokens.
- Generated random throwaway seeded credentials, stored as Vercel Secrets for
  Production and Preview and in the git-ignored root `.env`. No values were
  printed, committed, or captured in screenshots.
- Headless Playwright Chromium verified all three journeys on both URLs at
  desktop (1440 x 900) and mobile (390 x 844): seeded sign-in reaches
  "Your account"; search for tote opens the product and adds it to the cart;
  checkout reaches Payment with Place order disabled. Payment was not submitted.
- Fresh `uv run pytest`: 21 passed, 11 local-server browser tests skipped;
  `uv run ruff check .`: passes; `uv run pyright`: zero errors.
- No origin remote is configured; no push or milestone PR was attempted. The CLI's
  automatic attempt to connect the upstream GitHub repository failed; both
  deployments were made directly through the CLI without a Git connection.

M0 acceptance is complete. The live
journey command is a cost/confirmation scaffold and explicitly exits without a
call; the real adapter is M1. Intelligent diff selection, real Fetch/Playwright
acquisition, GitHub publishing and Search/fix enrichment remain M2–M5.
