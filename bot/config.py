from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()

def _optional_int(name: str) -> int | None:
    value = os.getenv(name, '').strip()
    if not value: return None
    try: return int(value)
    except ValueError as exc: raise ValueError(f'{name} must be an integer Discord ID') from exc

@dataclass(frozen=True, slots=True)
class Settings:
    discord_bot_token: str
    database_path: str = 'data/valorant_manager.sqlite3'
    guild_id: int | None = None
    participant_role_id: int | None = None
    admin_role_ids: tuple[int, ...] = ()
    log_level: str = 'INFO'

    @classmethod
    def from_env(cls) -> 'Settings':
        token = os.getenv('DISCORD_BOT_TOKEN', '').strip()
        if not token:
            raise RuntimeError('DISCORD_BOT_TOKEN is missing. Copy .env.example to .env and add your bot token locally.')
        raw_roles = os.getenv('ADMIN_ROLE_IDS', '').strip()
        try: admin_roles = tuple(int(item.strip()) for item in raw_roles.split(',') if item.strip())
        except ValueError as exc: raise ValueError('ADMIN_ROLE_IDS must be comma-separated Discord role IDs') from exc
        return cls(token, os.getenv('DATABASE_PATH', 'data/valorant_manager.sqlite3'), _optional_int('DISCORD_GUILD_ID'), _optional_int('PARTICIPANT_ROLE_ID'), admin_roles, os.getenv('LOG_LEVEL', 'INFO').upper())
