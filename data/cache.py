"""
Utility functions for SeerInfo plugin.
"""

import base64
import zlib
from pathlib import Path

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

_temp_file_cache: dict[str, str] = {}  # fingerprint -> file_path
_cache_dir: Path | None = None

# 图片格式映射：魔数 -> (mime_type, suffix)
_IMAGE_FORMATS: dict[bytes, tuple[str, str]] = {
    b"\x89PNG": ("image/png", ".png"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpeg"),
}


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
    """使用 CRC32 生成快速指纹。"""
    size = len(data)
    if size <= 4096:
        crc = zlib.crc32(data)
    else:
        crc = zlib.crc32(data[:2048])
        crc = zlib.crc32(data[-2048:], crc)
    return f"{crc & 0xFFFFFFFF:08x}{size:08x}"


def _detect_image_format(data: bytes) -> tuple[str, str]:
    """检测图片格式，返回 (mime_type, suffix)。"""
    for magic, fmt in _IMAGE_FORMATS.items():
        if data[: len(magic)] == magic:
            return fmt
    return "image/jpeg", ".jpeg"


def to_data_uri(data: bytes, mime_type: str | None = None) -> str:
    """将字节数据转换为 Data URI。mime_type 为 None 时自动检测格式。"""
    if mime_type is None:
        mime_type, _ = _detect_image_format(data)
    b64 = base64.b64encode(data)
    return f"data:{mime_type};base64,{b64.decode()}"


def save_bytes_to_temp_file(image_bytes: bytes, suffix: str | None = None) -> str:
    """将字节数据保存到临时文件。suffix 为 None 时自动检测格式。"""
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
