# VALORANT Tournament Manager

A Discord bot and lightweight competition-management system for **aBlitz's Challenges**.

## Current status

The first bot MVP foundation and participant registration workflow are implemented.

- Discord slash-command bot using discord.py
- SQLite persistence for registrations
- Private player registration and status commands
- Admin pending queue, approval and rejection
- Optional Participant role assignment after approval
- Environment-based configuration; secrets stay out of source control

## Repository layout

- bot/ — Python bot application and registration workflow
- docs/ — GitHub Pages community site, Terms and Privacy
- .env.example — safe configuration template (no real credentials)

## Local development

Use Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit .env locally and set DISCORD_BOT_TOKEN. Optionally configure DISCORD_GUILD_ID, PARTICIPANT_ROLE_ID and ADMIN_ROLE_IDS. Then run:

```bash
python -m bot
```

Full instructions and command details: [Bot setup](bot/README.md).

**Never commit .env, bot tokens, API keys or passwords.** If a token is exposed, regenerate it in the Discord Developer Portal.

## Registration commands

- /registration register — submit Riot ID in GameName#TagLine format
- /registration status — check registration status
- /registration pending — admin-only pending queue
- /registration approve — approve a pending member
- /registration reject — reject a pending member

Riot ID validation is format-only. There is no Riot API integration or account-ownership verification yet; an admin must review registrations manually.

## Next milestones

1. Challenge creation, claims and evidence review
2. Leaderboards and event history
3. 5v5 tournament registration, teams and brackets
4. Audit-channel logging and deployment automation

## Disclaimer

This is an independent community project. It is not affiliated with, endorsed by, or sponsored by Riot Games or Discord. VALORANT and Riot Games are trademarks or registered trademarks of Riot Games, Inc.
