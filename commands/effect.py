"""Battle effect command: 异常."""

import tempfile
from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from astrbot.core.utils.session_waiter import session_waiter, SessionController
import astrbot.api.message_components as Comp

from ..depends.db import BattleEffectDataGetter, db_manager
from ..depends.image import BattleEffectImageGetter


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
        if not arg.strip():
            yield event.plain_result("❌请提供要查询的异常状态名称。\n用法：/异常 <名称>")
            return

        if not db_manager.is_database_loaded("seerapi"):
            yield event.plain_result("❌数据库未加载，请稍后再试")
            return

        sessions = db_manager.get_all_sessions()
        effects = BattleEffectDataGetter(sessions, arg)

        if not effects:
            yield event.plain_result(f"❌未找到匹配的异常状态: {arg}")
            return

        if len(effects) > 20:
            yield event.plain_result(f"❌重名超过20个，请重新检索关键词！")
            return

        async def prepare_result(effect_obj):
            image_bytes = await BattleEffectImageGetter.get_bytes(str(effect_obj.id))
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(image_bytes)
                temp_path = f.name
            info = self._build_effect_info(effect_obj)
            return [
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info),
            ]

        if len(effects) == 1:
            yield event.chain_result(await prepare_result(effects[0]))
            return

        async def send_result(effect_obj, evt):
            await evt.send(evt.chain_result(await prepare_result(effect_obj)))

        prompt_items = [
            {"name": effect.name, "desc": str(effect.id), "value": effect.id}
            for effect in effects[:20]
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
            await send_result(effects[index], evt)
            controller.stop()

        msg = f"请问你想查询的异常状态是……\n"
        for i, item in enumerate(prompt_items, 1):
            msg += f"{i}. {item['name']}（{item['desc']}）\n"
        msg += "\n💬 输入序号选择 · 输入 0 退出"

        yield event.plain_result(msg)

        try:
            await handler(event)
        except TimeoutError:
            yield event.plain_result("⏰选择超时，已退出")
        except Exception as e:
            logger.error(f"battle_effect selection error: {e}")
            yield event.plain_result(f"发生错误: {e}")


__all__ = ["EffectCommands"]