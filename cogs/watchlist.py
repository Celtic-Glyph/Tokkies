import io
import random
import asyncio

import discord
from discord.ext import commands
from datetime import datetime
from zoneinfo import ZoneInfo

from utils import (
    _guild_lists, _store, _save_store, _safe_delete_after,
    _find_title_index_insensitive, _confirm, search_movie,
    _get_tz_name, _format_countdown, _is_locked, _make_footer,
    SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR, EMPTY_COLOR, WARNING_COLOR,
    AUTO_DELETE_AFTER, SLOW_DELETE, FAST_DELETE,
)


# ── Custom check: block modifications when list is locked ────────────────────
def require_unlocked():
    async def predicate(ctx):
        if ctx.guild is None:
            return True
        gid = str(ctx.guild.id)
        if _is_locked(gid) and not ctx.author.guild_permissions.administrator:
            embed = discord.Embed(
                title="🔒 Watchlist Locked",
                description="The watchlist is locked. Only admins can modify it.",
                color=ERROR_COLOR,
            )
            await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, FAST_DELETE))
            return False
        return True
    return commands.check(predicate)


class WatchlistCog(commands.Cog, name="Watchlist"):
    def __init__(self, bot):
        self.bot = bot

    # ── helb ────────────────────────────────────────────────────────────────

    @commands.command(name="help")
    async def help_command(self, ctx):
        p = _store.get(str(ctx.guild.id) if ctx.guild else f"dm_{ctx.author.id}", {}).get("prefix", ".")
        embed = discord.Embed(title="🎬 Tokkies — All Commands", color=INFO_COLOR)
        embed.add_field(name="📌 Watchlist", value="\n".join([
            f"`{p}add <title>` – Add a movie",
            f"`{p}remove <title>` – Remove a movie",
            f"`{p}list` – Show watchlist",
            f"`{p}move <from> <to>` – Reorder by position",
            f"`{p}rename <old> | <new>` – Rename a movie",
            f"`{p}clearlist` – Clear the watchlist",
            f"`{p}export` – Download watchlist as .txt",
        ]), inline=False)
        embed.add_field(name="🎬 Discovery", value="\n".join([
            f"`{p}search <title>` – Look up a movie on TMDB",
            f"`{p}info <#/title>` – Full details for a watchlist movie",
            f"`{p}poster <#/title>` – Show movie poster",
            f"`{p}random` – Pick a random movie",
            f"`{p}top` – Rank watchlist by TMDB rating",
            f"`{p}suggest` – Get a popular movie suggestion",
            f"`{p}poll Movie1 | Movie2 | ...` – Vote on tonight's movie",
        ]), inline=False)
        embed.add_field(name="✅ Watched", value="\n".join([
            f"`{p}watched <title>` – Mark as watched",
            f"`{p}watchedlist` – Show watched movies",
            f"`{p}unwatch <title>` – Remove from watched",
            f"`{p}clearwatched` – Clear watched list",
        ]), inline=False)
        embed.add_field(name="📊 Stats", value="\n".join([
            f"`{p}stats` – Server summary",
            f"`{p}dupes` – Find duplicate entries",
        ]), inline=False)
        embed.add_field(name="🍿 Movie Night", value="\n".join([
            f"`{p}set time <weekday> <day> <time>` – Schedule movie night",
            f"`{p}set channel #channel` – Set reminder channel",
            f"`{p}set tz <timezone>` – Set timezone",
            f"`{p}night` – Show next movie night",
            f"`{p}cancelnight` – Cancel movie night",
        ]), inline=False)
        embed.add_field(name="⚙️ Admin", value="\n".join([
            f"`{p}lock` / `{p}unlock` – Lock watchlist to admins",
            f"`{p}setprefix <prefix>` – Change command prefix",
            f"`{p}purge <n>` – Delete bot's last N messages",
            f"`{p}announce <msg>` – Post to movie night channel",
            f"`{p}backup` – DM you a JSON backup",
            f"`{p}reset` – Wipe all server data",
            f"`{p}block <@user>` / `{p}unblock <@user>` – Block/unblock a user",
            f"`{p}import` – Bulk-add movies from a .txt attachment",
            f"`{p}autodelete on/off/status` – Toggle auto-delete",
        ]), inline=False)
        embed.set_footer(text="Admin commands require Administrator permission.")
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

    # ── Core list commands ───────────────────────────────────────────────────

    @commands.command(name="add")
    @require_unlocked()
    async def add_movie(self, ctx, *, title: str):
        gid, movie_list, _ = _guild_lists(ctx)
        movie_list.append(title)
        _save_store()
        embed = discord.Embed(
            title="Movie Added! 🎬",
            description=f"**{title}** added to the watchlist.",
            color=SUCCESS_COLOR,
        )
        embed.add_field(name="Position", value=f"#{len(movie_list)}", inline=True)
        embed.set_footer(text=_make_footer(ctx))
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="remove")
    @require_unlocked()
    async def remove_movie(self, ctx, *, title: str):
        gid, movie_list, _ = _guild_lists(ctx)
        title = title.strip()
        if not title:
            embed = discord.Embed(title="Missing Title ⚠️", description="Usage: `.remove <movie title>`", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        idx = _find_title_index_insensitive(movie_list, title)
        if idx is not None:
            removed = movie_list.pop(idx)
            _save_store()
            embed = discord.Embed(title="Movie Removed 🗑️", description=f"**{removed}** removed from watchlist.", color=SUCCESS_COLOR)
        else:
            embed = discord.Embed(title="Not Found ❌", description=f"**{title}** is not in your watchlist.", color=ERROR_COLOR)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="list")
    async def show_list(self, ctx):
        _, movie_list, _ = _guild_lists(ctx)
        if not movie_list:
            embed = discord.Embed(title="Watchlist is Empty 📭", description="Add some with `.add <title>`", color=EMPTY_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        formatted = "\n".join(f"{i+1}. {t}" for i, t in enumerate(movie_list))
        if len(formatted) > 3900:
            formatted = formatted[:3900] + "\n... (list too long)"

        embed = discord.Embed(title="🎬 Your Watchlist", description=formatted, color=INFO_COLOR)
        embed.set_footer(text=_make_footer(ctx, f"Total: {len(movie_list)} movies"))
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="move")
    @require_unlocked()
    async def move_movie(self, ctx, from_pos: int, to_pos: int):
        gid, movie_list, _ = _guild_lists(ctx)
        n = len(movie_list)
        if n == 0:
            embed = discord.Embed(title="Watchlist Empty 📭", color=EMPTY_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))
        if not (1 <= from_pos <= n and 1 <= to_pos <= n):
            embed = discord.Embed(
                title="Invalid Position ⚠️",
                description=f"Positions must be between 1 and {n}.\nExample: `.move 3 1`",
                color=ERROR_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))
        if from_pos == to_pos:
            embed = discord.Embed(title="Already There 🤔", description="That movie is already in that position.", color=INFO_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        title = movie_list.pop(from_pos - 1)
        movie_list.insert(to_pos - 1, title)
        _save_store()
        embed = discord.Embed(
            title="✅ Moved!",
            description=f"**{title}** moved from #{from_pos} to #{to_pos}.",
            color=SUCCESS_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="rename")
    @require_unlocked()
    async def rename_movie(self, ctx, *, args: str):
        if " | " not in args:
            embed = discord.Embed(
                title="Usage ⚠️",
                description="Separate old and new title with ` | `\nExample: `.rename Old Title | New Title`",
                color=ERROR_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        old_title, new_title = [p.strip() for p in args.split(" | ", 1)]
        gid, movie_list, _ = _guild_lists(ctx)
        idx = _find_title_index_insensitive(movie_list, old_title)
        if idx is None:
            embed = discord.Embed(title="Not Found ❌", description=f"**{old_title}** is not in your watchlist.", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        movie_list[idx] = new_title
        _save_store()
        embed = discord.Embed(
            title="✏️ Renamed!",
            description=f"**{old_title}** → **{new_title}**",
            color=SUCCESS_COLOR,
        )
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="clearlist")
    @require_unlocked()
    async def clear_list(self, ctx):
        gid, movie_list, _ = _guild_lists(ctx)
        if not movie_list:
            embed = discord.Embed(title="Nothing to Clear 🧹", description="Your watchlist is already empty.", color=EMPTY_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        confirmed = await _confirm(ctx, f"⚠️ Clear all {len(movie_list)} movies from your watchlist?")
        if not confirmed:
            embed = discord.Embed(title="Cancelled ❌", description="Watchlist was not cleared.", color=INFO_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, FAST_DELETE))

        _store[gid]["movie_list"] = []
        _save_store()
        embed = discord.Embed(title="🗑️ Movie list cleared!", color=SUCCESS_COLOR)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="export")
    async def export_list(self, ctx):
        _, movie_list, _ = _guild_lists(ctx)
        if not movie_list:
            embed = discord.Embed(title="Nothing to Export 📭", description="Your watchlist is empty.", color=EMPTY_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        content = "\n".join(f"{i+1}. {t}" for i, t in enumerate(movie_list))
        file    = discord.File(io.BytesIO(content.encode("utf-8")), filename="watchlist.txt")
        embed   = discord.Embed(
            title="📄 Watchlist Exported",
            description=f"{len(movie_list)} movies — open the file below.",
            color=SUCCESS_COLOR,
        )
        await ctx.send(embed=embed, file=file, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

    # ── Poster + Random (TMDB) ───────────────────────────────────────────────

    @commands.command(name="poster")
    async def poster(self, ctx, *, query: str):
        _, movie_list, _ = _guild_lists(ctx)
        if not movie_list:
            embed = discord.Embed(title="Watchlist Empty 📭", color=EMPTY_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        query = query.strip()
        if query.isdigit():
            index = int(query)
            if not (1 <= index <= len(movie_list)):
                embed = discord.Embed(title="Invalid Number ⚠️", color=ERROR_COLOR)
                return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))
            title = movie_list[index - 1]
        else:
            q         = query.lower()
            match_idx = next((i for i, t in enumerate(movie_list) if t.strip().lower() == q), None)
            if match_idx is None:
                match_idx = next((i for i, t in enumerate(movie_list) if q in t.strip().lower()), None)
            if match_idx is None:
                embed = discord.Embed(title="Movie Not Found ❌", description=f"Couldn't find **{query}** in your watchlist.", color=ERROR_COLOR)
                return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))
            title = movie_list[match_idx]
            index = match_idx + 1

        movie = await search_movie(title)
        if isinstance(movie, dict) and movie.get("__error__"):
            embed = discord.Embed(title="TMDB Error ⚠️", description=movie["__error__"], color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))
        if not movie or not movie.get("poster_path"):
            embed = discord.Embed(title=f"No Poster Found for **{title}**", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        embed = discord.Embed(title=title, color=INFO_COLOR)
        embed.set_image(url=f"https://image.tmdb.org/t/p/w500{movie['poster_path']}")
        embed.set_footer(text=_make_footer(ctx, f"#{index} • Powered by TMDB"))
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="random")
    async def random_movie(self, ctx):
        gid, movie_list, _ = _guild_lists(ctx)
        if not movie_list:
            embed = discord.Embed(title="Watchlist Empty 📭", color=EMPTY_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        loading_embed = discord.Embed(title="🎲 Random Pick", description="Loading........ ⏳", color=INFO_COLOR)
        loading_embed.set_footer(text="Picking a movie for you...")
        loading_msg = await ctx.send(embed=loading_embed)
        await asyncio.sleep(2)
        try:
            await loading_msg.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        title = random.choice(movie_list)
        movie = await search_movie(title)

        result_embed = discord.Embed(title="🎬 Random Movie Picked!", description=f"**{title}**", color=SUCCESS_COLOR)
        if movie and not (isinstance(movie, dict) and movie.get("__error__")):
            overview = (movie.get("overview") or "").strip()
            release  = movie.get("release_date") or "Unknown"
            rating   = movie.get("vote_average")
            votes    = movie.get("vote_count")
            if overview:
                result_embed.add_field(name="📝 Overview", value=overview[:800] + ("…" if len(overview) > 800 else ""), inline=False)
            result_embed.add_field(name="📅 Release", value=release, inline=True)
            if rating is not None:
                result_embed.add_field(name="⭐ Rating", value=f"{rating}/10 ({votes} votes)", inline=True)
            if movie.get("poster_path"):
                result_embed.set_image(url=f"https://image.tmdb.org/t/p/w500{movie['poster_path']}")
        else:
            result_embed.add_field(name="Info", value="Couldn't fetch TMDB info this time 😅", inline=False)

        ts      = _store[gid].get("movie_night")
        tz_name = _get_tz_name(gid)
        if ts:
            dt = datetime.fromtimestamp(int(ts), ZoneInfo(tz_name))
            result_embed.add_field(
                name="🍿 Next Movie Night",
                value=f"{dt.strftime('%a %d %b • %H:%M')} ({tz_name})\n**{_format_countdown(dt, tz_name)}**",
                inline=False,
            )
        result_embed.set_footer(text=_make_footer(ctx, "Powered by TMDB"))
        await ctx.send(embed=result_embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))


async def setup(bot):
    await bot.add_cog(WatchlistCog(bot))
