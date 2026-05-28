"""
Local HTML rendering for SeerInfo plugin.

Uses Jinja2 for template rendering and Playwright for HTML to image conversion.
This avoids relying on AstrBot's remote html_render API.
"""

import asyncio
from pathlib import Path
from typing import Any

import jinja2
from playwright.async_api import async_playwright

from astrbot.api import logger


DEFAULT_TIMEOUT = 30000
DEFAULT_VIEWPORT_WIDTH = 1200
INITIAL_VIEWPORT_HEIGHT = 600


class LocalRenderer:
    """Local HTML renderer using Jinja2 + Playwright."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(self._get_templates_dir())),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
            keep_trailing_newline=True,
        )

    @staticmethod
    def _get_templates_dir() -> Path:
        plugin_dir = Path(__file__).parent.parent
        return plugin_dir / "templates"

    async def _get_browser(self):
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                ],
            )
        return self._browser

    async def render_template(
        self,
        template_name: str,
        data: dict[str, Any],
        *,
        viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> bytes:
        template = self._env.get_template(template_name)
        html_content = template.render(**data)
        return await self._render_html(html_content, viewport_width, timeout)

    async def render_string(
        self,
        html_string: str,
        *,
        viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> bytes:
        return await self._render_html(html_string, viewport_width, timeout)

    async def _render_html(
        self,
        html_content: str,
        viewport_width: int,
        timeout: float,
    ) -> bytes:
        browser = await self._get_browser()

        context = await browser.new_context(
            viewport={
                "width": viewport_width,
                "height": INITIAL_VIEWPORT_HEIGHT,
            },
            device_scale_factor=2,
            ignore_https_errors=True,
        )
        page = await context.new_page()

        try:
            await page.set_content(html_content, wait_until="networkidle", timeout=timeout)
            await asyncio.sleep(0.2)

            screenshot = await page.screenshot(
                type="png",
                full_page=True,
                timeout=timeout,
                animations="disabled",
                caret="hide",
            )
            return screenshot
        except Exception as e:
            logger.error(f"Failed to render HTML to image: {e}")
            raise
        finally:
            await page.close()
            await context.close()

    async def close(self):
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


_renderer: LocalRenderer | None = None


def get_renderer() -> LocalRenderer:
    global _renderer
    if _renderer is None:
        _renderer = LocalRenderer()
    return _renderer


async def close_renderer():
    global _renderer
    if _renderer:
        await _renderer.close()
        _renderer = None


async def render_html_to_bytes(
    template_string: str,
    data: dict[str, Any],
    *,
    viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    renderer = get_renderer()
    template = renderer._env.from_string(template_string)
    html_content = template.render(**data)
    return await renderer.render_string(
        html_content,
        viewport_width=viewport_width,
        timeout=timeout,
    )


async def render_template_to_bytes(
    template_name: str,
    data: dict[str, Any],
    *,
    viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    renderer = get_renderer()
    return await renderer.render_template(
        template_name,
        data,
        viewport_width=viewport_width,
        timeout=timeout,
    )


__all__ = [
    "LocalRenderer",
    "get_renderer",
    "close_renderer",
    "render_html_to_bytes",
    "render_template_to_bytes",
]