import astrbot.api.message_components as Comp
from astrbot.api.event import AstrMessageEvent

from ..data import BattleEffectDataGetter
from ..service import BattleEffectImageGetter, save_bytes_to_temp_file
from .common_handler import multi_select_query


class EffectHandler:
    @staticmethod
    def _build_effect_info(effect) -> str:
        type_names = (
            ", ".join(getattr(t, "name", "") for t in getattr(effect, "type", []) or []) or "无"
        )
        resistance_name = getattr(getattr(effect, "resistance", None), "name", "无")
        info = (
            f"💎【{effect.name}（ID：{effect.id}）】\n"
            f"类型：{type_names}\n"
            f"抗性类型：{resistance_name}\n"
            f"效果：{effect.desc or ''}"
        )
        return info

    async def battle_effect(self, event: AstrMessageEvent, arg: str = ""):
        async for result in multi_select_query(
            event,
            arg,
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
