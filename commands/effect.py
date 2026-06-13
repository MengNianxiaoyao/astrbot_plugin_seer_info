"""Battle effect command: 异常."""

from astrbot.api.event import AstrMessageEvent
import astrbot.api.message_components as Comp

from ..data.db import BattleEffectDataGetter
from ..data.image_fetcher import BattleEffectImageGetter
from ..data.cache import save_bytes_to_temp_file
from ._common import multi_select_query


class EffectCommands:
    """Handler for battle effect (异常状态) commands."""

    @staticmethod
    def _build_effect_info(effect) -> str:
        type_names = ', '.join(
            getattr(t, 'name', '') for t in getattr(effect, 'type', []) or []
        ) or '无'
        resistance_name = getattr(getattr(effect, 'resistance', None), 'name', '无')

        info = (
            f"💎【{effect.name}（ID：{effect.id}）】\n"
            f"类型：{type_names}\n"
            f"抗性类型：{resistance_name}\n"
            f"效果：{effect.desc or ''}"
        )
        return info

    async def battle_effect(self, event: AstrMessageEvent, arg: str = ""):
        """查询异常状态信息"""
        async for result in multi_select_query(
            event, arg,
            getter=BattleEffectDataGetter,
            prepare_result=self._prepare_result,
            label="异常状态",
            error_log_name="battle_effect",
        ):
            yield result

    async def _prepare_result(self, effect_obj):
        image_bytes = await BattleEffectImageGetter.get_bytes(str(effect_obj.id))
        temp_path = save_bytes_to_temp_file(image_bytes)
        info = self._build_effect_info(effect_obj)
        return [
            Comp.Image.fromFileSystem(temp_path),
            Comp.Plain(info),
        ]
