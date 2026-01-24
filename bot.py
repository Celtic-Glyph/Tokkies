import os
import json
import random
import requests
import asyncio
import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks

# ────────────────────────────────────────────────
# Load secrets
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

# Intents
intents = discord.Intents.default()
intents.message_content = True

# Bot setup
bot = commands.Bot(command_prefix=".", intents=intents)

# Auto-delete user's command message
@bot.before_invoke
async def delete_command(ctx):
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

# ────────────────────────────────────────────────
# Colors
SUCCESS_COLOR = discord.Color.blurple()
ERROR_COLOR   = discord.Color.red()
INFO_COLOR    = discord.Color.blue()
WARNING_COLOR = discord.Color.orange()
EMPTY_COLOR   = discord.Color.dark_grey()

# Auto-delete time (seconds)
AUTO_DELETE_AFTER = 20
SLOW_DELETE = 50
FAST_DELETE = 10

# ========== Persistent store (per-guild) ==========

DATA_FILE = "movie_data.json"
_store = {}   # {"guild_id_str": {"movie_list": [], "watched_list": [], "movie_night": None, "movie_night_channel_id": None, "timezone": "UTC"}}
_legacy = None

DEFAULT_TZ = "UTC"

def _save_store():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(_store, f, ensure_ascii=False, indent=2)

def _normalize_entry(entry: dict) -> dict:
    """Ensure new keys always exist."""
    entry.setdefault("movie_list", [])
    entry.setdefault("watched_list", [])
    entry.setdefault("movie_night", None)  # unix ts int or None
    entry.setdefault("movie_night_channel_id", None)
    entry.setdefault("timezone", DEFAULT_TZ)
    return entry

def _load_store():
    global _store, _legacy
    if not os.path.exists(DATA_FILE):
        _store = {}
        _legacy = None
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Per-guild dict format
        if isinstance(data, dict) and any(str(k).isdigit() for k in data.keys()):
            _store = {}
            for k, v in data.items():
                if not isinstance(v, dict):
                    v = {}
                _store[str(k)] = _normalize_entry({
                    "movie_list": v.get("movie_list", []),
                    "watched_list": v.get("watched_list", []),
                    "movie_night": v.get("movie_night"),
                    "movie_night_channel_id": v.get("movie_night_channel_id"),
                    "timezone": v.get("timezone", DEFAULT_TZ),
                })
            _legacy = None
            return

        # Legacy list format
        if isinstance(data, list):
            _store = {}
            _legacy = {"movie_list": data, "watched_list": [], "movie_night": None, "movie_night_channel_id": None, "timezone": DEFAULT_TZ}
            return

        # Legacy single-dict format
        if isinstance(data, dict) and ("movie_list" in data or "watched_list" in data):
            _store = {}
            _legacy = {
                "movie_list": data.get("movie_list", []),
                "watched_list": data.get("watched_list", []),
                "movie_night": data.get("movie_night"),
                "movie_night_channel_id": data.get("movie_night_channel_id"),
                "timezone": data.get("timezone", DEFAULT_TZ),
            }
            return

        _store = {}
        _legacy = None

    except Exception:
        _store = {}
        _legacy = None

def _ensure_guild(guild_id: int):
    gid = str(guild_id)
    if gid not in _store:
        if _legacy:
            _store[gid] = _normalize_entry({
                "movie_list": list(_legacy.get("movie_list", [])),
                "watched_list": list(_legacy.get("watched_list", [])),
                "movie_night": _legacy.get("movie_night"),
                "movie_night_channel_id": _legacy.get("movie_night_channel_id"),
                "timezone": _legacy.get("timezone", DEFAULT_TZ),
            })
            _legacy.clear()
            _save_store()
        else:
            _store[gid] = _normalize_entry({})
            _save_store()
    else:
        _store[gid] = _normalize_entry(_store[gid])

def _guild_lists(ctx):
    """Per guild / per DM lists."""
    if ctx.guild is None:
        gid = f"dm_{ctx.author.id}"
        if gid not in _store:
            _store[gid] = _normalize_entry({})
            _save_store()
    else:
        gid = str(ctx.guild.id)
        _ensure_guild(ctx.guild.id)

    entry = _store[gid]
    return gid, entry["movie_list"], entry["watched_list"]

def _get_tz_name(gid: str) -> str:
    return _store.get(gid, {}).get("timezone", DEFAULT_TZ)

def _set_tz_name(gid: str, tz: str):
    _store[gid]["timezone"] = tz
    _save_store()

# ========== TMDB Helpers ==========

def search_movie(query):
    if not TMDB_API_KEY:
        return {"__error__": "TMDB_API_KEY is missing (not loaded from .env)"}

    url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": TMDB_API_KEY, "query": query}

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
    except Exception as e:
        return {"__error__": f"TMDB request failed: {e}"}

    # TMDB returns these fields when something is wrong (e.g., invalid API key)
    if isinstance(data, dict) and data.get("success") is False:
        return {"__error__": data.get("status_message", "TMDB error")}

    if isinstance(data, dict) and data.get("status_code") and not data.get("results"):
        return {"__error__": data.get("status_message", "TMDB error")}

    if data.get("results"):
        return data["results"][0]

    return None


# ========== Movie Night helpers ==========

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

def _parse_time_str(s: str):
    """Accepts: 8pm, 8:30pm, 20:00, 20"""
    s = s.strip().lower().replace(" ", "")
    ampm = None
    if s.endswith("am"):
        ampm = "am"
        s = s[:-2]
    elif s.endswith("pm"):
        ampm = "pm"
        s = s[:-2]

    if ":" in s:
        hh, mm = s.split(":", 1)
    else:
        hh, mm = s, "0"

    hour = int(hh)
    minute = int(mm)

    if ampm:
        if hour == 12:
            hour = 0
        if ampm == "pm":
            hour += 12

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("invalid time")
    return hour, minute

def _next_datetime_for(day_name: str, day_num: int, time_str: str, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)

    wanted_wd = WEEKDAYS.get(day_name.lower())
    hour, minute = _parse_time_str(time_str)

    year, month = now.year, now.month

    def make_candidate(y, m):
        last_day = calendar.monthrange(y, m)[1]
        if day_num < 1 or day_num > last_day:
            raise ValueError(f"day must be 1..{last_day} for {y}-{m:02d}")
        return datetime(y, m, day_num, hour, minute, tzinfo=tz)

    cand = make_candidate(year, month)
    if cand <= now:
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
        cand = make_candidate(year, month)

    # If weekday provided, nudge forward until it matches
    if wanted_wd is not None:
        while cand.weekday() != wanted_wd:
            cand += timedelta(days=1)

    return cand

def _format_countdown(dt: datetime, tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    if dt <= now:
        return "now"
    delta = dt - now
    days = delta.days
    seconds = delta.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if days > 0:
        return f"in {days}d {hours}h {minutes}m"
    if hours > 0:
        return f"in {hours}h {minutes}m"
    return f"in {minutes}m"

# ========== Events ==========

@bot.event
async def on_ready():
    _load_store()
    if not movie_night_checker.is_running():
        movie_night_checker.start()
    print(f"✅ Logged in as {bot.user} | Auto-delete after {AUTO_DELETE_AFTER}s enabled")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user in message.mentions:
        embed = discord.Embed(
            title="🎬 Tokkies",
            description=(
                "Hey! 👋 I can help you manage a **Movie List** and keep track of what you've watched.\n\n"
                "**How to use me:**\n"
                "Use commands starting with `.` or just pick from below 👇"
            ),
            color=INFO_COLOR
        )

        embed.add_field(
            name="📌 Watchlist Commands",
            value=(
                "`.add <title>` – Add a movie\n"
                "`.list` – Show watchlist\n"
                "`.poster <number>` – Show a movie poster\n"
                "`.random` – Pick a random movie\n"
                "`.clearlist` – Clear the watchlist"
            ),
            inline=False
        )

        embed.add_field(
            name="✅ Watched Commands",
            value=(
                "`.watched <title>` – Mark as watched\n"
                "`.watchedlist` – Show watched movies\n"
                "`.unwatch <title>` – Remove from watched\n"
                "`.clearwatched` – Clear watched list"
            ),
            inline=False
        )

        embed.add_field(
            name="🍿 Movie Night",
            value=(
                "`.set time tuesday 27 8pm` – Schedule movie night\n"
                "`.set channel #channel` – Set reminder channel\n"
                "`.set tz Europe/Berlin` – Set timezone\n"
                "`.night` – Show next movie night\n"
                "`.cancelnight` – Cancel movie night"
            ),
            inline=False
        )

        embed.set_footer(text="Tip: Commands auto-delete after a few seconds ✨")
        await message.channel.send(embed=embed, delete_after=SLOW_DELETE)

    await bot.process_commands(message)

# ========== Background checker ==========

@tasks.loop(seconds=20)
async def movie_night_checker():
    try:
        now_utc = datetime.now(ZoneInfo("UTC")).timestamp()
    except Exception:
        # fallback if tz database isn't available
        now_utc = datetime.utcnow().timestamp()

    for gid, entry in list(_store.items()):
        ts = entry.get("movie_night")
        if not ts:
            continue

        # Ensure entry normalized
        _normalize_entry(entry)

        if now_utc >= float(ts):
            channel_id = entry.get("movie_night_channel_id")
            channel = bot.get_channel(channel_id) if channel_id else None

            embed = discord.Embed(
                title="🍿 Movie Night Time!",
                description="It’s time! Start the movie night 🎬",
                color=SUCCESS_COLOR
            )

            if channel:
                try:
                    await channel.send(embed=embed)
                except Exception:
                    pass

            entry["movie_night"] = None
            _save_store()

# ========== Commands ==========

@bot.command(name="add")
async def add_movie(ctx, *, title: str):
    gid, movie_list, _ = _guild_lists(ctx)
    movie_list.append(title)
    _save_store()
    embed = discord.Embed(
        title="Movie Added! 🎬",
        description=f"**{title}** added to the watchlist.",
        color=SUCCESS_COLOR
    )
    embed.add_field(name="Position", value=f"#{len(movie_list)}", inline=True)
    embed.set_footer(text="This message will auto-delete soon")
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

@bot.command(name="list")
async def show_list(ctx):
    _, movie_list, _ = _guild_lists(ctx)
    if not movie_list:
        embed = discord.Embed(
            title="Watchlist is Empty 📭",
            description="No movies yet! Add some with `.add <title>`",
            color=EMPTY_COLOR
        )
        await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)
        return

    formatted = "\n".join([f"{i+1}. {title}" for i, title in enumerate(movie_list)])
    if len(formatted) > 3900:
        formatted = formatted[:3900] + "\n... (list too long)"

    embed = discord.Embed(
        title="🎬 Your Watchlist",
        description=formatted,
        color=INFO_COLOR
    )
    embed.set_footer(text=f"Total: {len(movie_list)} movies • Auto-deletes in {AUTO_DELETE_AFTER}s")
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

@bot.command(name="poster")
async def poster(ctx, *, query: str):
    _, movie_list, _ = _guild_lists(ctx)

    if not movie_list:
        embed = discord.Embed(title="Watchlist Empty 📭", color=EMPTY_COLOR)
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    query = query.strip()

    # 1) If user gave a number, treat it as an index
    if query.isdigit():
        index = int(query)
        if not (1 <= index <= len(movie_list)):
            embed = discord.Embed(title="Invalid Number ⚠️", color=ERROR_COLOR)
            return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

        title = movie_list[index - 1]

    else:
        # 2) Otherwise treat it as a title lookup in the watchlist
        q = query.lower()

        # exact match first
        match_idx = next((i for i, t in enumerate(movie_list) if t.strip().lower() == q), None)

        # fallback: partial match
        if match_idx is None:
            match_idx = next((i for i, t in enumerate(movie_list) if q in t.strip().lower()), None)

        if match_idx is None:
            embed = discord.Embed(
                title="Movie Not Found ❌",
                description=f"Couldn't find **{query}** in your watchlist.\nUse `.list` to see titles.",
                color=ERROR_COLOR
            )
            return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

        title = movie_list[match_idx]
        index = match_idx + 1  # for footer

    # Fetch poster from TMDB
    movie = search_movie(title)

    if isinstance(movie, dict) and movie.get("__error__"):
        embed = discord.Embed(
            title="TMDB Error ⚠️",
            description=movie["__error__"],
            color=ERROR_COLOR
        )
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    if not movie or not movie.get("poster_path"):
        embed = discord.Embed(title=f"No Poster Found for **{title}**", color=ERROR_COLOR)
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    poster_url = f"https://image.tmdb.org/t/p/w500{movie['poster_path']}"
    embed = discord.Embed(title=title, color=INFO_COLOR)
    embed.set_image(url=poster_url)
    embed.set_footer(text=f"#{index} • Powered by TMDB • Auto-deletes soon")
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)


@bot.command(name="clearlist")
async def clear_list(ctx):
    gid, _, _ = _guild_lists(ctx)
    _store[gid]["movie_list"] = []
    _save_store()
    embed = discord.Embed(title="🗑️ Movie list cleared!", color=SUCCESS_COLOR)
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

# ---- Movie Night commands ----

@bot.group(name="set", invoke_without_command=True)
async def set_group(ctx):
    embed = discord.Embed(
        title="Set Commands ⚙️",
        description="Use:\n`.set time <weekday> <day> <time>`\nExample: `.set time tuesday 27 8pm`\n\nOptional:\n`.set channel #channel`\n`.set tz Europe/Berlin`",
        color=INFO_COLOR
    )
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

@set_group.command(name="time")
async def set_time(ctx, weekday: str, day: int, time: str):
    gid, _, _ = _guild_lists(ctx)
    tz_name = _get_tz_name(gid)

    try:
        dt = _next_datetime_for(weekday, day, time, tz_name)
    except Exception as e:
        embed = discord.Embed(
            title="Invalid Time/Date ⚠️",
            description=f"Example: `.set time tuesday 27 8pm`\n\nError: `{e}`",
            color=ERROR_COLOR
        )
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    # default: current channel unless set otherwise
    channel_id = _store[gid].get("movie_night_channel_id") or ctx.channel.id

    _store[gid]["movie_night"] = int(dt.timestamp())
    _store[gid]["movie_night_channel_id"] = channel_id
    _save_store()

    embed = discord.Embed(
        title="🎟️ Movie Night Scheduled!",
        description=f"**When:** {dt.strftime('%a %d %b %Y • %H:%M')} ({tz_name})\n**Countdown:** {_format_countdown(dt, tz_name)}",
        color=SUCCESS_COLOR
    )
    await ctx.send(embed=embed, delete_after=SLOW_DELETE)

@set_group.command(name="channel")
async def set_channel(ctx, channel: discord.TextChannel):
    gid, _, _ = _guild_lists(ctx)
    _store[gid]["movie_night_channel_id"] = channel.id
    _save_store()
    embed = discord.Embed(
        title="✅ Movie Night Channel Set",
        description=f"Reminders will be posted in {channel.mention}",
        color=SUCCESS_COLOR
    )
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

@set_group.command(name="tz")
async def set_tz(ctx, *, tz_name: str):
    gid, _, _ = _guild_lists(ctx)
    try:
        ZoneInfo(tz_name)
    except Exception:
        embed = discord.Embed(
            title="Invalid Timezone ⚠️",
            description="Example: `.set tz Europe/Berlin` or `.set tz UTC`",
            color=ERROR_COLOR
        )
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    _set_tz_name(gid, tz_name)
    embed = discord.Embed(
        title="✅ Timezone Set",
        description=f"Timezone is now **{tz_name}**",
        color=SUCCESS_COLOR
    )
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

@bot.command(name="night")
async def night(ctx):
    gid, _, _ = _guild_lists(ctx)
    ts = _store[gid].get("movie_night")
    tz_name = _get_tz_name(gid)

    if not ts:
        embed = discord.Embed(
            title="No Movie Night Scheduled 📭",
            description="Set one with `.set time tuesday 27 8pm`",
            color=EMPTY_COLOR
        )
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    dt = datetime.fromtimestamp(int(ts), ZoneInfo(tz_name))
    embed = discord.Embed(
        title="🎬 Next Movie Night",
        description=f"**When:** {dt.strftime('%a %d %b %Y • %H:%M')} ({tz_name})\n**Countdown:** {_format_countdown(dt, tz_name)}",
        color=INFO_COLOR
    )
    await ctx.send(embed=embed, delete_after=SLOW_DELETE)

@bot.command(name="cancelnight")
async def cancel_night(ctx):
    gid, _, _ = _guild_lists(ctx)
    _store[gid]["movie_night"] = None
    _save_store()
    embed = discord.Embed(title="🗑️ Movie night cancelled!", color=SUCCESS_COLOR)
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

# ---- Random upgraded ----

@bot.command(name="random")
async def random_movie(ctx):
    gid, movie_list, _ = _guild_lists(ctx)
    if not movie_list:
        embed = discord.Embed(title="Watchlist Empty 📭", color=EMPTY_COLOR)
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    loading_embed = discord.Embed(
        title="🎲 Random Pick",
        description="Loading........ ⏳",
        color=INFO_COLOR
    )
    loading_embed.set_footer(text="Picking a movie for you...")
    loading_msg = await ctx.send(embed=loading_embed)

    await asyncio.sleep(2)

    try:
        await loading_msg.delete()
    except (discord.Forbidden, discord.HTTPException):
        pass

    title = random.choice(movie_list)
    movie = search_movie(title)

    result_embed = discord.Embed(
        title="🎬 Random Movie Picked!",
        description=f"**{title}**",
        color=SUCCESS_COLOR
    )

    if movie:
        overview = (movie.get("overview") or "").strip()
        release = movie.get("release_date") or "Unknown"
        rating = movie.get("vote_average")
        votes = movie.get("vote_count")

        if overview:
            if len(overview) > 800:
                overview = overview[:800] + "…"
            result_embed.add_field(name="📝 Overview", value=overview, inline=False)

        result_embed.add_field(name="📅 Release", value=release, inline=True)

        if rating is not None:
            result_embed.add_field(name="⭐ Rating", value=f"{rating}/10 ({votes} votes)", inline=True)

        if movie.get("poster_path"):
            result_embed.set_image(url=f"https://image.tmdb.org/t/p/w500{movie['poster_path']}")
    else:
        result_embed.add_field(name="Info", value="Couldn’t fetch TMDB info this time 😅", inline=False)

    # Movie night countdown below
    ts = _store[gid].get("movie_night")
    tz_name = _get_tz_name(gid)
    if ts:
        dt = datetime.fromtimestamp(int(ts), ZoneInfo(tz_name))
        result_embed.add_field(
            name="🍿 Next Movie Night",
            value=f"{dt.strftime('%a %d %b • %H:%M')} ({tz_name})\n**{_format_countdown(dt, tz_name)}**",
            inline=False
        )

    result_embed.set_footer(text=f"Auto-deletes in {AUTO_DELETE_AFTER}s • Powered by TMDB")
    await ctx.send(embed=result_embed, delete_after=AUTO_DELETE_AFTER)

# ---- Watched commands ----

def _find_title_index_insensitive(items, title: str):
    t = title.strip().lower()
    for i, v in enumerate(items):
        if v.strip().lower() == t:
            return i
    return None

@bot.command(name="watched")
async def watched(ctx, *, title: str):
    gid, movie_list, watched_list = _guild_lists(ctx)
    title = title.strip()
    if not title:
        embed = discord.Embed(
            title="Missing Title ⚠️",
            description="Usage: `.watched <movie title>`",
            color=ERROR_COLOR
        )
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    removed_from_watchlist = False
    title_to_add = title

    idx = _find_title_index_insensitive(movie_list, title)
    if idx is not None:
        title_to_add = movie_list.pop(idx)
        removed_from_watchlist = True

    if _find_title_index_insensitive(watched_list, title_to_add) is None:
        watched_list.append(title_to_add)
        _save_store()

        embed = discord.Embed(
            title="Marked as Watched ✅",
            description=f"**{title_to_add}** added to your **Watched Movies List**.",
            color=SUCCESS_COLOR
        )
        if removed_from_watchlist:
            embed.add_field(name="Watchlist", value="Removed from watchlist.", inline=False)

        embed.set_footer(text="This message will auto-delete soon")
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    embed = discord.Embed(
        title="Already Watched 🎞️",
        description=f"**{title_to_add}** is already in your watched list.",
        color=INFO_COLOR
    )
    embed.set_footer(text="This message will auto-delete soon")
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

@bot.command(name="watchedlist")
async def watchedlist(ctx):
    _, _, watched_list = _guild_lists(ctx)
    if not watched_list:
        embed = discord.Embed(
            title="Watched List is Empty 📭",
            description="Mark movies as watched with `.watched <title>`",
            color=EMPTY_COLOR
        )
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    formatted = "\n".join([f"{i+1}. {title}" for i, title in enumerate(watched_list)])
    if len(formatted) > 3900:
        formatted = formatted[:3900] + "\n... (list too long)"

    embed = discord.Embed(
        title="✅ Watched Movies List",
        description=formatted,
        color=INFO_COLOR
    )
    embed.set_footer(text=f"Total: {len(watched_list)} movies • Auto-deletes in {AUTO_DELETE_AFTER}s")
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

@bot.command(name="unwatch")
async def unwatch(ctx, *, title: str):
    gid, _, watched_list = _guild_lists(ctx)
    title = title.strip()
    if not title:
        embed = discord.Embed(
            title="Missing Title ⚠️",
            description="Usage: `.unwatch <movie title>`",
            color=ERROR_COLOR
        )
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    idx = _find_title_index_insensitive(watched_list, title)
    if idx is None:
        embed = discord.Embed(
            title="Not Found ❌",
            description=f"**{title}** is not in your watched list.",
            color=ERROR_COLOR
        )
        embed.set_footer(text="This message will auto-delete soon")
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    removed = watched_list.pop(idx)
    _save_store()

    embed = discord.Embed(
        title="↩️ Removed from Watched",
        description=f"**{removed}** removed from your **Watched Movies List**.",
        color=SUCCESS_COLOR
    )
    embed.set_footer(text="This message will auto-delete soon")
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

@bot.command(name="clearwatched")
async def clearwatched(ctx):
    gid, _, watched_list = _guild_lists(ctx)
    if not watched_list:
        embed = discord.Embed(
            title="Nothing to Clear 🧹",
            description="Your watched list is already empty.",
            color=EMPTY_COLOR
        )
        return await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

    _store[gid]["watched_list"] = []
    _save_store()

    embed = discord.Embed(
        title="🗑️ Watched list cleared!",
        color=SUCCESS_COLOR
    )
    await ctx.send(embed=embed, delete_after=AUTO_DELETE_AFTER)

# ========== Run ==========
bot.run(DISCORD_TOKEN)
