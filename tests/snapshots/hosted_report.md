<!-- ux-guardian -->
## UX Guardian — 1 confirmed regression

[Preview](https://preview.example.invalid) · [Production](https://production.example.invalid) · 0s · TinyFish $0.00

> Synthetic fixture replay — no website was tested and no API was called.

| Journey | Why tested | Preview desktop | Prod desktop | Preview mobile | Prod mobile |
| --- | --- | --- | --- | --- | --- |
| Sign in with test account | M0 contract fixture; not selected from a real diff. | PASS | Not run | Not run | Not run |
| Search → product → add to cart | M0 contract fixture; not selected from a real diff. | Not run | Not run | Not run | Not run |
| Checkout to payment step | M0 contract fixture; not selected from a real diff. | Not run | Not run | Not run | Not run |

<details>
<summary>P1 — Mobile sign-in is blocked by an overlay</summary>

**Repro steps**

1. Open /login at 390 × 844.
2. Fill the seeded test-account fields.
3. Click Sign in; the overlay intercepts the click.

| Preview | Production |
| --- | --- |
| <img width="260" alt="Preview" src="https://raw.githubusercontent.com/o/r/ux-guardian-assets/pr-42/run-123/shots/preview.png"> | Not recorded |

**Evidence**

- Preview fails; production passes on mobile.
- Synthetic retry fails again at step 2.
- Playwright: Sign in cannot receive pointer events.
- Fetch: login entry page renders on both environments.

**Fix suggestion**

**Hypothesis:** Inspect the overlay positioning in the diff.

No patch is proposed without a real diff.

Confidence: low

</details>

### TinyFish agent journeys (desktop)

| Journey | Env | Result | Steps | Cost | Final step | Run ID |
| --- | --- | --- | --- | --- | --- | --- |
| Sign in with test account | Preview | PASS | 2 | $0.00 | <img width="220" alt="Final step" src="https://raw.githubusercontent.com/o/r/ux-guardian-assets/pr-42/run-123/agent/abcdefgh-final.jpg"> | abcdefgh |

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

[Full evidence (zip)](https://github.com/o/r/actions/runs/123#artifacts)
