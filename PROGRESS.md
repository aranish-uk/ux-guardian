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

## M1 — TinyFish sign-in adapter and screenshot evidence

2026-10-11, branch `feat/m1`. Continued the uncommitted adapter and CLI work.
The earlier conclusion that the API key was rejected was incorrect.

- Existing run `44b34ea9-e2e1-4198-a80c-4477867e0554` was accepted and then
  cancelled by the old screenshot exception handler. Free authenticated
  `GET /v1/runs/{id}?screenshots=url` returned 200. Returned screenshot URLs
  use `https://agent.tinyfish.ai/runs/{id}/steps/{step}/screenshot`: this missing
  `/v1` path returned 401 both without and with `X-API-Key`. Correcting it to
  `/v1/runs/{id}/steps/{step}/screenshot` with `X-API-Key` returned 200 (JPEG).
  No new Agent run was used to diagnose this. The cancelled run reports
  `num_of_steps: 0`, although three action entries exist; the prior adapter's
  conservative cost estimate was $0.048. Its settled billed cost is not exposed
  by this response and is not claimed as verified.
- Submit, poll and cancel use the Agent host and `X-API-Key`, never Bearer auth.
  Only HTTPS Agent screenshot endpoints receive that header; external signed
  image URLs receive no API key or Authorization header. Redirects are not
  followed with credentials. Screenshot HTTP errors and network/download errors
  warn without response bodies, signed URLs or secrets, and do not cancel runs.
  Submit 401 stops immediately without retry, polling or cancellation.
- One additional paid run was made through the explicit live CLI:
  `3dc7ff0c-1d92-451c-b6dc-dab71679e2dd`, sign-in on production at the Agent's
  default desktop viewport, COMPLETED and PASS. The agent confirmed the
  "Your account" heading. 7 reported steps × $0.016 = **$0.112** actual
  step-based cost; estimate was $0.40 for the 25-step cap. Five JPEG screenshots
  were downloaded to the ignored `artifacts/runs/{id}` directory. Step 6 returned
  404 and was skipped; step 7 had no screenshot. No second run was needed.
  The redacted final API response is committed as
  `ux_guardian/fixtures/tinyfish_sign_in.json`; raw images remain local only.
- Every goal contains FR6's safety preamble, injected credentials, the allowed
  demo origin and explicit success criteria. Passing requires COMPLETED status,
  `result.completed` and `result.success_criteria_met`. JSON and CLI evidence
  are redacted before saving/rendering. The restricted object output schema
  includes a success-criteria boolean and none of the prohibited schema keywords.
- The client queues at configurable concurrency (default 2), reserves estimated
  budget before submitting, and cancels running work at the observed step cap or
  duration cap (maximum 300 seconds). Caps are client-side polling limits, so
  in-flight work can overshoot between polls. Account-gated capture/strict/max-step
  options are opt-in, with fallback only on a named capability rejection.
- Agent API viewport is not controllable: `--viewport mobile` remains rejected
  before confirmation or submission. **Mobile coverage moves to Playwright in
  M2**; this run does not claim a configured pixel-size viewport.
- Regression tests use httpx mocked transports and the recorded redacted response,
  never paid calls: exact hosts/paths/auth for submit, poll, cancel and both image
  types; nonfatal screenshot 401/403/404/500; submit 401; safety/redaction; terminal
  result truth conditions; caps, timeout, capability fallback, origin/mobile
  refusal; bounded concurrency and budget reservation; CLI confirmation/output.
  The old M0 CLI test was updated to the $0.40 estimate and its obsolete confirmed
  scaffold invocation removed, preventing it from starting a live run in pytest.

Validation: `uv run pytest`, `uv run ruff check .`, and `uv run pyright` pass
(45 passed, 11 local-demo browser tests skipped; Ruff clean; Pyright zero errors).
Existing judge truth-table/severity tests and FR10 report snapshot remain green. Local demo browser tests are skipped by
ordinary pytest unless the demo harness is running; M1 adds no browser scripts.
No push was performed; M2–M6 remain out of this commit.
