"""Attribute type matchup command: 属性."""

from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from astrbot.core.utils.session_waiter import session_waiter, SessionController

from ..depends.db import TypeCombinationDataGetter, db_manager
from ..render.type_matchup import render_type_matchup


class AttributeCommands:
    """Handler for attribute type matchup commands."""

    async def type_matchup(self, event: AstrMessageEvent, arg: str = ""):
        """查询属性克制表"""
        if not arg.strip():
            yield event.plain_result("❌请提供要查询的属性名称。\n用法：/属性 <属性名>")
            return

        if not db_manager.is_database_loaded("seerapi"):
            yield event.plain_result("❌数据库未加载，请稍后再试")
            return

        sessions = db_manager.get_all_sessions()
        types = TypeCombinationDataGetter(sessions, arg)

        if not types:
            yield event.plain_result(f"❌未找到匹配的属性: {arg}")
            return

        if len(types) > 20:
            yield event.plain_result(f"❌重名超过20个，请重新检索关键词！")
            return

        async def send_result(type_combo, evt):
            temp_path = await render_type_matchup(type_combo)
            await evt.send(evt.image_result(temp_path))

        if len(types) == 1:
            await send_result(types[0], event)
            return

        prompt_items = [
            {"name": f"{t.primary.name if t.primary else ''}{t.secondary.name if t.secondary else '（单属性）'}",
             "desc": str(t.id), "value": t.id}
            for t in types[:20]
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
            await send_result(types[index], evt)
            controller.stop()

        msg = f"请问你想查询的属性是……\n"
        for i, item in enumerate(prompt_items, 1):
            msg += f"{i}. {item['name']}（{item['desc']}）\n"
        msg += "\n💬 输入序号选择 · 输入 0 退出"

        yield event.plain_result(msg)

        try:
            await handler(event)
        except TimeoutError:
            yield event.plain_result("⏰选择超时，已退出")
        except Exception as e:
            logger.error(f"type_matchup selection error: {e}")
            yield event.plain_result(f"发生错误: {e}")


__all__ = ["AttributeCommands"]