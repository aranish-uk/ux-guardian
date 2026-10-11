# M5 fix enrichment

Build `FixContext` from the confirmed finding and only its relevant changed-file
hunks, then call `await suggest_fix(ctx, llm, search)`. The existing
`ux_guardian.agents.base.LlmClient` protocol is unchanged. The existing
`ux_guardian.llm.OpenAiLlmClient` accepts `output_model=FixSuggestion` for OpenAI
structured output and uses `LLM_API_KEY` plus the configured `llm_model`.
There is no separate fix client and no automatic retry.

CI calls `run.enrich_findings` after judging and optional Agent evidence. It uses
ownership/shared files linked to the journey, falling back to all UI hunks when
none match. Only confirmed findings receive enrichment. A run permits at most
three LLM calls total, including the analyzer call; additional findings display
`Fix suggestion unavailable`. Each enrichment has a 30-second timeout, including
optional Search. Missing credentials, timeouts and provider failures never block
report publication. Saved `report.json` contains the rendered result, so replay
and `run --dry-run` remain offline.

Create one `SearchClient` per pipeline run and share it between findings. It reads
`TINYFISH_API_KEY` from the environment and uses a per-instance query cache and
rolling 30/minute limiter. `should_search(ctx)` is a conservative heuristic for
external errors, recognized library names, package imports and dependency changes.
Generic errors and obvious app overlay/404 evidence do not trigger Search.
Only returned Search URLs can survive the citation gate (maximum two). Optional
Search failures return no sources; unavailable or invalid LLM output displays
`Fix suggestion unavailable`.

`suggest_fix` removes low-confidence, malformed and out-of-scope patches. It accepts
text unified diffs; metadata-only renames, binary and symlink patches are rejected.
Both old and new paths must occur in `ctx.hunks`. The caller can additionally use
`validate_patch(patch, repo_dir)` against a preview checkout; it runs
`git apply --check` and does not apply changes. Rendering does not check applicability.

`render_fix` emits a unified `diff` fence in a collapsible Suggested patch block
for issue comments. GitHub inline suggestion blocks are not used. Low confidence
renders `Hypothesis:` and no patch.

`fixtures/m5_mobile_overlay_fix.json` and `fixtures/m5_broken_cart_fix.json` record
two real structured-output LLM responses, contexts from the seeded demo branch
diffs, and exact rendered Markdown. Both patches passed `git apply --check` against
temporary preview fragments. Replay tests use fake LLMs and make no live calls.
