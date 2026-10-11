<!-- ux-guardian -->
## UX Guardian — 1 confirmed regression

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
| <img width="260" alt="Preview" src="artifacts\m2-mobile-overlay\screenshots\sign-in-preview-mobile.png"> | <img width="260" alt="Production" src="artifacts\m2-mobile-overlay\screenshots\sign-in-prod-mobile.png"> |

**Evidence**

- mobile: selector:button[type=submit]

**Fix suggestion**

**Root-cause hypothesis:** Overlay intercepts input.

Remove pointer interception.

Confidence: high

<details>
<summary>Suggested patch</summary>

```diff
--- a/demo-app/components/auth/login.tsx
+++ b/demo-app/components/auth/login.tsx
@@ -1 +1 @@
-overlay
+button
```

</details>

</details>

### TinyFish agent journeys (desktop)

| Journey | Env | Result | Steps | Cost | Final step | Run ID |
| --- | --- | --- | --- | --- | --- | --- |

No desktop agent journeys were run.

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
