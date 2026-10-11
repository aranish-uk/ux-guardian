"""Login must fail closed when no seeded account is configured."""

import os

import pytest
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.skipif(
    os.environ.get("UX_GUARDIAN_DEMO_UNSEEDED") != "1", reason="Use demo smoke --unseeded"
)


def test_missing_credentials_refuse_login() -> None:
    url = os.environ["UX_GUARDIAN_DEMO_URL"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        response = context.request.post(
            f"{url}/api/login",
            headers={"Origin": url},
            form={"email": "invalid", "password": "invalid"},
        )
        assert response.status == 503
        assert not context.cookies()
        page = context.new_page()
        page.goto(f"{url}/account")
        assert page.url == f"{url}/login"
        browser.close()
