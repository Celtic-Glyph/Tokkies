import discord
from discord.ext import commands

from utils import (
    _guild_lists, _store, _normalize_entry, _save_store, _safe_delete_after,
    _get_auto_delete_enabled, _set_auto_delete_enabled,
    SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR,
    AUTO_DELETE_AFTER, SLOW_DELETE,
)


class SettingsCog(commands.Cog, name="Settings"):
    def __init__(self, bot):
        self.bot = bot

    # ── .autodelete group ────────────────────────────────────────────────────

    @commands.group(name="autodelete", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def autodelete_group(self, ctx):
        gid, _, _ = _guild_lists(ctx)
        enabled   = _get_auto_delete_enabled(gid)
        embed = discord.Embed(
            title="Auto-Delete Settings",
            description=(
                f"Current server: **{'Enabled' if enabled else 'Disabled'}**\n\n"
                "Commands:\n"
                "`.autodelete on`\n"
                "`.autodelete off`\n"
                "`.autodelete status`\n"
                "`.autodelete set <guild_id> on`\n"
                "`.autodelete set <guild_id> off`"
            ),
            color=INFO_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

    @autodelete_group.command(name="status")
    @commands.has_permissions(administrator=True)
    async def autodelete_status(self, ctx):
        gid, _, _ = _guild_lists(ctx)
        enabled   = _get_auto_delete_enabled(gid)
        embed = discord.Embed(
            title="Auto-Delete Status",
            description=f"Auto-delete is currently **{'enabled' if enabled else 'disabled'}** for this server.",
            color=INFO_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @autodelete_group.command(name="on")
    @commands.has_permissions(administrator=True)
    async def autodelete_on(self, ctx):
        gid, _, _ = _guild_lists(ctx)
        _set_auto_delete_enabled(gid, True)
        embed = discord.Embed(
            title="✅ Auto-Delete Enabled",
            description="Auto-delete is now enabled for this server.",
            color=SUCCESS_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @autodelete_group.command(name="off")
    @commands.has_permissions(administrator=True)
    async def autodelete_off(self, ctx):
        gid, _, _ = _guild_lists(ctx)
        _set_auto_delete_enabled(gid, False)
        embed = discord.Embed(
            title="🛑 Auto-Delete Disabled",
            description="Auto-delete is now disabled for this server.",
            color=SUCCESS_COLOR,
        )
        await ctx.send(embed=embed)

    @autodelete_group.command(name="set")
    @commands.is_owner()
    async def autodelete_set(self, ctx, guild_id: int, state: str):
        state = state.lower().strip()
        if state not in ("on", "off"):
            embed = discord.Embed(
                title="Invalid State ⚠️",
                description="Use `on` or `off`.\nExample: `.autodelete set 123456789012345678 off`",
                color=ERROR_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            embed = discord.Embed(
                title="Guild Not Found ❌",
                description="The bot is not in that server, or the guild ID is invalid.",
                color=ERROR_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        gid = str(guild_id)
        if gid not in _store:
            _store[gid] = _normalize_entry({})

        _set_auto_delete_enabled(gid, state == "on")
        embed = discord.Embed(
            title="✅ Auto-Delete Updated",
            description=f"Auto-delete is now **{state}** for **{guild.name}** (`{guild_id}`).",
            color=SUCCESS_COLOR,
        )
        if state == "off":
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @autodelete_group.error
    async def autodelete_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            embed = discord.Embed(
                title="Permission Denied 🚫",
                description="You need **Administrator** permission to use this command.",
                color=ERROR_COLOR,
            )
            await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))
        elif isinstance(error, commands.NotOwner):
            embed = discord.Embed(
                title="Owner Only 🚫",
                description="Only the bot owner can change another server's auto-delete setting.",
                color=ERROR_COLOR,
            )
            await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))


async def setup(bot):
    await bot.add_cog(SettingsCog(bot))
