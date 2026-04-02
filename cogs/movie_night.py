from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from utils import (
    _guild_lists, _store, _save_store, _safe_delete_after,
    _get_tz_name, _set_tz_name, _next_datetime_for, _format_countdown,
    SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR, EMPTY_COLOR,
    AUTO_DELETE_AFTER, SLOW_DELETE,
)


class MovieNightCog(commands.Cog, name="Movie Night"):
    def __init__(self, bot):
        self.bot = bot
        self.movie_night_checker.start()

    def cog_unload(self):
        self.movie_night_checker.cancel()

    # ── Background task ──────────────────────────────────────────────────────

    @tasks.loop(seconds=20)
    async def movie_night_checker(self):
        try:
            now_utc = datetime.now(ZoneInfo("UTC")).timestamp()
        except Exception:
            now_utc = datetime.utcnow().timestamp()

        for gid, entry in list(_store.items()):
            ts = entry.get("movie_night")
            if not ts:
                continue

            if now_utc >= float(ts):
                channel_id = entry.get("movie_night_channel_id")
                channel    = self.bot.get_channel(channel_id) if channel_id else None

                embed = discord.Embed(
                    title="🍿 Movie Night Time!",
                    description="It's time! Start the movie night 🎬",
                    color=SUCCESS_COLOR,
                )
                if channel:
                    try:
                        await channel.send(embed=embed)
                    except Exception:
                        pass

                entry["movie_night"] = None
                _save_store()

    # ── .set group ───────────────────────────────────────────────────────────

    @commands.group(name="set", invoke_without_command=True)
    async def set_group(self, ctx):
        embed = discord.Embed(
            title="Set Commands ⚙️",
            description=(
                "Use:\n`.set time <weekday> <day> <time>`\n"
                "Example: `.set time tuesday 27 8pm`\n\n"
                "Optional:\n`.set channel #channel`\n`.set tz Europe/Berlin`"
            ),
            color=INFO_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @set_group.command(name="time")
    async def set_time(self, ctx, weekday: str, day: int, time: str):
        gid, _, _ = _guild_lists(ctx)
        tz_name   = _get_tz_name(gid)

        try:
            dt = _next_datetime_for(weekday, day, time, tz_name)
        except Exception as e:
            embed = discord.Embed(
                title="Invalid Time/Date ⚠️",
                description=f"Example: `.set time tuesday 27 8pm`\n\nError: `{e}`",
                color=ERROR_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        channel_id = _store[gid].get("movie_night_channel_id") or ctx.channel.id
        _store[gid]["movie_night"]            = int(dt.timestamp())
        _store[gid]["movie_night_channel_id"] = channel_id
        _save_store()

        embed = discord.Embed(
            title="🎟️ Movie Night Scheduled!",
            description=(
                f"**When:** {dt.strftime('%a %d %b %Y • %H:%M')} ({tz_name})\n"
                f"**Countdown:** {_format_countdown(dt, tz_name)}"
            ),
            color=SUCCESS_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

    @set_group.command(name="channel")
    async def set_channel(self, ctx, channel: discord.TextChannel):
        gid, _, _ = _guild_lists(ctx)
        _store[gid]["movie_night_channel_id"] = channel.id
        _save_store()
        embed = discord.Embed(
            title="✅ Movie Night Channel Set",
            description=f"Reminders will be posted in {channel.mention}",
            color=SUCCESS_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @set_group.command(name="tz")
    async def set_tz(self, ctx, *, tz_name: str):
        gid, _, _ = _guild_lists(ctx)
        try:
            ZoneInfo(tz_name)
        except Exception:
            embed = discord.Embed(
                title="Invalid Timezone ⚠️",
                description="Example: `.set tz Europe/Berlin` or `.set tz UTC`",
                color=ERROR_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        _set_tz_name(gid, tz_name)
        embed = discord.Embed(
            title="✅ Timezone Set",
            description=f"Timezone is now **{tz_name}**",
            color=SUCCESS_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    # ── Standalone movie night commands ──────────────────────────────────────

    @commands.command(name="night")
    async def night(self, ctx):
        gid, _, _ = _guild_lists(ctx)
        ts        = _store[gid].get("movie_night")
        tz_name   = _get_tz_name(gid)

        if not ts:
            embed = discord.Embed(
                title="No Movie Night Scheduled 📭",
                description="Set one with `.set time tuesday 27 8pm`",
                color=EMPTY_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        dt    = datetime.fromtimestamp(int(ts), ZoneInfo(tz_name))
        embed = discord.Embed(
            title="🎬 Next Movie Night",
            description=(
                f"**When:** {dt.strftime('%a %d %b %Y • %H:%M')} ({tz_name})\n"
                f"**Countdown:** {_format_countdown(dt, tz_name)}"
            ),
            color=INFO_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

    @commands.command(name="cancelnight")
    async def cancel_night(self, ctx):
        gid, _, _ = _guild_lists(ctx)
        _store[gid]["movie_night"] = None
        _save_store()
        embed = discord.Embed(title="🗑️ Movie night cancelled!", color=SUCCESS_COLOR)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))


async def setup(bot):
    await bot.add_cog(MovieNightCog(bot))
