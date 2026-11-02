# Bot setup (local development)

## Requirements
- Python 3.11 or newer
- A Discord application with a bot user
- The bot invited with the applications.commands and bot scopes

## Install
From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit .env locally and set DISCORD_BOT_TOKEN. Never commit .env or paste the token into chat. Regenerate it in the Discord Developer Portal immediately if exposed.

## Configure roles
- DISCORD_GUILD_ID: optional; set your server ID for fast command sync during development. Leave blank for global command sync.
- PARTICIPANT_ROLE_ID: optional role assigned after approval.
- ADMIN_ROLE_IDS: optional comma-separated admin role IDs. Members with Manage Server or Administrator are also authorised.

If role assignment is enabled, give the bot Manage Roles and move its bot role above the Participant role. Do not grant Administrator.

## Run

```bash
python -m bot
```

SQLite is created automatically at data/valorant_manager.sqlite3 and is ignored by Git.

## Slash commands
- /registration register riot_id:GameName#TagLine — submit a Riot ID privately.
- /registration status — check your status.
- /registration pending — admin-only pending queue.
- /registration approve member:@player — approve a pending registration.
- /registration reject member:@player note:... — reject with an optional note.

Riot ID format is checked locally only; there is no Riot API or ownership verification. Admins must validate submissions manually. Never request a Riot or Discord password.

## Current limitations
- One registration per Discord member per server.
- Rejected members may submit again; approved members must ask an admin to correct their Riot ID.
- Reviews are stored in SQLite. Dedicated audit-channel logging is planned for a later iteration.
- Back up the SQLite database when deploying to a VPS.
