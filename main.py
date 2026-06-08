"""
AstrBot Plugin: Seer Info (赛尔号数据查询)

Ported from IronsBot NoneBot2 plugin to AstrBot framework.
"""

import aiohttp

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

from .seer_data.db import (
    db_manager,
    register_database,
    register_local_database,
    cancel_sync_tasks,
)
from .depends.render import close_renderer
from .commands import (
    PetCommands,
    AttributeCommands,
    EffectCommands,
    MintmarkCommands,
    EquipCommands,
    TitleCommands,
    MiscCommands,
)


class SeerInfoPlugin(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.config = config
        self.name = "astrbot_plugin_seer_info"
        self._setup_databases()
        self._init_commands()

    def _init_commands(self):
        render_mode = self.config.get("render_mode", "local")
        is_local = render_mode == "local"
        self._pet_cmds = PetCommands(is_local=is_local, html_render=self.html_render)
        self._attr_cmds = AttributeCommands(is_local=is_local, html_render=self.html_render)
        self._effect_cmds = EffectCommands()
        self._mintmark_cmds = MintmarkCommands()
        self._equip_cmds = EquipCommands()
        self._title_cmds = TitleCommands()
        self._misc_cmds = MiscCommands()

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
            register_local_database("seerapi")

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
            register_local_database("aliases")

    async def terminate(self):
        logger.info("SeerInfo 插件已卸载")
        cancel_sync_tasks()
        db_manager.dispose_all()
        if self.config.get("render_mode", "local") == "local":
            await close_renderer()

    @filter.command("精灵", alias={"查询精灵信息", "魂印", "技能"}, ignore_prefix=True)
    async def pet_info(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._pet_cmds.pet_info(event, arg):
            yield result

    @filter.command("立绘", alias={"皮肤", "查询立绘"}, ignore_prefix=True)
    async def pet_image(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._pet_cmds.pet_image(event, arg):
            yield result

    @filter.command("属性", alias={"属性表"},ignore_prefix=True)
    async def type_matchup(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._attr_cmds.type_matchup(event, arg):
            yield result

    @filter.command("异常", alias={"查询异常", "异常状态", "查询异常状态"}, ignore_prefix=True)
    async def battle_effect(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._effect_cmds.battle_effect(event, arg):
            yield result

    @filter.command("刻印", ignore_prefix=True)
    async def mintmark(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._mintmark_cmds.mintmark(event, arg):
            yield result

    @filter.command("宝石", alias={"刻印宝石"}, ignore_prefix=True)
    async def gem(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._mintmark_cmds.gem(event, arg):
            yield result

    @filter.command("套装", alias={"查询套装信息"}, ignore_prefix=True)
    async def suit(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._equip_cmds.suit(event, arg):
            yield result

    @filter.command("部件", alias={"查询部件信息"}, ignore_prefix=True)
    async def equip(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._equip_cmds.equip(event, arg):
            yield result

    @filter.command("称号", alias={"查询称号信息"}, ignore_prefix=True)
    async def title_info(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._title_cmds.title_info(event, arg):
            yield result

    @filter.command("下周预告", alias={"预告"}, ignore_prefix=True)
    async def preview_cmd(self, event: AstrMessageEvent):
        async for result in self._misc_cmds.preview_cmd(event):
            yield result

    @filter.command("开服查询", alias={"开服了吗"}, ignore_prefix=True)
    async def server_info_cmd(self, event: AstrMessageEvent):
        async for result in self._misc_cmds.server_info_cmd(event):
            yield result

    @filter.command("帮助", ignore_prefix=True)
    async def help_cmd(self, event: AstrMessageEvent):
        async for result in self._misc_cmds.help_cmd(event):
            yield result


__all__ = ["SeerInfoPlugin"]