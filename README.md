# TinyFish UX Guardian

CodeRabbit reviews your code. TinyFish reviews your user experience.

M0 establishes the Python foundation and a three-journey demo storefront.
Live TinyFish integration begins in M1; signal acquisition, diff intelligence,
GitHub reporting and enrichment follow in M2–M5. See [PRD.md](PRD.md) and
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

Writes `artifacts/report.json` and `artifacts/report.md`. Evidence is a **synthetic
contract fixture**, not a live recording. The supplied URL is never contacted;
no SDK is instantiated, no credentials are needed and no TinyFish cost is incurred.
M0 does not yet acquire evidence or publish a PR comment. The fixture report
is reproducible offline and its markdown layout has a snapshot test.

```text
uv run ux-guardian live journey --journey sign-in --env prod
```

This reserved paid-run command shows the maximum step-cost estimate and asks
for confirmation. In M0 it then exits explicitly without a live call. The working
TinyFish adapter is M1. An estimate above the configured budget is rejected.
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

No Vercel token or saved login was available during initial implementation.
Authenticate locally with `pnpm dlx vercel@63.1.2 login`, then link a dedicated
`ux-guardian-demo` project from `demo-app/`. For Git integration, select `demo-app`
as the project's Root Directory. Configure `TEST_EMAIL` and `TEST_PASSWORD` as
Vercel secrets for both Preview and Production; keep them out of build arguments.

Inspect the linked project before deploying. Deploy the verified source once as
preview and once as production. Preview must be publicly reachable by TinyFish:
PRD section 13 permits disabling protection on this demo project. Set the verified
production URL in `.ux-guardian/config.yaml` and record both real URLs in
`PROGRESS.md`. The current localhost URL is explicitly a local placeholder.
M0 remains incomplete until both hosted URLs load.

## Attribution

Based on [browser-use/vibetest-use](https://github.com/browser-use/vibetest-use)
at commit `fe0b90ac9d6a129ce06f5b53074241a9f205015b`, with original history
preserved. Upstream declares MIT in its README and has no LICENSE file.
See [NOTICE](NOTICE). The bounded asyncio swarm and optional MCP interface are
adapted; browser-use and its provider-specific LLM dependencies are removed.
No code was copied from the reference-only repositories listed in the PRD.
