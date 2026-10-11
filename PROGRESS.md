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


## M2 — deterministic desktop/mobile checks, Fetch and comparative judge

2026-10-11, branch `feat/m2` created from `feat/m1`.

Decision: TinyFish Agents remain desktop-only because the API has no viewport
control. Playwright owns both desktop (1440 × 900) and mobile (iPhone 13 descriptor,
configured 390 × 844) for every journey's entry page and critical controls.
FR5, FR6, FR7, the section 9 viewport swap row and the dated PRD Decision log now
reflect this; FR4, FR8 and the Agent cost example were aligned as well.

Implemented and verified:

- Playwright records origin HTTP status, console/page errors, failed requests,
  selector presence/visibility/enabled state and trial-click actionability.
  Trial clicks detect overlays without submitting forms or navigating. Each
  journey/environment/viewport has a full-page PNG; pixelmatch + Pillow pads
  unequal page sizes and writes a diff PNG and pixel count as evidence only.
- Fetch makes one `POST https://api.fetch.tinyfish.ai` batch per live command,
  using `X-API-Key`, markdown and `ttl: 0`. Both live comparisons returned all
  six entry pages with no Fetch flags. Exactly two free batch calls (12 entry
  URLs total) were made; no Agent runs or paid steps were started.
  Per-URL extraction errors, near-empty text (<40 characters) and missing
  success-criteria text are advisory. Only structured origin HTTP errors count
  as hard signals; service/auth/quota/transport errors cannot confirm findings.
  The documented results[]/errors[] contract is covered by mocked transports;
  successful Fetch results establish a fetched baseline without inventing an
  exact origin HTTP status. No redirects forward the API key and no retries
  multiply live calls.
- Pure judge functions cover all four rows for deterministic-only mobile and
  Agent-only desktop paths. Preview-only hard signals confirm without Agents.
  Controls are compared against the same observed prod control; unknown or
  failed baselines do not establish a pass. Agent-only candidates still need
  a second preview attempt failing at the same/earlier step or a new hard signal.
  Tests cover absent/hidden/disabled/covered controls, HTTP status, blocking
  console errors, pre-existing failures, improvement, noisy console errors,
  failed requests, pixel changes and unknown navigation baselines.
- Severity aggregation: a control blocker on one viewport is P1; blockers on
  both viewports or an origin 4xx/5xx are P0. Console errors are marked blocking
  by acquisition only when critical-control checks independently show blockage;
  arbitrary console errors alone remain evidence. These are entry-page checks,
  not a claim that complete authenticated journeys were executed.

Real deployment comparisons:

- Production (unchanged): https://ux-guardian-demo.vercel.app
- Clean preview (config default):
  https://ux-guardian-demo-f4vlvs23b-aranish-uk.vercel.app
- Seeded preview:
  https://ux-guardian-demo-fj66mu9nm-aranish-uk.vercel.app
- `demo/mobile-signin-overlay` was created from `feat/m0` in the ignored
  `.worktrees/mobile-signin` worktree. Commit `243e847` adds an overlay on the
  sign-in submit button only below 640px. Deployed from that branch using
  `npx vercel@63.1.2 deploy --yes`; deployment
  `dpl_7TvnwQ8AD5t7jsXiKbpgBWAZkJ16` reached READY with Preview target and no
  production URL. No production deployment/promotion or configuration change
  was performed.
- `uv run ux-guardian live checks --env both --output artifacts/m2-clean`:
  **12 PASS checks, zero findings**, 52.75 seconds, TinyFish $0.00.
- `uv run ux-guardian live checks --env both --preview-url
  https://ux-guardian-demo-fj66mu9nm-aranish-uk.vercel.app --output
  artifacts/m2-mobile-overlay`: **one confirmed P1 mobile sign-in finding**,
  11 PASS checks and the preview/mobile sign-in FAIL, 53.17 seconds, TinyFish
  $0.00. The control was present, visible and enabled but could not receive
  input; production/mobile and preview/desktop passed. All search/cart and
  checkout entry controls passed. Screenshot inspection confirms the covering
  overlay and blank credential fields.
- Reports recorded as `ux_guardian/fixtures/m2_clean.json` and
  `ux_guardian/fixtures/m2_mobile_overlay.json`, with FR10 Markdown snapshots.
  Screenshots and diff PNGs remain under ignored `artifacts/m2-*` directories.
  Nonzero mobile pixel diffs also occur on the clean preview (preview toolbar);
  they correctly produce zero findings.
- `run --dry-run` defaults to the recorded overlay evidence; `--checks-fixture`
  selects another saved report. Tests replay both recordings with acquisition
  functions disabled, recomputing findings without Agents or any API call.
  The legacy M0 synthetic report snapshot/retry tests remain green.

Validation on Windows: `uv run pytest` **91 passed, 11 local-demo harness tests
skipped**; `uv run ruff check .` passes; `uv run pyright` zero errors. A network-free
inline-HTML Chromium test proves overlays fail actionability despite visible,
enabled controls and proves trial checks never invoke click handlers. CI now
installs Chromium and Linux browser dependencies before pytest. Linux was not
executed on this Windows box; the existing Windows/Ubuntu matrix verifies it
when pushed. A CLI dry-run smoke and `git diff --check` also pass.

M2 acceptance is complete. No push, PR publishing, Agent call, payment submission
or production modification was performed. M3–M6 remain out of scope.

## M3 — authoritative diff selection and additive OpenAI inference

2026-10-11, `feat/m3` created from `feat/m2`.

- Normalizes unified diffs, `git diff <base>...<head>` and GitHub PR files JSON
  to changed files, old/new paths and patch hunks. Ownership globs operate on
  app-relative paths (the demo-app prefix is removed), including deleted and
  renamed paths. Root layout, global CSS, middleware and dependency changes
  conservatively select all demo journeys: every entry page shares the demo's
  root layout/styles/dependency graph. Shared reasons are deterministic.
- The LlmClient protocol now has an official OpenAI SDK adapter. Provider/model
  come from config; LLM_API_KEY comes from environment/ignored .env. Pydantic
  validates structured JSON, confidence and known journey IDs. Stage 2 reviews
  unmatched files and can only add journeys. Low confidence remains advisory
  and selects no Agent runs. Patches prefer UI files and use a UTF-8 byte upper
  bound on byte-BPE tokens; this is conservative and requires no tokenizer
  network downloads. Prompt data and saved reasons are redacted.
- `analyze` is offline: exact normalized-diff SHA-256 recordings complete stage
  2 for the demo branches. Unknown unmatched files report "LLM review required"
  instead of claiming no impact. `--diff-file` accepts text or PR-files JSON;
  `--llm-fixture` replays a saved live output only for its matching diff.
- One explicit `uv run ux-guardian live models` made one free models.list call.
  The key includes gpt-6-luna, gpt-5.6-luna, gpt-5.4-nano and other models.
  Chose **gpt-6-luna**, available to this key and documented as a current efficient
  model for focused workloads, with structured outputs. Official pricing is
  $0.10 input / $0.50 output per million tokens:
  https://developers.openai.com/api/docs/models/gpt-6-luna.
  The SDK uses Responses parse with Pydantic, store=false, an output cap and zero
  retries. Ordinary tests/CLI never instantiate a live SDK client.
- Live verification used explicit `live analyze --base feat/m0 --head <branch>`:
  (a) all three journeys selected by authoritative global-CSS sharing; the LLM
  independently identified sign-in at high confidence; (b) search-cart and
  checkout selected by the deleted cart ownership path, with LLM medium/high
  confidence respectively; (c) no journeys, no findings and no Agent runs.
  Four inference calls total: one per demo plus a repeated copy analysis after
  correcting a Windows-default text decoding error that altered a Unicode arrow.
  The final copy diff preserves every character except the marketing sentence.
  All three final responses and real diffs against feat/m0 are committed fixtures.
  Live demo verification also reviews owned hunks to meet the one-call-per-demo
  check; it still cannot remove glob/shared selections.

Preview-only demo deployments from branches based on `feat/m0`:

- `demo/broken-cart-route`, commit `86f91aa`: moves app/cart to app/bag while
  leaving navigation and add-to-cart links pointing at `/cart`, which now 404s.
  https://ux-guardian-demo-mqmzr4avw-aranish-uk.vercel.app
  Deployment dpl_9jhQ8JxQE7PZE9MWqzm9dHL6vA8t reached READY, productionUrl null.
- `demo/copy-change`, final commit `299a62a`: marketing sentence change only.
  https://ux-guardian-demo-a9nq91ptg-aranish-uk.vercel.app
  Deployment dpl_CrU43uHvZAjQNmbj16iRCu91eUEL reached READY, productionUrl null.
  The earlier copy preview was superseded after preserving Unicode.
- Both deployed with `npx vercel@63.1.2 deploy --yes` from their ignored branch
  worktrees. No --prod, promotion, Git connection or project configuration edit.
  Production remains https://ux-guardian-demo.vercel.app.

`uv run ux-guardian live checks --env both --preview-url
https://ux-guardian-demo-mqmzr4avw-aranish-uk.vercel.app --output
artifacts/m3-broken-cart` ran all M2 checks: 10 PASS, checkout preview desktop
and mobile FAIL with origin 404, passing prod baselines, **one confirmed P0**,
80.81 seconds, TinyFish $0.00, no Agents. Fetch made one free six-URL batch;
its extraction warnings remain advisory. Report JSON is recorded in
ux_guardian/fixtures/m3_broken_cart.json; screenshots/diffs remain ignored local
artifacts. The M3 FR10 Markdown snapshot and replay recompute the P0 offline.
Unauthenticated HTTP checks also verified broken `/cart` 404, production `/cart`
200, and final copy preview 200 with the expected marketing sentence.

Validation: pytest 124 passed, 11 local-demo harness tests skipped; Ruff clean;
Pyright zero errors. M3 tests cover demo selections and both input formats,
authoritative/additive behavior, low-confidence no-run behavior, malformed or
unknown LLM results, shared dependencies, script-only config changes, glob
semantics, rename/delete/binary/plain diffs, truncation and redaction, offline
CLI replay and stale-record rejection, SDK requests and sanitized no-retry
errors. Existing judge truth table, severity rules and report snapshots pass.
Linux execution remains delegated to the existing CI quality matrix.

No TinyFish Agent run, payment submission, push, remote/credential configuration,
or production modification. M3 acceptance is complete; M4–M6 remain outstanding.

## M4 — slim manual workflow (2026-10-11)

Implemented on `feat/m4` from `feat/m3`, for local commit and supervisor handoff.
The authorized M4 scope uses workflow_dispatch only, read-only contents access,
and screenshot links to Actions artifacts instead of an assets branch. Inputs
are PR number, existing demo preview URL, trusted base_ref (default main), and
agent_runs (default false). The workflow installs uv/locked dependencies and
Chromium, invokes the CI command, and always uploads available evidence.

`ux-guardian ci` reads PR metadata and paginated changed files through httpx,
rejects forks and incomplete file lists, analyzes affected journeys, runs Fetch
then both Playwright viewports on preview/prod, judges, renders, writes JSON and
Markdown plus the job summary, and upserts the marker-keyed comment. It prints
the comment URL and exits 1 on configured fail_on severities (default P0).
Missing LLM credentials conservatively select all journeys for unmatched files.

Optional Agents use the BrowserAgent seam, only affected journeys and desktop
preview/prod pairs, with an estimated budget capped at min(config budget, $2).
The budget divides into per-journey step caps (three pairs: 20 steps, $1.92).
Agent-only failures remain in the unconfirmed section; paid confirmation retries
and diff-grounded fix suggestions remain deferred. Existing adapter polling
and cancellation enforce client-side caps; actual billing depends on TinyFish's
step reporting and cancellation latency. No paid call was made in this work.

Verified: `uv run pytest -q` **140 passed, 11 local-demo tests skipped**;
`uv run ruff check .` passed; `uv run pyright` zero errors. Sixteen M4 tests
use MockTransport and recorded evidence: create/update and pagination, sanitized
API errors, fork rejection before acquisition/publication, safe demo origins,
selected-only acquisition, clean/no-journey early stop, conservative fallback,
Fetch-before-Playwright order, confirmed mobile P1 and route P0, fail_on exit,
artifact links, step summary, saved-JSON rendering, Agent-off defaults and
desktop budget allocation. Updated all FR10 snapshots for singular regression
and manual rerun wording; mandatory judge/severity tests remain green.

No GitHub credentials are available here, so real PR publication and Linux
workflow execution remain for the supervisor after push/merge and dispatch.
Nothing was pushed, deployed, merged, or sent to a live API.
