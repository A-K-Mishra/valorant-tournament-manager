# VALORANT Tournament Manager

A Discord bot and lightweight competition-management system for **aBlitz's Challenges**.

The project is intended to support:
- Individual VALORANT achievement challenges (for example, Aces, 4Ks and clutch wins).
- Community tournaments, including organised 5v5 events.
- Participant registration and manual admin approval.
- Evidence submissions with manual review.
- Leaderboards, tournament results and an auditable reward ledger.

## Project status

Initial repository scaffold. Bot functionality has not been implemented yet.

## Planned structure

```text
.
├── bot/
│   └── .gitkeep
├── docs/
│   ├── index.md
│   ├── terms.md
│   └── privacy.md
├── .gitignore
├── requirements.txt
└── README.md
```

## Planned technology

- Python 3.11+
- discord.py (Discord interactions and commands)
- SQLite (initial persistence layer)
- APScheduler (scheduled event tasks)

## Local setup

1. Install Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install dependencies with `pip install -r requirements.txt`.
4. Configure the Discord bot token as an environment variable named `DISCORD_BOT_TOKEN` when the bot implementation is added.

**Never commit bot tokens, API keys, passwords, or other secrets.** Do not share your Discord bot token in chat or in source control.

## Documentation

- [Community site](docs/index.md)
- [Terms of Service](docs/terms.md)
- [Privacy Policy](docs/privacy.md)

## Disclaimer

This is an independent community project. It is not affiliated with, endorsed by, or sponsored by Riot Games or Discord. VALORANT and Riot Games are trademarks or registered trademarks of Riot Games, Inc.
