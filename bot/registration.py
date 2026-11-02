from __future__ import annotations

import re
import discord
from discord import app_commands
from discord.ext import commands

_RIOT_ID_RE = re.compile(r"^[^#\s]{3,16}#[A-Za-z0-9]{3,5}$")


def validate_riot_id(value: str) -> str:
    normalized = value.strip()
    if not _RIOT_ID_RE.fullmatch(normalized):
        raise ValueError("Use GameName#TagLine format (game name 3–16 characters; tag 3–5 letters/numbers).")
    return normalized


def _is_admin(interaction: discord.Interaction, configured_role_ids: tuple[int, ...]) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    permissions = interaction.user.guild_permissions
    return (
        permissions.administrator
        or permissions.manage_guild
        or any(role.id in configured_role_ids for role in interaction.user.roles)
    )


class Registration(commands.GroupCog, group_name="registration", group_description="Player registration and admin review"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _is_configured_admin(self, interaction: discord.Interaction) -> bool:
        role_ids = await self.bot.registration_db.get_admin_role_ids(interaction.guild_id)
        return _is_admin(interaction, role_ids + self.bot.settings.admin_role_ids)

    @app_commands.command(name="register", description="Submit your Riot ID for community approval")
    @app_commands.guild_only()
    async def register(self, interaction: discord.Interaction, riot_id: str) -> None:
        try:
            riot_id = validate_riot_id(riot_id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        result = await self.bot.registration_db.submit(interaction.guild_id, interaction.user.id, riot_id)
        messages = {
            "submitted": f"Your Riot ID **{discord.utils.escape_markdown(riot_id)}** was submitted. Registration is **pending admin approval**.",
            "already_pending": "You already have a registration awaiting review. Please wait for an admin.",
            "already_approved": "You are already an approved participant. Ask an admin if your Riot ID needs changing.",
        }
        await interaction.response.send_message(messages[result], ephemeral=True)
        if result == "submitted":
            await self.bot.process_role_sync_jobs()

    @app_commands.command(name="status", description="Check your participant registration status")
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        row = await self.bot.registration_db.get(interaction.guild_id, interaction.user.id)
        if not row:
            message = "You are not registered yet. Use /registration register to submit your Riot ID."
        else:
            message = (
                f"Registration status: **{row['status']}**\n"
                f"Riot ID: **{discord.utils.escape_markdown(row['riot_id'])}**"
            )
            if row["review_note"]:
                message += f"\nAdmin note: {discord.utils.escape_markdown(row['review_note'])}"
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="pending", description="List registrations awaiting approval")
    @app_commands.guild_only()
    async def pending(self, interaction: discord.Interaction) -> None:
        if not await self._is_configured_admin(interaction):
            await interaction.response.send_message(
                "You need Manage Server, Administrator, or a configured admin role.", ephemeral=True
            )
            return
        rows = await self.bot.registration_db.pending(interaction.guild_id)
        if not rows:
            await interaction.response.send_message("There are no pending registrations.", ephemeral=True)
            return
        lines = [
            f"• <@{row['user_id']}> — **{discord.utils.escape_markdown(row['riot_id'])}** "
            f"(submitted {row['submitted_at']} UTC)"
            for row in rows
        ]
        await interaction.response.send_message(
            "**Pending registrations**\n" + "\n".join(lines),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _review(
        self, interaction: discord.Interaction, member: discord.Member,
        decision: str, note: str | None,
    ) -> None:
        if not await self._is_configured_admin(interaction):
            await interaction.response.send_message(
                "You need Manage Server, Administrator, or a configured admin role.", ephemeral=True
            )
            return
        result = await self.bot.registration_db.review(
            interaction.guild_id, member.id, interaction.user.id, decision, note
        )
        if result == "not_pending":
            await interaction.response.send_message("That member has no pending registration.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Registration for {member.mention} **{decision}**. Role updates have been queued.",
            ephemeral=True,
        )
        await self.bot.process_role_sync_jobs()
        try:
            await member.send(
                f"Your aBlitz's Challenges registration has been **{decision}**."
                + (f" Admin note: {note}" if note else "")
            )
        except discord.Forbidden:
            pass

    @app_commands.command(name="approve", description="Approve a member's pending registration")
    @app_commands.guild_only()
    async def approve(
        self, interaction: discord.Interaction, member: discord.Member, note: str | None = None
    ) -> None:
        await self._review(interaction, member, "approved", note)

    @app_commands.command(name="reject", description="Reject a member's pending registration")
    @app_commands.guild_only()
    async def reject(
        self, interaction: discord.Interaction, member: discord.Member, note: str | None = None
    ) -> None:
        await self._review(interaction, member, "rejected", note)


class Configuration(commands.GroupCog, group_name="config", group_description="Configure this Discord server"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        role_ids = await self.bot.registration_db.get_admin_role_ids(interaction.guild_id)
        allowed = _is_admin(interaction, role_ids + self.bot.settings.admin_role_ids)
        if not allowed:
            await interaction.response.send_message(
                "You need Manage Server, Administrator, or a configured admin role.", ephemeral=True
            )
        return allowed

    @app_commands.command(name="show", description="Show this server's bot configuration")
    @app_commands.guild_only()
    async def show(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        settings = await self.bot.registration_db.get_guild_settings(interaction.guild_id)
        admin_roles = await self.bot.registration_db.get_admin_role_ids(interaction.guild_id)
        def mention(role_id: int | None) -> str:
            return f"<@&{role_id}>" if role_id else "Not configured"
        await interaction.response.send_message(
            f"**Server configuration**\n"
            f"Participant role: {mention(settings['participant_role_id'])}\n"
            f"Pending role: {mention(settings['pending_role_id'])}\n"
            f"Admin roles: {', '.join(mention(role_id) for role_id in admin_roles) or 'None'}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _set_role(
        self, interaction: discord.Interaction, role: discord.Role, setting: str, label: str
    ) -> None:
        if not await self._require_admin(interaction):
            return
        if role.is_default() or role.managed:
            await interaction.response.send_message(
                "Choose a normal server role; @everyone and integration-managed roles cannot be used.",
                ephemeral=True,
            )
            return
        guild = interaction.guild
        bot_member = guild.me if guild else None
        if bot_member is None:
            await interaction.response.send_message(
                "I couldn't resolve my server membership. Please try again shortly.", ephemeral=True
            )
            return
        if not bot_member.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "I need the Manage Roles permission before a registration role can be configured.",
                ephemeral=True,
            )
            return
        if role >= bot_member.top_role:
            await interaction.response.send_message(
                "That role is at or above my highest role. Move my bot role above it in Server Settings → Roles.",
                ephemeral=True,
            )
            return
        settings = await self.bot.registration_db.get_guild_settings(interaction.guild_id)
        other_setting = (
            "pending_role_id" if setting == "participant_role_id" else "participant_role_id"
        )
        if settings[other_setting] == role.id:
            await interaction.response.send_message(
                "Pending and Participant must be different roles.", ephemeral=True
            )
            return
        await self.bot.registration_db.set_registration_role_and_reconcile(
            interaction.guild_id, setting, role.id
        )
        await interaction.response.send_message(
            f"{label} set to {role.mention}. Existing registrations are being reconciled.",
            ephemeral=True,
        )
        await self.bot.process_role_sync_jobs()


    @app_commands.command(name="role-sync-status", description="Show queued and failed registration role updates")
    @app_commands.guild_only()
    async def role_sync_status(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        summary = await self.bot.registration_db.role_sync_summary(interaction.guild_id)
        lines = [
            "**Registration role sync**",
            f"Ready to process: **{summary['pending']}**",
            f"Waiting for retry: **{summary['waiting']}**",
            f"Stopped after 8 failures: **{summary['exhausted']}**",
        ]
        for job in summary["recent"]:
            error = discord.utils.escape_markdown(job["last_error"] or "Unknown error")
            lines.append(
                f"• <@{job['user_id']}> / <@&{job['role_id']}> ({job['operation']}, "
                f"{job['attempts']} attempts): {error[:180]}"
            )
        await interaction.response.send_message(
            "\n".join(lines), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="role-sync-retry", description="Retry failed registration role updates")
    @app_commands.guild_only()
    async def role_sync_retry(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        count = await self.bot.registration_db.retry_failed_role_sync_jobs(interaction.guild_id)
        await interaction.response.send_message(
            f"Reset **{count}** failed role update(s). Processing them now.", ephemeral=True
        )
        await self.bot.process_role_sync_jobs()

    @app_commands.command(name="participant-role", description="Set the role given to approved players")
    @app_commands.guild_only()
    async def participant_role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await self._set_role(interaction, role, "participant_role_id", "Participant role")

    @app_commands.command(name="pending-role", description="Set the role given to applicants awaiting review")
    @app_commands.guild_only()
    async def pending_role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await self._set_role(interaction, role, "pending_role_id", "Pending role")

    @app_commands.command(name="admin-role-add", description="Allow a role to administer tournament registrations")
    @app_commands.guild_only()
    async def admin_role_add(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if not await self._require_admin(interaction):
            return
        await self.bot.registration_db.add_admin_role(interaction.guild_id, role.id, interaction.user.id)
        await interaction.response.send_message(f"{role.mention} can now administer tournament registrations.", ephemeral=True)

    @app_commands.command(name="admin-role-remove", description="Remove a role's tournament admin access")
    @app_commands.guild_only()
    async def admin_role_remove(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if not await self._require_admin(interaction):
            return
        removed = await self.bot.registration_db.remove_admin_role(interaction.guild_id, role.id)
        message = "Admin role removed." if removed else "That role was not configured."
        await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Registration(bot))
    await bot.add_cog(Configuration(bot))
