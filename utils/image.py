"""
Utility functions for SeerInfo plugin.
"""

import asyncio
import base64
import hashlib
import os
from pathlib import Path
from typing import Callable

import aiohttp
from PIL import Image, ImageDraw
from io import BytesIO

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

_temp_file_cache: dict[str, str] = {}  # sha256 -> file_path
_cache_dir: str | None = None


def _get_cache_dir() -> str:
    global _cache_dir
    if _cache_dir is None:
        _cache_dir = str(Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_seer_info" / "image_cache")
        os.makedirs(_cache_dir, exist_ok=True)
    return _cache_dir


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


def to_data_uri(data: bytes, mime_type: str = "image/png") -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def save_bytes_to_temp_file(image_bytes: bytes, suffix: str = ".png") -> str:
    key = hashlib.sha256(image_bytes).hexdigest()
    cached = _temp_file_cache.get(key)
    if cached and os.path.exists(cached):
        logger.info(f"图片缓存命中: {os.path.basename(cached)}")
        return cached
    filename = key[:16] + suffix
    path = os.path.join(_get_cache_dir(), filename)
    with open(path, "wb") as f:
        f.write(image_bytes)
    _temp_file_cache[key] = path
    logger.info(f"图片缓存创建: {filename} ({len(image_bytes) / (1024 * 1024):.2f} MB)")
    return path


__all__ = ["GetImage", "create_fallback_image", "to_data_uri", "save_bytes_to_temp_file"]