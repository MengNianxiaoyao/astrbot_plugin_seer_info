"""参数解析工具"""


def parse_string_arg(event: Any) -> str:
    """从事件中解析字符串参数"""
    try:
        return event.message_str.strip()
    except Exception:
        return ""


def parse_int_arg(event: Any) -> int:
    """从事件中解析整数参数"""
    arg = parse_string_arg(event)
    if not arg.isdigit():
        raise ValueError("不是有效的数字")
    return int(arg)


__all__ = ["parse_string_arg", "parse_int_arg"]