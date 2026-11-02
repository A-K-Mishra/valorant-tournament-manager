from __future__ import annotations
from pathlib import Path
import aiosqlite

class RegistrationDatabase:
    def __init__(self, database_path: str) -> None: self.database_path = database_path

    async def initialize(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('PRAGMA journal_mode=WAL')
            await db.execute('PRAGMA foreign_keys=ON')
            await db.execute('''CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                riot_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected')),
                submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, reviewed_at TEXT,
                reviewed_by INTEGER, review_note TEXT, UNIQUE (guild_id, user_id))''')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_registrations_status ON registrations(guild_id, status, submitted_at)')
            await db.commit()

    async def submit(self, guild_id: int, user_id: int, riot_id: str) -> str:
        async with aiosqlite.connect(self.database_path) as db:
            cur = await db.execute('SELECT status FROM registrations WHERE guild_id=? AND user_id=?', (guild_id, user_id))
            row = await cur.fetchone()
            if row and row[0] == 'approved': return 'already_approved'
            if row and row[0] == 'pending': return 'already_pending'
            await db.execute('''INSERT INTO registrations(guild_id,user_id,riot_id,status,submitted_at,reviewed_at,reviewed_by,review_note)
                VALUES(?,?,?,'pending',CURRENT_TIMESTAMP,NULL,NULL,NULL)
                ON CONFLICT(guild_id,user_id) DO UPDATE SET riot_id=excluded.riot_id,status='pending',submitted_at=CURRENT_TIMESTAMP,reviewed_at=NULL,reviewed_by=NULL,review_note=NULL''', (guild_id,user_id,riot_id))
            await db.commit()
            return 'submitted'

    async def get(self, guild_id: int, user_id: int):
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute('SELECT * FROM registrations WHERE guild_id=? AND user_id=?', (guild_id,user_id))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def pending(self, guild_id: int, limit: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM registrations WHERE guild_id=? AND status='pending' ORDER BY submitted_at ASC LIMIT ?", (guild_id,limit))
            return [dict(row) for row in await cur.fetchall()]

    async def review(self, guild_id: int, user_id: int, reviewer_id: int, status: str, note: str | None = None) -> str:
        if status not in {'approved','rejected'}: raise ValueError('Review status must be approved or rejected')
        async with aiosqlite.connect(self.database_path) as db:
            cur = await db.execute("UPDATE registrations SET status=?,reviewed_at=CURRENT_TIMESTAMP,reviewed_by=?,review_note=? WHERE guild_id=? AND user_id=? AND status='pending'", (status,reviewer_id,note,guild_id,user_id))
            await db.commit()
            return 'updated' if cur.rowcount else 'not_pending'
