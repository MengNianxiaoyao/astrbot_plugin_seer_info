import asyncio
from functools import partial

import aiohttp
from astrbot.api import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star

from .config import PluginConfig
from .core import (
    AttributeHandler,
    EffectHandler,
    EquipHandler,
    MintmarkHandler,
    MiscHandler,
    PetHandler,
    TitleHandler,
    close_renderer,
    get_renderer,
)
from .data.db import (
    cancel_sync_tasks,
    db_manager,
    register_database,
    register_local_database,
)
from .data.image_fetcher import close_shared_session


class SeerInfoPlugin(Star):
    def __init__(self, context: Context, config):
        super().__init__(context)
        self.cfg = PluginConfig(config, context)
        self._is_local_render = self.cfg.render_mode == "local"
        self._setup_databases()
        self._init_handlers()
        if self._is_local_render:
            asyncio.create_task(self._prewarm_renderer())

    def _setup_databases(self):
        async def get_fingerprint(url: str, session: aiohttp.ClientSession) -> str:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return (await resp.read()).decode().strip()

        def _register(name: str, sync_url_key: str, fp_url_key: str, interval_key: str):
            sync_url = getattr(self.cfg, sync_url_key, "")
            if sync_url:
                fp_url = getattr(self.cfg, fp_url_key, "")
                fp = partial(get_fingerprint, fp_url) if fp_url else None
                interval = getattr(self.cfg, interval_key, 60)
                register_database(
                    name,
                    sync_url=sync_url,
                    sync_interval_minutes=interval,
                    get_fingerprint=fp,
                )
            else:
                register_local_database(name)

        _register(
            "seerapi",
            "seerapi_sync_url",
            "seerapi_fingerprint_url",
            "seerapi_sync_interval_minutes",
        )
        _register(
            "aliases",
            "alias_sync_url",
            "alias_fingerprint_url",
            "alias_sync_interval_minutes",
        )

    def _init_handlers(self):
        html_render = None if self._is_local_render else self.html_render
        image_format = self.cfg.image_format
        jpeg_quality = self.cfg.jpeg_quality
        self._pet_handler = PetHandler(
            html_render=html_render,
            image_format=image_format,
            jpeg_quality=jpeg_quality,
        )
        self._attr_handler = AttributeHandler(
            html_render=html_render,
            image_format=image_format,
            jpeg_quality=jpeg_quality,
        )
        self._effect_handler = EffectHandler()
        self._mintmark_handler = MintmarkHandler()
        self._equip_handler = EquipHandler()
        self._title_handler = TitleHandler()
        self._misc_handler = MiscHandler()

    async def _prewarm_renderer(self):
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
    async def pet_info(self, event, arg: str = ""):
        async for result in self._pet_handler.pet_info(event, arg):
            yield result

    @filter.command(
        "立绘",
        alias={"皮肤", "查询立绘"},
        desc="查询精灵或皮肤立绘",
        ignore_prefix=True,
    )
    async def pet_image(self, event, arg: str = ""):
        async for result in self._pet_handler.pet_image(event, arg):
            yield result

    @filter.command("属性", alias={"属性表"}, desc="查询属性克制表", ignore_prefix=True)
    async def type_matchup(self, event, arg: str = ""):
        async for result in self._attr_handler.type_matchup(event, arg):
            yield result

    @filter.command(
        "异常",
        alias={"查询异常", "异常状态", "查询异常状态"},
        desc="查询异常状态信息",
        ignore_prefix=True,
    )
    async def battle_effect(self, event, arg: str = ""):
        async for result in self._effect_handler.battle_effect(event, arg):
            yield result

    @filter.command("刻印", desc="查询刻印信息及数值", ignore_prefix=True)
    async def mintmark(self, event, arg: str = ""):
        async for result in self._mintmark_handler.mintmark(event, arg):
            yield result

    @filter.command("宝石", alias={"刻印宝石"}, desc="查询刻印宝石信息", ignore_prefix=True)
    async def gem(self, event, arg: str = ""):
        async for result in self._mintmark_handler.gem(event, arg):
            yield result

    @filter.command("套装", alias={"查询套装信息"}, desc="查询套装信息", ignore_prefix=True)
    async def suit(self, event, arg: str = ""):
        async for result in self._equip_handler.suit(event, arg):
            yield result

    @filter.command("部件", alias={"查询部件信息"}, desc="查询装备部件信息", ignore_prefix=True)
    async def equip(self, event, arg: str = ""):
        async for result in self._equip_handler.equip(event, arg):
            yield result

    @filter.command("称号", alias={"查询称号信息"}, desc="查询称号信息", ignore_prefix=True)
    async def title_info(self, event, arg: str = ""):
        async for result in self._title_handler.title_info(event, arg):
            yield result

    @filter.command("下周预告", alias={"预告"}, desc="获取下周预告图", ignore_prefix=True)
    async def preview_cmd(self, event):
        async for result in self._misc_handler.preview_cmd(event):
            yield result

    @filter.command("开服查询", alias={"开服了吗"}, desc="查询服务器是否已开服", ignore_prefix=True)
    async def server_info_cmd(self, event):
        async for result in self._misc_handler.server_info_cmd(event):
            yield result

    @filter.command("帮助", desc="显示帮助信息", ignore_prefix=True)
    async def help_cmd(self, event):
        async for result in self._misc_handler.help_cmd(event):
            yield result
