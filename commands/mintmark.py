"""Mintmark commands: 刻印, 宝石."""

import tempfile
from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from astrbot.core.utils.session_waiter import session_waiter, SessionController
import astrbot.api.message_components as Comp

from ..depends.db import MintmarkDataGetter, GemDataGetter, db_manager
from ..depends.image import MintmarkBodyImageGetter
from ..constants import _item_desc_fmt


class MintmarkCommands:
    """Handler for mintmark (刻印) and gem (宝石) commands."""

    async def _save_bytes_to_temp_file(self, image_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(image_bytes)
            return f.name

    @staticmethod
    def _build_mintmark_info(mm) -> str:
        info = f"💎【{mm.name}】\n"
        if getattr(mm, 'desc', None):
            info += f"描述：{mm.desc}\n"
        if hasattr(mm, 'attributes') and mm.attributes:
            attrs = ", ".join([f"{a.name}: {a.value}" for a in mm.attributes])
            info += f"属性：{attrs}\n"
        return info

    @staticmethod
    def _build_gem_info(gem) -> str:
        info = f"💎【{gem.name}】\n"
        if hasattr(gem, 'skill_effect_in_use') and gem.skill_effect_in_use:
            effect_infos = []
            for se in gem.skill_effect_in_use:
                if getattr(se, 'info', None):
                    effect_infos.append(se.info)
            if effect_infos:
                info += f"效果：{' | '.join(effect_infos)}\n"
        return info

    async def mintmark(self, event: AstrMessageEvent, arg: str = ""):
        """查询刻印信息及数值"""
        if not arg.strip():
            yield event.plain_result("❌请提供要查询的刻印名称。\n用法：/刻印 <名称>")
            return

        if not db_manager.is_database_loaded("seerapi"):
            yield event.plain_result("❌数据库未加载，请稍后再试")
            return

        sessions = db_manager.get_all_sessions()
        mintmarks = MintmarkDataGetter(sessions, arg)

        if not mintmarks:
            yield event.plain_result(f"❌未找到匹配的刻印: {arg}")
            return

        if len(mintmarks) > 20:
            yield event.plain_result(f"❌重名超过20个，请重新检索关键词！")
            return

        async def send_result(mm, evt):
            image_bytes = await MintmarkBodyImageGetter.get_bytes(str(mm.id))
            temp_path = await self._save_bytes_to_temp_file(image_bytes)
            info = self._build_mintmark_info(mm)
            await evt.send(evt.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ]))

        if len(mintmarks) == 1:
            await send_result(mintmarks[0], event)
            return

        prompt_items = [
            {"name": mm.name, "desc": _item_desc_fmt(mm), "value": mm.id}
            for mm in mintmarks[:20]
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
            await send_result(mintmarks[index], evt)
            controller.stop()

        msg = f"请问你想查询的刻印是……\n"
        for i, item in enumerate(prompt_items, 1):
            msg += f"{i}. {item['name']}（{item['desc']}）\n"
        msg += "\n💬 输入序号选择 · 输入 0 退出"

        yield event.plain_result(msg)

        try:
            await handler(event)
        except TimeoutError:
            yield event.plain_result("⏰选择超时，已退出")
        except Exception as e:
            logger.error(f"mintmark selection error: {e}")
            yield event.plain_result(f"发生错误: {e}")

    async def gem(self, event: AstrMessageEvent, arg: str = ""):
        """查询刻印宝石信息"""
        if not arg.strip():
            yield event.plain_result("❌请提供要查询的宝石名称。\n用法：/宝石 <名称>")
            return

        if not db_manager.is_database_loaded("seerapi"):
            yield event.plain_result("❌数据库未加载，请稍后再试")
            return

        sessions = db_manager.get_all_sessions()
        gems = GemDataGetter(sessions, arg)

        if not gems:
            yield event.plain_result(f"❌未找到匹配的宝石: {arg}")
            return

        if len(gems) > 20:
            yield event.plain_result(f"❌重名超过20个，请重新检索关键词！")
            return

        async def send_result(gem_obj, evt):
            info = self._build_gem_info(gem_obj)
            await evt.send(evt.plain_result(info))

        if len(gems) == 1:
            await send_result(gems[0], event)
            return

        prompt_items = [
            {"name": g.name, "desc": str(g.id), "value": g.id}
            for g in gems[:20]
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
            await send_result(gems[index], evt)
            controller.stop()

        msg = f"请问你想查询的宝石是……\n"
        for i, item in enumerate(prompt_items, 1):
            msg += f"{i}. {item['name']}（{item['desc']}）\n"
        msg += "\n💬 输入序号选择 · 输入 0 退出"

        yield event.plain_result(msg)

        try:
            await handler(event)
        except TimeoutError:
            yield event.plain_result("⏰选择超时，已退出")
        except Exception as e:
            logger.error(f"gem selection error: {e}")
            yield event.plain_result(f"发生错误: {e}")


__all__ = ["MintmarkCommands"]