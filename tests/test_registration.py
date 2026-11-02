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
        failed_target = next(job for job in failed if job["id"] == target_job_id)
        assert failed_target["attempts"] == 1
        assert failed_target["status"] == "failed"
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
