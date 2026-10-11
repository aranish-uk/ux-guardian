# TinyFish UX Guardian

CodeRabbit reviews your code. TinyFish reviews your user experience.

## How it works

1. Diff analyzer → selects customer journeys affected by the PR.
2. TinyFish Fetch pre-check → compares journey entry pages on preview and production.
3. Playwright desktop/mobile checks vs production → captures deterministic signals and screenshots.
4. TinyFish Agent customer journeys → tests preview and production at the default desktop viewport; the judge confirms regressions against the production baseline.
5. Sticky PR comment → repro steps, severity, screenshots and an AI fix suggestion.

## Live demos

- [PR #1: P1 mobile sign-in](https://github.com/aranish-uk/ux-guardian/pull/1)
- [PR #2: P0 broken cart route](https://github.com/aranish-uk/ux-guardian/pull/2)
- [PR #3: clean, 0 findings](https://github.com/aranish-uk/ux-guardian/pull/3)
- [Demo store](https://ux-guardian-demo.vercel.app)

See [the three-minute demo script](docs/DEMO.md) for the walkthrough and architecture.

## Built on open source

A fork of [browser-use/vibetest-use](https://github.com/browser-use/vibetest-use),
with browser-use replaced by TinyFish for customer journeys. Playwright supplies
deterministic desktop/mobile checks; GitHub Actions runs the PR workflow.
The original attribution and [NOTICE](NOTICE) are retained below.

## Honest limitations

- TinyFish Agent has no viewport control. Agents use the default desktop viewport;
  Playwright covers mobile, including controls blocked by overlays.
- Agent concurrency is 2 by default, so runs queue rather than all starting together.
- Returned Agent screenshot URLs omitted `/v1` and failed with HTTP 401. The adapter
  works around this by correcting the Agent-host path to
  `/v1/runs/{id}/steps/{step}/screenshot` before downloading. Some step images can
  still be unavailable; screenshots are evidence, not the regression verdict.
- On this M4 base, dispatch is manual and screenshots are linked through Actions
  artifacts. Agent-only failures remain unconfirmed without a retry; AI fix
  enrichment is separate M5 work. The linked demos show the prepared demo results.

See [PRD.md](PRD.md) and [PROGRESS.md](PROGRESS.md) for scope and verified status.

## Development

Python 3.12, uv, Node 24 and pnpm 12.11.2 are required. These commands work on
Windows and Linux:

```text
uv sync
uv run pytest
uv run ruff check .
uv run pyright
uv run playwright install chromium
```

On Linux, install Chromium's OS dependencies with
`uv run playwright install-deps chromium` if needed.

## Fixture replay

```text
uv run ux-guardian run --preview-url https://preview.example.invalid --pr 1 --dry-run
```

Writes `artifacts/report.json` and `artifacts/report.md` from the recorded M2
mobile-overlay comparison. The supplied URL is never contacted. No credentials
or network are needed; the judge recomputes the finding from saved signals.
Replay the clean comparison with:

```text
uv run ux-guardian run --preview-url https://offline.invalid --pr 1 --dry-run --checks-fixture ux_guardian/fixtures/m2_clean.json
```

## Live checks (M2)

```text
uv run ux-guardian live checks --env both
uv run ux-guardian live checks --env both --preview-url https://ux-guardian-demo-fj66mu9nm-aranish-uk.vercel.app --output artifacts/m2-overlay
```

The first command uses the clean `preview_url` and `production_url` from config.
The second uses the seeded overlay preview. `--env prod` or `--env preview`
acquires one environment only and cannot confirm a comparative finding.
Each run sends one Fetch markdown batch containing the six entry URLs and
checks all three entry pages on desktop and iPhone 13 mobile, with configured
dimensions. Set `TINYFISH_API_KEY` in the environment or ignored `.env` for Fetch.
No Agent runs, credentials in forms, payments, or PR publishing are involved.
Full-page screenshots, padded pixel diffs and reports stay under `artifacts/`.
Pixel differences and Fetch text warnings are evidence only.

A critical control failing only on preview confirms a finding immediately.
Mobile-only blockers are P1; blockers on both viewports or origin 4xx/5xx are P0.
Trial clicks detect overlays without clicking or submitting. Console errors are
considered blocking by acquisition only when a critical control is also blocked;
console noise and failed requests alone do not confirm a finding. These checks
cover entry pages and controls, not complete authenticated journeys.

```text
uv run ux-guardian live journey --journey sign-in --env prod
```

This separate M1 command estimates paid Agent steps and asks for confirmation.
Agents are desktop-only because the API has no viewport control. An estimate
above the configured budget is rejected.
The optional `uv run ux-guardian-mcp` exposes fixture-only `start` and `results`
tools; it cannot launch a paid agent.

## Demo app

M3 diff selection is available offline for the three recorded demo diffs:

```text
uv run ux-guardian analyze --base feat/m0 --head demo/mobile-signin-overlay
uv run ux-guardian analyze --base feat/m0 --head demo/broken-cart-route
uv run ux-guardian analyze --base feat/m0 --head demo/copy-change
```

`--diff-file` accepts unified diff text or a GitHub PR files JSON array.
Ownership globs and shared dependencies are authoritative. Stage 2 adds
high/medium-confidence journeys; low confidence is advisory and selects no runs.
The demo uses one global stylesheet and root layout shared by every entry page,
so changing either selects all three journeys. Patches prefer UI files and use
a conservative UTF-8 byte bound on the token budget, without tokenizer downloads.

Ordinary `analyze` never calls an API. It replays exact-diff recordings and marks
unrecorded unmatched files as requiring LLM review. `--llm-fixture` accepts a
saved live output, verified against the normalized diff's SHA-256. Explicit live
commands use `LLM_API_KEY`, the configured provider/model, and the official SDK:

```text
uv run ux-guardian live models
uv run ux-guardian live analyze --base feat/m0 --head demo/copy-change --output artifacts/analysis.json
```

`live models` makes one free discovery request. `live analyze` makes at most one
billable structured-output request, with retries disabled, and no TinyFish Agent
calls. For demo verification it also reviews owned hunks; that review remains
additive and cannot remove deterministic selections. The full PR orchestration
is a later milestone.

Run these from `demo-app/`:

```text
pnpm install --frozen-lockfile
pnpm build
pnpm typecheck
```

From the repository root:

```text
uv run ux-guardian demo smoke
uv run ux-guardian demo smoke --unseeded
uv run ux-guardian demo serve
```

The smoke command starts the production build on a free loopback port, generates
an ephemeral seeded account in memory, runs pytest on desktop and mobile, and
stops the server. It saves screenshots of the account, cart and disabled payment
step under `artifacts/demo/`. It never captures credential fields, session storage,
or request bodies. The unseeded test verifies that missing credentials refuse login.

For manual use, provide `TEST_EMAIL` and `TEST_PASSWORD` in the environment or a
root `.env` (already ignored). No default account or password exists. The CLI loads
`.env` without overriding existing environment variables and the demo inherits
those variables. Do not put credentials in tracked files or paste them into logs.

Journeys:

- `/login` → environment-seeded account → `/account`.
- `/search` → `/products/everyday-tote` → `/cart` (persists in localStorage).
- `/cart` → `/checkout` → address → payment stub. Place order is disabled;
  there is no payment endpoint.

The seeded account is a demo-only environment-backed identity; sessions use
signed expiring HttpOnly cookies. This is not a general-purpose account system.

## Vercel handoff

The hosted demo and clean preview are configured in `.ux-guardian/config.yaml`.
The seeded regression is on `demo/mobile-signin-overlay`, based on `feat/m0`,
with its preview URL and verification recorded in [PROGRESS.md](PROGRESS.md).
The project Root Directory is `demo-app`; a linked branch worktree deploys
from its repository root with `npx vercel@63.1.2 deploy` (preview target).
Use Vercel Preview environment secrets; do not promote the regression to production.

## Attribution

Based on [browser-use/vibetest-use](https://github.com/browser-use/vibetest-use)
at commit `fe0b90ac9d6a129ce06f5b53074241a9f205015b`, with original history
preserved. Upstream declares MIT in its README and has no LICENSE file.
See [NOTICE](NOTICE). The bounded asyncio swarm and optional MCP interface are
adapted; browser-use and its provider-specific LLM dependencies are removed.
No code was copied from the reference-only repositories listed in the PRD.
## Manual M4 workflow

After the supervisor merges the workflow to `main`, dispatch it for an existing
same-repository demo PR and its Vercel preview:

```text
gh workflow run ux-guardian.yml --ref main -f pr_number=123 -f preview_url="https://ux-guardian-demo-PREVIEW-aranish-uk.vercel.app" -f base_ref=main -f agent_runs=false
```

Replace the PR number and preview URL with the demo PR's values. Configure Action
secrets `TINYFISH_API_KEY`, `LLM_API_KEY`, `TEST_EMAIL`, and `TEST_PASSWORD`.
GitHub supplies `GITHUB_TOKEN`. The trusted `base_ref` supplies Guardian code and
configuration; PR code is read as diff data through the API and never checked out.
Fork PRs are rejected before acquisition or publication.

The workflow selects journeys, runs free Fetch and deterministic desktop/mobile
checks against preview and production, judges and renders the evidence, and
updates one `<!-- ux-guardian -->` comment. It uploads reports and screenshots
even when a confirmed P0 makes the pipeline fail, and writes the report to the
job summary. Screenshot links open the workflow run's artifact download area.
No assets branch or deployment event is used in this slim M4.

For a local CI invocation, supply `GITHUB_REPOSITORY=owner/repo` and `GITHUB_TOKEN`
in the environment, then use `uv run ux-guardian ci --pr 123 --preview-url URL`.
The command prints the sticky comment URL; configured `fail_on` findings exit 1.
Without an LLM key, unmatched files conservatively select all journeys.

Paid Agent runs require `agent_runs=true` (or CLI `--agent-runs`). That explicit
opt-in authorizes the displayed estimate. Desktop-only preview/production pairs
divide a budget of at most $2 into step caps (three pairs: 20 steps each, $1.92).
Agent-only failures remain unconfirmed because this slim milestone does not run
paid confirmation retries; deterministic regressions still confirm independently.
