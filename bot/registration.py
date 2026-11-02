from __future__ import annotations
import re
import discord
from discord import app_commands
from discord.ext import commands

_RIOT_ID_RE = re.compile(r'^[^#\\s]{3,16}#[A-Za-z0-9]{3,5}$')

def validate_riot_id(value: str) -> str:
    normalized = value.strip()
    if not _RIOT_ID_RE.fullmatch(normalized):
        raise ValueError('Use GameName#TagLine format (game name 3–16 characters; tag 3–5 letters/numbers).')
    return normalized

class Registration(commands.GroupCog, group_name='registration', group_description='Player registration and admin review'):
    def __init__(self, bot: commands.Bot) -> None: self.bot = bot

    @staticmethod
    def _is_admin(interaction: discord.Interaction, role_ids: tuple[int, ...]) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member): return False
        perms = interaction.user.guild_permissions
        return perms.administrator or perms.manage_guild or any(r.id in role_ids for r in interaction.user.roles)

    @app_commands.command(name='register', description='Submit your Riot ID for community approval')
    @app_commands.guild_only()
    async def register(self, interaction: discord.Interaction, riot_id: str) -> None:
        try: riot_id = validate_riot_id(riot_id)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True); return
        result = await self.bot.registration_db.submit(interaction.guild_id, interaction.user.id, riot_id)
        messages = {
            'submitted': f'Your Riot ID **{discord.utils.escape_markdown(riot_id)}** was submitted. Registration is **pending admin approval**.',
            'already_pending': 'You already have a registration awaiting review. Please wait for an admin.',
            'already_approved': 'You are already an approved participant. Ask an admin if your Riot ID needs changing.'}
        await interaction.response.send_message(messages[result], ephemeral=True)

    @app_commands.command(name='status', description='Check your participant registration status')
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        row = await self.bot.registration_db.get(interaction.guild_id, interaction.user.id)
        if not row: message = 'You are not registered yet. Use /registration register to submit your Riot ID.'
        else:
            message = f"Registration status: **{row['status']}**\nRiot ID: **{discord.utils.escape_markdown(row['riot_id'])}**"
            if row['review_note']: message += f"\nAdmin note: {discord.utils.escape_markdown(row['review_note'])}"
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name='pending', description='List registrations awaiting approval')
    @app_commands.guild_only()
    async def pending(self, interaction: discord.Interaction) -> None:
        if not self._is_admin(interaction, self.bot.settings.admin_role_ids):
            await interaction.response.send_message('You need Manage Server, Administrator, or an approved admin role.', ephemeral=True); return
        rows = await self.bot.registration_db.pending(interaction.guild_id)
        if not rows: await interaction.response.send_message('There are no pending registrations.', ephemeral=True); return
        lines = [f"• <@{r['user_id']}> — **{discord.utils.escape_markdown(r['riot_id'])}** (submitted {r['submitted_at']} UTC)" for r in rows]
        await interaction.response.send_message('**Pending registrations**\n' + '\n'.join(lines), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def _review(self, interaction: discord.Interaction, member: discord.Member, decision: str, note: str | None) -> None:
        if not self._is_admin(interaction, self.bot.settings.admin_role_ids):
            await interaction.response.send_message('You need Manage Server, Administrator, or an approved admin role.', ephemeral=True); return
        result = await self.bot.registration_db.review(interaction.guild_id, member.id, interaction.user.id, decision, note)
        if result == 'not_pending': await interaction.response.send_message('That member has no pending registration.', ephemeral=True); return
        suffix = ''
        if decision == 'approved' and self.bot.settings.participant_role_id:
            role = interaction.guild.get_role(self.bot.settings.participant_role_id)
            if role is None: suffix = ' Configured Participant role was not found; check PARTICIPANT_ROLE_ID.'
            else:
                try: await member.add_roles(role, reason=f'Registration approved by {interaction.user}')
                except discord.Forbidden: suffix = " I couldn't assign the Participant role; check Manage Roles and role hierarchy."
        await interaction.response.send_message(f'Registration for {member.mention} **{decision}**.{suffix}', ephemeral=True)
        try: await member.send(f"Your aBlitz's Challenges registration has been **{decision}**." + (f' Admin note: {note}' if note else ''))
        except discord.Forbidden: pass

    @app_commands.command(name='approve', description="Approve a member's pending registration")
    @app_commands.guild_only()
    async def approve(self, interaction: discord.Interaction, member: discord.Member, note: str | None = None) -> None:
        await self._review(interaction, member, 'approved', note)

    @app_commands.command(name='reject', description="Reject a member's pending registration")
    @app_commands.guild_only()
    async def reject(self, interaction: discord.Interaction, member: discord.Member, note: str | None = None) -> None:
        await self._review(interaction, member, 'rejected', note)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Registration(bot))
