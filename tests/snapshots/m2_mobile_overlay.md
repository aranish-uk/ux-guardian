<!-- ux-guardian -->
## UX Guardian — 1 confirmed regressions

[Preview](https://ux-guardian-demo-fj66mu9nm-aranish-uk.vercel.app) · [Production](https://ux-guardian-demo.vercel.app) · 53.17s · TinyFish $0.00

| Journey | Why tested | Preview desktop | Prod desktop | Preview mobile | Prod mobile |
| --- | --- | --- | --- | --- | --- |
| Sign in with test account | All configured journeys (M2 entry checks) | PASS | PASS | FAIL | PASS |
| Search → product → add to cart | All configured journeys (M2 entry checks) | PASS | PASS | PASS | PASS |
| Checkout to payment step | All configured journeys (M2 entry checks) | PASS | PASS | PASS | PASS |

<details>
<summary>P1 — Sign in with test account blocked on mobile</summary>

**Repro steps**

1. Open https://ux-guardian-demo-fj66mu9nm-aranish-uk.vercel.app/login at 390px width.
2. Inspect the critical controls and compare with production.

| Preview | Production |
| --- | --- |
| ![Preview](artifacts\m2-mobile-overlay\screenshots\sign-in-preview-mobile.png) | ![Production](artifacts\m2-mobile-overlay\screenshots\sign-in-prod-mobile.png) |

**Evidence**

- mobile: selector:button[type=submit]

**Fix suggestion**

Pending diff-grounded enrichment (M5).

</details>

<details>
<summary>Pre-existing issues (0)</summary>

None.

</details>

<details>
<summary>Flaky / needs human look (0)</summary>

None.

</details>

<details>
<summary>Improved (0)</summary>

None.

</details>

Re-run: push again once the Action is configured (M4). `/ux-guardian rerun` is planned after MVP.

Cost: Agent $0.00 · Fetch $0.00 · Search $0.00 · Total $0.00
