# Bot setup (local development)

## Requirements
- Python 3.11 or newer
- A Discord application with a bot user
- The bot invited with the `bot` and `applications.commands` scopes

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Set `DISCORD_BOT_TOKEN` in `.env`. Never commit `.env` or paste your token into chat. Regenerate it immediately if exposed.

## Discord permissions and role hierarchy

Grant the bot **Manage Roles**. Move the bot's own role above the `Pending` and `Participant` roles. Do not grant Administrator. The bot can only assign roles below its highest role.

The server owner or a member with Manage Server/Administrator can configure the bot. Additional admin roles can be configured with `/config admin-role-add`.

## Configure the server

Create two Discord roles named `Pending` and `Participant`. Names are conventions; the bot stores the selected role IDs.

Use these slash commands:
- `/config pending-role role:@Pending`
- `/config participant-role role:@Participant`
- `/config show`
- `/config admin-role-add role:@TournamentAdmin`
- `/config admin-role-remove role:@TournamentAdmin`

Guild settings are stored in SQLite, not in `.env`. `.env` is reserved for secrets and infrastructure settings.

## Registration workflow

- `/registration register riot_id:GameName#TagLine` — submit a Riot ID; the bot queues assignment of Pending.
- `/registration status` — check status.
- `/registration pending` — admin-only review queue.
- `/registration approve member:@player` — approve; Pending is removed and Participant is assigned.
- `/registration reject member:@player note:...` — reject; Pending is removed.

Role changes use a SQLite outbox (`role_sync_jobs`). If Discord is temporarily unavailable or permissions prevent a change, the job is retained and retried by the background worker. Completed operations are idempotent. The bot also restores the appropriate role when a registered member rejoins.

## Data and limitations

SQLite is created automatically at `data/valorant_manager.sqlite3`. It stores registrations, per-guild settings, admin-role mappings, and role-sync jobs. Back up this file when deploying. Use persistent disk storage if hosting outside your Mac.

Riot ID validation checks format only; it does not verify ownership through Riot's API. Admins must validate submissions manually. Never request a Riot or Discord password.
