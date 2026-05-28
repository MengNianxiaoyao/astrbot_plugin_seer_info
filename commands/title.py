"""Title command: 称号."""

import tempfile
from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from astrbot.core.utils.session_waiter import session_waiter, SessionController
import astrbot.api.message_components as Comp

from ..depends.db import TitleDataGetter, db_manager
from ..depends.image import TitleImageGetter


class TitleCommands:
    """Handler for title (称号) commands."""

    async def _save_bytes_to_temp_file(self, image_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(image_bytes)
            return f.name

    @staticmethod
    def _build_title_info(title) -> str:
        info = f"【{title.name}】\n"
        info += f"🆔：{title.id}"
        if getattr(title, 'ability_desc', None):
            info += f"\n效果：{title.ability_desc}"
        return info

    async def title_info(self, event: AstrMessageEvent, arg: str = ""):
        """查询称号信息"""
        if not arg.strip():
            yield event.plain_result("❌请提供要查询的称号名称或ID。\n用法：/称号 <名称>")
            return

        if not db_manager.is_database_loaded("seerapi"):
            yield event.plain_result("❌数据库未加载，请稍后再试")
            return

        sessions = db_manager.get_all_sessions()
        titles = TitleDataGetter(sessions, arg)

        if not titles:
            yield event.plain_result(f"❌未找到匹配的称号: {arg}")
            return

        if len(titles) > 20:
            yield event.plain_result(f"❌重名超过20个，请重新检索关键词！")
            return

        async def send_result(title_obj, evt):
            image_bytes = await TitleImageGetter.get_bytes(str(title_obj.id))
            temp_path = await self._save_bytes_to_temp_file(image_bytes)
            info = self._build_title_info(title_obj)
            await evt.send(evt.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ]))

        if len(titles) == 1:
            await send_result(titles[0], event)
            return

        prompt_items = [
            {"name": title.name, "desc": str(title.id), "value": title.id}
            for title in titles[:20]
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
            await send_result(titles[index], evt)
            controller.stop()

        msg = f"请问你想查询的称号是……\n"
        for i, item in enumerate(prompt_items, 1):
            msg += f"{i}. {item['name']}（{item['desc']}）\n"
        msg += "\n💬 输入序号选择 · 输入 0 退出"

        yield event.plain_result(msg)

        try:
            await handler(event)
        except TimeoutError:
            yield event.plain_result("⏰选择超时，已退出")
        except Exception as e:
            logger.error(f"title_info selection error: {e}")
            yield event.plain_result(f"发生错误: {e}")


__all__ = ["TitleCommands"]