# TinyFish UX Guardian pitch

Rebuild from the repository root:

```text
uv run python pitch/build.py
```

`index.html` is the six-slide source. `img/` contains the two public PR #1
evidence screenshots. The builder downloads them only if missing, then renders
locally with Playwright Chromium at 1280 × 720 CSS pixels, with backgrounds.
No TinyFish or LLM API calls are made.

Verified: all six layouts visually reviewed, both images loaded, no slide overflow,
six PDF pages at 960 × 540 points (16:9), and `ruff check pitch/build.py` passed.
Demo figures and results are supplied pitch claims; the future GitHub App,
personas, and Monitor are labeled as vision.
