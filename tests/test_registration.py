import asyncio

import pytest

from bot.database import RegistrationDatabase
from bot.registration import validate_riot_id


def test_riot_id_validation_accepts_valid_format():
    assert validate_riot_id('PlayerName#1234') == 'PlayerName#1234'
    assert validate_riot_id('  PlayerName#EUW  ') == 'PlayerName#EUW'


@pytest.mark.parametrize('value', ['', 'ab#123', 'PlayerName', 'Player#12', 'Player#123456', 'Player Name#1234', 'Player#12 3'])
def test_riot_id_validation_rejects_invalid_format(value):
    with pytest.raises(ValueError):
        validate_riot_id(value)


def test_registration_lifecycle(tmp_path):
    async def scenario():
        db = RegistrationDatabase(str(tmp_path / 'test.sqlite3'))
        await db.initialize()
        assert await db.submit(10, 20, 'PlayerName#1234') == 'submitted'
        assert await db.submit(10, 20, 'OtherName#1234') == 'already_pending'
        row = await db.get(10, 20)
        assert row['status'] == 'pending'
        assert row['riot_id'] == 'PlayerName#1234'
        assert len(await db.pending(10)) == 1
        assert await db.review(10, 20, 99, 'approved') == 'updated'
        assert await db.review(10, 20, 99, 'rejected') == 'not_pending'
        assert (await db.get(10, 20))['status'] == 'approved'
        assert await db.submit(10, 20, 'Changed#1234') == 'already_approved'
        assert await db.submit(11, 20, 'Changed#1234') == 'submitted'
        assert await db.review(11, 20, 99, 'rejected', 'Please check your Riot ID') == 'updated'
        assert await db.submit(11, 20, 'Corrected#1234') == 'submitted'
        assert (await db.get(11, 20))['status'] == 'pending'
    asyncio.run(scenario())
