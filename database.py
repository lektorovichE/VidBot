import aiosqlite
from datetime import date, datetime, timedelta

DB_PATH = "vidbot.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT,
                first_name    TEXT,
                premium_until TEXT,
                downloads_today INTEGER DEFAULT 0,
                last_reset    TEXT DEFAULT '',
                total_downloads INTEGER DEFAULT 0,
                joined_at     TEXT DEFAULT (date('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                stars      INTEGER,
                plan       TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                url        TEXT,
                platform   TEXT,
                status     TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.commit()


async def get_or_create_user(user_id: int, username: str, first_name: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()

        if not row:
            await db.execute(
                "INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
                (user_id, username, first_name),
            )
            await db.commit()
            async with db.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()

        return dict(row)


async def reset_daily_if_needed(user_id: int):
    today = str(date.today())
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT last_reset FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if row and row[0] != today:
            await db.execute(
                "UPDATE users SET downloads_today = 0, last_reset = ? WHERE user_id = ?",
                (today, user_id),
            )
            await db.commit()


async def is_premium(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT premium_until FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    if not row or not row[0]:
        return False
    try:
        return datetime.fromisoformat(row[0]) > datetime.now()
    except Exception:
        return False


async def get_downloads_today(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT downloads_today FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else 0


async def increment_downloads(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE users
               SET downloads_today = downloads_today + 1,
                   total_downloads = total_downloads + 1
               WHERE user_id = ?""",
            (user_id,),
        )
        await db.commit()


async def activate_premium(user_id: int, days: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT premium_until FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()

        now = datetime.now()
        if row and row[0]:
            try:
                current = datetime.fromisoformat(row[0])
                base = max(current, now)
            except Exception:
                base = now
        else:
            base = now

        new_until = base + timedelta(days=days)
        await db.execute(
            "UPDATE users SET premium_until = ? WHERE user_id = ?",
            (new_until.isoformat(), user_id),
        )
        await db.commit()


async def log_payment(user_id: int, stars: int, plan: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO payments (user_id, stars, plan) VALUES (?, ?, ?)",
            (user_id, stars, plan),
        )
        await db.commit()


async def log_download(user_id: int, url: str, platform: str, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO downloads (user_id, url, platform, status) VALUES (?, ?, ?, ?)",
            (user_id, url, platform, status),
        )
        await db.commit()


# ── ADMIN STATS ──────────────────────────────────────────────────────────────

async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total_users = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE joined_at = date('now')"
        ) as cur:
            today_users = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE premium_until > datetime('now')"
        ) as cur:
            premium_users = (await cur.fetchone())[0]

        async with db.execute("SELECT COUNT(*) FROM downloads") as cur:
            total_dl = (await cur.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM downloads WHERE created_at >= date('now')"
        ) as cur:
            today_dl = (await cur.fetchone())[0]

        async with db.execute("SELECT COALESCE(SUM(stars), 0) FROM payments") as cur:
            total_stars = (await cur.fetchone())[0]

    return {
        "total_users": total_users,
        "today_users": today_users,
        "premium_users": premium_users,
        "total_downloads": total_dl,
        "today_downloads": today_dl,
        "total_stars": total_stars,
    }


async def get_all_user_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            rows = await cur.fetchall()
    return [r[0] for r in rows]
