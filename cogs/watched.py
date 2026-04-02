import discord
from discord.ext import commands

from utils import (
    _guild_lists, _store, _save_store, _safe_delete_after,
    _find_title_index_insensitive, _confirm, _make_footer,
    SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR, EMPTY_COLOR,
    AUTO_DELETE_AFTER, FAST_DELETE,
)


class WatchedCog(commands.Cog, name="Watched"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="watched")
    async def watched(self, ctx, *, title: str):
        gid, movie_list, watched_list = _guild_lists(ctx)
        title = title.strip()
        if not title:
            embed = discord.Embed(
                title="Missing Title ⚠️",
                description="Usage: `.watched <movie title>`",
                color=ERROR_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        removed_from_watchlist = False
        title_to_add           = title

        idx = _find_title_index_insensitive(movie_list, title)
        if idx is not None:
            title_to_add           = movie_list.pop(idx)
            removed_from_watchlist = True

        if _find_title_index_insensitive(watched_list, title_to_add) is None:
            watched_list.append(title_to_add)
            _save_store()
            embed = discord.Embed(
                title="Marked as Watched ✅",
                description=f"**{title_to_add}** added to your **Watched Movies List**.",
                color=SUCCESS_COLOR,
            )
            if removed_from_watchlist:
                embed.add_field(name="Watchlist", value="Removed from watchlist.", inline=False)
            embed.set_footer(text=_make_footer(ctx))
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        embed = discord.Embed(
            title="Already Watched 🎞️",
            description=f"**{title_to_add}** is already in your watched list.",
            color=INFO_COLOR,
        )
        embed.set_footer(text=_make_footer(ctx))
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="watchedlist")
    async def watchedlist(self, ctx):
        _, _, watched_list = _guild_lists(ctx)
        if not watched_list:
            embed = discord.Embed(
                title="Watched List is Empty 📭",
                description="Mark movies as watched with `.watched <title>`",
                color=EMPTY_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        formatted = "\n".join(f"{i+1}. {t}" for i, t in enumerate(watched_list))
        if len(formatted) > 3900:
            formatted = formatted[:3900] + "\n... (list too long)"

        embed = discord.Embed(title="✅ Watched Movies List", description=formatted, color=INFO_COLOR)
        embed.set_footer(text=_make_footer(ctx, f"Total: {len(watched_list)} movies"))
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="unwatch")
    async def unwatch(self, ctx, *, title: str):
        gid, _, watched_list = _guild_lists(ctx)
        title = title.strip()
        if not title:
            embed = discord.Embed(
                title="Missing Title ⚠️",
                description="Usage: `.unwatch <movie title>`",
                color=ERROR_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        idx = _find_title_index_insensitive(watched_list, title)
        if idx is None:
            embed = discord.Embed(
                title="Not Found ❌",
                description=f"**{title}** is not in your watched list.",
                color=ERROR_COLOR,
            )
            embed.set_footer(text="This message will auto-delete soon")
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        removed = watched_list.pop(idx)
        _save_store()
        embed = discord.Embed(
            title="↩️ Removed from Watched",
            description=f"**{removed}** removed from your **Watched Movies List**.",
            color=SUCCESS_COLOR,
        )
        embed.set_footer(text=_make_footer(ctx))
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

    @commands.command(name="clearwatched")
    async def clearwatched(self, ctx):
        gid, _, watched_list = _guild_lists(ctx)
        if not watched_list:
            embed = discord.Embed(
                title="Nothing to Clear 🧹",
                description="Your watched list is already empty.",
                color=EMPTY_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        confirmed = await _confirm(ctx, f"⚠️ Clear all {len(watched_list)} movies from your watched list?")
        if not confirmed:
            embed = discord.Embed(title="Cancelled ❌", description="Watched list was not cleared.", color=INFO_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, FAST_DELETE))

        _store[gid]["watched_list"] = []
        _save_store()
        embed = discord.Embed(title="🗑️ Watched list cleared!", color=SUCCESS_COLOR)
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))


async def setup(bot):
    await bot.add_cog(WatchedCog(bot))
