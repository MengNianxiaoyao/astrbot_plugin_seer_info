"""
AstrBot Plugin: Seer Info (赛尔号数据查询)

Ported from IronsBot NoneBot2 plugin to AstrBot framework.
"""

import asyncio
import os
import re
import tempfile
from io import BytesIO
from pathlib import Path

import aiohttp
import jinja2
from PIL import Image, ImageDraw, ImageFont

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger
from astrbot.core.utils.session_waiter import session_waiter, SessionController
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
import astrbot.api.message_components as Comp
from seerapi_models import MintmarkORM
from seerapi_models.common import SixAttributes
from seerapi_models.mintmark import AbilityPartORM, SkillPartORM, UniversalPartORM

from .depends.db import (
    PetORM,
    PetDataGetter,
    PetSkinDataGetter,
    MintmarkDataGetter,
    GemDataGetter,
    SuitDataGetter,
    EquipDataGetter,
    TypeCombinationDataGetter,
    BattleEffectDataGetter,
    TitleDataGetter,
    TitlePartORM,
    db_manager,
    register_database,
    register_local_database,
    get_plugin_db_path,
    _build_pinyin_fts,
)
from .render.pet_info import render_pet_info_data, PET_TEMPLATE
from .depends.image import (
    PetBodyImageGetter,
    PetHeadImageGetter,
    MintmarkBodyImageGetter,
    ElementTypeImageGetter,
    SuitImageGetter,
    EquipImageGetter,
    TitleImageGetter,
    BattleEffectImageGetter,
    PreviewImageGetter,
)


EQUIP_PART_TYPE_MAP = {
    0: "头部",
    1: "眼部",
    2: "腰部",
    3: "手部",
    4: "脚部",
    5: "背景",
    6: "星际座驾",
}


def _mark_attributes(mintmark: MintmarkORM) -> SixAttributes | None:
    part = mintmark.ability_part or mintmark.skill_part or mintmark.universal_part
    if isinstance(part, AbilityPartORM):
        attr = part.max_attr_value.to_model()
    elif isinstance(part, UniversalPartORM):
        attr = part.max_attr_value.to_model()
        if part.extra_attr_value:
            attr = attr + part.extra_attr_value.to_model()
    elif isinstance(part, SkillPartORM):
        return None
    else:
        raise TypeError(f"未知的刻印类型: {type(part)}")
    return attr.round()


def _mark_type_description(attributes: SixAttributes | None) -> str:
    strings: list[str] = []
    if attributes is None:
        return ""
    if attributes.atk and not attributes.sp_atk:
        strings.append("物")
    elif attributes.sp_atk and not attributes.atk:
        strings.append("特")
    elif attributes.atk and attributes.sp_atk:
        strings.append("双刀")

    if (attributes.atk >= 54 or attributes.sp_atk >= 54) and attributes.spd < 40:
        strings.append("攻")
    if attributes.spd >= 40:
        strings.append("速")
    if attributes.def_ >= 40 or attributes.sp_def >= 40:
        strings.append("盾")
    if attributes.hp >= 100:
        strings.append("体")

    return "".join(strings)


def _fmt_attr(label: str, value: float, col_width: int = 8) -> str:
    text = f"-{label}{value}"
    cjk_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    display_len = len(text) + cjk_count
    return text + "\u2007" * max(col_width - display_len, 1)


def _item_desc_fmt(mintmark: MintmarkORM) -> str:
    attr = _mark_attributes(mintmark)
    if attr is None or not (desc := _mark_type_description(attr)):
        return f"{mintmark.id}"
    return f"{mintmark.id} {desc}"


class SeerInfoPlugin(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.config = config
        self.name = "astrbot_plugin_seer_info"
        self._setup_databases()

    def _setup_databases(self):
        seerapi_sync_url = self.config.get("seerapi_sync_url", "")
        seerapi_fingerprint_url = self.config.get("seerapi_fingerprint_url", "")
        seerapi_sync_interval = self.config.get("seerapi_sync_interval_minutes", 60)

        async def get_seerapi_fingerprint(session: aiohttp.ClientSession) -> str:
            async with session.get(seerapi_fingerprint_url) as resp:
                resp.raise_for_status()
                return (await resp.read()).decode().strip()

        if seerapi_sync_url:
            register_database(
                "seerapi",
                sync_url=seerapi_sync_url,
                sync_interval_minutes=seerapi_sync_interval,
                get_fingerprint=get_seerapi_fingerprint if seerapi_fingerprint_url else None,
            )
        else:
            default_path = get_plugin_db_path("seerapi")
            register_local_database("seerapi", file_path=default_path)

        alias_sync_url = self.config.get("alias_sync_url", "")
        alias_fingerprint_url = self.config.get("alias_fingerprint_url", "")
        alias_sync_interval = self.config.get("alias_sync_interval_minutes", 60)

        async def get_alias_fingerprint(session: aiohttp.ClientSession) -> str:
            async with session.get(alias_fingerprint_url) as resp:
                resp.raise_for_status()
                return (await resp.read()).decode().strip()

        if alias_sync_url:
            register_database(
                "aliases",
                sync_url=alias_sync_url,
                sync_interval_minutes=alias_sync_interval,
                get_fingerprint=get_alias_fingerprint if alias_fingerprint_url else None,
            )
        else:
            default_alias_path = get_plugin_db_path("aliases")
            register_local_database("aliases", file_path=default_alias_path)

    async def terminate(self):
        logger.info("SeerInfo 插件已卸载")

    async def _render_pet_info_html(self, pet, sessions: dict) -> str:
        render_data = await render_pet_info_data(pet)
        return await self.html_render(
            PET_TEMPLATE,
            render_data,
            options={"scale": "device", "type": "png"},
        )

    async def _save_bytes_to_temp_file(self, image_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(image_bytes)
            return f.name

    async def _handle_selection(
        self,
        event: AstrMessageEvent,
        prompt_items: list[dict],
        on_select: callable,
        entity_name: str = "选项",
    ):
        msg = f"请问你想查询的{entity_name}是……\n"
        for i, item in enumerate(prompt_items, 1):
            msg += f"{i}. {item['name']}（{item['desc']}）\n"
        msg += "\n💬 输入序号选择 · 输入 0 退出"

        yield event.plain_result(msg)

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
            await on_select(evt, prompt_map[user_input], prompt_items[index], index)
            controller.stop()

        try:
            await handler(event)
        except TimeoutError:
            yield event.plain_result("⏰选择超时，已退出")
        except Exception as e:
            logger.error(f"selection error: {e}")
            yield event.plain_result(f"发生错误: {e}")

    @filter.command("精灵", alias={"查询精灵信息", "魂印", "技能"})
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

        if len(pets) == 1:
            pet = pets[0]
            image_url = await self._render_pet_info_html(pet, sessions)
            yield event.image_result(image_url)
            return

        prompt_items = [
            {"name": pet.name, "desc": str(pet.id), "value": pet.id}
            for pet in pets[:20]
        ]

        async def on_select(evt: AstrMessageEvent, pet_id: int, item: dict, index: int):
            session = db_manager.get_all_sessions()
            pet_obj = session.get("seerapi", {}).get(PetORM, pet_id)
            if not pet_obj:
                await evt.send(evt.plain_result(f"❌未找到精灵 ID: {pet_id}"))
                return
            image_url = await self._render_pet_info_html(pet_obj, session)
            await evt.send(evt.image_result(image_url))

        async for r in self._handle_selection(event, prompt_items, on_select, "精灵"):
            yield r

    @filter.command("立绘", alias={"皮肤", "查询立绘"})
    async def pet_image(self, event: AstrMessageEvent, arg: str = ""):
        """查询精灵或皮肤立绘"""
        if not arg.strip():
            yield event.plain_result("❌请提供要查询的立绘名称或ID。\n用法：/立绘 <名称>")
            return

        sessions = db_manager.get_all_sessions()
        skins = PetSkinDataGetter(sessions, arg)

        if not skins:
            yield event.plain_result(f"❌未找到匹配的立绘: {arg}")
            return

        if len(skins) == 1:
            skin = skins[0]
            image_bytes = await PetBodyImageGetter.get_bytes(str(skin.resource_id))
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(image_bytes)
                temp_path = f.name
            yield event.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(f"💎【{skin.name}】")
            ])
            return

        prompt_items = [
            {"name": skin.name, "desc": str(skin.resource_id), "value": skin.resource_id}
            for skin in skins[:20]
        ]

        async def on_select(evt: AstrMessageEvent, resource_id: int, item: dict, index: int):
            skin = skins[index]
            image_bytes = await PetBodyImageGetter.get_bytes(str(resource_id))
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(image_bytes)
                temp_path = f.name
            await evt.send(evt.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(f"💎【{skin.name}】")
            ]))

        async for r in self._handle_selection(event, prompt_items, on_select, "立绘"):
            yield r

    @filter.command("属性")
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

        if len(types) == 1:
            type_combo = types[0]
            from .render.type_matchup import render_type_matchup
            temp_path = await render_type_matchup(type_combo, self.html_render)
            yield event.image_result(temp_path)
            return

        prompt_items = [
            {"name": f"{t.primary.name if t.primary else ''}{t.secondary.name if t.secondary else '（单属性）'}",
             "desc": str(t.id), "value": t.id}
            for t in types[:20]
        ]

        async def on_select(evt: AstrMessageEvent, type_id: int, item: dict, index: int):
            type_combo = types[index]
            from .render.type_matchup import render_type_matchup
            temp_path = await render_type_matchup(type_combo, self.html_render)
            await evt.send(evt.image_result(temp_path))

        async for r in self._handle_selection(event, prompt_items, on_select, "属性"):
            yield r

    @filter.command("异常", alias={"查询异常状态"})
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

        if len(effects) == 1:
            effect = effects[0]
            image_bytes = await BattleEffectImageGetter.get_bytes(str(effect.id))
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(image_bytes)
                temp_path = f.name
            chain = [
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(f"💎【{effect.name}】\n{effect.desc or ''}")
            ]
            yield event.chain_result(chain)
            return

        prompt_items = [
            {"name": effect.name, "desc": str(effect.id), "value": effect.id}
            for effect in effects[:20]
        ]

        async def on_select(evt: AstrMessageEvent, effect_id: int, item: dict, index: int):
            effect = effects[index]
            image_bytes = await BattleEffectImageGetter.get_bytes(str(effect_id))
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(image_bytes)
                temp_path = f.name
            await evt.send(evt.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(f"💎【{effect.name}】\n{effect.desc or ''}")
            ]))

        async for r in self._handle_selection(event, prompt_items, on_select, "异常状态"):
            yield r

    @filter.command("刻印")
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

        if len(mintmarks) == 1:
            mm = mintmarks[0]
            image_bytes = await MintmarkBodyImageGetter.get_bytes(str(mm.id))
            temp_path = await self._save_bytes_to_temp_file(image_bytes)
            info = f"💎【{mm.name}】\n"
            if mm.desc:
                info += f"描述：{mm.desc}\n"
            if hasattr(mm, 'attributes') and mm.attributes:
                attrs = ", ".join([f"{a.name}: {a.value}" for a in mm.attributes])
                info += f"属性：{attrs}\n"
            yield event.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ])
            return

        prompt_items = [
            {"name": mm.name, "desc": _item_desc_fmt(mm), "value": mm.id}
            for mm in mintmarks[:20]
        ]

        async def on_select(evt: AstrMessageEvent, mm_id: int, item: dict, index: int):
            mm = mintmarks[index]
            image_bytes = await MintmarkBodyImageGetter.get_bytes(str(mm.id))
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(image_bytes)
                temp_path = f.name

            info = f"💎【{mm.name}】\n"
            if mm.desc:
                info += f"描述：{mm.desc}\n"
            if hasattr(mm, 'attributes') and mm.attributes:
                attrs = ", ".join([f"{a.name}: {a.value}" for a in mm.attributes])
                info += f"属性：{attrs}\n"

            await evt.send(evt.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ]))

        async for r in self._handle_selection(event, prompt_items, on_select, "刻印"):
            yield r

    @filter.command("宝石")
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

        if len(gems) == 1:
            gem = gems[0]
            info = f"💎【{gem.name}】\n"
            if hasattr(gem, 'skill_effect_in_use') and gem.skill_effect_in_use:
                effect_infos = []
                for se in gem.skill_effect_in_use:
                    if hasattr(se, 'info') and se.info:
                        effect_infos.append(se.info)
                if effect_infos:
                    info += f"效果：{' | '.join(effect_infos)}\n"
            yield event.plain_result(info)
            return

        prompt_items = [
            {"name": g.name, "desc": str(g.id), "value": g.id}
            for g in gems[:20]
        ]

        async def on_select(evt: AstrMessageEvent, gem_id: int, item: dict, index: int):
            try:
                gem = gems[index]
                info = f"💎【{gem.name}】\n"
                if hasattr(gem, 'skill_effect_in_use') and gem.skill_effect_in_use:
                    effect_infos = []
                    for se in gem.skill_effect_in_use:
                        if hasattr(se, 'info') and se.info:
                            effect_infos.append(se.info)
                    if effect_infos:
                        info += f"效果：{' | '.join(effect_infos)}\n"
                await evt.send(evt.plain_result(info))
            except Exception as e:
                logger.error(f"gem on_select error: {e}")
                await evt.send(evt.plain_result(f"发生错误: {e}"))

        async for r in self._handle_selection(event, prompt_items, on_select, "宝石"):
            yield r

    @filter.command("套装", alias={"查询套装信息"})
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

        if len(suits) == 1:
            suit = suits[0]
            image_bytes = await SuitImageGetter.get_bytes(str(suit.id))
            temp_path = await self._save_bytes_to_temp_file(image_bytes)
            info = f"🏆【{suit.name}】\n"
            if hasattr(suit, 'bonus') and suit.bonus and suit.bonus.desc:
                info += f"套装效果：{suit.bonus.desc}\n"
            yield event.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ])
            return

        prompt_items = [
            {"name": s.name, "desc": str(s.id), "value": s.id}
            for s in suits[:20]
        ]

        async def on_select(evt: AstrMessageEvent, suit_id: int, item: dict, index: int):
            suit = suits[index]
            image_bytes = await SuitImageGetter.get_bytes(str(suit.id))
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(image_bytes)
                temp_path = f.name

            info = f"🏆【{suit.name}】\n"
            if hasattr(suit, 'bonus') and suit.bonus and suit.bonus.desc:
                info += f"套装效果：{suit.bonus.desc}\n"

            await evt.send(evt.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ]))

        async for r in self._handle_selection(event, prompt_items, on_select, "套装"):
            yield r

    @filter.command("部件", alias={"查询部件信息"})
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

        if len(equips) == 1:
            equip = equips[0]
            image_bytes = await EquipImageGetter.get_bytes(str(equip.id))
            temp_path = await self._save_bytes_to_temp_file(image_bytes)

            part_type_id = getattr(getattr(equip, 'part_type', None), 'id', None)
            part_type_name = EQUIP_PART_TYPE_MAP.get(part_type_id, "未知") if part_type_id is not None else "未知"

            info = f"👚【{equip.name}】\n"
            info += f"🆔：{equip.id}\n"
            info += f"部件类型：{part_type_name}\n"
            if hasattr(equip, 'suit') and equip.suit:
                info += f"所属套装：{equip.suit.name}（{equip.suit.id}）\n"
            bonus_desc = getattr(equip, 'bonus', None)
            if bonus_desc and hasattr(bonus_desc, 'desc') and bonus_desc.desc:
                info += f"效果：{bonus_desc.desc}\n"

            yield event.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ])
            return

        prompt_items = [
            {"name": e.name, "desc": str(e.id), "value": e.id}
            for e in equips[:20]
        ]

        async def on_select(evt: AstrMessageEvent, equip_id: int, item: dict, index: int):
            equip = equips[index]
            image_bytes = await EquipImageGetter.get_bytes(str(equip.id))
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                f.write(image_bytes)
                temp_path = f.name

            part_type_id = getattr(getattr(equip, 'part_type', None), 'id', None)
            part_type_name = EQUIP_PART_TYPE_MAP.get(part_type_id, "未知") if part_type_id is not None else "未知"

            info = f"👚【{equip.name}】\n"
            info += f"🆔：{equip.id}\n"
            info += f"部件类型：{part_type_name}\n"
            if hasattr(equip, 'suit') and equip.suit:
                info += f"所属套装：{equip.suit.name}（{equip.suit.id}）\n"
            bonus_desc = getattr(equip, 'bonus', None)
            if bonus_desc and hasattr(bonus_desc, 'desc') and bonus_desc.desc:
                info += f"效果：{bonus_desc.desc}\n"

            await evt.send(evt.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ]))

        async for r in self._handle_selection(event, prompt_items, on_select, "部件"):
            yield r

    @filter.command("称号", alias={"查询称号信息"})
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

        if len(titles) == 1:
            title = titles[0]
            image_bytes = await TitleImageGetter.get_bytes(str(title.id))
            temp_path = await self._save_bytes_to_temp_file(image_bytes)
            info = f"【{title.name}】\n"
            info += f"🆔：{title.id}"
            if title.ability_desc:
                info += f"\n效果：{title.ability_desc}"
            yield event.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ])
            return

        if len(titles) > 20:
            yield event.plain_result(f"❌重名超过20个，请重新检索关键词！")
            return

        prompt_items = [
            {"name": title.name, "desc": str(title.id), "value": title.id}
            for title in titles[:20]
        ]

        async def on_select(evt: AstrMessageEvent, title_id: int, item: dict, index: int):
            title = titles[index]
            image_bytes = await TitleImageGetter.get_bytes(str(title.id))
            temp_path = await self._save_bytes_to_temp_file(image_bytes)
            info = f"【{title.name}】\n"
            info += f"🆔：{title.id}"
            if title.ability_desc:
                info += f"\n效果：{title.ability_desc}"
            await evt.send(evt.chain_result([
                Comp.Image.fromFileSystem(temp_path),
                Comp.Plain(info)
            ]))

        async for r in self._handle_selection(event, prompt_items, on_select, "称号"):
            yield r

    @filter.command("下周预告")
    async def preview_cmd(self, event: AstrMessageEvent):
        """获取下周预告图"""
        image_bytes = await PreviewImageGetter.get_bytes("")
        temp_path = await self._save_bytes_to_temp_file(image_bytes)
        yield event.chain_result([
            Comp.Image.fromFileSystem(temp_path),
            Comp.Plain("预告图来自 https://github.com/WhY15w/seer-unity-preview-img-dumper")
        ])

    @filter.command("开服查询", alias={"开服了吗"})
    async def server_info_cmd(self, event: AstrMessageEvent):
        """查询服务器是否已开服"""
        import httpx
        import re
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://unity-notice.61.com/unity_notice/")
                resp.raise_for_status()
                data = resp.json()

            for item in data:
                if item.get("type") == 3:
                    text = re.sub(r"<[^>]*>", "", item.get("text", ""))
                    text = text.replace("\\n", "\n")
                    yield event.plain_result(text)
                    return
            yield event.plain_result("开服了哦~")
        except Exception as e:
            logger.error(f"开服查询失败: {e}")
            yield event.plain_result("开服了哦~")

    @filter.command("帮助")
    async def help_cmd(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """🤖 赛尔号数据查询插件

命令：
  🐱精灵相关：
    精灵/查询精灵信息/魂印/技能 <名称/ID> — 查询精灵基础信息
    立绘/皮肤/查询立绘 <名称/ID> — 查询精灵或皮肤立绘
    属性 <名称/ID> — 查询属性克制表
    异常/查询异常状态 <名称/ID> — 查询异常状态信息

  💮刻印相关：
    刻印 <名称/ID> — 查询刻印信息及数值
    宝石 <名称/ID> — 查询刻印宝石信息

  👚装备相关：
    套装/查询套装信息 <名称/ID> — 查询套装信息
    部件/查询部件信息 <名称/ID> — 查询装备部件信息

  🏅称号相关：
    称号/查询称号信息 <名称/ID> — 查询称号信息

  🔀其他功能：
    下周预告 — 获取下周预告图
    开服查询 — 查询服务器是否已开服"""
        yield event.plain_result(help_text)


__all__ = ["SeerInfoPlugin"]