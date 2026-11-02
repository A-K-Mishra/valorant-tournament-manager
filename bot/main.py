from __future__ import annotations
import logging
import discord
from discord.ext import commands
from bot.config import Settings
from bot.database import RegistrationDatabase

class TournamentManagerBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        super().__init__(command_prefix='!', intents=discord.Intents.default())
        self.settings = settings
        self.registration_db = RegistrationDatabase(settings.database_path)

    async def setup_hook(self) -> None:
        await self.registration_db.initialize()
        await self.load_extension('bot.registration')
        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logging.info('Synced %d application commands to guild %s', len(synced), self.settings.guild_id)
        else:
            synced = await self.tree.sync()
            logging.info('Synced %d global application commands', len(synced))

    async def on_ready(self) -> None:
        logging.info('Logged in as %s (ID: %s)', self.user, self.user.id if self.user else 'unknown')

def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO), format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    TournamentManagerBot(settings).run(settings.discord_bot_token, log_handler=None)

if __name__ == '__main__': main()
