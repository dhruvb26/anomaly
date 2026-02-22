from __future__ import annotations

from playwright.async_api import async_playwright


class AsyncBrowserManager:
    """Manages a single Playwright browser/page lifecycle for web tools."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._page = None

    async def page(self):
        if self._page is None or self._page.is_closed():
            if self._pw is None:
                self._pw = await async_playwright().start()
            if self._browser is None or not self._browser.is_connected():
                self._browser = await self._pw.chromium.launch(
                    headless=False,
                    channel="chrome",
                )
            self._page = await self._browser.new_page()
            await self._page.set_viewport_size({"width": 1280, "height": 900})
        return self._page

    async def close(self) -> None:
        if self._page and not self._page.is_closed():
            await self._page.close()
        if self._browser and self._browser.is_connected():
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._pw = self._browser = self._page = None
