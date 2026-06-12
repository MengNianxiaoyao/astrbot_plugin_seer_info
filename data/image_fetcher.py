"""
Image fetching dependencies for SeerInfo plugin.
"""

import asyncio
from collections import OrderedDict
from collections.abc import Callable

import aiohttp

from astrbot.api import logger

_shared_session: aiohttp.ClientSession | None = None
_session_lock = asyncio.Lock()
_image_cache: OrderedDict[str, bytes] = OrderedDict()  # url -> image bytes, LRU cache
_MAX_CACHE_SIZE = 128


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
    logger.info("已清除图片缓存")


class GetImage:
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
                    if len(_image_cache) > _MAX_CACHE_SIZE:
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

    from PIL import Image, ImageDraw
    from io import BytesIO

    img = Image.new('RGB', (300, 100), color='white')
    draw = ImageDraw.Draw(img)
    draw.text((10, 40), "获取图片失败！", fill='red')

    buffer = BytesIO()
    img.save(buffer, format='PNG')
    _fallback_cache = buffer.getvalue()
    return _fallback_cache


_fallback_cache: bytes | None = None


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

PreviewImageGetter = GetImage(
    "https://cnb.cool/HurryWang/seer-unity-preview-img-dumper-cnb/-/git/raw/master/img/preview.png",
)


__all__ = [
    "GetImage",
    "close_shared_session",
    "PetBodyImageGetter",
    "PetHeadImageGetter",
    "MintmarkBodyImageGetter",
    "ElementTypeImageGetter",
    "SuitImageGetter",
    "EquipImageGetter",
    "TitleImageGetter",
    "BattleEffectImageGetter",
    "PreviewImageGetter",
]