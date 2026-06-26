"""Title command: 称号."""

import astrbot.api.message_components as Comp
from astrbot.api.event import AstrMessageEvent

from ..data.cache import save_bytes_to_temp_file
from ..data.db import TitleDataGetter
from ..data.image_fetcher import TitleImageGetter
from ._common import multi_select_query


class TitleCommands:
    """Handler for title (称号) commands."""

    @staticmethod
    def _build_title_info(title) -> str:
        info = f"【{title.name}】\n"
        info += f"🆔：{title.id}"
        if getattr(title, 'ability_desc', None):
            info += f"\n效果：{title.ability_desc}"
        return info

    async def title_info(self, event: AstrMessageEvent, arg: str = ""):
        """查询称号信息"""
        async for result in multi_select_query(
            event, arg,
            getter=TitleDataGetter,
            prepare_result=self._prepare_result,
            label="称号",
            error_log_name="title_info",
        ):
            yield result

    async def _prepare_result(self, title_obj):
        image_bytes = await TitleImageGetter.get_bytes(str(title_obj.id))
        temp_path = save_bytes_to_temp_file(image_bytes)
        info = self._build_title_info(title_obj)
        return [
            Comp.Image.fromFileSystem(temp_path),
            Comp.Plain(info),
        ]
