"""Run via `uv run ux-guardian demo smoke`; no TinyFish is involved."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect, sync_playwright

BASE_URL = os.environ.get("UX_GUARDIAN_DEMO_URL", "")
pytestmark = [pytest.mark.demo, pytest.mark.skipif(not BASE_URL, reason="Use demo smoke")]


@pytest.fixture(params=[{"width": 1440, "height": 900}, {"width": 390, "height": 844}])
def page(request: pytest.FixtureRequest) -> Iterator[Page]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport=request.param)
        page = context.new_page()
        yield page
        context.close()
        browser.close()


def fill_secret(page: Page, label: str, value: str) -> None:
    try:
        page.get_by_label(label, exact=True).fill(value)
    except Exception:
        pytest.fail("Unable to fill seeded credential field", pytrace=False)


def test_sign_in(page: Page) -> None:
    page.goto(f"{BASE_URL}/account")
    expect(page).to_have_url(f"{BASE_URL}/login")
    fill_secret(page, "Email", os.environ["TEST_EMAIL"])
    fill_secret(page, "Password", os.environ["TEST_PASSWORD"])
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("heading", name="Your account", exact=True)).to_be_visible()
    cookie = next(cookie for cookie in page.context.cookies() if cookie.get("name") == "ux-session")
    assert cookie.get("httpOnly")
    assert cookie.get("sameSite") == "Lax"
    save_screenshot(page, "account")


def test_wrong_credentials_and_forged_session(page: Page) -> None:
    page.goto(f"{BASE_URL}/login")
    fill_secret(page, "Email", os.environ["TEST_EMAIL"])
    fill_secret(page, "Password", "invalid")
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Unable to sign in")).to_have_text(
        "Unable to sign in with those details."
    )
    page.context.add_cookies([{"name": "ux-session", "value": "forged", "url": BASE_URL}])
    page.goto(f"{BASE_URL}/account")
    expect(page).to_have_url(f"{BASE_URL}/login")


def test_search_product_cart(page: Page) -> None:
    page.goto(f"{BASE_URL}/search")
    page.get_by_role("searchbox", name="Search products").fill("tote")
    page.get_by_role("button", name="Search", exact=True).click()
    page.get_by_role("link", name="Everyday tote", exact=True).click()
    page.get_by_role("button", name="Add to cart", exact=True).click()
    page.get_by_role("link", name="View cart", exact=True).click()
    expect(page.get_by_role("heading", name="Your cart", exact=True)).to_be_visible()
    expect(page.get_by_text("Everyday tote", exact=True)).to_be_visible()
    save_screenshot(page, "cart")
    page.reload()
    expect(page.get_by_text("Everyday tote", exact=True)).to_be_visible()


def test_checkout_stops_at_payment(page: Page) -> None:
    page.goto(f"{BASE_URL}/products/everyday-tote")
    page.get_by_role("button", name="Add to cart", exact=True).click()
    page.get_by_role("link", name="View cart", exact=True).click()
    page.get_by_role("link", name="Checkout", exact=True).click()
    page.get_by_label("Full name", exact=True).fill("Demo Customer")
    page.get_by_label("Street address", exact=True).fill("123 Example Street")
    page.get_by_label("City", exact=True).fill("Example City")
    page.get_by_label("Postal code", exact=True).fill("12345")
    page.get_by_role("button", name="Continue to payment", exact=True).click()
    expect(page.get_by_role("heading", name="Payment", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Place order", exact=True)).to_be_disabled()
    expect(page.get_by_text("Payments are disabled in this demo.", exact=True)).to_be_visible()
    assert page.request.post(f"{BASE_URL}/api/payment").status == 404
    save_screenshot(page, "payment")


def test_unknown_product_and_origin_guard(page: Page) -> None:
    response = page.goto(f"{BASE_URL}/products/missing")
    assert response is not None and response.status == 404
    response = page.request.post(
        f"{BASE_URL}/api/login",
        headers={"Origin": "https://other.invalid"},
        data={"email": "invalid", "password": "invalid"},
    )
    assert response.status == 403


def save_screenshot(page: Page, name: str) -> None:
    target = os.environ.get("UX_GUARDIAN_DEMO_ARTIFACTS")
    if target:
        output = Path(target)
        output.mkdir(parents=True, exist_ok=True)
        viewport = page.viewport_size
        width = viewport["width"] if viewport else 0
        page.screenshot(path=str(output / f"{name}-{width}.png"), full_page=True)
