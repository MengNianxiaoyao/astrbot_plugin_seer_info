"""
Local HTML rendering for SeerInfo plugin.

Uses Jinja2 for template rendering and Playwright for HTML to image conversion.
This avoids relying on AstrBot's remote html_render API.

Reference: https://github.com/AstrBotDevs/astrbot-t2i-service
"""

import asyncio
from pathlib import Path
from typing import Any

import jinja2
from jinja2.sandbox import SandboxedEnvironment
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright._impl._errors import TargetClosedError

from astrbot.api import logger


DEFAULT_TIMEOUT = 30000
DEFAULT_VIEWPORT_WIDTH = 1200


class LocalRenderer:
    """Local HTML renderer using Jinja2 + Playwright."""

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()
        self._env = SandboxedEnvironment(
            loader=jinja2.FileSystemLoader(str(self._get_templates_dir())),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
            keep_trailing_newline=True,
        )

    @staticmethod
    def _get_templates_dir() -> Path:
        plugin_dir = Path(__file__).parent.parent
        return plugin_dir / "templates"

    async def _get_browser(self) -> Browser:
        """获取共享的浏览器实例（延迟初始化，线程安全）"""
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-gpu",
                    ],
                )
                logger.info("Playwright 浏览器已启动")
            return self._browser

    async def _get_context(self) -> BrowserContext:
        """获取共享的浏览器上下文"""
        browser = await self._get_browser()
        if self._context is None or not self._context.browser:
            self._context = await browser.new_context(
                viewport={
                    "width": DEFAULT_VIEWPORT_WIDTH,
                    "height": 600,
                },
                device_scale_factor=2,
                ignore_https_errors=True,
            )
        return self._context

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
        context = await self._get_context()
        page: Page | None = None
        try:
            page = await context.new_page()
        except TargetClosedError:
            logger.warning("Context closed, recreating...")
            if self._context:
                await self._context.close()
            self._context = None
            context = await self._get_context()
            page = await context.new_page()

        try:
            await page.set_viewport_size({"width": viewport_width, "height": 600})
            await page.set_content(html_content, wait_until="networkidle", timeout=timeout)

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
            if page:
                await page.close()

    async def close(self):
        """关闭浏览器实例"""
        async with self._lock:
            if self._context:
                try:
                    await self._context.close()
                except Exception:
                    pass
                self._context = None

            if self._browser:
                if self._browser.is_connected():
                    await self._browser.close()
                self._browser = None
                logger.info("Playwright 浏览器已关闭")

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None


_renderer: LocalRenderer | None = None


def get_renderer() -> LocalRenderer:
    global _renderer
    if _renderer is None:
        _renderer = LocalRenderer()
    return _renderer


async def close_renderer():
    """关闭渲染器（插件卸载时调用）"""
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