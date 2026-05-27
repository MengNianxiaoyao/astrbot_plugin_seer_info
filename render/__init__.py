"""
Image rendering utilities for SeerInfo plugin.
"""

import asyncio
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from typing import Optional

from astrbot.api import logger


async def render_pet_info(pet) -> bytes:
    """Render pet information card."""
    try:
        width, height = 400, 600
        img = Image.new('RGB', (width, height), color='#1a1a2e')
        draw = ImageDraw.Draw(img)

        try:
            title_font = ImageFont.truetype("arial.ttf", 24)
            body_font = ImageFont.truetype("arial.ttf", 16)
        except:
            title_font = ImageFont.load_default()
            body_font = ImageFont.load_default()

        draw.rectangle([10, 10, width-10, height-10], outline='#4a4a6a', width=2)

        draw.text((20, 20), f"【{pet.name}】", fill='#ffd700', font=title_font)

        y = 60
        if hasattr(pet, 'level') and pet.level:
            draw.text((20, y), f"等级: {pet.level}", fill='#ffffff', font=body_font)
            y += 30

        if hasattr(pet, 'element_type') and pet.element_type:
            draw.text((20, y), f"属性: {pet.element_type}", fill='#87ceeb', font=body_font)
            y += 30

        if hasattr(pet, 'description') and pet.description:
            desc = pet.description[:50] + "..." if len(pet.description) > 50 else pet.description
            draw.text((20, y), f"描述: {desc}", fill='#cccccc', font=body_font)
            y += 30

        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    except Exception as e:
        logger.error(f"渲染精灵信息失败: {e}")
        raise


async def render_type_matchup(type_combo) -> bytes:
    """Render type matchup chart."""
    try:
        width, height = 500, 400
        img = Image.new('RGB', (width, height), color='#2d2d44')
        draw = ImageDraw.Draw(img)

        try:
            title_font = ImageFont.truetype("arial.ttf", 20)
            body_font = ImageFont.truetype("arial.ttf", 14)
        except:
            title_font = ImageFont.load_default()
            body_font = ImageFont.load_default()

        draw.rectangle([10, 10, width-10, height-10], outline='#6a6a8a', width=2)

        title = f"属性克制表"
        draw.text((20, 20), title, fill='#ffd700', font=title_font)

        y = 60
        if hasattr(type_combo, 'primary') and type_combo.primary:
            draw.text((20, y), f"主属性: {type_combo.primary.name}", fill='#87ceeb', font=body_font)
            y += 25

        if hasattr(type_combo, 'secondary') and type_combo.secondary:
            draw.text((20, y), f"副属性: {type_combo.secondary.name}", fill='#98fb98', font=body_font)
            y += 25

        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    except Exception as e:
        logger.error(f"渲染属性克制表失败: {e}")
        raise


async def render_peak_pool(pool_type: str) -> bytes:
    """Render peak pool info."""
    try:
        width, height = 600, 800
        img = Image.new('RGB', (width, height), color='#1a1a2e')
        draw = ImageDraw.Draw(img)

        try:
            title_font = ImageFont.truetype("arial.ttf", 24)
            body_font = ImageFont.truetype("arial.ttf", 14)
        except:
            title_font = ImageFont.load_default()
            body_font = ImageFont.load_default()

        title = f"巅峰{pool_type}池"
        draw.text((width//2 - 60, 20), title, fill='#ffd700', font=title_font)

        draw.text((20, 60), "数据加载中...", fill='#ffffff', font=body_font)

        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    except Exception as e:
        logger.error(f"渲染巅峰池失败: {e}")
        raise


async def render_peak_pool_vote() -> bytes:
    """Render peak pool vote info."""
    try:
        width, height = 600, 800
        img = Image.new('RGB', (width, height), color='#1a1a2e')
        draw = ImageDraw.Draw(img)

        try:
            title_font = ImageFont.truetype("arial.ttf", 24)
        except:
            title_font = ImageFont.load_default()

        draw.text((200, 350), "巅峰池票选", fill='#ffd700', font=title_font)

        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    except Exception as e:
        logger.error(f"渲染巅峰票选失败: {e}")
        raise


async def render_peak_pet_rank(rank_type: str) -> bytes:
    """Render peak pet rank."""
    try:
        width, height = 600, 800
        img = Image.new('RGB', (width, height), color='#1a1a2e')
        draw = ImageDraw.Draw(img)

        try:
            title_font = ImageFont.truetype("arial.ttf", 24)
        except:
            title_font = ImageFont.load_default()

        draw.text((200, 350), f"巅峰{rank_type}榜", fill='#ffd700', font=title_font)

        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    except Exception as e:
        logger.error(f"渲染巅峰排行失败: {e}")
        raise


__all__ = [
    "render_pet_info",
    "render_type_matchup",
    "render_peak_pool",
    "render_peak_pool_vote",
    "render_peak_pet_rank",
]