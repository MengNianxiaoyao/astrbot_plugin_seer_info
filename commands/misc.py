"""Misc commands: 下周预告, 开服查询, 帮助."""

import re
import tempfile
from astrbot.api.event import AstrMessageEvent
import httpx

from ..seer_data.image import PreviewImageGetter


class MiscCommands:
    """Handler for misc commands: preview, server info, help."""

    async def _save_bytes_to_temp_file(self, image_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            f.write(image_bytes)
            return f.name

    async def preview_cmd(self, event: AstrMessageEvent):
        """获取下周预告图"""
        image_bytes = await PreviewImageGetter.get_bytes("")
        temp_path = await self._save_bytes_to_temp_file(image_bytes)
        from astrbot.api.message_components import Comp
        yield event.chain_result([
            Comp.Image.fromFileSystem(temp_path),
            Comp.Plain("预告图来自 https://github.com/WhY15w/seer-unity-preview-img-dumper")
        ])

    async def server_info_cmd(self, event: AstrMessageEvent):
        """查询服务器是否已开服"""
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
            yield event.plain_result("开服了哦~")

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


__all__ = ["MiscCommands"]