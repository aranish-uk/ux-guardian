# AGENTS.md: TinyFish UX Guardian

Read `PRD.md` before doing anything. It is the source of truth for scope. If a request conflicts with the PRD, ask before expanding scope.

## Environment
- Windows Server 2025 dev box, PowerShell 7. Python 3.12 + `uv`, Node 24 + pnpm (demo app only), Git, gh, VS Code are installed.
- CI runs on `ubuntu-latest`. Everything must work on both: write dev tooling as Python entry points (`uv run …`), not bash or `.ps1`.
- Use `pathlib`; never hard-code `/` or `\`.
- Browsers for Playwright: `uv run playwright install chromium`.
- No WSL and no Docker on this machine.

## Starting point (M0)
1. `git clone https://github.com/browser-use/vibetest-use upstream-vibetest`. Use it as the base, then rename the package `vibetest/` to `ux_guardian/` per PRD §10.
2. Keep attribution: create `NOTICE` crediting browser-use/vibetest-use (MIT per its README; the upstream repo has no LICENSE file).
3. Remove the `browser-use` dependency entirely. Every touchpoint is in `vibetest/agents.py` (`scout_page`, `run_single_agent`, `summarize_bug_reports`, the `browser_use.llm` imports). See the swap table in PRD §9.
4. Reference-only repos (read for ideas, **copy no code**): `browser-use/qa-use`, `ka-brian/self-testing-github-action` (no license), `Autonoma-AI/autonoma` (BSL).

## Rules
1. **Scope.** Build the hackathon MVP (PRD §5–§11) in milestone order, M0 to M6. Don't start long-term-vision items (§14).
2. **Plumbing is open source; intelligence is TinyFish.** Use the TinyFish Agent, Fetch and Search only for their PRD §6 roles. Use Playwright for deterministic checks. Don't add Stagehand, Skyvern or other agent frameworks; browser-use is allowed only as the optional benchmark adapter.
3. **Vendor isolation.** Only `ux_guardian/agents/tinyfish.py` and `ux_guardian/tinyfish/*` may import `tinyfish`. Everything else depends on the `BrowserAgent` protocol.
4. **Secrets.** Read `TINYFISH_API_KEY`, `LLM_API_KEY`, `TEST_EMAIL` and `TEST_PASSWORD` from the environment or a git-ignored `.env`.
   - Never commit, log or print them.
   - Never put them in fixtures or screenshot captions.
   - Add `.env` to `.gitignore` before creating it.
5. **Money.** Every TinyFish Agent call costs money ($0.016 per step).
   - Tests must use recorded fixtures, never live calls.
   - Live runs only via `uv run ux-guardian live ...`, which prints the estimated cost and asks for confirmation.
   - Respect `budget_usd_per_run`.
6. **Safety.** Agent goals always include the safety preamble from PRD FR6. Never point agents at sites other than the demo app's preview and production URLs.
7. **"Done" means tested.** Each milestone needs:
   - `pytest` tests (the judge truth table and severity rules are mandatory).
   - `ruff check` and `pyright` passing.
   - A short note in `PROGRESS.md` saying what was verified and how.
8. **Commits.** Small and conventional (`feat(agents): …`), one milestone per PR. Never force-push `main`.
9. **Comment output** must match PRD FR10. Keep a snapshot test of the rendered markdown for a fixture `report.json`.

## Commands (create these in M0)
- `uv sync`
- `uv run pytest`, `uv run ruff check .`, `uv run pyright`
- `uv run ux-guardian live journey --journey sign-in --env prod` (one real TinyFish run; prints the cost estimate first)
- `uv run ux-guardian run --preview-url <url> --pr <n> --dry-run` (full pipeline; `--dry-run` uses fixtures)
