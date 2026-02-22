from __future__ import annotations

from langchain_core.tools import tool

from .manager import AsyncBrowserManager

_browser = AsyncBrowserManager()


@tool
async def web_navigate(url: str) -> str:
    """Navigate to a URL and return the page title and visible text content.

    Args:
        url: The URL to navigate to.
    """
    try:
        page = await _browser.page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        title = await page.title()
        content = await page.inner_text("body")
        if len(content) > 20_000:
            content = content[:20_000] + "\n… [truncated]"
        return f"Title: {title}\nURL: {page.url}\n\nContent:\n{content}"
    except Exception as exc:
        return f"Error navigating to {url}: {exc}"


@tool
async def web_get_page_content() -> str:
    """Get the full visible text content of the current page."""
    try:
        page = await _browser.page()
        content = await page.inner_text("body")
        if len(content) > 30_000:
            content = content[:30_000] + "\n… [truncated]"
        return f"URL: {page.url}\nTitle: {await page.title()}\n\n{content}"
    except Exception as exc:
        return f"Error getting page content: {exc}"


@tool
async def web_click(selector: str) -> str:
    """Click an element on the current page by CSS selector.

    Args:
        selector: CSS selector of the element to click.
    """
    try:
        page = await _browser.page()
        await page.click(selector, timeout=10_000)
        await page.wait_for_load_state("domcontentloaded")
        return f"Clicked '{selector}'. Current URL: {page.url}"
    except Exception as exc:
        return f"Error clicking '{selector}': {exc}"


@tool
async def web_fill(selector: str, value: str) -> str:
    """Fill a form field on the current page.

    Args:
        selector: CSS selector of the input element.
        value: The text to type into the element.
    """
    try:
        page = await _browser.page()
        await page.fill(selector, value, timeout=10_000)
        return f"Filled '{selector}' with '{value}'"
    except Exception as exc:
        return f"Error filling '{selector}': {exc}"


@tool
async def web_screenshot(file_path: str = "/tmp/screenshot.png") -> str:
    """Take a screenshot of the current page and save it.

    Args:
        file_path: Local file path to save the screenshot.
    """
    try:
        page = await _browser.page()
        await page.screenshot(path=file_path, full_page=True)
        return f"Screenshot saved to {file_path}. Current URL: {page.url}"
    except Exception as exc:
        return f"Error taking screenshot: {exc}"


@tool
async def web_go_back() -> str:
    """Navigate back to the previous page in browser history."""
    try:
        page = await _browser.page()
        await page.go_back(wait_until="domcontentloaded")
        return f"Navigated back. Current URL: {page.url}"
    except Exception as exc:
        return f"Error navigating back: {exc}"


@tool
async def web_get_links() -> str:
    """Extract all links (anchor tags) from the current page."""
    try:
        page = await _browser.page()
        links = await page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                text: a.innerText.trim().substring(0, 100),
                href: a.href
            })).filter(l => l.text && l.href)"""
        )
        if not links:
            return "No links found on the current page."
        lines = [f"- [{link['text']}]({link['href']})" for link in links[:50]]
        suffix = f"\n… and {len(links) - 50} more" if len(links) > 50 else ""
        return f"Found {len(links)} links (showing up to 50):\n" + "\n".join(lines) + suffix
    except Exception as exc:
        return f"Error extracting links: {exc}"


@tool
async def web_evaluate_js(expression: str) -> str:
    """Evaluate a JavaScript expression on the current page and return the result.

    Args:
        expression: JavaScript expression to evaluate.
    """
    try:
        page = await _browser.page()
        result = await page.evaluate(expression)
        text = str(result)
        if len(text) > 10_000:
            text = text[:10_000] + "\n… [truncated]"
        return text
    except Exception as exc:
        return f"Error evaluating JS: {exc}"


WEB_SURFER_TOOLS = [
    web_navigate,
    web_get_page_content,
    web_click,
    web_fill,
    web_screenshot,
    web_go_back,
    web_get_links,
    web_evaluate_js,
]
