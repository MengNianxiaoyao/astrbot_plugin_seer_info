"""
Utility functions for SeerInfo plugin.
"""

import asyncio
from typing import Callable

import aiohttp
from PIL import Image, ImageDraw
from io import BytesIO


class GetImage:
    """多 URL 备选图片获取器"""

    def __init__(
        self,
        *url_templates: str,
        fallback: Callable | None = None,
        client_getter: Callable | None = None,
    ):
        if not url_templates:
            raise ValueError("至少需要一个 URL 模板")

        self._client_getter = client_getter
        self.url_templates = url_templates
        self.fallback = fallback

    async def _fetch_image_bytes(self, url: str) -> bytes:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.read()

    async def get_bytes(self, arg: str) -> bytes:
        last_error: Exception | None = None
        for template in self.url_templates:
            url = template.format(arg)
            try:
                return await self._fetch_image_bytes(url)
            except Exception as e:
                last_error = e
                continue

        error = last_error or RuntimeError("所有 URL 均请求失败")
        if self.fallback is not None:
            return await self.fallback(error)
        raise error

    async def __call__(self, arg: str) -> bytes:
        return await self.get_bytes(arg)


def create_fallback_image(error_text: str = "获取图片失败") -> bytes:
    """创建 fallback 占位图"""
    img = Image.new('RGB', (300, 100), color='#333333')
    draw = ImageDraw.Draw(img)
    draw.text((80, 40), error_text, fill='#ff6b6b')
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()


__all__ = ["GetImage", "create_fallback_image"]