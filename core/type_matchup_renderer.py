import asyncio
from typing import Any

from astrbot.api import logger
from seerapi_models import TypeCombinationORM

from .renderer import get_template_content, render_to_image
from .type_calc import calc_attack_table, calc_defense_table
from ..data import db_manager
from ..service import ElementTypeImageGetter, to_data_uri

TYPE_MATCHUP_TEMPLATE = get_template_content("type_matchup/template.html.j2")


async def build_type_matchup_render_data(type_combo: TypeCombinationORM) -> dict[str, Any]:
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
    render_data = await build_type_matchup_render_data(type_combo)
    return await render_to_image(
        TYPE_MATCHUP_TEMPLATE,
        render_data,
        html_render=html_render,
        image_format=image_format,
        jpeg_quality=jpeg_quality,
    )
