import aiosqlite
import time
from typing import Optional, List, Dict, Any, Tuple
from config import DATABASE_PATH

class Database:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path

    async def init_db(self):
        """Инициализация таблиц базы данных SQLite"""
        async with aiosqlite.connect(self.db_path) as db:
            # Таблица промокодов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS codes (
                    code TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    max_uses INTEGER DEFAULT 1,
                    used_count INTEGER DEFAULT 0,
                    expires_at INTEGER NULL,
                    created_by INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    note TEXT DEFAULT '',
                    PRIMARY KEY (code, guild_id)
                )
            """)

            # Таблица истории активаций (для исключения повторной активации одним юзером)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS redemptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    redeemed_at INTEGER NOT NULL,
                    UNIQUE(code, guild_id, user_id)
                )
            """)

            await db.commit()

    async def create_code(
        self,
        code: str,
        guild_id: int,
        role_id: int,
        max_uses: int = 1,
        expires_at: Optional[int] = None,
        created_by: int = 0,
        note: str = ""
    ) -> Tuple[bool, str]:
        """Создать новый промокод"""
        clean_code = code.strip().upper()
        now = int(time.time())

        async with aiosqlite.connect(self.db_path) as db:
            # Проверяем, существует ли уже такой код на сервере
            async with db.execute(
                "SELECT code FROM codes WHERE code = ? AND guild_id = ?",
                (clean_code, guild_id)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return False, f"Код `{clean_code}` уже существует на этом сервере!"

            await db.execute(
                """
                INSERT INTO codes (code, guild_id, role_id, max_uses, used_count, expires_at, created_by, created_at, is_active, note)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?, 1, ?)
                """,
                (clean_code, guild_id, role_id, max_uses, expires_at, created_by, now, note)
            )
            await db.commit()
            return True, f"Код `{clean_code}` успешно создан!"

    async def get_code(self, code: str, guild_id: int) -> Optional[Dict[str, Any]]:
        """Получить информацию о коде"""
        clean_code = code.strip().upper()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM codes WHERE code = ? AND guild_id = ?",
                (clean_code, guild_id)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def redeem_code(
        self,
        code: str,
        guild_id: int,
        user_id: int
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Попытка активации кода пользователем.
        Возвращает: (успех: bool, сообщение: str, role_id: Optional[int])
        """
        clean_code = code.strip().upper()
        now = int(time.time())

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            # 1. Поиск кода
            async with db.execute(
                "SELECT * FROM codes WHERE code = ? AND guild_id = ?",
                (clean_code, guild_id)
            ) as cursor:
                code_data = await cursor.fetchone()

            if not code_data:
                return False, "❌ Код не найден. Проверьте правильность ввода.", None

            # 2. Активен ли код администратором
            if not code_data["is_active"]:
                return False, "❌ Этот код деактивирован администратором.", None

            # 3. Проверка срока годности
            if code_data["expires_at"] and now > code_data["expires_at"]:
                return False, "⏳ Срок действия этого промокода истёк!", None

            # 4. Проверка лимита использований (если max_uses > 0; 0 означает бесконечно)
            if code_data["max_uses"] > 0 and code_data["used_count"] >= code_data["max_uses"]:
                return False, "🚫 Лимит активаций этого кода исчерпан!", None

            # 5. Проверка, активировал ли этот пользователь уже этот код
            async with db.execute(
                "SELECT id FROM redemptions WHERE code = ? AND guild_id = ? AND user_id = ?",
                (clean_code, guild_id, user_id)
            ) as cursor:
                already_redeemed = await cursor.fetchone()

            if already_redeemed:
                return False, "⚠️ Вы уже активировали этот код ранее!", None

            # 6. Атомарное применение активации
            role_id = code_data["role_id"]
            new_used_count = code_data["used_count"] + 1

            # Обновляем счетчик
            await db.execute(
                "UPDATE codes SET used_count = ? WHERE code = ? AND guild_id = ?",
                (new_used_count, clean_code, guild_id)
            )

            # Записываем в историю
            await db.execute(
                """
                INSERT INTO redemptions (code, guild_id, user_id, role_id, redeemed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (clean_code, guild_id, user_id, role_id, now)
            )

            await db.commit()
            return True, "✅ Код успешно активирован!", role_id

    async def list_codes(
        self,
        guild_id: int,
        only_active: bool = False,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Список кодов сервера"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if only_active:
                query = "SELECT * FROM codes WHERE guild_id = ? AND is_active = 1 ORDER BY created_at DESC LIMIT ?"
                params = (guild_id, limit)
            else:
                query = "SELECT * FROM codes WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?"
                params = (guild_id, limit)

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def revoke_code(self, code: str, guild_id: int) -> bool:
        """Деактивировать код (отозвать)"""
        clean_code = code.strip().upper()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "UPDATE codes SET is_active = 0 WHERE code = ? AND guild_id = ?",
                (clean_code, guild_id)
            ) as cursor:
                await db.commit()
                return cursor.rowcount > 0

    async def delete_code(self, code: str, guild_id: int) -> bool:
        """Удалить код полностью из базы"""
        clean_code = code.strip().upper()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM redemptions WHERE code = ? AND guild_id = ?",
                (clean_code, guild_id)
            )
            async with db.execute(
                "DELETE FROM codes WHERE code = ? AND guild_id = ?",
                (clean_code, guild_id)
            ) as cursor:
                await db.commit()
                return cursor.rowcount > 0

    async def get_code_stats(self, code: str, guild_id: int) -> Optional[Dict[str, Any]]:
        """Получить статистику по коду и список активировавших юзеров"""
        clean_code = code.strip().upper()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM codes WHERE code = ? AND guild_id = ?",
                (clean_code, guild_id)
            ) as cursor:
                code_data = await cursor.fetchone()
                if not code_data:
                    return None

            async with db.execute(
                "SELECT user_id, redeemed_at FROM redemptions WHERE code = ? AND guild_id = ? ORDER BY redeemed_at DESC",
                (clean_code, guild_id)
            ) as cursor:
                redemptions = await cursor.fetchall()

            res = dict(code_data)
            res["redemptions"] = [dict(r) for r in redemptions]
            return res

db = Database()
