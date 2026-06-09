"""
Database dependencies for SeerInfo plugin.

Simplified from IronsBot's db_sync system for AstrBot.
"""

import asyncio
import os
import re
import sqlite3
from collections.abc import Callable, Generator, Iterable
from pathlib import Path
from typing import Any, Final, Generic, Protocol, TypeVar, Union

import aiohttp
from pypinyin import lazy_pinyin
from seerapi_models import (
    PetORM,
    PetSkinORM,
    MintmarkORM,
    GemORM,
    SuitORM,
    EquipORM,
    TitlePartORM,
    TypeCombinationORM,
    ElementTypeORM,
    BattleEffectORM,
)
from seerapi_models.build_model import BaseResModel
from sqlalchemy import text
from sqlalchemy.engine.base import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, Session as SQLModelSession, SQLModel, create_engine, select, col, func, or_, and_

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path


from ..core.type_calc import invalidate_relation_cache


_ALIASES_DB = "aliases"


class PetAliasORM(SQLModel, table=True):
    __tablename__ = "pet_aliases"
    __table_args__ = {"extend_existing": True}
    name: str = Field(primary_key=True)
    target_id: int = Field(primary_key=True)



class AliasModelProtocol(Protocol):
    name: str
    target_id: int


def get_plugin_db_path(db_name: str) -> str:
    """获取插件数据库文件的默认路径。
    
    返回: data/plugin_data/astrbot_plugin_seer_info/{db_name}.sqlite
    """
    plugin_data_path = Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_seer_info"
    plugin_data_path.mkdir(parents=True, exist_ok=True)
    return str(plugin_data_path / f"{db_name}.sqlite")


class DatabaseManager:
    """管理多个命名内存数据库引擎的管理器。

    每个数据库通过唯一的名称标识，数据存储在内存中，
    通过从远程 SQLite 文件导入数据来更新。
    """

    def __init__(self):
        self._engines: dict[str, Engine] = {}
        self._post_load_hooks: dict[str, list[Callable]] = {}

    @staticmethod
    def _create_memory_engine() -> Engine:
        """创建一个共享连接的内存 SQLite 引擎。"""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        _register_strip_func(engine)
        return engine

    def register_post_load_hook(
        self, name: str, hook: Callable[[Engine], None]
    ) -> None:
        """注册一个在数据库从文件加载到内存后执行的钩子。"""
        self._post_load_hooks.setdefault(name, []).append(hook)

    def load_from_file(self, name: str, file_path: str) -> None:
        """从 SQLite 文件导入全部数据到新的内存引擎，然后原子替换旧引擎。"""
        new_engine = self._create_memory_engine()

        source = sqlite3.connect(file_path)
        try:
            raw_conn = new_engine.raw_connection()
            try:
                source.backup(raw_conn.dbapi_connection)
            finally:
                raw_conn.close()
        finally:
            source.close()

        for hook in self._post_load_hooks.get(name, []):
            try:
                hook(new_engine)
            except Exception:
                logger.warning(f"数据库 '{name}' 的 post-load 钩子执行失败")

        old_engine = self._engines.get(name)
        self._engines[name] = new_engine
        if old_engine is not None:
            old_engine.dispose()
        if name == "seerapi":
            invalidate_relation_cache()
        logger.info(f"已从文件导入数据到内存数据库 '{name}'")

    def get_engine(self, name: str) -> Engine | None:
        """获取指定名称的数据库引擎。"""
        return self._engines.get(name)

    def get_session(self, name: str) -> Generator[SQLModelSession, None, None] | None:
        """获取指定数据库的会话生成器。"""
        engine = self.get_engine(name)
        if engine is None:
            return None

        def _gen() -> Generator[SQLModelSession, None, None]:
            with SQLModelSession(engine) as session:
                yield session

        return _gen()

    def get_all_sessions(self) -> dict[str, SQLModelSession]:
        """创建所有已注册数据库的会话字典。"""
        return {
            name: SQLModelSession(engine)
            for name, engine in self._engines.items()
        }

    @property
    def registered_names(self) -> list[str]:
        """获取所有已注册的数据库名称。"""
        return list(self._engines.keys())

    def is_database_loaded(self, name: str) -> bool:
        """检查数据库是否已加载（有实际数据）。"""
        return name in self._engines

    def dispose_all(self) -> None:
        """释放所有引擎的连接池。"""
        for name, engine in self._engines.items():
            engine.dispose()
            logger.info(f"已释放数据库引擎 '{name}'")
        self._engines.clear()


db_manager: Final[DatabaseManager] = DatabaseManager()
_sync_tasks: dict[str, asyncio.Task] = {}


def register_database(
    name: str,
    *,
    sync_url: str,
    sync_interval_minutes: int = 60,
    get_fingerprint: Callable[[aiohttp.ClientSession], Any] | None = None,
):
    async def sync_task():
        while True:
            await sync_database(name, sync_url, get_fingerprint)
            logger.info(f"数据库 '{name}' 将在 {sync_interval_minutes} 分钟后再次检查")
            await asyncio.sleep(sync_interval_minutes * 60)

    _sync_tasks[name] = asyncio.create_task(sync_task())


def cancel_sync_tasks() -> None:
    """取消所有同步任务。"""
    for name, task in _sync_tasks.items():
        if not task.done():
            task.cancel()
            logger.info(f"已取消数据库 '{name}' 的同步任务")
    _sync_tasks.clear()


def register_local_database(name: str):
    """注册本地数据库文件，使用默认路径：
    data/plugin_data/{plugin_name}/{name}.sqlite
    """
    file_path = get_plugin_db_path(name)
    
    if not os.path.exists(file_path):
        logger.warning(f"本地文件 '{file_path}' 不存在，跳过注册 {name}")
        return

    db_manager.load_from_file(name, file_path)


async def sync_database(name: str, sync_url: str, get_fingerprint: Callable | None = None):
    if not sync_url:
        return

    plugin_db_path = get_plugin_db_path(name)
    plugin_db_file = Path(plugin_db_path)
    sha256_path = plugin_db_path + ".sha256"

    try:
        async with aiohttp.ClientSession() as session:
            if plugin_db_file.exists() and get_fingerprint:
                try:
                    remote_fingerprint = await get_fingerprint(session)

                    local_fingerprint = None
                    if os.path.exists(sha256_path):
                        local_fingerprint = Path(sha256_path).read_text().strip()

                    if remote_fingerprint and remote_fingerprint == local_fingerprint:
                        if db_manager.is_database_loaded(name):
                            logger.info(f"数据库 '{name}' 指纹未变化，跳过更新")
                        else:
                            logger.info(f"数据库 '{name}' 指纹未变化，使用本地数据")
                            db_manager.load_from_file(name, plugin_db_path)
                        return
                except Exception as e:
                    logger.warning(f"指纹检查失败: {e}，将继续下载")

            logger.info(f"开始从 {sync_url} 下载数据库 '{name}'...")
            async with session.get(sync_url, allow_redirects=True) as resp:
                resp.raise_for_status()
                data = await resp.read()

            plugin_db_file.parent.mkdir(parents=True, exist_ok=True)
            plugin_db_file.write_bytes(data)

            if get_fingerprint:
                try:
                    remote_fp = await get_fingerprint(session)
                    Path(sha256_path).write_text(remote_fp.strip())
                    logger.info(f"已保存指纹: {remote_fp.strip()}")
                except Exception as e:
                    logger.warning(f"保存指纹失败: {e}")

            size_mb = len(data) / (1024 * 1024)
            logger.info(f"数据库 '{name}' 已下载，大小: {size_mb:.2f} MB")

            db_manager.load_from_file(name, plugin_db_path)

    except Exception as e:
        logger.error(f"数据库 '{name}' 同步失败: {e}")


_IGNORED_CHARS = ".·・•‧∙⋅。—–-_/ "
_STRIP_SPECIAL_RE = re.compile(f"[{re.escape(_IGNORED_CHARS)}]")


def _strip_special(text: str) -> str:
    return _STRIP_SPECIAL_RE.sub("", text)


def _register_strip_func(engine: Engine) -> None:
    """注册 SQLite 自定义函数，单次调用完成字符替换，避免 13 层嵌套 REPLACE。"""
    def _sqlite_strip(text):
        if text is None:
            return None
        for ch in _IGNORED_CHARS:
            text = text.replace(ch, "")
        return text

    with engine.connect() as conn:
        conn.connection.connection.create_function("_strip", 1, _sqlite_strip)
        conn.commit()


def _col_strip_special(column: Any) -> Any:
    return func._strip(column)


_T_Model = TypeVar("_T_Model", bound=BaseResModel)


class IdResolver(Generic[_T_Model]):
    def __init__(self, model: type[_T_Model], *, db_name: str = "seerapi"):
        self.model = model
        self.db_name = db_name

    def __call__(self, sessions: dict, arg: str) -> Union[tuple[_T_Model], tuple]:
        if not arg.isdigit():
            return ()
        session = sessions.get(self.db_name)
        if session is None:
            return ()
        obj = session.get(self.model, int(arg))
        return (obj,) if obj else ()


class NameResolver(Generic[_T_Model]):
    def __init__(self, model: type[_T_Model], *, db_name: str = "seerapi", name_column: str = "name"):
        if not hasattr(model, name_column):
            from astrbot.api import logger
            logger.warning(f"Model {model} has no column {name_column}")
        self.model = model
        self.db_name = db_name
        self.name_column = getattr(model, name_column, None)

    def __call__(self, sessions: dict, arg: str) -> Iterable[_T_Model]:
        if not self.name_column:
            return ()

        session = sessions.get(self.db_name)
        if session is None:
            return ()

        stripped_arg = _strip_special(arg)
        statement = select(self.model).where(
            _col_strip_special(col(self.name_column)).like(f"%{stripped_arg}%")
        )
        return session.exec(statement).all()


class AliasResolver(Generic[_T_Model]):
    def __init__(
        self,
        model: type[_T_Model],
        alias_model: type[AliasModelProtocol],
        *,
        alias_db: str = _ALIASES_DB,
        data_db: str = "seerapi",
    ):
        self.model = model
        self.alias_model = alias_model
        self.alias_db = alias_db
        self.data_db = data_db

    def __call__(self, sessions: dict, arg: str) -> Iterable[_T_Model]:
        alias_session = sessions.get(self.alias_db)
        if alias_session is None:
            return ()

        stripped_arg = _strip_special(arg)
        try:
            statement = select(self.alias_model).where(
                _col_strip_special(col(self.alias_model.name)).like(f"%{stripped_arg}%")
            )
            aliases = alias_session.exec(statement).all()
            ids = {alias.target_id for alias in aliases}
        except Exception:
            return ()

        if not ids:
            return ()

        data_session = sessions.get(self.data_db)
        if data_session is None:
            return ()

        return data_session.exec(
            select(self.model).where(col(self.model.id).in_(ids))
        ).all()


_PINYIN_FTS_TABLE = "pinyin_fts"
_PINYIN_FTS_SOURCES: dict[str, str] = {
    "pet": "SELECT id, name FROM pet",
    "pet_skins": "SELECT id, name FROM pet_skins",
}


class PinyinResolver(Generic[_T_Model]):
    """通过汉语拼音（全拼或首字母）搜索模型对象，基于 FTS5 索引。"""

    @staticmethod
    def _to_pinyin_needle(arg: str) -> tuple[str, list[str] | None] | None:
        """将用户输入转换为拼音搜索字符串。"""
        stripped = _strip_special(arg)
        if stripped.isascii():
            if not stripped.isalpha():
                return None
            return (stripped.lower(), None)
        syllables = [s.lower() for s in lazy_pinyin(stripped)]
        needle = "".join(syllables)
        return (needle, syllables)

    def __init__(
        self,
        model: type[_T_Model],
        *,
        source_table: str,
        db_name: str = "seerapi",
    ):
        self.model = model
        self.source_table = source_table
        self.db_name = db_name

    def __call__(self, sessions: dict, arg: str) -> Iterable[_T_Model]:
        needle_data = self._to_pinyin_needle(arg)
        if not needle_data:
            return ()
        needle, input_syllables = needle_data

        session = sessions.get(self.db_name)
        if session is None:
            return ()

        try:
            with session.connection().engine.connect() as conn:
                result = conn.execute(
                    text(
                        f"SELECT rowid FROM [{_PINYIN_FTS_TABLE}] "
                        "WHERE source_table = :src "
                        "AND (pinyin_full MATCH :q OR pinyin_initials MATCH :q)"
                    ),
                    {"src": self.source_table, "q": f'"{needle}"'}
                )
                rowids = [row[0] for row in result.fetchall()]
        except Exception:
            return ()

        if not rowids:
            return ()

        return session.exec(
            select(self.model).where(col(self.model.id).in_(rowids))
        ).all()


class Getter(Generic[_T_Model]):
    def __init__(self, model: type[_T_Model], *resolvers):
        self.model = model
        self.resolvers = resolvers

    def get(self, session: Session, id_: int) -> _T_Model | None:
        return session.get(self.model, id_)

    def __call__(self, sessions: dict, arg: str) -> tuple[_T_Model, ...]:
        if not arg:
            return ()

        seen: dict[int, _T_Model] = {}
        for resolver in self.resolvers:
            for obj in resolver(sessions, arg):
                seen.setdefault(obj.id, obj)

        return tuple(seen.values())


PetDataGetter = Getter(
    PetORM,
    IdResolver(PetORM),
    NameResolver(PetORM),
    AliasResolver(PetORM, PetAliasORM),
    PinyinResolver(PetORM, source_table="pet"),
)

PetSkinDataGetter = Getter(
    PetSkinORM,
    IdResolver(PetSkinORM),
    NameResolver(PetSkinORM),
    PinyinResolver(PetSkinORM, source_table="pet_skins"),
)

MintmarkDataGetter = Getter(
    MintmarkORM,
    IdResolver(MintmarkORM),
    NameResolver(MintmarkORM),
)

GemDataGetter = Getter(
    GemORM,
    IdResolver(GemORM),
    NameResolver(GemORM),
)

SuitDataGetter = Getter(
    SuitORM,
    IdResolver(SuitORM),
    NameResolver(SuitORM),
)

EquipDataGetter = Getter(
    EquipORM,
    IdResolver(EquipORM),
    NameResolver(EquipORM),
)


class TypeCombinationResolver:
    """将用户输入拆分为单属性名，再按 ID 组合查询 TypeCombinationORM。

    支持任意顺序输入：如 "火战斗" 和 "战斗火" 都能匹配到同一条双属性记录。
    """

    def __init__(self, *, db_name: str = "seerapi"):
        self.db_name = db_name

    def __call__(self, sessions: dict, arg: str) -> Iterable[TypeCombinationORM]:
        session = sessions.get(self.db_name)
        if session is None:
            logger.warning("TypeCombinationResolver: 未找到数据库会话")
            return ()

        stripped = _strip_special(arg)
        if not stripped:
            return ()

        all_types = session.exec(select(ElementTypeORM)).all()
        name_to_id: dict[str, int] = {t.name: t.id for t in all_types}

        if stripped in name_to_id:
            tid = name_to_id[stripped]
            results = list(
                session.exec(
                    select(TypeCombinationORM).where(
                        TypeCombinationORM.primary_id == tid,
                        TypeCombinationORM.secondary_id is None,
                    )
                ).all()
            )
            if results:
                return results

        found: dict[int, TypeCombinationORM] = {}
        for i in range(1, len(stripped)):
            left, right = stripped[:i], stripped[i:]
            if left not in name_to_id or right not in name_to_id:
                continue
            a, b = name_to_id[left], name_to_id[right]
            combos = session.exec(
                select(TypeCombinationORM).where(
                    or_(
                        and_(
                            TypeCombinationORM.primary_id == a,
                            TypeCombinationORM.secondary_id == b,
                        ),
                        and_(
                            TypeCombinationORM.primary_id == b,
                            TypeCombinationORM.secondary_id == a,
                        ),
                    )
                )
            ).all()
            for combo in combos:
                found.setdefault(combo.id, combo)

        return tuple(found.values())


TypeCombinationDataGetter = Getter(
    TypeCombinationORM,
    IdResolver(TypeCombinationORM),
    NameResolver(TypeCombinationORM),
    TypeCombinationResolver(),
)

BattleEffectDataGetter = Getter(
    BattleEffectORM,
    IdResolver(BattleEffectORM),
    NameResolver(BattleEffectORM),
)

TitleDataGetter = Getter(
    TitlePartORM,
    IdResolver(TitlePartORM),
    NameResolver(TitlePartORM),
)


def _build_pinyin_fts(engine: Engine) -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS pinyin_fts USING fts5("
                "source_table, pinyin_full, pinyin_initials, "
                "tokenize='trigram')"
            ))
            existing_tables = {
                row[0] for row in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            }
            for source_table, query in _PINYIN_FTS_SOURCES.items():
                if source_table not in existing_tables:
                    continue
                try:
                    rows = conn.execute(text(query)).fetchall()
                    for row_id, name in rows:
                        syllables = lazy_pinyin(_strip_special(name))
                        full = "".join(syllables)
                        initials = "".join(s[0] for s in syllables if s)
                        conn.execute(
                            text(
                                f"INSERT INTO [{_PINYIN_FTS_TABLE}] (rowid, source_table, pinyin_full, pinyin_initials) "
                                "VALUES (:rowid, :src, :full, :initials)"
                            ),
                            {"rowid": row_id, "src": source_table, "full": full, "initials": initials}
                        )
                except Exception as e:
                    logger.error(f"拼音 FTS 索引填充失败 for {source_table}: {e}")
            conn.commit()
    except Exception as e:
        logger.error(f"拼音 FTS 索引构建失败: {e}")


db_manager.register_post_load_hook("seerapi", _build_pinyin_fts)


__all__ = [
    "db_manager",
    "register_database",
    "register_local_database",
    "get_plugin_db_path",
    "cancel_sync_tasks",
    "PetDataGetter",
    "MintmarkDataGetter",
    "GemDataGetter",
    "SuitDataGetter",
    "EquipDataGetter",
    "TypeCombinationDataGetter",
    "BattleEffectDataGetter",
    "TitleDataGetter",
    "TitlePartORM",
    "Getter",
    "IdResolver",
    "NameResolver",
    "AliasResolver",
    "PinyinResolver",
]