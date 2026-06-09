"""属性克制倍率计算（纯计算逻辑，不涉及命令注册或渲染）。"""

from seerapi_models.element_type import ElementTypeRelationORM, TypeCombinationORM
from sqlmodel import Session, select

_SUPER_EFFECTIVE = 2
_IMMUNE = 0

RelationMap = dict[tuple[int, int], float]

_relation_cache: RelationMap | None = None
_all_combos_cache: list[TypeCombinationORM] | None = None


def _load_relations(session: Session) -> RelationMap:
    global _relation_cache
    if _relation_cache is not None:
        return _relation_cache
    rows = session.exec(
        select(
            ElementTypeRelationORM.source_id,
            ElementTypeRelationORM.target_id,
            ElementTypeRelationORM.multiple,
        )
    ).all()
    _relation_cache = {(src, tgt): mul for src, tgt, mul in rows}
    return _relation_cache


def invalidate_relation_cache():
    global _relation_cache, _all_combos_cache
    _relation_cache = None
    _all_combos_cache = None


def _lookup(table: RelationMap, atk_id: int, def_id: int) -> float:
    return table.get((atk_id, def_id), 1.0)


def _calc_mixed(c1: float, c2: float) -> float:
    total = c1 + c2
    if c1 == _SUPER_EFFECTIVE and c2 == _SUPER_EFFECTIVE:
        return total
    if _IMMUNE in (c1, c2):
        return total / 4
    return total / 2


def _double_attacks_single(
    table: RelationMap,
    atk_primary_id: int,
    atk_secondary_id: int,
    def_id: int,
) -> float:
    c1 = _lookup(table, atk_primary_id, def_id)
    c2 = _lookup(table, atk_secondary_id, def_id)
    return _calc_mixed(c1, c2)


def _calc_multiplier(
    table: RelationMap,
    attacker: TypeCombinationORM,
    defender: TypeCombinationORM,
) -> float:
    atk_sec = attacker.secondary_id
    def_sec = defender.secondary_id

    if atk_sec is None and def_sec is None:
        return _lookup(table, attacker.primary_id, defender.primary_id)

    if atk_sec is None and def_sec is not None:
        c1 = _lookup(table, attacker.primary_id, defender.primary_id)
        c2 = _lookup(table, attacker.primary_id, def_sec)
        return _calc_mixed(c1, c2)

    if atk_sec is not None and def_sec is None:
        return _double_attacks_single(
            table, attacker.primary_id, atk_sec, defender.primary_id
        )

    c1 = _double_attacks_single(
        table, attacker.primary_id, atk_sec, defender.primary_id
    )
    c2 = _double_attacks_single(table, attacker.primary_id, atk_sec, def_sec)
    return (c1 + c2) / 2


def calc_attack_table(
    session: Session,
    attacker: TypeCombinationORM,
) -> list[tuple[TypeCombinationORM, float]]:
    global _all_combos_cache
    table = _load_relations(session)
    if _all_combos_cache is None:
        _all_combos_cache = list(session.exec(select(TypeCombinationORM)).all())
    all_combos = _all_combos_cache
    return [(combo, _calc_multiplier(table, attacker, combo)) for combo in all_combos]


def calc_defense_table(
    session: Session,
    defender: TypeCombinationORM,
) -> list[tuple[TypeCombinationORM, float]]:
    global _all_combos_cache
    table = _load_relations(session)
    if _all_combos_cache is None:
        _all_combos_cache = list(session.exec(select(TypeCombinationORM)).all())
    all_combos = _all_combos_cache
    return [(combo, _calc_multiplier(table, combo, defender)) for combo in all_combos]