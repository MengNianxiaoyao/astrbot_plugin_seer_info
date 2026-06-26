"""Pet-related commands: 精灵, 立绘."""

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.utils.session_waiter import SessionController, session_waiter

from ..core.renderer import render_to_image
from ..data.cache import save_bytes_to_temp_file
from ..data.db import (
    PetDataGetter,
    PetORM,
    PetSkinDataGetter,
    db_manager,
)
from ..data.image_fetcher import PetBodyImageGetter
from ..renderers.pet_info import PET_TEMPLATE, render_pet_info_data
from ._common import multi_select_query


class PetCommands:
    """Handler for pet-related commands."""

    def __init__(self, html_render=None, image_format: str = "jpeg", jpeg_quality: int = 85):
        self._html_render = html_render
        self._image_format = image_format
        self._jpeg_quality = jpeg_quality

    async def _render_pet_info_html(self, pet) -> str:
        render_data = await render_pet_info_data(pet)
        return await render_to_image(
            PET_TEMPLATE,
            render_data,
            html_render=self._html_render,
            image_format=self._image_format,
            jpeg_quality=self._jpeg_quality,
        )

    async def pet_info(self, event: AstrMessageEvent, arg: str = ""):
        """查询精灵基础信息"""
        if not arg.strip():
            yield event.plain_result("❌请提供要查询的精灵名称或ID。\n用法：/精灵 <名称>")
            return

        if not db_manager.is_database_loaded("seerapi"):
            yield event.plain_result("❌数据库未加载，请稍后再试")
            return

        sessions = db_manager.get_all_sessions()
        pets = PetDataGetter(sessions, arg)

        if not pets:
            yield event.plain_result(f"❌未找到匹配的精灵: {arg}")
            return

        if len(pets) > 20:
            yield event.plain_result("❌重名超过20个，请重新检索关键词！")
            return

        if len(pets) == 1:
            yield event.image_result(await self._render_pet_info_html(pets[0]))
            return

        prompt_items = [
            {"name": pet.name, "desc": str(pet.id), "value": pet.id}
            for pet in pets[:20]
        ]
        prompt_map = {str(i + 1): p["value"] for i, p in enumerate(prompt_items)}

        async def send_result(pet_obj, evt):
            await evt.send(evt.image_result(await self._render_pet_info_html(pet_obj)))

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

            pet_obj = sessions.get("seerapi").get(PetORM, prompt_map[user_input])
            if not pet_obj:
                await evt.send(evt.plain_result(f"❌未找到精灵 ID: {prompt_map[user_input]}"))
                controller.stop()
                return
            await send_result(pet_obj, evt)
            controller.stop()

        msg = "请问你想查询的精灵是……\n"
        for i, item in enumerate(prompt_items, 1):
            msg += f"{i}. {item['name']}（{item['desc']}）\n"
        msg += "\n💬 输入序号选择 · 输入 0 退出"

        yield event.plain_result(msg)

        try:
            await handler(event)
        except TimeoutError:
            yield event.plain_result("⏰选择超时，已退出")
        except Exception as e:
            logger.error(f"pet_info selection error: {e}")
            yield event.plain_result(f"发生错误: {e}")

    async def pet_image(self, event: AstrMessageEvent, arg: str = ""):
        """查询精灵或皮肤立绘"""
        async for result in multi_select_query(
            event, arg,
            getter=PetSkinDataGetter,
            prepare_result=self._prepare_skin_result,
            label="立绘",
            error_log_name="pet_image",
        ):
            yield result

    async def _prepare_skin_result(self, skin):
        image_bytes = await PetBodyImageGetter.get_bytes(str(skin.resource_id))
        temp_path = save_bytes_to_temp_file(image_bytes)
        return [
            Comp.Image.fromFileSystem(temp_path),
            Comp.Plain(f"💎【{skin.name}】"),
        ]
