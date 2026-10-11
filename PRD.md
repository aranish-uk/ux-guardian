# PRD: TinyFish UX Guardian

> **CodeRabbit reviews your code. TinyFish reviews your user experience.**

Status: Draft v1 · Owner: founder@tryada.app · Date: 2026-10-11
Build environment: Windows dev PC, Codex as the implementing agent (see `AGENTS.md`).

---

## 1. Problem

Code review catches code problems. It does not catch "the login button no longer works on mobile" or "checkout now dead-ends after the address step". Those regressions reach production because:

- **Code review is diff-centric.** Nobody clicks through the preview deployment for every PR.
- **E2E suites are brittle and incomplete.** They test what someone remembered to script, and they break on harmless UI changes.
- **Existing AI QA tools** (browser-use swarms, computer-use testers) run locally or on demand. They are not wired into the PR loop, and they don't compare against production, so they can't tell a regression from a pre-existing bug.

## 2. Product summary

UX Guardian runs on every PR that has a preview deployment. It:

1. **Analyzes the diff** to decide which user journeys could be affected.
2. **Sends TinyFish agents through those journeys like a real customer**, on both the preview and production at the Agent API's default desktop viewport, in parallel.
3. **Runs deterministic Playwright checks** on the same pages.
4. **Confirms regressions.** A failure only counts if it happens on preview, does not happen on production, and reproduces on a retry or is backed by a deterministic signal.
5. **Posts one PR comment**, updated in place, with repro steps, severity, before/after screenshots and a fix suggestion.

**Principle:** open source handles the plumbing; TinyFish handles only the intelligence.

## 3. Users and jobs to be done

| User | Job |
|---|---|
| PR author | "Tell me before merge if I broke a customer flow, with proof I can reproduce." |
| Reviewer | "Show me what changed for users, not just in code." |
| Eng lead / QA | "Catch regressions on critical journeys without maintaining a brittle E2E suite." |

## 4. Goals and non-goals

### Goals (MVP)
- **G1. Diff-aware.** Only run journeys plausibly affected by the PR, and explain why each one was selected.
- **G2. Comparative.** Every finding is judged against production, so pre-existing bugs are not blamed on the PR.
- **G3. Low noise.** Report only confirmed regressions. A clean PR gets a short "no regressions" comment.
- **G4. Actionable.** Each finding includes numbered repro steps, severity, screenshots of preview and prod at the failing step, and a fix suggestion grounded in the diff.
- **G5. Fast and cheap.** The comment appears within 10 minutes of the preview being ready, at no more than $3 of TinyFish spend per PR run.

### Non-goals (MVP)
- Multi-repo, multi-preview-provider or monorepo support.
- Authenticated journeys that need real user credentials. Use a seeded test account on the demo app; vault and profiles come later.
- Visual pixel-perfect design review. Playwright screenshot diffs are evidence, not verdicts.
- A hosted SaaS, dashboard or GitHub App. MVP is a GitHub Action.
- Load testing, security testing or accessibility auditing (later phases).

## 5. Hackathon MVP scope (time-boxed)

Exactly:
- **1 repo:** a demo web app we control, for example a small Next.js storefront deployed on Vercel.
- **1 preview URL** per PR, from Vercel's `deployment_status` event. **1 production URL** from config.
- **3 user journeys** defined in `.ux-guardian/journeys.yaml`:
  1. **Sign in.** Log in with the seeded test account and reach the dashboard.
  2. **Search → product → add to cart.**
  3. **Checkout** up to the payment step. Payment is stubbed and must never be submitted.
- **1 automated PR comment**, sticky (updated in place on every push).

Demo script: open three prepared PRs.
- **(a) Real regression.** The sign-in button is hidden behind an overlay on narrow viewports. Expect a P1 finding with repro steps.
- **(b) Broken route.** The cart link goes to a 404 page. Expect a P0 finding, flagged by both Playwright and the agent.
- **(c) Harmless copy change.** Expect "no regressions" and **zero** findings. This proves low noise.

## 6. How it works

```
PR opened/synchronized
        │
        ▼
GitHub Actions: wait for preview (deployment_status: success)
        │
        ▼
[1] Diff analyzer ── changed files + journeys.yaml ──► affected journeys (+reason)
        │
        ▼
[2] Fetch pre-check (TinyFish Fetch, free): fetch each journey's entry URL on preview & prod;
    instant signal for 4xx/5xx, empty render, missing key text
        │
        ▼
[3] Run in parallel ─────────────────────────────────────────────┐
    a. Playwright deterministic checks (preview & prod)          │
       - HTTP status, console errors, failed requests            │
       - key selectors visible/enabled, screenshots @ desktop+mobile
    b. TinyFish Agent swarm (preview & prod, per journey)        │
       - customer-persona goal + structured output_schema        │
       - per-step screenshots + action log                       │
        │◄────────────────────────────────────────────────────────┘
        ▼
[4] Judge: compare preview vs prod per journey → candidate regressions
        │
        ▼
[5] Confirm: a preview-only deterministic hard signal is confirmed immediately;
    agent-only candidates need a retry at the same/earlier step or a matching hard signal
        │
        ▼
[6] Enrich: severity + repro steps + fix suggestion (LLM over diff hunk + evidence;
    TinyFish Search for docs/known issues when the failure involves a third-party lib)
        │
        ▼
[7] Report: upload screenshots, upsert one sticky PR comment, write job summary,
    set check status (fail on P0/P1 if configured)
```

### TinyFish roles (each one does a distinct job)

| Product | Role | Why it's needed |
|---|---|---|
| **Agent** (`/v1/automation/run-async`, `run-batch`) | Acts as the customer: completes each journey on preview and prod and returns structured JSON plus step screenshots. | It's the core intelligence. It survives UI refactors that break scripted selectors. |
| **Fetch** (`api.fetch.tinyfish.ai`) | A cheap pre-check, and page text for the judge: rendered markdown of entry pages on preview vs prod. | It's free. It catches 404s and blank renders in seconds, before spending on agent steps, and gives the LLM judge text to compare. |
| **Search** (`api.search.tinyfish.ai`) | Grounds fix suggestions: looks up framework docs or known issues behind an error string, such as a console error from a library. | It makes suggestions cite real sources instead of guessing. It's optional per finding and skipped when the cause is obvious from the diff. |

## 7. Functional requirements

### FR1. Trigger and preview discovery
- Trigger on `deployment_status` where `state == success` and the environment is `Preview`. Also support `workflow_dispatch` with `preview_url` and `pr_number` inputs for manual and local runs.
- Resolve the PR from the deployment SHA. Skip forks: secrets are unavailable there, so post nothing.
- Production URL comes from `.ux-guardian/config.yaml` (`production_url`).

### FR2. Journey manifest (`.ux-guardian/journeys.yaml`)
```yaml
journeys:
  - id: sign-in
    name: Sign in with test account
    entry_path: /login
    goal: >
      You are a returning customer. Sign in with email {{TEST_EMAIL}} and password
      {{TEST_PASSWORD}}. Confirm you land on your account dashboard.
    success_criteria:
      - Dashboard heading containing "Your account" is visible
    owns:            # globs used by the diff analyzer
      - app/(auth)/**
      - components/auth/**
      - middleware.ts
    critical_selectors:   # for Playwright deterministic checks
      - "button[type=submit]"
    viewports: [desktop, mobile]
    max_steps: 25
```
Test credentials are injected from Action secrets at runtime and never committed.

### FR3. Diff analyzer
- Input: the PR's changed files with patch hunks (truncated to a token budget) and the journey manifest.
- **Stage 1 (deterministic):** select a journey if any changed file matches its `owns` globs.
- **Stage 2 (LLM):** for files that matched nothing, such as shared components, global CSS, layout or config, ask the LLM which journeys they could affect. It must return a reason and a confidence of high, medium or low per journey.
- Always include journeys whose shared dependencies changed: `package.json` dependency bumps, global styles, root layout.
- Output `affected: [{journey_id, reason, source: glob|llm}]`. If nothing is affected, post "No customer-facing journeys affected" with the reasoning and stop.

### FR4. Fetch pre-check
- For each affected journey, fetch `entry_path` on preview and prod in one request (`urls` takes up to 10). Use markdown format.
- Flag immediately: a fetch error on preview but not prod; empty or near-empty text on preview; or `success_criteria` keywords present on prod and missing on preview.
- Pre-check flags feed the judge and never post on their own. Fetch errors, near-empty text and missing keywords remain advisory; only an explicit non-2xx origin status with a passing prod baseline is a deterministic hard signal. Fetch API authentication, quota and extraction errors are not origin HTTP failures.

### FR5. Playwright deterministic checks
- Playwright owns desktop and mobile coverage. Run headless Chromium for every affected journey's entry page and critical selectors on preview and prod at **both** desktop and mobile (iPhone 13 device descriptor with configured dimensions), regardless of Agent viewport support.
- Record: HTTP status, console errors, failed network requests, whether each `critical_selector` is present, visible, enabled and able to receive input (trial actionability detects covering overlays), and a full-page screenshot per (journey, environment, viewport). Never submit forms during these checks.
- Compute a screenshot pixel diff (pixelmatch) as evidence for the report. It is never a verdict on its own.

### FR6. TinyFish agent runs
- Agent runs are **desktop-only**: one run per (journey × environment), at the API's default desktop viewport. TinyFish has no viewport control; reject mobile Agent requests. Playwright owns mobile coverage (FR5). Submit with `run-async` or `run-batch` and poll `GET /v1/runs/{id}`.
- Respect the account concurrency limit (2 by default) with a client-side queue. Make it configurable.
- `goal` is the journey goal with `{{BASE_URL}}`, `{{TEST_EMAIL}}` and similar templated in.
- Prepend this safety preamble to every goal: "Never submit payment, never send messages, never delete data."
- Use this `output_schema`, which the TinyFish restrictions allow (top level is an object, no `oneOf`, `const` or `additionalProperties`):
```json
{
  "type": "object",
  "properties": {
    "completed": {"type": "boolean"},
    "blocked_at_step": {"type": "string"},
    "observed_problem": {"type": "string"},
    "steps": {"type": "array", "items": {"type": "object", "properties": {
      "n": {"type": "integer"}, "action": {"type": "string"}, "observation": {"type": "string"}}}},
    "final_page_summary": {"type": "string"}
  },
  "required": ["completed", "steps"]
}
```
- **`COMPLETED` run status does not mean the journey succeeded.** Pass or fail comes from `result.completed` plus the success-criteria check.
- Store: the run ID, status, result, `steps[].screenshot` URLs and the `streaming_url`. Download screenshots immediately, because URLs may expire.
- Hard caps: `max_steps` per journey (default 25), `max_duration_seconds` 300, and a per-PR budget cap (see NFR3).

### FR7. Judge and confirmation
For each (journey, viewport), compare equivalent preview and production signals. Agent evidence exists only for desktop; mobile findings can be deterministic-only:

| Preview | Prod | Verdict |
|---|---|---|
| fail | pass | **Confirmed** for a deterministic hard signal; otherwise **candidate regression** |
| fail | fail | Pre-existing issue. Not attributed to the PR; listed in a collapsed "pre-existing" section. |
| pass | pass | OK |
| pass | fail | Possible fix. Noted as "improved" in a collapsed section. |

A deterministic Playwright or Fetch hard signal is **confirmed on its own** when it fails on preview and passes on prod. No Agent run or retry is needed. Hard signals: non-2xx origin HTTP status; a critical selector missing, hidden, disabled or covered so it cannot receive input; or a new console error established to block the journey. Compare the same control/error and viewport against prod; transport timeouts are inconclusive. Harmless console errors, failed requests, Fetch text warnings and pixel diffs are evidence only.

Agent-only candidates still require either:
- (a) a second Agent run on preview failing at the same or an earlier step, or
- (b) a matching deterministic hard signal with a passing prod baseline.

Do not confirm a preview-only agent failure using a deterministic failure that also exists on prod.

An unconfirmed candidate goes in a collapsed "flaky / needs human look" section with its evidence and is **not** counted as a finding.

### FR8. Severity rubric
| Severity | Definition | Example |
|---|---|---|
| P0 | A journey can't be completed on any viewport, or there's a hard error such as a 5xx, 404 or blank page. | Cart route 404 |
| P1 | The journey is blocked on one viewport, or needs a non-obvious workaround. | Mobile sign-in button covered by an overlay |
| P2 | The journey completes but is degraded: an extra step, a misleading message, a new console error with no visible impact. | Error toast on success |

Severity is assigned by rules first: P0 for an origin 4xx/5xx or a hard failure on all viewports; P1 for a hard failure on just one viewport. A selector/actionability failure on mobile alone is P1, even though it is independently confirmed. P2 covers degradation without a blocked journey. The LLM can only **lower** severity, with a justification, never raise it.

### FR9. Fix suggestions
- Input: the confirmed finding, the relevant diff hunks (from the files the analyzer linked to the journey), console errors and the agent's `observed_problem`.
- Output: a root-cause hypothesis, a suggested change shown as a unified-diff snippet or a GitHub suggestion block, and a confidence level.
- Call TinyFish Search only when an external error string or library is involved. Cite at most 2 URLs.
- When confidence is low, label it "hypothesis" and show no patch.

### FR10. PR comment (sticky)
- One comment, identified by a hidden `<!-- ux-guardian -->` marker and updated on every run.
- Layout:
  1. **Header:** the verdict ("2 confirmed regressions" or "No regressions"), preview and prod links, run duration and TinyFish cost.
  2. **Journey table:** journey, why it was tested, desktop and mobile results on preview and prod.
  3. **One collapsible block per confirmed finding:** severity badge, title, numbered repro steps (from the agent's step log), side-by-side preview and prod screenshots at the failing step, evidence (Playwright and Fetch signals), the fix suggestion, and a link to the TinyFish run replay.
  4. **Collapsed sections:** pre-existing issues, flaky/unconfirmed, improved.
  5. **Footer:** how to re-run (push again, or comment `/ux-guardian rerun`, which is post-MVP), and a cost breakdown.
- **Screenshot hosting:** upload PNGs to an orphan branch `ux-guardian-assets` under `pr-<n>/<run-id>/…` and embed them with `raw.githubusercontent.com` URLs. MVP assumes a public demo repo. Also upload all evidence as an Actions artifact.
- Also write the same report to `$GITHUB_STEP_SUMMARY`.
- Check run conclusion: `failure` if any confirmed P0 (configurable to include P1), otherwise `success`. Never fail the check on unconfirmed findings.

### FR11. Configuration (`.ux-guardian/config.yaml`)
`production_url`, `preview_url` (local live-check baseline; the Action overrides it from deployment discovery), `viewports`, `concurrency` (default 2), `budget_usd_per_run` (default 3), `fail_on: [P0]`, `llm_provider`, `llm_model`, `confirm_retries: 1`, `include_fetch_precheck: true`, `include_search: true`.

## 8. Non-functional requirements
- **NFR1. Latency:** comment posted within 10 minutes (p50) of the preview being ready, for 3 journeys × 2 environments × 2 viewports.
- **NFR2. Noise:** zero confirmed findings on the harmless-copy PR (demo c) in 5 out of 5 runs. A false-positive rate above 10% on clean PRs blocks release.
- **NFR3. Cost:** estimate before running. Step price is $0.016, so 3 journeys × 2 envs × ~20 desktop Agent steps ≈ $1.92 before confirmation retries. Playwright desktop/mobile and Fetch have no Agent step cost. Reduce spend by skipping prod Agent runs when a cached prod baseline for the same prod deploy SHA is under 24h old. Abort new agent runs once `budget_usd_per_run` is reached, and say so in the comment.
- **NFR4. Security:**
  - Secrets (`TINYFISH_API_KEY`, `LLM_API_KEY`, `TEST_EMAIL`, `TEST_PASSWORD`, `GITHUB_TOKEN`) come only from Action secrets.
  - Never log them, and redact them from step logs and screenshots captions.
  - Never run on fork PRs.
  - Least-privilege workflow `permissions`: `contents: write` (assets branch only), `pull-requests: write`, `checks: write`, `deployments: read`.
- **NFR5. Determinism:** every report is reproducible from the saved artifact JSON (`report.json`) without calling TinyFish again.
- **NFR6. Cross-platform dev:** scripts run on Windows (PowerShell 7) and Linux (CI). Use Python (`uv run …`) entry points, not bash or .ps1, for anything a developer runs locally.

## 9. Foundation: fork `browser-use/vibetest-use`

**Decision:** fork https://github.com/browser-use/vibetest-use. It is MIT per its README, but the repo has no LICENSE file, so keep the attribution in `NOTICE` and the README. Then replace browser-use with TinyFish.

**Why this repo.** Twelve OSS candidates were surveyed: vibetest-use, qa-use, shortest, magnitude browser-agent, testzeus-hercules, Skyvern, Autonoma, bug0 qa-agent, vostride agent-qa, self-testing-github-action, katalepsis and accelute. None does the full PR → diff → swarm → preview-vs-prod → PR-comment loop. vibetest-use already has the hardest part, **the swarm**:
- a scout agent catalogs the page;
- an LLM partitions it into 6–8 test tasks;
- a semaphore-bounded `asyncio.gather` runs the agents, up to 10 at once;
- an LLM summarizes the results into severity-ranked bugs.

It is about 560 lines of Python, and **every browser-use touchpoint is in one file** (`vibetest/agents.py`).

**The swap (one file):**
| vibetest-use today | UX Guardian |
|---|---|
| `scout_page()` uses a browser-use `Agent` to catalog UI elements | Journey-driven, not page-driven. Journeys come from `journeys.yaml`, selected by the diff analyzer. The scout becomes optional, used only for the "explore" persona post-MVP. |
| `run_single_agent()` uses `BrowserSession` + `Agent(...).run()` | `TinyFishAgent.run_journey()`: `run-async` → poll `GET /v1/runs/{id}` → `AgentRun` with step screenshots |
| `browser_use.llm.ChatGoogle` / `UserMessage` for partitioning and summary | A provider-agnostic `LlmClient` (diff analyzer, judge enrichment, fix suggestions) |
| Semaphore of 10 | Semaphore = TinyFish concurrency (default 2) plus the budget guard |
| MCP server entry (`vibetest/mcp_server.py`) | Kept as a bonus entry point; the main entry is a GitHub Action plus CLI |
| Viewport handling | TinyFish Agent uses its default desktop viewport only; Playwright checks every journey on desktop and mobile, including actionability under overlays. |
| Single URL | Each journey runs on both **preview and prod** and goes through the judge (FR7) |

**Borrowed patterns (reference only, no code copied):**
- **browser-use/qa-use** (archived, MIT per its README): the start-task → poll → map-steps-to-pass/fail flow, which matches TinyFish's run/get-run.
- **ka-brian/self-testing-github-action**: the PR flow, i.e. PR patches → test plan, a route sitemap, Octokit comments. It has **no license**, so read it for ideas only and copy no code.
- **Autonoma-AI/autonoma** (BSL 1.1): diff → affected-tests design and PR-comment layout. Ideas only, no code.

## 10. Technical design

### Stack
- **Python 3.12, managed with `uv`**, on the vibetest-use codebase.
- **Distribution:** a composite GitHub Action (`action.yml` → `uv run ux-guardian ...`) plus a CLI (`ux-guardian run --preview-url … --pr …`) for local runs.
- **Libraries:**
  - `tinyfish` (official Python SDK) for Agent, Fetch and Search
  - `playwright` (Python) for deterministic checks
  - `pixelmatch` + `Pillow` for screenshot diffs
  - `httpx`, `githubkit` or `PyGithub`, `pyyaml`, `pydantic` v2 (config and agent-output validation)
  - `typer` for the CLI
  - an LLM SDK behind an `LlmClient` protocol so the provider is swappable
- **Tests and quality:** `pytest` (with fixtures for agent results, diff samples and the judge truth table), `ruff`, `pyright`.
- **Demo app:** a separate small Next.js storefront in `demo-app/` (its own `package.json`, pnpm), deployed on Vercel.

### Module layout
```
ux_guardian/                 # renamed from vibetest/
  config.py            # load + validate config.yaml / journeys.yaml (pydantic)
  diff/analyzer.py     # glob stage + LLM stage -> affected journeys
  agents/base.py       # BrowserAgent protocol + AgentRun model
  agents/tinyfish.py   # TinyFishAgent (queue, poll, budget, screenshot download)  <- the swap
  tinyfish/fetch.py    # precheck
  tinyfish/search.py   # fix-suggestion grounding
  swarm.py             # from vibetest agents.py: semaphore fan-out over journeys x env x viewport
  checks/playwright.py
  judge/judge.py       # truth table + confirmation
  judge/severity.py
  enrich/fix.py
  report/render.py     # markdown comment + step summary (from vibetest summarize_bug_reports)
  report/assets.py     # orphan-branch upload
  github/pr.py         # sticky comment upsert, check run
  run.py               # orchestrator
  cli.py               # typer entry
  mcp_server.py        # kept from vibetest (optional)
action.yml
demo-app/              # Next.js storefront, 3 journeys, seeded regression branches
tests/
```

### `BrowserAgent` seam
```python
class BrowserAgent(Protocol):
    async def run_journey(
        self, *, base_url: str, journey: Journey, viewport: Viewport
    ) -> AgentRun: ...
```
`TinyFishAgent` is the shipped implementation. The judge, report and tests never import a vendor SDK. The original browser-use path can be kept behind the same protocol (`BrowserUseAgent`, optional extra) for a side-by-side benchmark in the demo, which turns the swap into a measurable story: cost, time and success rate per journey.

### Data contracts
- `AgentRun`: `{ runId, env: 'preview'|'prod', journeyId, viewport, status, completed, blockedAtStep?, observedProblem?, steps: [{n, action, observation, screenshotPath}], replayUrl, costUsd }`
- `report.json`: `{ pr, sha, previewUrl, prodUrl, affected[], runs[], checks[], findings[], preexisting[], flaky[], improved[], cost }`

## 11. Milestones (hackathon, time-boxed)
| # | Deliverable | Done when |
|---|---|---|
| M0 | Fork vibetest-use, rename the package, remove browser-use, `uv` project with `pytest`/`ruff`/`pyright` passing; demo app deployed to Vercel with 3 journeys and seeded accounts | Prod URL and one preview URL load; `uv run pytest` is green |
| M1 | `TinyFishAgent` runs one journey and saves the step screenshots | CLI prints pass/fail plus screenshots for sign-in on prod |
| M2 | Playwright checks, Fetch pre-check and judge truth table, with unit tests | Judge tests pass for all 4 table rows plus confirmation logic |
| M3 | Diff analyzer, glob and LLM stages | Correct journeys picked for demo PRs a, b and c |
| M4 | Report rendering, sticky comment, assets branch, Action workflow | Comment appears on a real PR in the demo repo |
| M5 | Fix suggestions, Search grounding, cost and budget guard | Findings show suggestions; the budget abort works |
| M6 | Demo hardening: run a/b/c five times each, tune prompts, record a demo video | NFR1 and NFR2 met |

## 12. Success metrics
- **Recall:** demo PRs a and b are each flagged with the right severity, in 5 out of 5 runs.
- **Precision:** demo PR c gets 0 findings in 5 out of 5 runs.
- **Speed:** p50 under 10 minutes from preview ready to comment.
- **Cost:** p50 at or under $2 per PR run.
- **Usefulness:** a judge can reproduce each finding from the comment alone in under 2 minutes.

## 13. Risks and mitigations
| Risk | Mitigation |
|---|---|
| Agent nondeterminism causes false positives | Compare against prod, confirm with a re-run or a deterministic signal, and send anything unconfirmed to a collapsed section |
| TinyFish concurrency of 2 makes runs slow | A queue; skip prod runs using a cached prod baseline; run only affected journeys; ask TinyFish for a higher limit before the demo |
| Screenshot URLs expire | Download immediately and host on the assets branch plus an artifact |
| `capture_config` / `strict` mode / `max_steps` are account-gated (403) | Don't depend on them. Use step screenshots from the run result and enforce step and time caps client-side; enable them if the account allows |
| Preview needs Vercel auth (deployment protection) | Turn protection off on the demo project, or pass a bypass token header (post-MVP) |
| LLM picks the wrong journeys | The glob stage is authoritative; the LLM only adds. Always print the reasons in the comment |
| Agent performs destructive actions | Safety preamble, a stubbed payment step on the demo app, and test accounts only |

## 14. Long-term vision (explicitly out of the MVP)
- A GitHub App with zero-config install, auto-discovered journeys (crawl plus analytics events), and journey generation from product specs.
- Authenticated journeys through TinyFish Browser Context Profiles and Vault.
- Persona swarms (new user, power user, screen-reader user, slow 3G, non-English locale) running in parallel per journey.
- Production monitoring with TinyFish Monitor, so the same journeys run on a schedule and alert on drift.
- Visual and UX-quality review (copy clarity, layout shift, accessibility) as advisory, non-blocking findings.
- Support for other preview providers (Netlify, Cloudflare Pages, Render) and monorepos.
- Learned flake models per journey; auto-generating a Playwright regression test from each confirmed finding and opening it as a follow-up PR.

## 15. Open questions
1. LLM provider for the diff analyzer, judge and fixes. The default proposal is to make it configurable and use whichever key the team has. Codex/OpenAI is natural given the dev setup.
2. Will TinyFish raise the concurrency limit and enable `capture_config` for the hackathon account?
3. Demo repo visibility: public is assumed, for raw-URL screenshot embedding.

## Decision log

- **2026-10-11 — M2 viewport ownership and deterministic confirmation.** M1 verified that the TinyFish Agent API has no viewport control. Agents remain desktop-only; Playwright checks every journey on desktop and mobile. A preview-only hard deterministic failure confirms a finding without an Agent run. One affected viewport is P1; all viewports or an origin 4xx/5xx is P0. Agent-only failures retain FR7 retry/confirmation requirements. Fetch warnings and pixel differences remain advisory.
