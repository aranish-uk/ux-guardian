<!-- ux-guardian -->
## UX Guardian — 1 confirmed regression

[Preview](https://ux-guardian-demo-mqmzr4avw-aranish-uk.vercel.app) · [Production](https://ux-guardian-demo.vercel.app) · 80.81s · TinyFish $0.00

| Journey | Why tested | Preview desktop | Prod desktop | Preview mobile | Prod mobile |
| --- | --- | --- | --- | --- | --- |
| Sign in with test account | All configured journeys (M2 entry checks) | PASS | PASS | PASS | PASS |
| Search → product → add to cart | All configured journeys (M2 entry checks) | PASS | PASS | PASS | PASS |
| Checkout to payment step | All configured journeys (M2 entry checks) | FAIL | PASS | FAIL | PASS |

<details>
<summary>P0 — Checkout to payment step blocked on desktop, mobile</summary>

**Repro steps**

1. Open https://ux-guardian-demo-mqmzr4avw-aranish-uk.vercel.app/cart at 1440px width.
2. Inspect the critical controls and compare with production.

| Preview | Production |
| --- | --- |
| ![Preview](artifacts/m3-broken-cart/screenshots/checkout-preview-desktop.png) | ![Production](artifacts/m3-broken-cart/screenshots/checkout-prod-desktop.png) |

**Evidence**

- desktop: console:Failed to load resource: the server responded with a status of 404 ()
- desktop: http_status
- desktop: selector:a[href=&quot;/checkout&quot;]
- mobile: console:Failed to load resource: the server responded with a status of 404 ()
- mobile: http_status
- mobile: selector:a[href=&quot;/checkout&quot;]
- Fetch: Fetch preview HTTP 404
- Fetch: Fetch entry failed

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

Re-run: dispatch the UX Guardian workflow with the PR number and preview URL. `/ux-guardian rerun` is planned after MVP.

Cost: Agent $0.00 · Fetch $0.00 · Search $0.00 · Total $0.00
