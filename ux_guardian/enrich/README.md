# M5 standalone modules

Build `FixContext` from the confirmed finding and only its relevant changed-file
hunks, then call `await suggest_fix(ctx, llm, search)`. The existing
`ux_guardian.agents.base.LlmClient` protocol is unchanged. `OpenAiFixClient` in
`enrich/llm.py` implements it with OpenAI strict structured output for
`FixSuggestion`; it reads `LLM_API_KEY` and optional `LLM_MODEL` (default
`gpt-4.1-mini`) from the environment. It makes one request, with no retries.

Create one `SearchClient` per pipeline run and share it between findings. It reads
`TINYFISH_API_KEY` from the environment and uses a per-instance query cache and
rolling 30/minute limiter. `should_search(ctx)` is a conservative heuristic for
external errors, recognized library names, package imports and dependency changes.
Generic errors and obvious app overlay/404 evidence do not trigger Search.
Only returned Search URLs can survive the citation gate (maximum two). Optional
Search failures return no sources; unavailable or invalid LLM output becomes a
low-confidence hypothesis.

`suggest_fix` removes low-confidence, malformed and out-of-scope patches. It accepts
text unified diffs; metadata-only renames, binary and symlink patches are rejected.
Both old and new paths must occur in `ctx.hunks`. The caller can additionally use
`validate_patch(patch, repo_dir)` against a preview checkout; it runs
`git apply --check` and does not apply changes. Rendering does not check applicability.

`render_fix` emits a GitHub suggestion for one file and one hunk, including
that hunk's replacement context lines. Attach it to the corresponding original
line range when using an inline review comment. For a new file the block presents
its contents; GitHub cannot apply it as an inline suggestion without an existing
line to attach to. Multiple-file and multiple-hunk patches render as unified diffs.
Low confidence renders `Hypothesis:`
and no patch. This module does not publish comments or modify the pipeline.

`fixtures/m5_mobile_overlay_fix.json` and `fixtures/m5_broken_cart_fix.json` record
two real structured-output LLM responses, contexts from the seeded demo branch
diffs, and exact rendered Markdown. Both patches passed `git apply --check` against
temporary preview fragments. Replay tests use fake LLMs and make no live calls.
