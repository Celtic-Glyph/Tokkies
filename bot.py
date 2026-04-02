import os
import asyncio

from dotenv import load_dotenv
import discord
from discord.ext import commands

from utils import (
    _load_store, _store, _normalize_entry,
    _guild_lists, _get_auto_delete_enabled, _is_blocked,
    INFO_COLOR, _make_footer,
)

# ────────────────────────────────────────────────
# Load secrets
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# ────────────────────────────────────────────────
# Dynamic prefix (per-guild, falls back to ".")
def get_prefix(bot, message):
    if message.guild:
        gid    = str(message.guild.id)
        prefix = _store.get(gid, {}).get("prefix", ".")
    else:
        prefix = "."
    return commands.when_mentioned_or(prefix)(bot, message)

# ────────────────────────────────────────────────
# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=get_prefix, intents=intents, help_command=None)

# Cogs to load
COGS = [
    "cogs.watchlist",
    "cogs.watched",
    "cogs.movie_night",
    "cogs.settings",
    "cogs.movies",
    "cogs.stats",
    "cogs.admin",
]

# ========== Hooks ==========

@bot.before_invoke
async def before_any_command(ctx):
    # Delete the command message first — before anything else can interrupt
    try:
        await ctx.message.delete()
    except Exception:
        pass

    # Block check
    if _is_blocked(ctx):
        raise commands.CheckFailure("blocked")

# ========== Events ==========

@bot.event
async def on_ready():
    _load_store()
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user in message.mentions:
        gid = str(message.guild.id) if message.guild else f"dm_{message.author.id}"
        if gid not in _store:
            _store[gid] = _normalize_entry({})

        prefix             = _store.get(gid, {}).get("prefix", ".")
        delete_after_value = 50 if _get_auto_delete_enabled(gid) else None

        embed = discord.Embed(
            title="🎬 Tokkies",
            description=(
                f"Hey! 👋 I'm your movie bot. Use `{prefix}help` for the full command list.\n\n"
                "**Quick reference** 👇"
            ),
            color=INFO_COLOR,
        )
        embed.add_field(
            name="📌 Watchlist",
            value=f"`{prefix}add` · `{prefix}remove` · `{prefix}list` · `{prefix}move` · `{prefix}rename` · `{prefix}export`",
            inline=False,
        )
        embed.add_field(
            name="🎬 Discovery",
            value=f"`{prefix}search` · `{prefix}info` · `{prefix}top` · `{prefix}suggest` · `{prefix}poll` · `{prefix}random` · `{prefix}poster`",
            inline=False,
        )
        embed.add_field(
            name="✅ Watched",
            value=f"`{prefix}watched` · `{prefix}watchedlist` · `{prefix}unwatch`",
            inline=False,
        )
        embed.add_field(
            name="📊 Stats",
            value=f"`{prefix}stats` · `{prefix}dupes`",
            inline=False,
        )
        embed.add_field(
            name="🍿 Movie Night",
            value=f"`{prefix}set time` · `{prefix}set channel` · `{prefix}set tz` · `{prefix}night` · `{prefix}cancelnight`",
            inline=False,
        )
        embed.add_field(
            name="⚙️ Admin",
            value=f"`{prefix}lock` · `{prefix}unlock` · `{prefix}setprefix` · `{prefix}purge` · `{prefix}announce` · `{prefix}backup` · `{prefix}reset` · `{prefix}block` · `{prefix}import`",
            inline=False,
        )
        embed.set_footer(text="Tip: Commands may auto-delete depending on server settings ✨")
        await message.channel.send(embed=embed, delete_after=delete_after_value)

    await bot.process_commands(message)

# ========== Entry point ==========

async def main():
    async with bot:
        for cog in COGS:
            await bot.load_extension(cog)
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
