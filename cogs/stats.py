from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from utils import (
    _guild_lists, _store, _safe_delete_after,
    _get_tz_name, _format_countdown, _is_locked,
    SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR, EMPTY_COLOR,
    AUTO_DELETE_AFTER, SLOW_DELETE,
)


class StatsCog(commands.Cog, name="Stats"):
    def __init__(self, bot):
        self.bot = bot

    # ── .stats ───────────────────────────────────────────────────────────────

    @commands.command(name="stats")
    async def stats(self, ctx):
        """Show a summary of this server's movie data and settings."""
        gid, movie_list, watched_list = _guild_lists(ctx)
        entry   = _store.get(gid, {})
        tz_name = _get_tz_name(gid)

        # Movie night countdown
        ts = entry.get("movie_night")
        if ts:
            dt        = datetime.fromtimestamp(int(ts), ZoneInfo(tz_name))
            night_val = f"{dt.strftime('%a %d %b • %H:%M')} ({tz_name})\n{_format_countdown(dt, tz_name)}"
        else:
            night_val = "Not scheduled"

        # Channel
        channel_id = entry.get("movie_night_channel_id")
        channel    = self.bot.get_channel(channel_id)
        chan_val   = channel.mention if channel else "Not set"

        locked        = entry.get("locked", False)
        prefix        = entry.get("prefix", ".")
        auto_del      = entry.get("auto_delete_enabled", True)
        blocked_count = len(entry.get("blocked_users", []))

        embed = discord.Embed(title="📊 Server Stats", color=INFO_COLOR)
        embed.add_field(name="🎬 Watchlist",    value=f"{len(movie_list)} movies",  inline=True)
        embed.add_field(name="✅ Watched",       value=f"{len(watched_list)} movies", inline=True)
        embed.add_field(name="🍿 Movie Night",   value=night_val,                    inline=False)
        embed.add_field(name="📺 Night Channel", value=chan_val,                     inline=True)
        embed.add_field(name="🕐 Timezone",      value=tz_name,                      inline=True)
        embed.add_field(name="🔒 List Locked",   value="Yes" if locked else "No",    inline=True)
        embed.add_field(name="⌨️ Prefix",        value=f"`{prefix}`",                inline=True)
        embed.add_field(name="🗑️ Auto-Delete",  value="On" if auto_del else "Off",  inline=True)
        embed.add_field(name="🚫 Blocked Users", value=str(blocked_count),           inline=True)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

    # ── .dupes ───────────────────────────────────────────────────────────────

    @commands.command(name="dupes")
    async def dupes(self, ctx):
        """Scan the watchlist for duplicate entries."""
        _, movie_list, _ = _guild_lists(ctx)
        if not movie_list:
            embed = discord.Embed(title="Watchlist Empty 📭", color=EMPTY_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        seen: dict[str, list[int]] = {}
        for i, title in enumerate(movie_list, start=1):
            key = title.strip().lower()
            seen.setdefault(key, []).append(i)

        dupes = {t: positions for t, positions in seen.items() if len(positions) > 1}

        if not dupes:
            embed = discord.Embed(
                title="No Duplicates Found ✅",
                description="Your watchlist is clean!",
                color=SUCCESS_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        lines = []
        for key, positions in dupes.items():
            # Show the actual title as stored (first occurrence)
            display = movie_list[positions[0] - 1]
            pos_str = ", ".join(f"#{p}" for p in positions)
            lines.append(f"**{display}** — appears at {pos_str}")

        description = "\n".join(lines)
        if len(description) > 3900:
            description = description[:3900] + "\n..."

        embed = discord.Embed(
            title=f"⚠️ {len(dupes)} Duplicate{'s' if len(dupes) != 1 else ''} Found",
            description=description,
            color=ERROR_COLOR,
        )
        embed.set_footer(text="Use .remove to clean them up.")
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))


async def setup(bot):
    await bot.add_cog(StatsCog(bot))
