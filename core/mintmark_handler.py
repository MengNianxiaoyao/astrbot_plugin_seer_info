import astrbot.api.message_components as Comp
from astrbot.api.event import AstrMessageEvent

from ..data import GemDataGetter, MintmarkDataGetter
from ..service import MintmarkBodyImageGetter, save_bytes_to_temp_file
from .common_handler import multi_select_query


class MintmarkHandler:
    @staticmethod
    def _build_mintmark_info(mm) -> str:
        info = f"💎【{mm.name}】\n"
        if getattr(mm, "desc", None):
            info += f"描述：{mm.desc}\n"
        if hasattr(mm, "attributes") and mm.attributes:
            attrs = ", ".join([f"{a.name}: {a.value}" for a in mm.attributes])
            info += f"属性：{attrs}\n"
        return info

    @staticmethod
    def _build_gem_info(gem) -> str:
        info = f"💎【{gem.name}】\n"
        if hasattr(gem, "skill_effect_in_use") and gem.skill_effect_in_use:
            effect_infos = []
            for se in gem.skill_effect_in_use:
                if getattr(se, "info", None):
                    effect_infos.append(se.info)
            if effect_infos:
                info += f"效果：{' | '.join(effect_infos)}\n"
        return info

    async def mintmark(self, event: AstrMessageEvent, arg: str = ""):
        async for result in multi_select_query(
            event,
            arg,
            getter=MintmarkDataGetter,
            prepare_result=self._prepare_mintmark_result,
            label="刻印",
            error_log_name="mintmark",
        ):
            yield result

    async def _prepare_mintmark_result(self, mm):
        image_bytes = await MintmarkBodyImageGetter.get_bytes(str(mm.id))
        temp_path = save_bytes_to_temp_file(image_bytes)
        info = self._build_mintmark_info(mm)
        return [
            Comp.Image.fromFileSystem(temp_path),
            Comp.Plain(info),
        ]

    async def gem(self, event: AstrMessageEvent, arg: str = ""):
        async for result in multi_select_query(
            event,
            arg,
            getter=GemDataGetter,
            prepare_result=self._prepare_gem_result,
            label="宝石",
            error_log_name="gem",
        ):
            yield result

    async def _prepare_gem_result(self, gem_obj):
        info = self._build_gem_info(gem_obj)
        return [Comp.Plain(info)]
