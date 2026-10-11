"""Build the six-page pitch locally; only the two public evidence images use the network."""

from pathlib import Path
from urllib.request import urlretrieve

from playwright.sync_api import sync_playwright


def main() -> None:
    root = Path(__file__).resolve().parent
    images = root / "img"
    images.mkdir(exist_ok=True)
    base = (
        "https://raw.githubusercontent.com/aranish-uk/ux-guardian/"
        "ux-guardian-assets/pr-1/action/shots/"
    )
    for name in ("sign-in-preview-mobile.png", "sign-in-prod-mobile.png"):
        destination = images / name
        if not destination.exists():
            urlretrieve(base + name, destination)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto((root / "index.html").as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready")
        assert page.locator(".slide").count() == 6
        assert page.evaluate(
            "Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)"
        ), "Evidence images failed to load"
        overflow = page.evaluate("""() => Array.from(document.querySelectorAll('.slide'))
            .map((s, i) => ({slide: i + 1, overflow: s.scrollHeight > s.clientHeight}))
            .filter(s => s.overflow)""")
        assert not overflow, f"Slide content overflow: {overflow}"
        page.pdf(
            path=str(root / "UX-Guardian-pitch.pdf"),
            width="1280px",
            height="720px",
            print_background=True,
        )
        browser.close()
    print(root / "UX-Guardian-pitch.pdf")


if __name__ == "__main__":
    main()
