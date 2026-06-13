"""Common query helpers for command handlers."""

from collections.abc import Awaitable, Callable

from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from astrbot.core.utils.session_waiter import session_waiter, SessionController


async def multi_select_query(
    event: AstrMessageEvent,
    arg: str,
    *,
    getter: Callable,
    prepare_result: Callable[..., Awaitable],
    label: str,
    result_type: str = "chain",
    error_log_name: str = "",
):
    """通用多选查询流程。

    Args:
        event: 消息事件
        arg: 用户输入参数
        getter: 数据获取函数，签名 (sessions, arg) -> results
        prepare_result: 异步函数，签名 (item) -> list[Component]
        label: 查询对象名称，如 "异常状态"、"称号"
        result_type: 单结果返回方式，"chain" 或 "image"
        error_log_name: 错误日志标识
    """
    from ..data.db import db_manager

    if not arg.strip():
        yield event.plain_result(f"❌请提供要查询的{label}名称。\n用法：/{label} <名称>")
        return

    if not db_manager.is_database_loaded("seerapi"):
        yield event.plain_result("❌数据库未加载，请稍后再试")
        return

    sessions = db_manager.get_all_sessions()
    results = getter(sessions, arg)

    if not results:
        yield event.plain_result(f"❌未找到匹配的{label}: {arg}")
        return

    if len(results) > 20:
        yield event.plain_result("❌重名超过20个，请重新检索关键词！")
        return

    if len(results) == 1:
        components = await prepare_result(results[0])
        if result_type == "image":
            yield event.image_result(components)
        else:
            yield event.chain_result(components)
        return

    prompt_items = [
        {"name": item.name, "desc": str(item.id), "value": item.id}
        for item in results[:20]
    ]
    prompt_map = {str(i + 1): p["value"] for i, p in enumerate(prompt_items)}

    async def send_result(item, evt):
        components = await prepare_result(item)
        await evt.send(evt.chain_result(components))

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
        await send_result(results[index], evt)
        controller.stop()

    msg = f"请问你想查询的{label}是……\n"
    for i, item in enumerate(prompt_items, 1):
        msg += f"{i}. {item['name']}（{item['desc']}）\n"
    msg += "\n💬 输入序号选择 · 输入 0 退出"

    yield event.plain_result(msg)

    try:
        await handler(event)
    except TimeoutError:
        yield event.plain_result("⏰选择超时，已退出")
    except Exception as e:
        log_name = error_log_name or label
        logger.error(f"{log_name} selection error: {e}")
        yield event.plain_result(f"发生错误: {e}")
