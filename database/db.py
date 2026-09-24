import aiosqlite
import os
from config import config

os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)


async def init_db():
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                sso_url TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                jobs_count INTEGER DEFAULT 0
            )
        """)
        await db.commit()


async def add_job(user_id: int, sso_url: str) -> int:
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO jobs (user_id, sso_url) VALUES (?, ?)",
            (user_id, sso_url)
        )
        await db.commit()
        return cur.lastrowid


async def update_job(job_id: int, status: str, result: str = None):
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "UPDATE jobs SET status=?, result=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, result, job_id)
        )
        await db.commit()


async def get_user_jobs(user_id: int, limit: int = 10):
    async with aiosqlite.connect(config.DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, status, created_at FROM jobs WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        )
        return await cur.fetchall()


async def register_user(user_id: int, username: str):
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )
        await db.commit()
