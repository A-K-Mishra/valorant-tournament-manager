from __future__ import annotations

from pathlib import Path
import aiosqlite


class RegistrationDatabase:
    """SQLite persistence for registrations, per-guild settings, and Discord role outbox."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path

    async def initialize(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("""CREATE TABLE IF NOT EXISTS registrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                riot_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected')),
                submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                reviewed_by INTEGER,
                review_note TEXT,
                UNIQUE (guild_id, user_id)
            )""")
            await db.execute("""CREATE INDEX IF NOT EXISTS idx_registrations_status
                ON registrations(guild_id, status, submitted_at)""")
            await db.execute("""CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                participant_role_id INTEGER,
                pending_role_id INTEGER,
                audit_channel_id INTEGER,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            await db.execute("""CREATE TABLE IF NOT EXISTS guild_admin_roles (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                added_by INTEGER,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (guild_id, role_id)
            )""")
            await db.execute("""CREATE TABLE IF NOT EXISTS role_sync_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                operation TEXT NOT NULL CHECK (operation IN ('add', 'remove')),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'complete', 'failed')),
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            cur = await db.execute("PRAGMA table_info(role_sync_jobs)")
            columns = {row[1] for row in await cur.fetchall()}
            if "next_attempt_at" not in columns:
                await db.execute("ALTER TABLE role_sync_jobs ADD COLUMN next_attempt_at REAL NOT NULL DEFAULT 0")
            await db.execute("""CREATE INDEX IF NOT EXISTS idx_role_sync_pending
                ON role_sync_jobs(status, next_attempt_at, created_at)""")
            await db.commit()

    async def get_guild_settings(self, guild_id: int) -> dict:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,))
            row = await cur.fetchone()
            return dict(row) if row else {
                "guild_id": guild_id, "participant_role_id": None,
                "pending_role_id": None, "audit_channel_id": None,
            }

    async def set_guild_setting(self, guild_id: int, key: str, value: int | None) -> None:
        columns = {"participant_role_id", "pending_role_id", "audit_channel_id"}
        if key not in columns:
            raise ValueError("Unsupported guild setting")
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("INSERT OR IGNORE INTO guild_settings(guild_id) VALUES(?)", (guild_id,))
            await db.execute(
                f"UPDATE guild_settings SET {key}=?, updated_at=CURRENT_TIMESTAMP WHERE guild_id=?",
                (value, guild_id),
            )
            await db.commit()

    async def set_registration_role_and_reconcile(
        self, guild_id: int, key: str, role_id: int,
    ) -> None:
        """Change a registration role and enqueue reconciliation for existing members."""
        if key not in {"participant_role_id", "pending_role_id"}:
            raise ValueError("Unsupported registration role setting")
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("BEGIN")
            cur = await db.execute(
                f"SELECT {key} FROM guild_settings WHERE guild_id=?", (guild_id,)
            )
            row = await cur.fetchone()
            old_role_id = row[0] if row else None
            await db.execute(
                "INSERT OR IGNORE INTO guild_settings(guild_id) VALUES(?)", (guild_id,)
            )
            await db.execute(
                f"UPDATE guild_settings SET {key}=?, updated_at=CURRENT_TIMESTAMP WHERE guild_id=?",
                (role_id, guild_id),
            )
            if old_role_id and old_role_id != role_id:
                cur = await db.execute(
                    "SELECT user_id FROM registrations WHERE guild_id=?",
                    (guild_id,),
                )
                for (user_id,) in await cur.fetchall():
                    await self._enqueue_role_job(db, guild_id, user_id, old_role_id, "remove")

            desired_status = "approved" if key == "participant_role_id" else "pending"
            cur = await db.execute(
                "SELECT user_id,status FROM registrations WHERE guild_id=?",
                (guild_id,),
            )
            for user_id, status in await cur.fetchall():
                operation = "add" if status == desired_status else "remove"
                await self._enqueue_role_job(db, guild_id, user_id, role_id, operation)
            await db.commit()

    async def add_admin_role(self, guild_id: int, role_id: int, added_by: int) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO guild_admin_roles(guild_id, role_id, added_by) VALUES(?,?,?)",
                (guild_id, role_id, added_by),
            )
            await db.commit()

    async def remove_admin_role(self, guild_id: int, role_id: int) -> bool:
        async with aiosqlite.connect(self.database_path) as db:
            cur = await db.execute(
                "DELETE FROM guild_admin_roles WHERE guild_id=? AND role_id=?", (guild_id, role_id)
            )
            await db.commit()
            return cur.rowcount > 0

    async def get_admin_role_ids(self, guild_id: int) -> tuple[int, ...]:
        async with aiosqlite.connect(self.database_path) as db:
            cur = await db.execute(
                "SELECT role_id FROM guild_admin_roles WHERE guild_id=? ORDER BY role_id", (guild_id,)
            )
            return tuple(row[0] for row in await cur.fetchall())

    async def _enqueue_role_job(
        self, db: aiosqlite.Connection, guild_id: int, user_id: int,
        role_id: int | None, operation: str,
    ) -> None:
        if role_id is None:
            return
        # Replace unfinished operations for this member/role with the latest intent.
        await db.execute(
            """DELETE FROM role_sync_jobs
               WHERE guild_id=? AND user_id=? AND role_id=?
                 AND status IN ('pending','failed')""",
            (guild_id, user_id, role_id),
        )
        await db.execute(
            """INSERT INTO role_sync_jobs(guild_id,user_id,role_id,operation)
               VALUES(?,?,?,?)""",
            (guild_id, user_id, role_id, operation),
        )

    async def submit(self, guild_id: int, user_id: int, riot_id: str) -> str:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("BEGIN")
            cur = await db.execute(
                "SELECT status FROM registrations WHERE guild_id=? AND user_id=?",
                (guild_id, user_id),
            )
            row = await cur.fetchone()
            if row and row[0] == "approved":
                await db.rollback()
                return "already_approved"
            if row and row[0] == "pending":
                await db.rollback()
                return "already_pending"
            await db.execute(
                """INSERT INTO registrations(guild_id,user_id,riot_id,status,submitted_at,
                       reviewed_at,reviewed_by,review_note)
                   VALUES(?,?,?,'pending',CURRENT_TIMESTAMP,NULL,NULL,NULL)
                   ON CONFLICT(guild_id,user_id) DO UPDATE SET
                       riot_id=excluded.riot_id,status='pending',submitted_at=CURRENT_TIMESTAMP,
                       reviewed_at=NULL,reviewed_by=NULL,review_note=NULL""",
                (guild_id, user_id, riot_id),
            )
            cur = await db.execute(
                "SELECT pending_role_id FROM guild_settings WHERE guild_id=?", (guild_id,)
            )
            settings = await cur.fetchone()
            await self._enqueue_role_job(db, guild_id, user_id, settings[0] if settings else None, "add")
            await db.commit()
            return "submitted"

    async def get(self, guild_id: int, user_id: int):
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM registrations WHERE guild_id=? AND user_id=?", (guild_id, user_id)
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def pending(self, guild_id: int, limit: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM registrations WHERE guild_id=? AND status='pending' "
                "ORDER BY submitted_at ASC LIMIT ?", (guild_id, limit)
            )
            return [dict(row) for row in await cur.fetchall()]

    async def review(
        self, guild_id: int, user_id: int, reviewer_id: int,
        status: str, note: str | None = None,
    ) -> str:
        if status not in {"approved", "rejected"}:
            raise ValueError("Review status must be approved or rejected")
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("BEGIN")
            cur = await db.execute(
                """UPDATE registrations SET status=?,reviewed_at=CURRENT_TIMESTAMP,
                       reviewed_by=?,review_note=?
                   WHERE guild_id=? AND user_id=? AND status='pending'""",
                (status, reviewer_id, note, guild_id, user_id),
            )
            if not cur.rowcount:
                await db.rollback()
                return "not_pending"
            cur = await db.execute(
                "SELECT participant_role_id,pending_role_id FROM guild_settings WHERE guild_id=?",
                (guild_id,),
            )
            settings = await cur.fetchone()
            participant_id, pending_id = settings if settings else (None, None)
            await self._enqueue_role_job(db, guild_id, user_id, pending_id, "remove")
            if status == "approved":
                await self._enqueue_role_job(db, guild_id, user_id, participant_id, "add")
            await db.commit()
            return "updated"

    async def pending_role_sync_jobs(self, limit: int = 100) -> list[dict]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """SELECT * FROM role_sync_jobs
                   WHERE status='pending'
                      OR (status='failed' AND attempts < 8 AND next_attempt_at <= unixepoch())
                   ORDER BY id ASC LIMIT ?""", (limit,)
            )
            return [dict(row) for row in await cur.fetchall()]


    async def role_sync_summary(self, guild_id: int) -> dict:
        async with aiosqlite.connect(self.database_path) as db:
            cur = await db.execute(
                """SELECT
                   SUM(CASE WHEN status='pending' OR (status='failed' AND attempts < 8 AND next_attempt_at <= unixepoch()) THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status='failed' AND attempts < 8 AND next_attempt_at > unixepoch() THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status='failed' AND attempts >= 8 THEN 1 ELSE 0 END)
                   FROM role_sync_jobs WHERE guild_id=?""", (guild_id,)
            )
            pending, waiting, exhausted = await cur.fetchone()
            cur = await db.execute(
                """SELECT user_id,role_id,operation,attempts,last_error
                   FROM role_sync_jobs WHERE guild_id=? AND status='failed'
                   ORDER BY attempts DESC,id DESC LIMIT 5""", (guild_id,)
            )
            recent = [
                {"user_id": r[0], "role_id": r[1], "operation": r[2],
                 "attempts": r[3], "last_error": r[4]}
                for r in await cur.fetchall()
            ]
            return {"pending": pending or 0, "waiting": waiting or 0,
                    "exhausted": exhausted or 0, "recent": recent}

    async def retry_failed_role_sync_jobs(self, guild_id: int) -> int:
        async with aiosqlite.connect(self.database_path) as db:
            cur = await db.execute(
                """UPDATE role_sync_jobs
                   SET status='pending',attempts=0,next_attempt_at=0,last_error=NULL,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE guild_id=? AND status='failed'""", (guild_id,)
            )
            await db.commit()
            return cur.rowcount

    async def finish_role_sync_job(self, job_id: int) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                "UPDATE role_sync_jobs SET status='complete',last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (job_id,),
            )
            await db.commit()

    async def fail_role_sync_job(self, job_id: int, error: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """UPDATE role_sync_jobs SET status='failed',attempts=attempts+1,
                       next_attempt_at=unixepoch() + MIN(30 * (1 << MIN(attempts, 7)), 3600),
                       last_error=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status != 'complete'""",
                (error[:1000], job_id),
            )
            await db.commit()
