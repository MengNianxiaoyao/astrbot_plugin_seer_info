"""规则辅助工具"""

import re
from typing import Any


BOT_COMMAND_ARG_KEY = "_irons_bot_command_arg"


class StartswithOrEndswithRule:
    """检查消息纯文本是否以指定字符串开头或结尾"""

    def __init__(
        self,
        prefixes: tuple[str, ...],
        suffixes: tuple[str, ...],
        ignorecase: bool = False,
    ) -> None:
        self.prefixes = prefixes
        self.suffixes = suffixes
        self.ignorecase = ignorecase

    async def __call__(self, event: Any, state: dict) -> bool:
        try:
            text = event.get_plaintext()
        except Exception:
            return False

        flags = re.IGNORECASE if self.ignorecase else 0

        sw = (
            re.match(
                f"^(?:{'|'.join(re.escape(p) for p in self.prefixes)})",
                text,
                flags,
            )
            if self.prefixes
            else None
        )
        ew = (
            re.search(
                f"(?:{'|'.join(re.escape(s) for s in self.suffixes)})$",
                text,
                flags,
            )
            if self.suffixes
            else None
        )

        if not sw and not ew:
            return False

        state["startswith"] = sw.group() if sw else ""
        state["endswith"] = ew.group() if ew else ""
        state[BOT_COMMAND_ARG_KEY] = text.replace(state["startswith"], "").replace(
            state["endswith"], ""
        )
        return True


class NoReply:
    """仅匹配没有回复消息的规则"""

    async def __call__(self, event: Any, _: dict) -> bool:
        reply = getattr(event, "reply", None)
        return reply is None


def startswith_or_endswith(
    prefixes: str | tuple[str, ...],
    suffixes: str | tuple[str, ...] | None = None,
    ignorecase: bool = True,
) -> Any:
    """匹配消息开头或结尾为指定字符串的规则"""
    if suffixes is None:
        suffixes = prefixes
    if isinstance(prefixes, str):
        prefixes = (prefixes,)
    if isinstance(suffixes, str):
        suffixes = (suffixes,)
    return StartswithOrEndswithRule(prefixes, suffixes, ignorecase)


def no_reply() -> Any:
    return NoReply()


__all__ = [
    "BOT_COMMAND_ARG_KEY",
    "StartswithOrEndswithRule",
    "NoReply",
    "startswith_or_endswith",
    "no_reply",
]