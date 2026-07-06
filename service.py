import asyncio
import base64
import zlib
from collections import OrderedDict
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

import aiohttp
from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from PIL import Image, ImageDraw

_cache_dir: Path | None = None
_temp_file_cache: dict[str, str] = {}
_IMAGE_FORMATS: dict[bytes, tuple[str, str]] = {
    b"\x89PNG": ("image/png", ".png"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpeg"),
}

_shared_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()
_image_cache: OrderedDict[str, bytes] = OrderedDict()
_MAX_IMAGE_CACHE = 128
_fallback_cache: bytes | None = None


def _get_cache_dir() -> Path:
    global _cache_dir
    if _cache_dir is None:
        _cache_dir = (
            Path(get_astrbot_data_path())
            / "plugin_data"
            / "astrbot_plugin_seer_info"
            / "image_cache"
        )
        _cache_dir.mkdir(parents=True, exist_ok=True)
    return _cache_dir


def _fast_fingerprint(data: bytes) -> str:
    size = len(data)
    if size <= 4096:
        crc = zlib.crc32(data)
    else:
        crc = zlib.crc32(data[:2048])
        crc = zlib.crc32(data[-2048:], crc)
    return f"{crc & 0xFFFFFFFF:08x}{size:08x}"


def _detect_image_format(data: bytes) -> tuple[str, str]:
    for magic, fmt in _IMAGE_FORMATS.items():
        if data[: len(magic)] == magic:
            return fmt
    return "image/jpeg", ".jpeg"


def to_data_uri(data: bytes, mime_type: str | None = None) -> str:
    if mime_type is None:
        mime_type, _ = _detect_image_format(data)
    b64 = base64.b64encode(data)
    return f"data:{mime_type};base64,{b64.decode()}"


def save_bytes_to_temp_file(image_bytes: bytes, suffix: str | None = None) -> str:
    if suffix is None:
        _, suffix = _detect_image_format(image_bytes)
    key = _fast_fingerprint(image_bytes)
    cached = _temp_file_cache.get(key)
    if cached and Path(cached).exists():
        logger.info(f"图片缓存命中: {Path(cached).name}")
        return cached
    filename = key[:16] + suffix
    path = _get_cache_dir() / filename
    if path.exists():
        _temp_file_cache[key] = str(path)
        logger.info(f"图片缓存命中: {filename}")
        return str(path)
    path.write_bytes(image_bytes)
    _temp_file_cache[key] = str(path)
    logger.info(f"图片缓存创建: {filename} ({len(image_bytes) / (1024 * 1024):.2f} MB)")
    return str(path)


async def _get_shared_session() -> aiohttp.ClientSession:
    global _shared_session
    if _shared_session is not None and not _shared_session.closed:
        return _shared_session
    async with _session_lock:
        if _shared_session is not None and not _shared_session.closed:
            return _shared_session
        _shared_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=10, limit_per_host=5),
        )
        return _shared_session


async def close_shared_session():
    global _shared_session
    if _shared_session and not _shared_session.closed:
        await _shared_session.close()
        logger.info("已关闭共享的 HTTP 会话")
        _shared_session = None
    _image_cache.clear()
    _temp_file_cache.clear()
    global _fallback_cache
    _fallback_cache = None
    logger.info("已清除资源缓存")


class GetImage:
    def __init__(
        self,
        *url_templates: str,
        fallback: Callable | None = None,
    ):
        if not url_templates:
            raise ValueError("至少需要一个 URL 模板")
        self.url_templates = url_templates
        self.fallback = fallback

    async def get_bytes(self, arg: str) -> bytes:
        session = await _get_shared_session()
        last_error: Exception | None = None
        for template in self.url_templates:
            url = template.format(arg)
            cached = _image_cache.get(url)
            if cached is not None:
                _image_cache.move_to_end(url)
                return cached
            try:
                async with session.get(url) as response:
                    response.raise_for_status()
                    data = await response.read()
                    _image_cache[url] = data
                    if len(_image_cache) > _MAX_IMAGE_CACHE:
                        _image_cache.popitem(last=False)
                    return data
            except Exception as e:
                last_error = e
                continue

        error = last_error or RuntimeError("所有 URL 均请求失败")
        if self.fallback is not None:
            return await self.fallback(error)
        raise error

    async def get_image_url(self, arg: str) -> str:
        session = await _get_shared_session()
        for template in self.url_templates:
            url = template.format(arg)
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        return url
            except Exception:
                continue
        return self.url_templates[0].format(arg)

    async def __call__(self, arg: str) -> bytes:
        return await self.get_bytes(arg)


async def _fallback_image(error: Exception) -> bytes:
    global _fallback_cache
    if _fallback_cache is not None:
        return _fallback_cache

    img = Image.new("RGB", (300, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 40), "获取图片失败！", fill="red")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    _fallback_cache = buffer.getvalue()
    return _fallback_cache


PetBodyImageGetter = GetImage(
    "https://newseer.61.com/web/monster/body/{}.png",
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/pet/body/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/pet/body/{}.png",
    fallback=_fallback_image,
)

PetHeadImageGetter = GetImage(
    "https://newseer.61.com/web/monster/head/{}.png",
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/pet/head/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/pet/head/{}.png",
    fallback=_fallback_image,
)

MintmarkBodyImageGetter = GetImage(
    "https://newseer.61.com/web/countermark/icon/{}.png",
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/countermark/icon/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/countermark/icon/{}.png",
    fallback=_fallback_image,
)

ElementTypeImageGetter = GetImage(
    "https://newseer.61.com/web/PetType/{}.png",
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/pettype/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/pettype/{}.png",
)

SuitImageGetter = GetImage(
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/item/cloth/suiticon/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/item/cloth/suiticon/{}.png",
)

EquipImageGetter = GetImage(
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/item/cloth/prev/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/item/cloth/prev/{}.png",
)

TitleImageGetter = GetImage(
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/achieve/title/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/achieve/title/{}.png",
)

BattleEffectImageGetter = GetImage(
    "https://cnb.cool/SeerAPI/seer-unity-assets/-/git/raw/main/newseer/assets/art/ui/assets/battleeffect/abnormal/{}.png",
    "https://raw.githubusercontent.com/SeerAPI/seer-unity-assets/refs/heads/main/newseer/assets/art/ui/assets/battleeffect/abnormal/{}.png",
)
