"""
AstrBot Plugin: Seer Info (赛尔号数据查询)

Ported from IronsBot NoneBot2 plugin to AstrBot framework.
"""

import asyncio
from functools import partial

import aiohttp

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

from .data.db import (
    db_manager,
    register_database,
    register_local_database,
    cancel_sync_tasks,
)
from .core.renderer import close_renderer, get_renderer
from .data.image_fetcher import close_shared_session
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
        self._is_local_render = self.config.get("render_mode", "local") == "local"
        self._load_config()
        self._init_commands()

    def _load_config(self):
        """从插件配置加载并初始化数据库"""
        self._setup_databases()
        if self._is_local_render:
            asyncio.create_task(self._prewarm_renderer())

    def _setup_databases(self):
        async def get_fingerprint(url: str, session: aiohttp.ClientSession) -> str:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return (await resp.read()).decode().strip()

        def _register(name: str, sync_url_key: str, fp_url_key: str, interval_key: str):
            sync_url = self.config.get(sync_url_key, "")
            if sync_url:
                fp_url = self.config.get(fp_url_key, "")
                fp = partial(get_fingerprint, fp_url) if fp_url else None
                interval = self.config.get(interval_key, 60)
                register_database(
                    name, sync_url=sync_url,
                    sync_interval_minutes=interval,
                    get_fingerprint=fp,
                )
            else:
                register_local_database(name)

        _register(
            "seerapi", "seerapi_sync_url",
            "seerapi_fingerprint_url",
            "seerapi_sync_interval_minutes",
        )
        _register(
            "aliases", "alias_sync_url",
            "alias_fingerprint_url",
            "alias_sync_interval_minutes",
        )

    def _init_commands(self):
        html_render = None if self._is_local_render else self.html_render
        image_format = self.config.get("image_format", "jpeg")
        jpeg_quality = self.config.get("jpeg_quality", 85)
        self._pet_cmds = PetCommands(
            html_render=html_render,
            image_format=image_format,
            jpeg_quality=jpeg_quality,
        )
        self._attr_cmds = AttributeCommands(
            html_render=html_render,
            image_format=image_format,
            jpeg_quality=jpeg_quality,
        )
        self._effect_cmds = EffectCommands()
        self._mintmark_cmds = MintmarkCommands()
        self._equip_cmds = EquipCommands()
        self._title_cmds = TitleCommands()
        self._misc_cmds = MiscCommands()

    async def _prewarm_renderer(self):
        """后台预热 Playwright 浏览器"""
        try:
            renderer = await get_renderer()
            await renderer.prewarm()
        except Exception as e:
            logger.warning(f"Playwright 浏览器预热失败: {e}")

    async def terminate(self):
        await cancel_sync_tasks()
        await close_shared_session()
        db_manager.dispose_all()
        if self._is_local_render:
            await close_renderer()
        logger.info("SeerInfo 插件已卸载")

    @filter.command(
        "精灵",
        alias={"查询精灵信息", "魂印", "技能"},
        desc="查询精灵基础信息",
        ignore_prefix=True,
    )
    async def pet_info(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._pet_cmds.pet_info(event, arg):
            yield result

    @filter.command(
        "立绘",
        alias={"皮肤", "查询立绘"},
        desc="查询精灵或皮肤立绘",
        ignore_prefix=True,
    )
    async def pet_image(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._pet_cmds.pet_image(event, arg):
            yield result

    @filter.command("属性", alias={"属性表"}, desc="查询属性克制表", ignore_prefix=True)
    async def type_matchup(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._attr_cmds.type_matchup(event, arg):
            yield result

    @filter.command(
        "异常",
        alias={"查询异常", "异常状态", "查询异常状态"},
        desc="查询异常状态信息",
        ignore_prefix=True,
    )
    async def battle_effect(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._effect_cmds.battle_effect(event, arg):
            yield result

    @filter.command("刻印", desc="查询刻印信息及数值", ignore_prefix=True)
    async def mintmark(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._mintmark_cmds.mintmark(event, arg):
            yield result

    @filter.command("宝石", alias={"刻印宝石"}, desc="查询刻印宝石信息", ignore_prefix=True)
    async def gem(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._mintmark_cmds.gem(event, arg):
            yield result

    @filter.command("套装", alias={"查询套装信息"}, desc="查询套装信息", ignore_prefix=True)
    async def suit(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._equip_cmds.suit(event, arg):
            yield result

    @filter.command("部件", alias={"查询部件信息"}, desc="查询装备部件信息", ignore_prefix=True)
    async def equip(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._equip_cmds.equip(event, arg):
            yield result

    @filter.command("称号", alias={"查询称号信息"}, desc="查询称号信息", ignore_prefix=True)
    async def title_info(self, event: AstrMessageEvent, arg: str = ""):
        async for result in self._title_cmds.title_info(event, arg):
            yield result

    @filter.command("下周预告", alias={"预告"}, desc="获取下周预告图", ignore_prefix=True)
    async def preview_cmd(self, event: AstrMessageEvent):
        async for result in self._misc_cmds.preview_cmd(event):
            yield result

    @filter.command("开服查询", alias={"开服了吗"}, desc="查询服务器是否已开服", ignore_prefix=True)
    async def server_info_cmd(self, event: AstrMessageEvent):
        async for result in self._misc_cmds.server_info_cmd(event):
            yield result

    @filter.command("帮助", desc="显示帮助信息", ignore_prefix=True)
    async def help_cmd(self, event: AstrMessageEvent):
        async for result in self._misc_cmds.help_cmd(event):
            yield result
