"""Entry-page checks only: no form submission, purchases, or agent calls."""

from pathlib import Path

from PIL import Image
from pixelmatch.contrib.PIL import pixelmatch
from playwright.async_api import Browser, Error, Page, async_playwright

from ux_guardian.checks.models import CheckResult, SelectorResult
from ux_guardian.config import Config, Environment, Journey, Viewport
from ux_guardian.security import redact


async def inspect_selectors(page: Page, selectors: list[str]) -> list[SelectorResult]:
    results = []
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="attached", timeout=5000)
        except Error:
            results.append(SelectorResult(selector=selector, present=False))
            continue
        visible = await locator.is_visible()
        enabled = await locator.is_enabled()
        receives_events = False
        if visible and enabled:
            try:
                # Actionability checks include stability and overlay interception.
                # Trial never clicks, submits, focuses or navigates.
                await locator.click(trial=True, timeout=2000)
                receives_events = True
            except Error:
                pass
        results.append(
            SelectorResult(
                selector=selector,
                present=True,
                visible=visible,
                enabled=enabled,
                receives_events=receives_events,
            )
        )
    return results


async def check_page(
    browser: Browser,
    *,
    config: Config,
    journey: Journey,
    base_url: str,
    env: Environment,
    viewport: Viewport,
    output: Path,
    mobile_device: dict,
) -> CheckResult:
    options = dict(mobile_device) if viewport == "mobile" else {}
    options["viewport"] = config.viewports[viewport]
    context = await browser.new_context(**options)
    try:
        page = await context.new_page()
        result = CheckResult(
            journey_id=journey.id,
            env=env,
            viewport=viewport,
            url=base_url + journey.entry_path,
        )
        page.on(
            "console",
            lambda message: (
                result.console_errors.append(redact(message.text))
                if message.type == "error"
                else None
            ),
        )
        page.on("pageerror", lambda error: result.console_errors.append(redact(str(error))))
        page.on(
            "requestfailed",
            lambda request: result.failed_requests.append(
                redact(f"{request.method} {request.url.split('?')[0]}: {request.failure}")
            ),
        )
        try:
            response = await page.goto(result.url, wait_until="networkidle", timeout=30000)
            result.http_status = response.status if response else None
        except Error:
            # Transport failure is inconclusive, not an HTTP regression.
            result.navigation_error = "Navigation did not settle within the check timeout"
        if result.http_status is not None:
            result.selectors = await inspect_selectors(page, journey.critical_selectors)
        # Console errors are advisory unless independently linked to a blocked
        # critical control; arbitrary console noise must never confirm a finding.
        if any(not item.passed for item in result.selectors):
            result.blocking_console_errors = list(result.console_errors)
        output.mkdir(parents=True, exist_ok=True)
        screenshot = output / f"{journey.id}-{env}-{viewport}.png"
        await page.screenshot(path=str(screenshot), full_page=True, animations="disabled")
        result.screenshot_path = screenshot.as_posix()
        return result
    finally:
        await context.close()


def screenshot_diff(preview: Path, prod: Path, output: Path) -> int:
    """Pad unequal full-page sizes without rescaling or discarding evidence."""
    with Image.open(preview) as first, Image.open(prod) as second:
        size = (max(first.width, second.width), max(first.height, second.height))
        left = Image.new("RGBA", size, "white")
        right = Image.new("RGBA", size, "white")
        left.paste(first.convert("RGBA"), (0, 0))
        right.paste(second.convert("RGBA"), (0, 0))
        diff = Image.new("RGBA", size)
        count = pixelmatch(left, right, diff)
        output.parent.mkdir(parents=True, exist_ok=True)
        diff.save(output)
        return count


async def run_checks(
    *,
    config: Config,
    journeys: list[Journey],
    environments: list[Environment],
    output: Path,
) -> list[CheckResult]:
    results = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            for journey in journeys:
                # Playwright owns both viewports for every journey, regardless
                # of the historical agent viewport list in the manifest.
                for viewport in ("desktop", "mobile"):
                    for env in environments:
                        results.append(
                            await check_page(
                                browser,
                                config=config,
                                journey=journey,
                                base_url=config.preview_url
                                if env == "preview"
                                else config.production_url,
                                env=env,
                                viewport=viewport,
                                output=output,
                                mobile_device=playwright.devices["iPhone 13"],
                            )
                        )
        finally:
            await browser.close()
    for preview in (item for item in results if item.env == "preview"):
        prod = next(
            (
                item
                for item in results
                if item.env == "prod"
                and item.journey_id == preview.journey_id
                and item.viewport == preview.viewport
            ),
            None,
        )
        if prod and prod.screenshot_path and preview.screenshot_path:
            path = output / f"{preview.journey_id}-{preview.viewport}-diff.png"
            preview.pixel_diff_count = screenshot_diff(
                Path(preview.screenshot_path),
                Path(prod.screenshot_path),
                path,
            )
            preview.pixel_diff_path = path.as_posix()
    return results
