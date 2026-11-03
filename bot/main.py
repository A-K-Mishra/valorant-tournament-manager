from __future__ import annotations

import asyncio
import logging
import discord
from discord.ext import commands
from bot.config import Settings
from bot.database import RegistrationDatabase


class TournamentManagerBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.registration_db = RegistrationDatabase(settings.database_path)
        self._role_sync_task: asyncio.Task | None = None
        self._role_sync_lock = asyncio.Lock()

    async def setup_hook(self) -> None:
        await self.registration_db.initialize()
        await self.load_extension("bot.registration")
        if self.settings.guild_id:
            guild = discord.Object(id=self.settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logging.info("Synced %d application commands to guild %s", len(synced), self.settings.guild_id)
        else:
            synced = await self.tree.sync()
            logging.info("Synced %d global application commands", len(synced))

    async def on_ready(self) -> None:
        logging.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "unknown")
        if self._role_sync_task is None or self._role_sync_task.done():
            self._role_sync_task = asyncio.create_task(self._role_sync_worker())

    async def process_role_sync_jobs(self) -> None:
        # Commands and the periodic worker can trigger this concurrently.
        async with self._role_sync_lock:
            await self._process_role_sync_jobs_locked()

    async def _process_role_sync_jobs_locked(self) -> None:
        jobs = await self.registration_db.pending_role_sync_jobs()
        for job in jobs:
            try:
                guild = self.get_guild(job["guild_id"])
                if guild is None:
                    raise RuntimeError("Bot is not connected to the configured server")
                member = guild.get_member(job["user_id"])
                if member is None:
                    member = await guild.fetch_member(job["user_id"])
                role = guild.get_role(job["role_id"])
                if role is None:
                    raise RuntimeError(f"Role {job['role_id']} no longer exists")
                if job["operation"] == "add":
                    if role not in member.roles:
                        await member.add_roles(role, reason="Tournament registration role synchronization")
                elif role in member.roles:
                    await member.remove_roles(role, reason="Tournament registration role synchronization")
                await self.registration_db.finish_role_sync_job(job["id"])
            except (discord.HTTPException, RuntimeError) as exc:
                await self.registration_db.fail_role_sync_job(job["id"], str(exc))
                logging.warning("Role sync job %s failed: %s", job["id"], exc)

    async def _role_sync_worker(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            await self.process_role_sync_jobs()
            await asyncio.sleep(30)

    async def on_member_join(self, member: discord.Member) -> None:
        # Reconcile a pending registration if a member rejoins after submitting.
        row = await self.registration_db.get(member.guild.id, member.id)
        if not row:
            return
        settings = await self.registration_db.get_guild_settings(member.guild.id)
        desired_role_id = (
            settings["participant_role_id"] if row["status"] == "approved"
            else settings["pending_role_id"] if row["status"] == "pending"
            else None
        )
        configured_ids = {
            settings["participant_role_id"], settings["pending_role_id"]
        } - {None}
        try:
            for role_id in configured_ids:
                role = member.guild.get_role(role_id)
                if role is None:
                    continue
                should_have = role_id == desired_role_id
                has_role = role in member.roles
                if should_have and not has_role:
                    await member.add_roles(role, reason="Restore tournament registration role")
                elif not should_have and has_role:
                    await member.remove_roles(role, reason="Reconcile tournament registration roles")
        except discord.HTTPException as exc:
            logging.warning("Could not reconcile roles for %s: %s", member.id, exc)


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    TournamentManagerBot(settings).run(settings.discord_bot_token, log_handler=None)


if __name__ == "__main__":
    main()
