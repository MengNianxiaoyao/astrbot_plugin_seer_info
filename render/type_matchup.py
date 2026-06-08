"""Render type matchup chart using HTML template."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from seerapi_models import TypeCombinationORM

from astrbot.api import logger

from ..seer_data.image import ElementTypeImageGetter
from ..depends.type_calc import calc_attack_table, calc_defense_table
from ..seer_data.db import db_manager
from ..depends.render import render_html_to_bytes
from ._common import to_data_uri

TEMPLATE_PATH = "templates/type_matchup"
TEMPLATE_NAME = "template.html.j2"


def _get_template_path() -> str:
    plugin_dir = Path(__file__).parent.parent
    return str(plugin_dir / TEMPLATE_PATH / TEMPLATE_NAME)


TYPE_MATCHUP_TEMPLATE = open(_get_template_path(), "r", encoding="utf-8").read()


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
        icon_bytes_list = await asyncio.gather(
            *(ElementTypeImageGetter.get_bytes(str(cid)) for cid in id_list),
            return_exceptions=True
        )

        icon_map: dict[int, str] = {}
        for cid, data in zip(id_list, icon_bytes_list):
            if not isinstance(data, Exception):
                icon_map[cid] = to_data_uri(data)

        type_name = getattr(type_combo, 'name', '未知')
        type_icon = icon_map.get(type_combo.id, '')

        attack_items = []
        for combo, mult in attack_table:
            if mult != 1.0:
                attack_items.append({
                    'icon': icon_map.get(combo.id, ''),
                    'name': getattr(combo, 'name', ''),
                    'multiplier': mult,
                })

        attack_items.sort(key=lambda x: x['multiplier'], reverse=True)

        defense_items = []
        for combo, mult in defense_table:
            if mult != 1.0:
                defense_items.append({
                    'icon': icon_map.get(combo.id, ''),
                    'name': getattr(combo, 'name', ''),
                    'multiplier': mult,
                })

        defense_items.sort(key=lambda x: x['multiplier'], reverse=True)

        return {
            'type_name': type_name,
            'type_icon': type_icon,
            'attack_items': attack_items,
            'defense_items': defense_items,
            'cell_size': 72,
            'cell_gap': 6,
        }

    except Exception as e:
        logger.error(f"构建属性克制表数据失败: {e}")
        return {
            'type_name': getattr(type_combo, 'name', '未知'),
            'attack_items': [],
            'defense_items': [],
            'cell_size': 72,
            'cell_gap': 6,
        }


async def render_type_matchup(
    type_combo: TypeCombinationORM,
    is_local: bool = True,
    html_render=None,
) -> str:
    """Render type matchup chart to PNG image.

    Args:
        type_combo: The TypeCombinationORM object
        is_local: Whether to use local Playwright rendering
        html_render: AstrBot's html_render function (required for remote mode)

    Returns:
        Path to the rendered image file
    """
    render_data = await build_type_matchup_render_data(type_combo)

    if is_local:
        image_bytes = await render_html_to_bytes(
            TYPE_MATCHUP_TEMPLATE,
            render_data,
            viewport_width=1200,
        )
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(image_bytes)
            return f.name
    else:
        return await html_render(
            TYPE_MATCHUP_TEMPLATE,
            render_data,
            options={"scale": "device", "type": "png"},
        )