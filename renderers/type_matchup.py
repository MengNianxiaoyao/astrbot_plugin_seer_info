"""Render type matchup chart using HTML template."""

import asyncio
from pathlib import Path
from typing import Any

from astrbot.api import logger
from seerapi_models import TypeCombinationORM

from ..core.renderer import render_to_image
from ..core.type_calc import calc_attack_table, calc_defense_table
from ..data.cache import to_data_uri
from ..data.db import db_manager
from ..data.image_fetcher import ElementTypeImageGetter

TEMPLATE_PATH = "templates/type_matchup"
TEMPLATE_NAME = "template.html.j2"

TYPE_MATCHUP_TEMPLATE = (Path(__file__).parent.parent / TEMPLATE_PATH / TEMPLATE_NAME).read_text(
    encoding="utf-8"
)


async def build_type_matchup_render_data(type_combo: TypeCombinationORM) -> dict[str, Any]:
    """Build render data for type matchup chart."""
    sessions = db_manager.get_all_sessions()
    session = sessions.get("seerapi")
    if not session:
        raise RuntimeError("数据库未加载，请稍后再试")

    try:
        attack_table = calc_attack_table(session, type_combo)
        defense_table = calc_defense_table(session, type_combo)

        all_combo_ids: dict[int, None] = {type_combo.id: None}
        for combo, _ in attack_table:
            all_combo_ids.setdefault(combo.id, None)
        for combo, _ in defense_table:
            all_combo_ids.setdefault(combo.id, None)

        id_list = list(all_combo_ids)
        icon_map: dict[int, str] = {}
        async with asyncio.TaskGroup() as tg:
            tasks = {
                cid: tg.create_task(ElementTypeImageGetter.get_bytes(str(cid))) for cid in id_list
            }
        for cid, task in tasks.items():
            try:
                icon_map[cid] = to_data_uri(task.result())
            except Exception:
                pass

        type_name = getattr(type_combo, "name", "未知")
        type_icon = icon_map.get(type_combo.id, "")

        attack_items = []
        for combo, mult in attack_table:
            if mult != 1.0:
                attack_items.append(
                    {
                        "icon": icon_map.get(combo.id, ""),
                        "name": getattr(combo, "name", ""),
                        "multiplier": mult,
                    }
                )

        attack_items.sort(key=lambda x: x["multiplier"], reverse=True)

        defense_items = []
        for combo, mult in defense_table:
            if mult != 1.0:
                defense_items.append(
                    {
                        "icon": icon_map.get(combo.id, ""),
                        "name": getattr(combo, "name", ""),
                        "multiplier": mult,
                    }
                )

        defense_items.sort(key=lambda x: x["multiplier"], reverse=True)

        return {
            "type_name": type_name,
            "type_icon": type_icon,
            "attack_items": attack_items,
            "defense_items": defense_items,
            "cell_size": 72,
            "cell_gap": 6,
        }

    except Exception as e:
        logger.error(f"构建属性克制表数据失败: {e}")
        return {
            "type_name": getattr(type_combo, "name", "未知"),
            "attack_items": [],
            "defense_items": [],
            "cell_size": 72,
            "cell_gap": 6,
        }


async def render_type_matchup(
    type_combo: TypeCombinationORM,
    html_render=None,
    image_format: str = "jpeg",
    jpeg_quality: int = 85,
) -> str:
    """Render type matchup chart to image.

    Args:
        type_combo: The TypeCombinationORM object
        html_render: AstrBot's html_render function (None for local rendering)
        image_format: Image output format (jpeg or png)
        jpeg_quality: JPEG quality (1-100)

    Returns:
        Path to the rendered image file
    """
    render_data = await build_type_matchup_render_data(type_combo)
    return await render_to_image(
        TYPE_MATCHUP_TEMPLATE,
        render_data,
        html_render=html_render,
        image_format=image_format,
        jpeg_quality=jpeg_quality,
    )
