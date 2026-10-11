# M0 execution ledger

- Approved design: user approved M0 implementation in chat on 2026-10-11.
- Plan executed inline on feat/m0; the initial repo had no commits, so preserving
  upstream history and switching to a feature branch established the working base.
- Task 1: contract tests failed on missing modules, then passed after implementation.
  Truth table, severity, completion semantics, bounded concurrency, config safety,
  CLI paid gate, fixture replay and report snapshot verified.
- Task 2: browser tests initially failed at login because NextURL canonicalizes
  loopback hosts. Installed-code inspection identified the cause; Host-based origin
  comparison and redirect preserve the browser's origin. Unseeded login then passed.
- Task 2: strict alert locator matched Next's route announcer; scoped the locator to
  the application's error text. All ten desktop/mobile cases then passed.
- Security: escaped-secret regression test failed with post-JSON string redaction;
  moved redaction to structured values before serialization and verified it passes.
- Scope: pure judge/severity/renderer foundations are present because AGENTS.md
  mandates their tests per milestone. Real signal acquisition and publishing remain
  later milestones. Fixtures are explicitly synthetic, not represented as live runs.
- Task 3: Vercel whoami reports loggedIn false and project inspection starts device
  login. GitHub authentication and origin are also absent. Hosted acceptance is pending.
- Final: fixed review finding (redaction after Markdown escaping) — strengthened
  escaped-secret test RED→GREEN; shared redact_model before rendering covers MCP
  and file output. Foundation suite 21/21, Ruff and Pyright pass.
- Final: declined-to-judge decisions — hosted/GitHub authentication remains a
  recorded external blocker; Linux CI is unexecuted locally; browser/build checks
  have local evidence; M1–M6 items remain deferred per milestone order; auth is
  intentionally seeded-demo-only; upstream MIT status is stated accurately without
  asserting that a missing license file has been supplied.
