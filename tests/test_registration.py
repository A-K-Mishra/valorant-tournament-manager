import asyncio

import pytest

from bot.database import RegistrationDatabase
from bot.registration import validate_riot_id


def test_riot_id_validation_accepts_valid_format():
    assert validate_riot_id("PlayerName#1234") == "PlayerName#1234"
    assert validate_riot_id("  PlayerName#EUW  ") == "PlayerName#EUW"


@pytest.mark.parametrize(
    "value",
    ["", "ab#123", "PlayerName", "Player#12", "Player#123456", "Player Name#1234", "Player#12 3"],
)
def test_riot_id_validation_rejects_invalid_format(value):
    with pytest.raises(ValueError):
        validate_riot_id(value)


def test_registration_lifecycle_and_role_outbox(tmp_path):
    async def scenario():
        db = RegistrationDatabase(str(tmp_path / "test.sqlite3"))
        await db.initialize()
        await db.set_guild_setting(10, "pending_role_id", 501)
        await db.set_guild_setting(10, "participant_role_id", 502)

        assert await db.submit(10, 20, "PlayerName#1234") == "submitted"
        jobs = await db.pending_role_sync_jobs()
        assert [(job["role_id"], job["operation"]) for job in jobs] == [(501, "add")]

        assert await db.submit(10, 20, "OtherName#1234") == "already_pending"
        row = await db.get(10, 20)
        assert row["status"] == "pending"
        assert row["riot_id"] == "PlayerName#1234"
        assert len(await db.pending(10)) == 1

        assert await db.review(10, 20, 99, "approved") == "updated"
        jobs = await db.pending_role_sync_jobs()
        # The approval supersedes the earlier Pending-role add. Only the
        # latest desired operation for each role should remain in the outbox.
        assert [(job["role_id"], job["operation"]) for job in jobs] == [
            (501, "remove"), (502, "add")
        ]
        assert await db.review(10, 20, 99, "rejected") == "not_pending"
        assert (await db.get(10, 20))["status"] == "approved"
        assert await db.submit(10, 20, "Changed#1234") == "already_approved"

        assert await db.submit(11, 20, "Changed#1234") == "submitted"
        assert await db.review(11, 20, 99, "rejected", "Please check your Riot ID") == "updated"
        assert (await db.get(11, 20))["status"] == "rejected"
        assert await db.submit(11, 20, "Corrected#1234") == "submitted"
        assert (await db.get(11, 20))["status"] == "pending"

        await db.add_admin_role(10, 700, 99)
        assert await db.get_admin_role_ids(10) == (700,)
        assert await db.remove_admin_role(10, 700) is True
        assert await db.get_admin_role_ids(10) == ()

        target_job_id = jobs[0]["id"]
        await db.fail_role_sync_job(target_job_id, "temporary failure")
        failed = await db.pending_role_sync_jobs()
        assert target_job_id not in {job["id"] for job in failed}
        summary = await db.role_sync_summary(10)
        assert summary["waiting"] == 1
        assert summary["recent"][0]["attempts"] == 1
        assert await db.retry_failed_role_sync_jobs(10) == 1
        retried = await db.pending_role_sync_jobs()
        assert target_job_id in {job["id"] for job in retried}
        await db.finish_role_sync_job(target_job_id)
        remaining = await db.pending_role_sync_jobs()
        assert target_job_id not in {job["id"] for job in remaining}
        assert {job["id"] for job in remaining} == {job["id"] for job in jobs[1:]}

    asyncio.run(scenario())


def test_existing_database_migrates_without_losing_registrations(tmp_path):
    async def scenario():
        db = RegistrationDatabase(str(tmp_path / "legacy.sqlite3"))
        await db.initialize()
        assert await db.submit(1, 2, "Legacy#1234") == "submitted"
        await db.initialize()
        assert (await db.get(1, 2))["riot_id"] == "Legacy#1234"
        assert (await db.get_guild_settings(1))["participant_role_id"] is None

    asyncio.run(scenario())



def test_role_sync_retry_migration_adds_backoff_column_to_legacy_database(tmp_path):
    async def scenario():
        db = RegistrationDatabase(str(tmp_path / "legacy-role-jobs.sqlite3"))
        await db.initialize()
        import aiosqlite
        async with aiosqlite.connect(db.database_path) as conn:
            await conn.execute("DROP TABLE role_sync_jobs")
            await conn.execute("""CREATE TABLE role_sync_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, role_id INTEGER NOT NULL,
                operation TEXT NOT NULL CHECK (operation IN ('add','remove')),
                status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','complete','failed')),
                attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            await conn.execute(
                "INSERT INTO role_sync_jobs(guild_id,user_id,role_id,operation) VALUES(1,2,3,'add')"
            )
            await conn.commit()
        await db.initialize()
        jobs = await db.pending_role_sync_jobs()
        assert len(jobs) == 1
        assert jobs[0]["next_attempt_at"] == 0

    asyncio.run(scenario())


def test_changing_registration_roles_reconciles_existing_members(tmp_path):
    async def scenario():
        db = RegistrationDatabase(str(tmp_path / "reconcile.sqlite3"))
        await db.initialize()
        await db.set_guild_setting(7, "pending_role_id", 501)
        await db.set_guild_setting(7, "participant_role_id", 502)

        assert await db.submit(7, 20, "Pending#1234") == "submitted"
        assert await db.submit(7, 21, "Approved#1234") == "submitted"
        assert await db.review(7, 21, 99, "approved") == "updated"

        await db.set_registration_role_and_reconcile(7, "participant_role_id", 503)
        jobs = await db.pending_role_sync_jobs()
        intents = {(job["user_id"], job["role_id"]): job["operation"] for job in jobs}
        assert intents[(20, 502)] == "remove"
        assert intents[(21, 502)] == "remove"
        assert intents[(20, 503)] == "remove"
        assert intents[(21, 503)] == "add"

        await db.set_registration_role_and_reconcile(7, "pending_role_id", 504)
        jobs = await db.pending_role_sync_jobs()
        intents = {(job["user_id"], job["role_id"]): job["operation"] for job in jobs}
        assert intents[(20, 501)] == "remove"
        assert intents[(21, 501)] == "remove"
        assert intents[(20, 504)] == "add"
        assert intents[(21, 504)] == "remove"

    asyncio.run(scenario())
