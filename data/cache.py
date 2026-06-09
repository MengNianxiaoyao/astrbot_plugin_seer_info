"""
Utility functions for SeerInfo plugin.
"""

import base64
import hashlib
import os
from pathlib import Path

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

_temp_file_cache: dict[str, str] = {}  # md5 -> file_path
_cache_dir: str | None = None


def _get_cache_dir() -> str:
    global _cache_dir
    if _cache_dir is None:
        _cache_dir = str(Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_seer_info" / "image_cache")
        os.makedirs(_cache_dir, exist_ok=True)
    return _cache_dir


def to_data_uri(data: bytes, mime_type: str = "image/png") -> str:
    b64 = base64.b64encode(data)
    return f"data:{mime_type};base64,{b64.decode()}"


def save_bytes_to_temp_file(image_bytes: bytes, suffix: str = ".png") -> str:
    key = hashlib.md5(image_bytes, usedforsecurity=False).hexdigest()
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


__all__ = ["to_data_uri", "save_bytes_to_temp_file"]