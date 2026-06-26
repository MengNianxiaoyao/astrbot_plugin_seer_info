"""
Local HTML rendering for SeerInfo plugin.

Uses Jinja2 for template rendering and Playwright for HTML to image conversion.
This avoids relying on AstrBot's remote html_render API.

Reference: https://github.com/AstrBotDevs/astrbot-t2i-service
"""

import asyncio
from collections import OrderedDict
from pathlib import Path
from typing import Any

import jinja2
from astrbot.api import logger
from jinja2.sandbox import SandboxedEnvironment
from playwright._impl._errors import TargetClosedError
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from ..data.cache import save_bytes_to_temp_file

DEFAULT_TIMEOUT = 30000
DEFAULT_VIEWPORT_WIDTH = 1200


class LocalRenderer:
    """Local HTML renderer using Jinja2 + Playwright."""

    def __init__(self, page_pool_size: int = 4):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page_pool: asyncio.Queue[Page] = asyncio.Queue(maxsize=page_pool_size)
        self._page_pool_size = page_pool_size
        self._env = SandboxedEnvironment(
            loader=jinja2.FileSystemLoader(str(self._get_templates_dir())),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
            keep_trailing_newline=True,
        )
        self._string_template_cache: OrderedDict[str, jinja2.Template] = OrderedDict()
        self._MAX_TEMPLATE_CACHE = 16

    @staticmethod
    def _get_templates_dir() -> Path:
        plugin_dir = Path(__file__).parent.parent
        return plugin_dir / "templates"

    async def _get_browser(self) -> Browser:
        """获取共享的浏览器实例（延迟初始化）"""
        if self._browser is None or not self._browser.is_connected():
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--ignore-gpu-blocklist",
                    "--enable-gpu-rasterization",
                    "--enable-zero-copy",
                    "--disable-features=PaintHolding",
                    "--disable-ipc-flooding-protection",
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

    async def _get_page(self) -> Page:
        """从页面池获取页面，如果池为空则创建新页面"""
        try:
            page = self._page_pool.get_nowait()
            if not page.is_closed():
                return page
        except asyncio.QueueEmpty:
            pass

        context = await self._get_context()
        return await context.new_page()

    async def _return_page(self, page: Page) -> None:
        """归还页面到池中，如果池满则关闭页面"""
        if page.is_closed():
            return

        try:
            self._page_pool.put_nowait(page)
        except asyncio.QueueFull:
            await page.close()

    async def render_template(
        self,
        template_name: str,
        data: dict[str, Any],
        *,
        viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
        timeout_ms: float = DEFAULT_TIMEOUT,
        image_format: str = "jpeg",
        jpeg_quality: int = 85,
    ) -> bytes:
        template = self._env.get_template(template_name)
        html_content = template.render(**data)
        return await self._render_html(
            html_content, viewport_width, timeout_ms, image_format, jpeg_quality
        )

    async def render_string(
        self,
        html_string: str,
        *,
        viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
        timeout_ms: float = DEFAULT_TIMEOUT,
        image_format: str = "jpeg",
        jpeg_quality: int = 85,
    ) -> bytes:
        return await self._render_html(
            html_string, viewport_width, timeout_ms, image_format, jpeg_quality
        )

    async def _render_html(
        self,
        html_content: str,
        viewport_width: int,
        timeout_ms: float,
        image_format: str = "jpeg",
        jpeg_quality: int = 85,
    ) -> bytes:
        page = await self._get_page()
        try:
            return await self._screenshot(
                page,
                html_content,
                viewport_width,
                timeout_ms,
                image_format,
                jpeg_quality,
            )
        except TargetClosedError:
            page = await self._get_page()
            return await self._screenshot(
                page,
                html_content,
                viewport_width,
                timeout_ms,
                image_format,
                jpeg_quality,
            )
        except Exception as e:
            logger.error(f"渲染图片失败: {e}")
            raise
        finally:
            if not page.is_closed():
                await self._return_page(page)

    async def _screenshot(
        self,
        page: Page,
        html_content: str,
        viewport_width: int,
        timeout_ms: float,
        image_format: str = "jpeg",
        jpeg_quality: int = 85,
    ) -> bytes:
        await page.set_viewport_size({"width": viewport_width, "height": 600})
        await page.set_content(html_content, wait_until="domcontentloaded", timeout=timeout_ms)

        screenshot_kwargs = {
            "full_page": True,
            "timeout": timeout_ms,
            "animations": "disabled",
            "caret": "hide",
        }

        if image_format == "png":
            screenshot_kwargs["type"] = "png"
        else:  # jpeg
            screenshot_kwargs["type"] = "jpeg"
            screenshot_kwargs["quality"] = jpeg_quality

        return await page.screenshot(**screenshot_kwargs)

    async def close(self):
        """关闭浏览器实例"""
        while not self._page_pool.empty():
            try:
                page = self._page_pool.get_nowait()
                if not page.is_closed():
                    await page.close()
            except asyncio.QueueEmpty:
                break

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

    async def prewarm(self):
        """预热浏览器，创建页面池中的页面"""
        context = await self._get_context()
        for _ in range(self._page_pool_size):
            page = await context.new_page()
            try:
                self._page_pool.put_nowait(page)
            except asyncio.QueueFull:
                await page.close()
                break
        logger.info("Playwright 浏览器已预热")


_renderer: LocalRenderer | None = None
_renderer_lock = asyncio.Lock()


async def get_renderer() -> LocalRenderer:
    global _renderer
    if _renderer is not None:
        return _renderer
    async with _renderer_lock:
        if _renderer is not None:
            return _renderer
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
    timeout_ms: float = DEFAULT_TIMEOUT,
    image_format: str = "jpeg",
    jpeg_quality: int = 85,
) -> bytes:
    renderer = await get_renderer()
    template = renderer._string_template_cache.get(template_string)
    if template is not None:
        renderer._string_template_cache.move_to_end(template_string)
    else:
        template = renderer._env.from_string(template_string)
        renderer._string_template_cache[template_string] = template
        if len(renderer._string_template_cache) > renderer._MAX_TEMPLATE_CACHE:
            renderer._string_template_cache.popitem(last=False)
    html_content = template.render(**data)
    return await renderer.render_string(
        html_content,
        viewport_width=viewport_width,
        timeout_ms=timeout_ms,
        image_format=image_format,
        jpeg_quality=jpeg_quality,
    )


async def render_template_to_bytes(
    template_name: str,
    data: dict[str, Any],
    *,
    viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
    timeout_ms: float = DEFAULT_TIMEOUT,
    image_format: str = "jpeg",
    jpeg_quality: int = 85,
) -> bytes:
    renderer = await get_renderer()
    return await renderer.render_template(
        template_name,
        data,
        viewport_width=viewport_width,
        timeout_ms=timeout_ms,
        image_format=image_format,
        jpeg_quality=jpeg_quality,
    )


async def render_to_image(
    template_string: str,
    data: dict[str, Any],
    *,
    html_render=None,
    image_format: str = "jpeg",
    jpeg_quality: int = 85,
) -> str:
    """统一渲染入口。html_render 为 None 时使用本地渲染，否则使用远程渲染。

    返回图片文件路径。
    """
    if html_render is not None:
        return await html_render(
            template_string,
            data,
            options={"scale": "device", "type": image_format},
        )
    image_bytes = await render_html_to_bytes(
        template_string,
        data,
        image_format=image_format,
        jpeg_quality=jpeg_quality,
    )
    return save_bytes_to_temp_file(image_bytes)


__all__ = [
    "LocalRenderer",
    "get_renderer",
    "close_renderer",
    "render_html_to_bytes",
    "render_template_to_bytes",
    "render_to_image",
]
