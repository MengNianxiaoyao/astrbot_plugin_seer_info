"""Constants and helper functions for SeerInfo plugin."""

from seerapi_models import MintmarkORM
from seerapi_models.common import SixAttributes
from seerapi_models.mintmark import AbilityPartORM, SkillPartORM, UniversalPartORM


EQUIP_PART_TYPE_MAP = {
    0: "头部",
    1: "面部",
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
        strings.append("双攻")

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
