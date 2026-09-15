import asyncio
import html
from pathlib import Path
from typing import Any

from astrbot.api import logger
from seerapi_models import MintmarkORM, PetORM
from seerapi_models.mintmark import PetMintmarkLink, SkillMintmarkLink
from sqlalchemy.orm import object_session
from sqlmodel import col, select

from ..service import (
    ElementTypeImageGetter,
    MintmarkBodyImageGetter,
    PetBodyImageGetter,
    PetHeadImageGetter,
    flip_image_horizontal,
    to_data_uri,
)
from .analyzer import AnalyzeDescParser, parse_analyze_desc
from .renderer import get_template_content

PET_TEMPLATE = get_template_content("pet_info/template.html.j2")
_TERM_COLOR = "#f35555"
_TERM_COLORS = (
    "#ff9e6e",
    "#f5d84a",
    "#8ae878",
    "#6eebc0",
    "#ff8ab8",
    "#e8a0ff",
    "#ff7b7b",
    "#ffd4a0",
)


def _extract_skill(skill_in_pet) -> list[dict[str, Any]]:
    skill = skill_in_pet.skill
    if not skill or getattr(skill, "id", 0) == 19002:
        return []

    skill_type = getattr(skill, "type", None)
    skill_category = getattr(skill, "category", None)
    skill_hide_effect = getattr(skill, "hide_effect", None)
    skill_activation_item = getattr(skill_in_pet, "skill_activation_item", None)

    effects = []
    for effect in getattr(skill, "skill_effect", []):
        parser = AnalyzeDescParser.from_cache(getattr(effect, "analyze_info", "") or "")
        effects.append(
            {
                "id": getattr(effect, "effect_id", 0),
                "info": parser.to_html(),
                "_parser": parser,
            }
        )

    hide_effect_desc = (
        getattr(skill_hide_effect, "description", None) if skill_hide_effect else None
    )
    activation_item = (
        getattr(skill_activation_item, "name", None) if skill_activation_item else None
    )

    result = {
        "id": skill.id,
        "name": skill.name,
        "type_id": skill_type.id if skill_type else 0,
        "type_name": skill_type.name if skill_type else "",
        "category_id": skill_category.id if skill_category else 0,
        "category_name": skill_category.name if skill_category else "",
        "power": skill.power or 0,
        "max_pp": skill.max_pp or 0,
        "accuracy": "必中" if skill.must_hit else skill.accuracy,
        "crit_rate": skill.crit_rate,
        "priority": skill.priority or 0,
        "must_hit": skill.must_hit,
        "info": skill.info,
        "learning_level": skill_in_pet.learning_level,
        "is_special": skill_in_pet.is_special,
        "is_advanced": skill_in_pet.is_advanced,
        "is_fifth": skill_in_pet.is_fifth,
        "effects": effects,
        "glossaries": [],
        "activation_item": activation_item,
        "friend_bonus": False,
        "hide_effect_desc": hide_effect_desc,
    }

    if hasattr(skill, "friend_skill_effect") and len(skill.friend_skill_effect) > 0:
        friend_skill = {
            **result,
            "friend_bonus": True,
            "is_special": True,
            "effects": [
                {"id": getattr(e, "effect_id", 0), "info": getattr(e, "info", "")}
                for e in skill.friend_skill_effect
            ],
        }
        return [result, friend_skill]

    return [result]


def _extract_soulmark(soulmarks: list, pet: PetORM) -> list[dict[str, Any]]:
    results = []
    for sm in soulmarks:
        sm_desc = getattr(sm, "analyze_desc", "") or getattr(sm, "desc", "")
        results.append(
            {
                "desc": parse_analyze_desc(sm_desc or ""),
                "intensified": getattr(sm, "intensified", False),
                "is_adv": getattr(sm, "is_adv", False),
                "pve_effective": getattr(sm, "pve_effective", None),
                "tags": [t.name for t in getattr(sm, "tag", []) or []],
                "glossaries": [],
                "_parser": AnalyzeDescParser.from_cache(sm_desc or ""),
            }
        )

    return results


def _apply_glossaries(
    pet: PetORM,
    soulmarks: list[dict[str, Any]],
    skills: list[dict[str, Any]],
) -> None:
    entries = {
        entry.name: entry
        for entry in getattr(pet, "glossary_entry", []) or []
        if getattr(entry, "name", None)
    }
    colors: dict[str, str] = {}
    seen: set[str] = set()

    def color_for(name: str) -> str:
        if name not in colors:
            colors[name] = _TERM_COLORS[len(colors) % len(_TERM_COLORS)]
        return colors[name]

    def terms_for(parser: AnalyzeDescParser) -> list[str]:
        return list(
            dict.fromkeys(
                segment.text
                for segment in parser.segments_by_color(_TERM_COLOR)
                if segment.text in entries
            )
        )

    def styles(text: str) -> str:
        name = html.unescape(text)
        return f'<b style="color:{color_for(name)}">{text}</b>'

    def process(item: dict[str, Any]) -> None:
        parser = item.pop("_parser", None)
        if parser is None:
            return
        names = terms_for(parser)
        item["desc"] = parser.to_html({"#f35555": styles})
        item["glossaries"] = []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            entry = entries[name]
            item["glossaries"].append(
                {
                    "name": name,
                    "desc": getattr(entry, "desc", ""),
                    "color": color_for(name),
                }
            )

    for soulmark in soulmarks:
        process(soulmark)
    for skill in skills:
        for effect in skill.get("effects", []):
            parser = effect.pop("_parser", None)
            if parser is None:
                continue
            names = terms_for(parser)
            effect["info"] = parser.to_html({"#f35555": styles})
            skill.setdefault("glossaries", [])
            for name in names:
                if name in seen:
                    continue
                seen.add(name)
                entry = entries[name]
                skill["glossaries"].append(
                    {
                        "name": name,
                        "desc": getattr(entry, "desc", ""),
                        "color": color_for(name),
                    }
                )


async def _build_pet_render_data(pet: PetORM) -> dict[str, Any]:
    pet_name = getattr(pet, "name", "未知精灵")
    pet_id = getattr(pet, "id", 0)

    gender_id = 0
    try:
        if hasattr(pet, "gender") and pet.gender:
            if isinstance(pet.gender, int):
                gender_id = pet.gender
            elif hasattr(pet.gender, "id"):
                gender_id = pet.gender.id
            elif hasattr(pet.gender, "value"):
                gender_id = int(pet.gender.value)
    except Exception:
        gender_id = 0

    pet_gender_icon = ""
    try:
        plugin_dir = Path(__file__).parent.parent
        icon_path = plugin_dir / "templates" / "pet_info" / "images" / f"{gender_id}.png"
        if icon_path.exists():
            pet_gender_icon = to_data_uri(icon_path.read_bytes())
    except Exception as e:
        logger.error(f"获取性别图标失败: {e}")

    pet_type_id = (
        pet.type.id if hasattr(pet, "type") and getattr(pet.type, "id", None) is not None else 0
    )
    pet_type_name = pet.type.name if hasattr(pet, "type") else ""

    all_skills = []
    if hasattr(pet, "skill_links") and pet.skill_links:
        for sl in pet.skill_links:
            all_skills.extend(_extract_skill(sl))

    soulmarks = _extract_soulmark(getattr(pet, "soulmark", []) or [], pet)
    if pet_id == 2500:
        soulmarks.append(
            {
                "desc": "登场首回合所有攻击先制+1同时增加20%暴击率",
                "intensified": True,
                "is_adv": False,
                "pve_effective": None,
                "tags": [],
                "glossaries": [],
            }
        )

    _apply_glossaries(pet, soulmarks, all_skills)

    fifth_skills = [s for s in all_skills if s.get("is_fifth")][::-1]
    advanced_skills = [s for s in all_skills if s.get("is_advanced")][::-1]
    special_skills = [s for s in all_skills if s.get("is_special")][::-1]
    level_skills = sorted(
        [
            s
            for s in all_skills
            if not s.get("is_fifth") and not s.get("is_advanced") and not s.get("is_special")
        ],
        key=lambda x: x.get("learning_level") or 0,
        reverse=True,
    )

    skill_ids = [sl.skill_id for sl in pet.skill_links] if pet.skill_links else []
    pet_skill_names = {s["name"] for s in all_skills}
    type_ids = list(
        {skill["type_id"] for skill in all_skills if skill.get("type_id")} | {pet_type_id}
    )

    session = object_session(pet)
    mintmarks = []
    if session:
        try:
            stmt = (
                select(MintmarkORM)
                .outerjoin(
                    SkillMintmarkLink,
                    col(SkillMintmarkLink.mintmark_id) == col(MintmarkORM.id),
                )
                .outerjoin(
                    PetMintmarkLink,
                    col(PetMintmarkLink.mintmark_id) == col(MintmarkORM.id),
                )
                .where(
                    col(SkillMintmarkLink.skill_id).in_(skill_ids)
                    | (col(PetMintmarkLink.pet_id) == pet_id)
                )
                .where(
                    col(PetMintmarkLink.pet_id).is_(None) | (col(PetMintmarkLink.pet_id) == pet_id)
                )
                .distinct()
            )
            mintmarks = session.execute(stmt).scalars().all()
        except Exception as e:
            logger.error(f"查询刻印数据失败: {e}")

    try:
        resource_id = getattr(pet, "resource_id", None)
        res_str = str(resource_id) if resource_id else None

        pet_head_task = (
            PetHeadImageGetter.get_bytes(res_str) if res_str else asyncio.sleep(0, result=b"")
        )
        pet_body_task = (
            PetBodyImageGetter.get_bytes(res_str) if res_str else asyncio.sleep(0, result=b"")
        )

        gather_results = await asyncio.gather(
            pet_head_task,
            pet_body_task,
            *(ElementTypeImageGetter.get_bytes(str(tid)) for tid in type_ids),
            ElementTypeImageGetter.get_bytes("prop"),
            *(MintmarkBodyImageGetter.get_bytes(str(mm.id)) for mm in mintmarks),
            return_exceptions=True,
        )

        pet_head_bytes, pet_body_bytes = gather_results[0], gather_results[1]
        type_icon_count = len(type_ids) + 1
        type_icon_results = gather_results[2 : 2 + type_icon_count]
        mm_icon_results = gather_results[2 + type_icon_count :]

        pet_head_img = "" if isinstance(pet_head_bytes, Exception) else to_data_uri(pet_head_bytes)
        if isinstance(pet_body_bytes, Exception):
            pet_body_img = ""
        else:
            try:
                pet_body_img = to_data_uri(flip_image_horizontal(pet_body_bytes))
            except Exception as e:
                logger.warning(f"水平翻转精灵立绘失败，使用原图: {e}")
                pet_body_img = to_data_uri(pet_body_bytes)

        type_icons = {}
        for i, tid in enumerate(type_ids):
            if not isinstance(type_icon_results[i], Exception):
                type_icons[str(tid)] = to_data_uri(type_icon_results[i])
        if not isinstance(type_icon_results[-1], Exception):
            type_icons["prop"] = to_data_uri(type_icon_results[-1])

        skill_marks = []
        for mm, icon_result in zip(mintmarks, mm_icon_results, strict=True):
            icon_uri = "" if isinstance(icon_result, Exception) else to_data_uri(icon_result)
            skill_marks.append(
                {
                    "id": mm.id,
                    "name": mm.name,
                    "desc": getattr(mm, "desc", ""),
                    "icon": icon_uri,
                    "skills": list(
                        dict.fromkeys(s.name for s in mm.skill if s.name in pet_skill_names)
                    ),
                }
            )
    except Exception as e:
        logger.error(f"获取精灵图标失败: {e}")
        pet_head_img = ""
        pet_body_img = ""
        type_icons = {}
        skill_marks = []

    stats = {}
    if hasattr(pet, "base_stats") and pet.base_stats:
        if hasattr(pet.base_stats, "to_model"):
            base_stats_model = pet.base_stats.to_model()
            if hasattr(base_stats_model, "round"):
                base_stats_model = base_stats_model.round()
            stats = base_stats_model.model_dump()

    advance_stats = None
    if hasattr(pet, "advance") and pet.advance:
        if hasattr(pet.advance.base_stats, "to_model"):
            adv_model = pet.advance.base_stats.to_model()
            if hasattr(adv_model, "round"):
                adv_model = adv_model.round()
            advance_stats = adv_model.model_dump()

    encyclopedia = getattr(pet, "encyclopedia", None)
    pet_introduction = getattr(encyclopedia, "introduction", None)
    pet_height = (
        f"{encyclopedia.height:g}cm"
        if encyclopedia is not None and getattr(encyclopedia, "height", None) is not None
        else "未知"
        if encyclopedia is not None
        else None
    )
    pet_weight = (
        f"{encyclopedia.weight:g}kg"
        if encyclopedia is not None and getattr(encyclopedia, "weight", None) is not None
        else "未知"
        if encyclopedia is not None
        else None
    )

    render_data = {
        "pet_name": pet_name,
        "pet_id": pet_id,
        "pet_gender_id": gender_id,
        "pet_gender_icon": pet_gender_icon,
        "pet_type_id": str(pet_type_id) if pet_type_id else "0",
        "pet_type_name": pet_type_name,
        "pet_introduction": pet_introduction,
        "pet_height": pet_height,
        "pet_weight": pet_weight,
        "pet_food": getattr(encyclopedia, "food", None),
        "pet_head_img": pet_head_img,
        "pet_body_img": pet_body_img,
        "type_icons": type_icons,
        "stats": stats,
        "advance_stats": advance_stats,
        "soulmarks": soulmarks,
        "fifth_skills": fifth_skills,
        "advanced_skills": advanced_skills,
        "special_skills": special_skills,
        "level_skills": level_skills,
        "skill_marks": skill_marks,
    }

    return render_data


async def render_pet_info_data(pet: PetORM) -> dict[str, Any]:
    return await _build_pet_render_data(pet)
