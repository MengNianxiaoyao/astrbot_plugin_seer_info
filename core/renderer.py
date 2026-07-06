import asyncio
from collections import OrderedDict
from pathlib import Path
from typing import Any

import jinja2
from astrbot.api import logger
from jinja2.sandbox import SandboxedEnvironment
from playwright._impl._errors import TargetClosedError
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from ..service import save_bytes_to_temp_file

DEFAULT_TIMEOUT = 30000
DEFAULT_VIEWPORT_WIDTH = 1200

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class TemplateCache:
    _file_cache: OrderedDict[str, str] = OrderedDict()
    _compiled_cache: OrderedDict[str, jinja2.Template] = OrderedDict()
    _MAX_FILE_CACHE = 32
    _MAX_COMPILED_CACHE = 32

    @classmethod
    def get_content(cls, relative_path: str) -> str:
        relative_path = relative_path.replace("/", "\\")
        cached = cls._file_cache.get(relative_path)
        if cached is not None:
            cls._file_cache.move_to_end(relative_path)
            return cached
        full_path = _TEMPLATES_DIR / relative_path
        content = full_path.read_text(encoding="utf-8")
        cls._file_cache[relative_path] = content
        if len(cls._file_cache) > cls._MAX_FILE_CACHE:
            cls._file_cache.popitem(last=False)
        return content

    @classmethod
    def compile_string(cls, env: SandboxedEnvironment, template_string: str) -> jinja2.Template:
        cached = cls._compiled_cache.get(template_string)
        if cached is not None:
            cls._compiled_cache.move_to_end(template_string)
            return cached
        template = env.from_string(template_string)
        cls._compiled_cache[template_string] = template
        if len(cls._compiled_cache) > cls._MAX_COMPILED_CACHE:
            cls._compiled_cache.popitem(last=False)
        return template


class LocalRenderer:
    def __init__(self, page_pool_size: int = 4):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page_pool: asyncio.Queue[Page] = asyncio.Queue(maxsize=page_pool_size)
        self._page_pool_size = page_pool_size
        self._env = SandboxedEnvironment(
            loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=jinja2.select_autoescape(["html", "xml"]),
            keep_trailing_newline=True,
        )

    async def _get_browser(self) -> Browser:
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
        browser = await self._get_browser()
        if self._context is None or not self._context.browser:
            self._context = await browser.new_context(
                viewport={"width": DEFAULT_VIEWPORT_WIDTH, "height": 600},
                device_scale_factor=2,
                ignore_https_errors=True,
            )
        return self._context

    async def _get_page(self) -> Page:
        try:
            page = self._page_pool.get_nowait()
            if not page.is_closed():
                return page
        except asyncio.QueueEmpty:
            pass
        context = await self._get_context()
        return await context.new_page()

    async def _return_page(self, page: Page) -> None:
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
                page, html_content, viewport_width, timeout_ms, image_format, jpeg_quality
            )
        except TargetClosedError:
            page = await self._get_page()
            return await self._screenshot(
                page, html_content, viewport_width, timeout_ms, image_format, jpeg_quality
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
        else:
            screenshot_kwargs["type"] = "jpeg"
            screenshot_kwargs["quality"] = jpeg_quality
        return await page.screenshot(**screenshot_kwargs)

    async def close(self):
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
    global _renderer
    if _renderer:
        await _renderer.close()
        _renderer = None


def get_template_content(relative_path: str) -> str:
    return TemplateCache.get_content(relative_path)


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
    template = TemplateCache.compile_string(renderer._env, template_string)
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
