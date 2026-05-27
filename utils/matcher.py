"""提示会话管理工具

提供 PromptSessionManager 管理 prompt 会话版本，
以及 enter_prompt_loop 创建带自定义 Rule 的临时 Matcher。
"""

from typing import Any

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context
from astrbot.api import logger


class PromptSessionManager:
    """基于版本号的 prompt 会话管理器"""

    def __init__(self) -> None:
        self._versions: dict[str, int] = {}

    def acquire(self, session_id: str) -> int:
        """分配新版本号，同时使该用户旧版本失效"""
        v = self._versions.get(session_id, 0) + 1
        self._versions[session_id] = v
        return v

    def invalidate(self, session_id: str) -> None:
        """使当前 session 的 prompt 失效"""
        self.acquire(session_id)

    def make_rule(
        self,
        session_id: str,
        version: int,
        content_check: Any,
    ) -> Any:
        """创建绑定版本号的 Rule"""
        versions = self._versions

        def _check(event: AstrMessageEvent) -> bool:
            if versions.get(session_id) != version:
                return False
            return content_check(event)

        return _check


prompt_session_manager = PromptSessionManager()


async def enter_prompt_loop(
    plugin: Any,
    matcher: Any,
    event: AstrMessageEvent,
    state: dict,
    prompt_text: str,
    items: list,
    resolver: Any,
) -> None:
    """发送 prompt 并创建临时 Matcher 进入选择循环

    Args:
        plugin: 插件实例
        matcher: 当前 Matcher
        event: 当前事件
        state: 会话状态
        prompt_text: 提示文本
        items: 选项列表 [{"name": ..., "desc": ..., "value": ...}]
        resolver: 选择解析回调
    """
    session_id = event.get_session_id()
    version = prompt_session_manager.acquire(session_id)

    msg = prompt_text
    for i, item in enumerate(items, 1):
        msg += f"{i}. {item['name']}（{item['desc']}）\n"
    msg += "\n💬 输入序号选择 · 输入 0 退出"

    await matcher.send(msg)

    state["_prompt_version"] = version
    state["_prompt_items"] = items
    state["_prompt_resolver"] = resolver

    raise NotImplementedError("需要使用 AstrBot 的 reject 机制实现")


__all__ = ["PromptSessionManager", "prompt_session_manager", "enter_prompt_loop"]