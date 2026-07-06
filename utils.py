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


def mintmark_attributes(mintmark: MintmarkORM) -> SixAttributes | None:
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
        raise TypeError(f"unknown mintmark type: {type(part)}")
    return attr.round()


def mintmark_type_description(attributes: SixAttributes | None) -> str:
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


def mintmark_item_desc(mintmark: MintmarkORM) -> str:
    attr = mintmark_attributes(mintmark)
    if attr is None or not (desc := mintmark_type_description(attr)):
        return f"{mintmark.id}"
    return f"{mintmark.id} {desc}"
