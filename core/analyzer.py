"""赛尔号魂印/技能描述解析器

将包含 [color=...] 和 [sprite name=...] 标签的描述文本解析为HTML。
"""

import html
import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

_TAG_RE = re.compile(
    r"\[color=(#[0-9a-fA-F]{6})\]"
    r"|\[/color\]"
    r"|\[sprite name=(\w+)\]"
    r"|([^\[]+|\[)"
)
_ID_SUFFIX_RE = re.compile(r"\((\d+)\)$")


@dataclass(slots=True)
class TextSegment:
    """一段带有可选颜色标记的文本片段"""

    text: str
    colors: tuple[str, ...] = ()
    id: int | None = None


@dataclass(slots=True)
class DescLine:
    """描述中的一行"""

    sprite: str | None = None
    indent: int = 0
    segments: list[TextSegment] = field(default_factory=list)

    @property
    def plain_text(self) -> str:
        return "".join(seg.text for seg in self.segments)

    def colored_texts(self, color: str) -> list[str]:
        """返回该行中包含指定颜色的所有文本"""
        return [seg.text for seg in self.segments if color in seg.colors]

    def to_html(
        self,
        styles: dict[str, Callable[[str], str]] | None = None,
    ) -> str:
        """将该行转为 HTML 文本"""
        parts: list[str] = []
        for seg in self.segments:
            result = html.escape(seg.text)
            if seg.colors and styles:
                seen: set[str] = set()
                for color in reversed(seg.colors):
                    if color not in seen and (styler := styles.get(color)):
                        result = styler(result)
                        seen.add(color)
            parts.append(result)
        return "".join(parts)


def _parse_desc_line(raw: str) -> DescLine:
    stripped = raw.lstrip()
    indent = len(raw) - len(stripped)
    line = DescLine(indent=indent)
    color_stack: list[str] = []
    current_opens = 0
    last_batch = 0

    for m in _TAG_RE.finditer(stripped):
        if m.group(1) is not None:
            color_stack.append(m.group(1))
            current_opens += 1
        elif m.group(0) == "[/color]":
            pop_count = min(max(1, last_batch), len(color_stack))
            for _ in range(pop_count):
                color_stack.pop()
            last_batch = 0
            current_opens = 0
        elif m.group(2) is not None:
            line.sprite = m.group(2)
        elif m.group(3) is not None:
            last_batch = current_opens
            current_opens = 0
            cur = tuple(set(color_stack))
            text = m.group(3)
            seg_id: int | None = None
            if id_match := _ID_SUFFIX_RE.search(text):
                seg_id = int(id_match.group(1))
                text = text[: id_match.start()]
            can_merge = (
                line.segments
                and line.segments[-1].colors == cur
                and line.segments[-1].id is None
                and seg_id is None
            )
            if can_merge:
                line.segments[-1].text += text
            else:
                line.segments.append(TextSegment(text=text, colors=cur, id=seg_id))

    return line


class AnalyzeDescParser:
    """赛尔号Analyze描述标签解析器（带缓存）"""

    _cache: OrderedDict[str, "AnalyzeDescParser"] = OrderedDict()
    _MAX_CACHE_SIZE = 512

    def __init__(self, desc: str) -> None:
        self.desc = desc
        self.lines: list[DescLine] = [_parse_desc_line(raw) for raw in desc.split("|")]

    @classmethod
    def from_cache(cls, desc: str) -> "AnalyzeDescParser":
        cached = cls._cache.get(desc)
        if cached is not None:
            cls._cache.move_to_end(desc)
            return cached
        instance = cls(desc)
        cls._cache[desc] = instance
        if len(cls._cache) > cls._MAX_CACHE_SIZE:
            cls._cache.popitem(last=False)
        return instance

    def lines_by_sprite(self, sprite: str) -> list[DescLine]:
        return [line for line in self.lines if line.sprite == sprite]

    @property
    def sprites(self) -> set[str]:
        return {line.sprite for line in self.lines if line.sprite}

    @property
    def segments(self) -> list[TextSegment]:
        """描述中出现的所有文本片段"""
        return [seg for line in self.lines for seg in line.segments]

    @property
    def segments_with_id(self) -> set[int]:
        """描述中出现的所有词条 ID"""
        return {seg.id for seg in self.segments if seg.id}

    @property
    def colors(self) -> set[str]:
        """描述中出现的所有颜色值"""
        return {c for line in self.lines for seg in line.segments for c in seg.colors}

    def to_plain_text(self, line_separator: str = "\n") -> str:
        return line_separator.join(line.plain_text for line in self.lines)

    def to_html(
        self,
        styles: dict[str, Callable[[str], str]] | None = None,
        line_separator: str = "<br>",
    ) -> str:
        return line_separator.join(line.to_html(styles) for line in self.lines)


_ANALYZE_DESC_STYLES: dict[str, Callable[..., str]] = {
    "#f35555": lambda t: f'<b style="color:#60e0ff">{t}</b>',
}


@lru_cache(maxsize=256)
def parse_analyze_desc(desc: str) -> str:
    """解析魂印/技能描述，返回HTML（带缓存）"""
    if not desc:
        return ""
    parser = AnalyzeDescParser.from_cache(desc)
    return parser.to_html(_ANALYZE_DESC_STYLES)
