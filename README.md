# TinyFish UX Guardian

CodeRabbit reviews your code. TinyFish reviews your user experience.

M0–M2 provide the demo storefront, desktop TinyFish Agent adapter, desktop/mobile
Playwright checks, free Fetch pre-check and comparative judge. Diff intelligence,
GitHub publishing and enrichment follow in M3–M5. See [PRD.md](PRD.md) and
[PROGRESS.md](PROGRESS.md) for scope and verified status.

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
