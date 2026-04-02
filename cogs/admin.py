import io
import os
import json
import asyncio
from datetime import datetime

import discord
from discord.ext import commands

from utils import (
    _guild_lists, _store, _normalize_entry, _save_store, _safe_delete_after,
    _find_title_index_insensitive, _confirm, is_owner_or_admin,
    SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR, EMPTY_COLOR, WARNING_COLOR,
    AUTO_DELETE_AFTER, SLOW_DELETE, FAST_DELETE,
)


def _get_target_gid(ctx, guild_id=None):
    """
    Resolve the target guild.
    - If guild_id is provided, caller must be the bot owner.
    - Returns (gid_str, error_str_or_None).
    - Also ensures the guild entry exists in _store.
    """
    try:
        owner_id = int(os.getenv("OWNER_ID", "0") or "0")
    except ValueError:
        owner_id = 0

    if guild_id is not None and ctx.author.id != owner_id:
        return None, "Only the bot owner can target other servers."

    target = guild_id if guild_id is not None else (ctx.guild.id if ctx.guild else None)
    if target is None:
        return None, "Can't determine target server. Provide a guild ID."

    gid = str(target)
    if gid not in _store:
        _store[gid] = _normalize_entry({})
        _save_store()

    return gid, None


class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot):
        self.bot = bot

    # ── .lock / .unlock ──────────────────────────────────────────────────────

    @commands.command(name="lock")
    @is_owner_or_admin()
    async def lock(self, ctx, guild_id: int = None):
        """Lock the watchlist. Owner can pass a guild_id to target another server."""
        gid, err = _get_target_gid(ctx, guild_id)
        if err:
            embed = discord.Embed(title="Error ❌", description=err, color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        if _store[gid].get("locked"):
            embed = discord.Embed(title="Already Locked 🔒", color=INFO_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        _store[gid]["locked"] = True
        _save_store()
        target = f"guild `{guild_id}`" if guild_id else "this server"
        embed = discord.Embed(title="🔒 Watchlist Locked", description=f"Only admins can modify the watchlist for {target}.", color=SUCCESS_COLOR)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="unlock")
    @is_owner_or_admin()
    async def unlock(self, ctx, guild_id: int = None):
        """Unlock the watchlist. Owner can pass a guild_id to target another server."""
        gid, err = _get_target_gid(ctx, guild_id)
        if err:
            embed = discord.Embed(title="Error ❌", description=err, color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        if not _store[gid].get("locked"):
            embed = discord.Embed(title="Already Unlocked 🔓", color=INFO_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        _store[gid]["locked"] = False
        _save_store()
        target = f"guild `{guild_id}`" if guild_id else "this server"
        embed = discord.Embed(title="🔓 Watchlist Unlocked", description=f"Everyone can modify the watchlist for {target}.", color=SUCCESS_COLOR)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    # ── .setprefix ───────────────────────────────────────────────────────────

    @commands.command(name="setprefix")
    @is_owner_or_admin()
    async def setprefix(self, ctx, prefix: str, guild_id: int = None):
        """Change the command prefix. Owner: .setprefix <prefix> [guild_id]"""
        prefix = prefix.strip()
        if not prefix or len(prefix) > 5:
            embed = discord.Embed(title="Invalid Prefix ⚠️", description="Prefix must be 1–5 characters.\nExample: `.setprefix !`", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        gid, err = _get_target_gid(ctx, guild_id)
        if err:
            embed = discord.Embed(title="Error ❌", description=err, color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        _store[gid]["prefix"] = prefix
        _save_store()
        target = f"guild `{guild_id}`" if guild_id else "this server"
        embed = discord.Embed(
            title="✅ Prefix Updated",
            description=f"Prefix for {target} is now `{prefix}`",
            color=SUCCESS_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

    # ── .purge ───────────────────────────────────────────────────────────────

    @commands.command(name="purge")
    @is_owner_or_admin()
    async def purge(self, ctx, amount: int = 10):
        """Delete the bot's last N messages in this channel (max 50)."""
        if not (1 <= amount <= 50):
            embed = discord.Embed(title="Invalid Amount ⚠️", description="Amount must be between 1 and 50.", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        deleted = 0
        async for message in ctx.channel.history(limit=300):
            if message.author == self.bot.user:
                try:
                    await message.delete()
                    deleted += 1
                except (discord.Forbidden, discord.HTTPException):
                    pass
                if deleted >= amount:
                    break

        await ctx.send(
            embed=discord.Embed(title=f"🗑️ Purged {deleted} message{'s' if deleted != 1 else ''}", color=SUCCESS_COLOR),
            delete_after=5,
        )

    # ── .announce ────────────────────────────────────────────────────────────

    @commands.command(name="announce")
    @is_owner_or_admin()
    async def announce(self, ctx, *, args: str):
        """Post to the movie night channel.
        Owner cross-server: .announce <guild_id> <message>
        Normal: .announce <message>
        """
        try:
            owner_id = int(os.getenv("OWNER_ID", "0") or "0")
        except ValueError:
            owner_id = 0

        guild_id = None
        message  = args
        parts    = args.split(None, 1)
        if (
            len(parts) >= 2
            and parts[0].isdigit()
            and len(parts[0]) >= 17
            and ctx.author.id == owner_id
        ):
            guild_id = int(parts[0])
            message  = parts[1]

        gid, err = _get_target_gid(ctx, guild_id)
        if err:
            embed = discord.Embed(title="Error ❌", description=err, color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        channel_id = _store[gid].get("movie_night_channel_id")
        if not channel_id:
            embed = discord.Embed(title="No Channel Set ⚠️", description="Set a movie night channel first with `.set channel #channel`", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        channel = self.bot.get_channel(channel_id)
        if not channel:
            embed = discord.Embed(title="Channel Not Found ❌", description="The saved channel no longer exists.", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        embed = discord.Embed(description=message, color=INFO_COLOR)
        embed.set_footer(text=f"📢 Announced by {ctx.author.display_name}")
        await channel.send(embed=embed)

        target = f"guild `{guild_id}`" if guild_id else channel.mention
        await ctx.send(
            embed=discord.Embed(title="✅ Announced", description=f"Message sent to {target}.", color=SUCCESS_COLOR),
            delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER),
        )

    # ── .backup ──────────────────────────────────────────────────────────────

    @commands.command(name="backup")
    @is_owner_or_admin()
    async def backup(self, ctx, guild_id: int = None):
        """DM a JSON backup. Owner: .backup [guild_id]"""
        gid, err = _get_target_gid(ctx, guild_id)
        if err:
            embed = discord.Embed(title="Error ❌", description=err, color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        data      = _store.get(gid, {})
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        content   = json.dumps(data, ensure_ascii=False, indent=2)
        file      = discord.File(io.BytesIO(content.encode("utf-8")), filename=f"tokkies_backup_{gid}_{timestamp}.json")
        target    = f"guild `{guild_id}`" if guild_id else "this server"

        try:
            await ctx.author.send(content=f"📦 Tokkies backup for {target}:", file=file)
            embed = discord.Embed(title="✅ Backup Sent", description="Check your DMs!", color=SUCCESS_COLOR)
        except discord.Forbidden:
            embed = discord.Embed(title="DMs Closed ❌", description="Enable DMs from server members and try again.", color=ERROR_COLOR)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    # ── .reset ───────────────────────────────────────────────────────────────

    @commands.command(name="reset")
    @is_owner_or_admin()
    async def reset(self, ctx, guild_id: int = None):
        """Wipe all data for this server (or another if owner provides guild_id)."""
        gid, err = _get_target_gid(ctx, guild_id)
        if err:
            embed = discord.Embed(title="Error ❌", description=err, color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        cross_server = guild_id is not None
        target_label = f"guild `{guild_id}`" if cross_server else "this server"

        confirmed = await _confirm(ctx, f"⚠️ Permanently wipe ALL data for {target_label}?")
        if not confirmed:
            embed = discord.Embed(title="Cancelled ❌", color=INFO_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, FAST_DELETE))

        # Local reset requires an extra "type RESET" step; cross-server skips it
        if not cross_server:
            embed = discord.Embed(
                title="Final Confirmation 🛑",
                description="Type `RESET` within **30 seconds** to confirm, or do nothing to cancel.",
                color=WARNING_COLOR,
            )
            await ctx.send(embed=embed)

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel and m.content == "RESET"

            try:
                await self.bot.wait_for("message", timeout=30.0, check=check)
            except asyncio.TimeoutError:
                embed = discord.Embed(title="Timed Out — Reset Cancelled ✅", color=INFO_COLOR)
                return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        _store[gid] = _normalize_entry({})
        _save_store()
        embed = discord.Embed(
            title="💥 Server Data Reset",
            description=f"All data for {target_label} has been wiped.",
            color=ERROR_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

    # ── .block / .unblock ────────────────────────────────────────────────────

    @commands.command(name="block")
    @is_owner_or_admin()
    async def block(self, ctx, target: str, guild_id: int = None):
        """Block a user. Use @mention or user ID. Owner: .block <user_id> <guild_id>"""
        user_id = _parse_user_id(target)
        if user_id is None:
            embed = discord.Embed(title="Invalid User ⚠️", description="Provide a @mention or a numeric user ID.", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        gid, err = _get_target_gid(ctx, guild_id)
        if err:
            embed = discord.Embed(title="Error ❌", description=err, color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        if user_id == ctx.author.id:
            embed = discord.Embed(title="Can't Block Yourself ⚠️", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        blocked = _store[gid].setdefault("blocked_users", [])
        if user_id in blocked:
            embed = discord.Embed(title="Already Blocked ⚠️", description=f"User `{user_id}` is already blocked.", color=INFO_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        blocked.append(user_id)
        _save_store()

        name       = _resolve_display_name(self.bot, user_id, gid)
        guild_name = _resolve_guild_name(self.bot, gid)
        embed = discord.Embed(title="🚫 User Blocked", description=f"**{name}** is blocked from Tokkies in **{guild_name}**.", color=SUCCESS_COLOR)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="unblock")
    @is_owner_or_admin()
    async def unblock(self, ctx, target: str, guild_id: int = None):
        """Unblock a user. Use @mention or user ID. Owner: .unblock <user_id> <guild_id>"""
        user_id = _parse_user_id(target)
        if user_id is None:
            embed = discord.Embed(title="Invalid User ⚠️", description="Provide a @mention or a numeric user ID.", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        gid, err = _get_target_gid(ctx, guild_id)
        if err:
            embed = discord.Embed(title="Error ❌", description=err, color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        blocked = _store[gid].get("blocked_users", [])
        if user_id not in blocked:
            embed = discord.Embed(title="Not Blocked ⚠️", description=f"User `{user_id}` isn't blocked.", color=INFO_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        blocked.remove(user_id)
        _save_store()

        name       = _resolve_display_name(self.bot, user_id, gid)
        guild_name = _resolve_guild_name(self.bot, gid)
        embed = discord.Embed(title="✅ User Unblocked", description=f"**{name}** can use Tokkies again in **{guild_name}**.", color=SUCCESS_COLOR)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    # ── .import ──────────────────────────────────────────────────────────────

    @commands.command(name="import")
    @is_owner_or_admin()
    async def import_list(self, ctx, guild_id: int = None):
        """Bulk-add movies from an attached .txt file. Owner: .import [guild_id]"""
        if not ctx.message.attachments:
            embed = discord.Embed(title="No Attachment ⚠️", description="Attach a `.txt` file with one movie title per line.", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        attachment = ctx.message.attachments[0]
        if not attachment.filename.lower().endswith(".txt"):
            embed = discord.Embed(title="Wrong File Type ⚠️", description="Please attach a `.txt` file.", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        gid, err = _get_target_gid(ctx, guild_id)
        if err:
            embed = discord.Embed(title="Error ❌", description=err, color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        try:
            raw   = await attachment.read()
            lines = raw.decode("utf-8", errors="ignore").splitlines()
        except Exception as e:
            embed = discord.Embed(title="Read Error ❌", description=f"Couldn't read the file: {e}", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        titles = [ln.strip() for ln in lines if ln.strip()]
        cleaned = []
        for t in titles:
            if t[0].isdigit() and ". " in t:
                t = t.split(". ", 1)[1].strip()
            cleaned.append(t)

        if not cleaned:
            embed = discord.Embed(title="Empty File ⚠️", description="The file had no valid titles.", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        movie_list = _store[gid]["movie_list"]
        added, skipped = [], []
        for title in cleaned:
            if _find_title_index_insensitive(movie_list, title) is None:
                movie_list.append(title)
                added.append(title)
            else:
                skipped.append(title)
        _save_store()

        target = f"guild `{guild_id}`" if guild_id else "this server"
        embed  = discord.Embed(title=f"📥 Import Complete — {target}", color=SUCCESS_COLOR)
        embed.add_field(name="✅ Added",    value=str(len(added)),      inline=True)
        embed.add_field(name="⏭️ Skipped", value=str(len(skipped)),    inline=True)
        embed.add_field(name="📋 Total",   value=str(len(movie_list)), inline=True)
        if skipped:
            skip_str = ", ".join(f"**{t}**" for t in skipped[:10])
            if len(skipped) > 10:
                skip_str += f" and {len(skipped) - 10} more"
            embed.add_field(name="Already in list", value=skip_str, inline=False)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

    # ── Error handler ────────────────────────────────────────────────────────

    @lock.error
    @unlock.error
    @setprefix.error
    @purge.error
    @announce.error
    @backup.error
    @reset.error
    @block.error
    @unblock.error
    @import_list.error
    async def admin_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            msg = "You need **Administrator** permission to use this command."
        elif isinstance(error, commands.NotOwner):
            msg = "Only the bot owner can use this command."
        elif isinstance(error, commands.CheckFailure):
            msg = "You need **Administrator** permission or be the bot owner to use this command."
        elif isinstance(error, commands.MemberNotFound):
            msg = "Couldn't find that user."
        elif isinstance(error, commands.BadArgument):
            msg = f"Invalid argument: {error}"
        else:
            return  # Let it bubble up
        embed = discord.Embed(title="Permission Denied 🚫", description=msg, color=ERROR_COLOR)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_user_id(target: str):
    """Parse a @mention or raw integer string into a user ID int."""
    cleaned = target.strip("<@!>")
    try:
        return int(cleaned)
    except ValueError:
        return None


def _resolve_display_name(bot, user_id: int, gid: str) -> str:
    guild = bot.get_guild(int(gid)) if gid.isdigit() else None
    if guild:
        member = guild.get_member(user_id)
        if member:
            return member.display_name
    return f"User {user_id}"


def _resolve_guild_name(bot, gid: str) -> str:
    if gid.isdigit():
        guild = bot.get_guild(int(gid))
        if guild:
            return guild.name
    return f"Guild {gid}"


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
