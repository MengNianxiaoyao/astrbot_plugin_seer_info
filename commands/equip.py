"""Equip commands: 套装, 部件."""

from astrbot.api.event import AstrMessageEvent
import astrbot.api.message_components as Comp

from ..seer_data.db import SuitDataGetter, EquipDataGetter
from ..seer_data.image import SuitImageGetter, EquipImageGetter
from ..constants import EQUIP_PART_TYPE_MAP
from ..utils.image import save_bytes_to_temp_file
from ._common import multi_select_query


class EquipCommands:
    """Handler for suit (套装) and equip (部件) commands."""

    @staticmethod
    def _build_suit_info(suit) -> str:
        info = f"👚【{suit.name}】（{suit.id}）\n"

        equips = getattr(suit, 'equips', None)
        if equips:
            info += "部件：\n"
            for equip in equips:
                part_type_id = getattr(getattr(equip, 'part_type', None), 'id', None)
                part_type_name = EQUIP_PART_TYPE_MAP.get(part_type_id, "未知")
                equip_text = f"  {part_type_name}：{equip.name}（{equip.id}）"
                bonus = getattr(equip, 'bonus', None)
                if bonus and getattr(bonus, 'desc', None):
                    equip_text += f"\n      效果：{bonus.desc}"
                info += equip_text + "\n"

        bonus = getattr(getattr(suit, 'bonus', None), 'desc', None)
        info += f"套装效果：{bonus or '无'}"
        return info

    @staticmethod
    def _build_equip_info(equip) -> str:
        part_type_id = getattr(getattr(equip, 'part_type', None), 'id', None)
        part_type_name = EQUIP_PART_TYPE_MAP.get(part_type_id, "未知") if part_type_id is not None else "未知"

        info = f"👚【{equip.name}】（{equip.id}\）\n"
        info += f"部件类型：{part_type_name}\n"

        suit = getattr(equip, 'suit', None)
        if suit:
            info += f"所属套装：{suit.name}（{suit.id}）\n"

        bonus = getattr(equip, 'bonus', None)
        if bonus and getattr(bonus, 'desc', None):
            info += f"效果：{bonus.desc}\n"

        return info

    async def suit(self, event: AstrMessageEvent, arg: str = ""):
        """查询套装信息"""
        async for result in multi_select_query(
            event, arg,
            getter=SuitDataGetter,
            prepare_result=self._prepare_suit_result,
            label="套装",
            error_log_name="suit",
        ):
            yield result

    async def _prepare_suit_result(self, suit_obj):
        image_bytes = await SuitImageGetter.get_bytes(str(suit_obj.id))
        temp_path = save_bytes_to_temp_file(image_bytes)
        info = self._build_suit_info(suit_obj)
        return [
            Comp.Image.fromFileSystem(temp_path),
            Comp.Plain(info),
        ]

    async def equip(self, event: AstrMessageEvent, arg: str = ""):
        """查询装备部件信息"""
        async for result in multi_select_query(
            event, arg,
            getter=EquipDataGetter,
            prepare_result=self._prepare_equip_result,
            label="部件",
            error_log_name="equip",
        ):
            yield result

    async def _prepare_equip_result(self, equip_obj):
        image_bytes = await EquipImageGetter.get_bytes(str(equip_obj.id))
        temp_path = save_bytes_to_temp_file(image_bytes)
        info = self._build_equip_info(equip_obj)
        return [
            Comp.Image.fromFileSystem(temp_path),
            Comp.Plain(info),
        ]


__all__ = ["EquipCommands"]
