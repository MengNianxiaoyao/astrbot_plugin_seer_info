"""
Utility functions for SeerInfo plugin.
"""

import base64
import hashlib
from pathlib import Path

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

_temp_file_cache: dict[str, str] = {}  # fingerprint -> file_path
_cache_dir: Path | None = None


def _get_cache_dir() -> Path:
    global _cache_dir
    if _cache_dir is None:
        _cache_dir = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_seer_info" / "image_cache"
        _cache_dir.mkdir(parents=True, exist_ok=True)
    return _cache_dir


def _fast_fingerprint(data: bytes) -> str:
    """取首尾各 2KB + 长度做快速指纹，比全量 MD5 快一个数量级。"""
    size = len(data)
    if size <= 4096:
        return hashlib.md5(data, usedforsecurity=False).hexdigest()
    head = data[:2048]
    tail = data[-2048:]
    return hashlib.md5(head + tail + size.to_bytes(8, "big"), usedforsecurity=False).hexdigest()


def to_data_uri(data: bytes, mime_type: str = "image/png") -> str:
    b64 = base64.b64encode(data)
    return f"data:{mime_type};base64,{b64.decode()}"


def save_bytes_to_temp_file(image_bytes: bytes, suffix: str = ".png") -> str:
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


__all__ = ["to_data_uri", "save_bytes_to_temp_file"]
