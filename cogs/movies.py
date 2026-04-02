import random
import asyncio

import discord
from discord.ext import commands

from utils import (
    _guild_lists, _store, _save_store, _safe_delete_after,
    _find_title_index_insensitive, _is_locked, _make_footer,
    search_movie, get_movie_details, get_popular_movies,
    SUCCESS_COLOR, ERROR_COLOR, INFO_COLOR, EMPTY_COLOR, WARNING_COLOR,
    AUTO_DELETE_AFTER, SLOW_DELETE, FAST_DELETE,
)

POLL_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
POLL_DURATION = 60  # seconds


class MoviesCog(commands.Cog, name="Movies"):
    def __init__(self, bot):
        self.bot = bot

    # ── .search — TMDB lookup without adding ────────────────────────────────

    @commands.command(name="search")
    async def search(self, ctx, *, title: str):
        """Look up a movie on TMDB. React ✅ to add it to your watchlist."""
        gid, movie_list, _ = _guild_lists(ctx)

        loading = await ctx.send(embed=discord.Embed(description=f"🔍 Searching for **{title}**...", color=INFO_COLOR))
        movie   = await search_movie(title)
        try:
            await loading.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        if not movie or (isinstance(movie, dict) and movie.get("__error__")):
            err = movie.get("__error__", "No results found.") if isinstance(movie, dict) else "No results found."
            embed = discord.Embed(title="Not Found ❌", description=err, color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        # Fetch full details for runtime/genres
        details = await get_movie_details(movie["id"]) if movie.get("id") else None

        embed = _build_movie_embed(movie, details, color=INFO_COLOR)
        already_in = _find_title_index_insensitive(movie_list, movie.get("title", title)) is not None
        locked     = _is_locked(gid) and not ctx.author.guild_permissions.administrator

        if already_in:
            embed.set_footer(text="Already in your watchlist ✅")
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

        if locked:
            embed.set_footer(text="🔒 Watchlist is locked — you can't add movies right now.")
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

        embed.set_footer(text="React ✅ within 30s to add this to your watchlist, or ❌ to dismiss.")
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ("✅", "❌") and reaction.message.id == msg.id

        try:
            reaction, _ = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
            if str(reaction.emoji) == "✅":
                movie_list.append(movie["title"])
                _save_store()
                done_embed = discord.Embed(
                    title="Added! 🎬",
                    description=f"**{movie['title']}** added to your watchlist at #{len(movie_list)}.",
                    color=SUCCESS_COLOR,
                )
                await msg.edit(embed=done_embed)
            else:
                await msg.delete()
                return
        except asyncio.TimeoutError:
            pass

        try:
            await msg.clear_reactions()
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ── .info — full TMDB details for a watchlist movie ─────────────────────

    @commands.command(name="info")
    async def info(self, ctx, *, query: str):
        """Show full TMDB details for a movie in your watchlist (by # or title)."""
        _, movie_list, _ = _guild_lists(ctx)
        if not movie_list:
            embed = discord.Embed(title="Watchlist Empty 📭", color=EMPTY_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        query = query.strip()
        if query.isdigit():
            index = int(query)
            if not (1 <= index <= len(movie_list)):
                embed = discord.Embed(title="Invalid Number ⚠️", description=f"Pick a number between 1 and {len(movie_list)}.", color=ERROR_COLOR)
                return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))
            title = movie_list[index - 1]
        else:
            q         = query.lower()
            match_idx = next((i for i, t in enumerate(movie_list) if t.strip().lower() == q), None)
            if match_idx is None:
                match_idx = next((i for i, t in enumerate(movie_list) if q in t.strip().lower()), None)
            if match_idx is None:
                embed = discord.Embed(title="Not Found ❌", description=f"**{query}** isn't in your watchlist. Use `.list` to check.", color=ERROR_COLOR)
                return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))
            title = movie_list[match_idx]
            index = match_idx + 1

        loading = await ctx.send(embed=discord.Embed(description=f"🔍 Fetching info for **{title}**...", color=INFO_COLOR))
        movie   = await search_movie(title)
        details = await get_movie_details(movie["id"]) if movie and movie.get("id") else None
        try:
            await loading.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        if not movie or (isinstance(movie, dict) and movie.get("__error__")):
            embed = discord.Embed(title="TMDB Error ⚠️", description="Couldn't fetch info for this movie.", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        embed = _build_movie_embed(movie, details, color=INFO_COLOR)
        embed.set_footer(text=_make_footer(ctx, f"#{index} on your watchlist • Powered by TMDB"))
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

    # ── .top — rank watchlist by TMDB rating ────────────────────────────────

    @commands.command(name="top")
    async def top(self, ctx):
        """Sort your watchlist by TMDB rating (top 15)."""
        gid, movie_list, _ = _guild_lists(ctx)
        if not movie_list:
            embed = discord.Embed(title="Watchlist Empty 📭", color=EMPTY_COLOR)
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        sample  = movie_list[:20]
        loading = await ctx.send(embed=discord.Embed(description=f"⭐ Fetching ratings for {len(sample)} movies...", color=INFO_COLOR))

        results = await asyncio.gather(*[search_movie(t) for t in sample])

        rated = []
        for title, movie in zip(sample, results):
            if movie and not (isinstance(movie, dict) and movie.get("__error__")):
                rating = movie.get("vote_average") or 0.0
                votes  = movie.get("vote_count") or 0
            else:
                rating, votes = 0.0, 0
            rated.append((title, rating, votes))

        rated.sort(key=lambda x: x[1], reverse=True)

        try:
            await loading.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (title, rating, votes) in enumerate(rated[:15]):
            prefix = medals[i] if i < 3 else f"`{i+1}.`"
            star   = f"⭐ {rating:.1f}" if rating else "⭐ N/A"
            lines.append(f"{prefix} **{title}** — {star}")

        embed = discord.Embed(
            title="⭐ Watchlist Ranked by TMDB Rating",
            description="\n".join(lines),
            color=INFO_COLOR,
        )
        if len(movie_list) > 20:
            embed.set_footer(text=_make_footer(ctx, f"Showing top {min(15, len(sample))} of first 20 • Powered by TMDB"))
        else:
            embed.set_footer(text=_make_footer(ctx, "Powered by TMDB"))
        await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

    # ── .suggest — random popular movie not in watchlist ────────────────────

    @commands.command(name="suggest")
    async def suggest(self, ctx):
        """Get a random popular TMDB movie not already in your watchlist."""
        gid, movie_list, _ = _guild_lists(ctx)
        locked = _is_locked(gid) and not ctx.author.guild_permissions.administrator

        loading = await ctx.send(embed=discord.Embed(description="🎲 Finding a suggestion for you...", color=INFO_COLOR))

        watchlist_lower = {t.strip().lower() for t in movie_list}
        pages   = random.sample(range(1, 6), 3)
        all_movies = []
        for page in pages:
            all_movies.extend(await get_popular_movies(page))

        available = [m for m in all_movies if m.get("title", "").lower() not in watchlist_lower]

        try:
            await loading.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

        if not available:
            embed = discord.Embed(
                title="Nothing New 🤷",
                description="All the popular movies are already in your watchlist! You're set.",
                color=INFO_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        pick    = random.choice(available)
        details = await get_movie_details(pick["id"]) if pick.get("id") else None
        embed   = _build_movie_embed(pick, details, color=SUCCESS_COLOR)

        if locked:
            embed.set_footer(text="🔒 Watchlist is locked — you can't add movies right now.")
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, SLOW_DELETE))

        embed.set_footer(text="React ✅ within 30s to add this to your watchlist, or ❌ to skip.")
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in ("✅", "❌") and reaction.message.id == msg.id

        try:
            reaction, _ = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
            if str(reaction.emoji) == "✅":
                movie_list.append(pick["title"])
                _save_store()
                done_embed = discord.Embed(
                    title="Added! 🎬",
                    description=f"**{pick['title']}** added to your watchlist at #{len(movie_list)}.",
                    color=SUCCESS_COLOR,
                )
                await msg.edit(embed=done_embed)
            else:
                await msg.delete()
                return
        except asyncio.TimeoutError:
            pass

        try:
            await msg.clear_reactions()
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ── .poll — reaction vote on which movie to watch ───────────────────────

    @commands.command(name="poll")
    async def poll(self, ctx, *, args: str):
        """Vote on tonight's movie. Separate options with |  (2–5 options, 60s poll)."""
        options = [o.strip() for o in args.split("|") if o.strip()]
        if not (2 <= len(options) <= 5):
            embed = discord.Embed(
                title="Usage ⚠️",
                description="Provide 2–5 movies separated by `|`\nExample: `.poll Inception | The Matrix | Interstellar`",
                color=ERROR_COLOR,
            )
            return await ctx.send(embed=embed, delete_after=_safe_delete_after(ctx, AUTO_DELETE_AFTER))

        lines = "\n".join(f"{POLL_EMOJIS[i]}  **{opt}**" for i, opt in enumerate(options))
        embed = discord.Embed(
            title="🗳️ Movie Night Poll",
            description=f"Vote for tonight's pick! Poll closes in **{POLL_DURATION}s**.\n\n{lines}",
            color=INFO_COLOR,
        )
        embed.set_footer(text="React with the number for your choice!")
        msg = await ctx.send(embed=embed)
        for i in range(len(options)):
            await msg.add_reaction(POLL_EMOJIS[i])

        await asyncio.sleep(POLL_DURATION)

        try:
            msg = await ctx.channel.fetch_message(msg.id)
        except (discord.NotFound, discord.HTTPException):
            return

        votes = []
        for i, opt in enumerate(options):
            reaction = discord.utils.get(msg.reactions, emoji=POLL_EMOJIS[i])
            count    = max((reaction.count - 1), 0) if reaction else 0  # subtract bot's own
            votes.append((opt, count))

        winner     = max(votes, key=lambda x: x[1])
        result_lines = "\n".join(
            f"{'🏆' if opt == winner[0] else POLL_EMOJIS[i]}  **{opt}** — {cnt} vote{'s' if cnt != 1 else ''}"
            for i, (opt, cnt) in enumerate(votes)
        )
        result_embed = discord.Embed(
            title=f"🏆 Poll Closed — {winner[0]} wins!",
            description=result_lines,
            color=SUCCESS_COLOR,
        )
        result_embed.set_footer(text=f"Winner: {winner[0]} with {winner[1]} vote{'s' if winner[1] != 1 else ''}!")
        await msg.edit(embed=result_embed)
        try:
            await msg.clear_reactions()
        except (discord.Forbidden, discord.HTTPException):
            pass


# ── Shared embed builder ─────────────────────────────────────────────────────

def _build_movie_embed(movie: dict, details: dict | None, *, color) -> discord.Embed:
    title    = movie.get("title", "Unknown")
    overview = (movie.get("overview") or "").strip()
    release  = movie.get("release_date") or "Unknown"
    rating   = movie.get("vote_average")
    votes    = movie.get("vote_count")

    embed = discord.Embed(title=title, color=color)
    if overview:
        embed.description = overview[:500] + ("…" if len(overview) > 500 else "")

    embed.add_field(name="📅 Release", value=release, inline=True)
    if rating is not None:
        embed.add_field(name="⭐ Rating", value=f"{rating:.1f}/10 ({votes:,} votes)", inline=True)

    if details:
        runtime = details.get("runtime")
        if runtime:
            embed.add_field(name="⏱️ Runtime", value=f"{runtime} min", inline=True)
        genres = ", ".join(g["name"] for g in details.get("genres", []))
        if genres:
            embed.add_field(name="🎭 Genres", value=genres, inline=False)

    if movie.get("poster_path"):
        embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w500{movie['poster_path']}")

    return embed


async def setup(bot):
    await bot.add_cog(MoviesCog(bot))
