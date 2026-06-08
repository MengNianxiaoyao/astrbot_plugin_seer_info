"""Equip commands: 套装, 部件."""

import tempfile
from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from astrbot.core.utils.session_waiter import session_waiter, SessionController
import astrbot.api.message_components as Comp

from ..seer_data.db import SuitDataGetter, EquipDataGetter, db_manager
from ..seer_data.image import SuitImageGetter, EquipImageGetter
from ..constants import EQUIP_PART_TYPE_MAP


class EquipCommands:
    """Handler for suit (套装) and equip (部件) commands."""

    async def _save_bytes_to_temp_file(self, image_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(image_bytes)
            return f.name

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
        if not arg.strip():
            yield event.plain_result("❌请提供要查询的套装名称。\n用法：/套装 <名称>")
            return

        if not db_manager.is_database_loaded("seerapi"):
            yield event.plain_result("❌数据库未加载，请稍后再试")
            return

        sessions = db_manager.get_all_sessions()
        suits = SuitDataGetter(sessions, arg)

        if not suits:
            yield event.plain_result(f"❌未找到匹配的套装: {arg}")
            return

        if len(suits) > 20:
            yield event.plain_result(f"❌重名超过20个，请重新检索关键词！")
            return

        async def prepare_result(suit_obj):
            image_bytes = await SuitImageGetter.get_bytes(str(suit_obj.id))
            temp_path = await self._save_bytes_to_temp_file(image_bytes)
            info = self._build_suit_info(suit_obj)
            return [
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ]

        if len(suits) == 1:
            yield event.chain_result(await prepare_result(suits[0]))
            return

        async def send_result(suit_obj, evt):
            await evt.send(evt.chain_result(await prepare_result(suit_obj)))

        prompt_items = [
            {"name": s.name, "desc": str(s.id), "value": s.id}
            for s in suits[:20]
        ]

        prompt_map = {str(i+1): p["value"] for i, p in enumerate(prompt_items)}

        @session_waiter(timeout=60, record_history_chains=False)
        async def handler(controller: SessionController, evt: AstrMessageEvent):
            user_input = evt.message_str.strip()
            if user_input == "0":
                await evt.send(evt.plain_result("❌已退出查询"))
                controller.stop()
                return

            if user_input not in prompt_map:
                await evt.send(evt.plain_result("⚠️序号无效，请重新输入"))
                controller.keep(timeout=60, reset_timeout=True)
                return

            index = int(user_input) - 1
            await send_result(suits[index], evt)
            controller.stop()

        msg = f"请问你想查询的套装是……\n"
        for i, item in enumerate(prompt_items, 1):
            msg += f"{i}. {item['name']}（{item['desc']}）\n"
        msg += "\n💬 输入序号选择 · 输入 0 退出"

        yield event.plain_result(msg)

        try:
            await handler(event)
        except TimeoutError:
            yield event.plain_result("⏰选择超时，已退出")
        except Exception as e:
            logger.error(f"suit selection error: {e}")
            yield event.plain_result(f"发生错误: {e}")

    async def equip(self, event: AstrMessageEvent, arg: str = ""):
        """查询装备部件信息"""
        if not arg.strip():
            yield event.plain_result("❌请提供要查询的部件名称。\n用法：/部件 <名称>")
            return

        if not db_manager.is_database_loaded("seerapi"):
            yield event.plain_result("❌数据库未加载，请稍后再试")
            return

        sessions = db_manager.get_all_sessions()
        equips = EquipDataGetter(sessions, arg)

        if not equips:
            yield event.plain_result(f"❌未找到匹配的部件: {arg}")
            return

        if len(equips) > 20:
            yield event.plain_result(f"❌重名超过20个，请重新检索关键词！")
            return

        async def prepare_result(equip_obj):
            image_bytes = await EquipImageGetter.get_bytes(str(equip_obj.id))
            temp_path = await self._save_bytes_to_temp_file(image_bytes)
            info = self._build_equip_info(equip_obj)
            return [
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ]

        if len(equips) == 1:
            yield event.chain_result(await prepare_result(equips[0]))
            return

        async def send_result(equip_obj, evt):
            await evt.send(evt.chain_result(await prepare_result(equip_obj)))

        prompt_items = [
            {"name": e.name, "desc": str(e.id), "value": e.id}
            for e in equips[:20]
        ]

        prompt_map = {str(i+1): p["value"] for i, p in enumerate(prompt_items)}

        @session_waiter(timeout=60, record_history_chains=False)
        async def handler(controller: SessionController, evt: AstrMessageEvent):
            user_input = evt.message_str.strip()
            if user_input == "0":
                await evt.send(evt.plain_result("❌已退出查询"))
                controller.stop()
                return

            if user_input not in prompt_map:
                await evt.send(evt.plain_result("⚠️序号无效，请重新输入"))
                controller.keep(timeout=60, reset_timeout=True)
                return

            index = int(user_input) - 1
            await send_result(equips[index], evt)
            controller.stop()

        msg = f"请问你想查询的部件是……\n"
        for i, item in enumerate(prompt_items, 1):
            msg += f"{i}. {item['name']}（{item['desc']}）\n"
        msg += "\n💬 输入序号选择 · 输入 0 退出"

        yield event.plain_result(msg)

        try:
            await handler(event)
        except TimeoutError:
            yield event.plain_result("⏰选择超时，已退出")
        except Exception as e:
            logger.error(f"equip selection error: {e}")
            yield event.plain_result(f"发生错误: {e}")


__all__ = ["EquipCommands"]