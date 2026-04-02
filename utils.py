import os
import json
import requests
import asyncio
import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

# ────────────────────────────────────────────────
# Colors
SUCCESS_COLOR = discord.Color.blurple()
ERROR_COLOR   = discord.Color.red()
INFO_COLOR    = discord.Color.blue()
WARNING_COLOR = discord.Color.orange()
EMPTY_COLOR   = discord.Color.dark_grey()

# Auto-delete durations (seconds)
AUTO_DELETE_AFTER = 20
SLOW_DELETE       = 50
FAST_DELETE       = 10

# ========== Persistent store (per-guild) ==========

DATA_FILE  = "movie_data.json"
_store     = {}
_legacy    = None
DEFAULT_TZ = "UTC"


def _save_store():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(_store, f, ensure_ascii=False, indent=2)


def _normalize_entry(entry: dict) -> dict:
    """Ensure all expected keys exist on an entry."""
    entry.setdefault("movie_list", [])
    entry.setdefault("watched_list", [])
    entry.setdefault("movie_night", None)
    entry.setdefault("movie_night_channel_id", None)
    entry.setdefault("timezone", DEFAULT_TZ)
    entry.setdefault("auto_delete_enabled", True)
    entry.setdefault("prefix", ".")
    entry.setdefault("locked", False)
    entry.setdefault("blocked_users", [])
    return entry


def _load_store():
    # NOTE: Never reassign _store (e.g. _store = {}). All cogs hold a reference
    # to this exact dict object. Always mutate in-place so those references stay valid.
    global _legacy
    _store.clear()
    _legacy = None

    if not os.path.exists(DATA_FILE):
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Current per-guild dict format
        if isinstance(data, dict) and any(
            str(k).isdigit() or str(k).startswith("dm_") for k in data.keys()
        ):
            for k, v in data.items():
                if not isinstance(v, dict):
                    v = {}
                _store[str(k)] = _normalize_entry({
                    "movie_list":             v.get("movie_list", []),
                    "watched_list":           v.get("watched_list", []),
                    "movie_night":            v.get("movie_night"),
                    "movie_night_channel_id": v.get("movie_night_channel_id"),
                    "timezone":               v.get("timezone", DEFAULT_TZ),
                    "auto_delete_enabled":    v.get("auto_delete_enabled", True),
                    "prefix":                 v.get("prefix", "."),
                    "locked":                 v.get("locked", False),
                    "blocked_users":          v.get("blocked_users", []),
                })
            return

        # Legacy: bare list
        if isinstance(data, list):
            _legacy = {
                "movie_list": data, "watched_list": [],
                "movie_night": None, "movie_night_channel_id": None,
                "timezone": DEFAULT_TZ, "auto_delete_enabled": True,
                "prefix": ".", "locked": False, "blocked_users": [],
            }
            return

        # Legacy: single dict
        if isinstance(data, dict) and ("movie_list" in data or "watched_list" in data):
            _legacy = {
                "movie_list":             data.get("movie_list", []),
                "watched_list":           data.get("watched_list", []),
                "movie_night":            data.get("movie_night"),
                "movie_night_channel_id": data.get("movie_night_channel_id"),
                "timezone":               data.get("timezone", DEFAULT_TZ),
                "auto_delete_enabled":    data.get("auto_delete_enabled", True),
                "prefix":                 data.get("prefix", "."),
                "locked":                 data.get("locked", False),
                "blocked_users":          data.get("blocked_users", []),
            }
            return

    except Exception:
        pass  # _store already cleared above, that's safe


def _ensure_guild(guild_id: int):
    gid = str(guild_id)
    if gid not in _store:
        if _legacy:
            _store[gid] = _normalize_entry({
                "movie_list":             list(_legacy.get("movie_list", [])),
                "watched_list":           list(_legacy.get("watched_list", [])),
                "movie_night":            _legacy.get("movie_night"),
                "movie_night_channel_id": _legacy.get("movie_night_channel_id"),
                "timezone":               _legacy.get("timezone", DEFAULT_TZ),
                "auto_delete_enabled":    _legacy.get("auto_delete_enabled", True),
                "prefix":                 _legacy.get("prefix", "."),
                "locked":                 _legacy.get("locked", False),
                "blocked_users":          _legacy.get("blocked_users", []),
            })
            _legacy.clear()
            _save_store()
        else:
            _store[gid] = _normalize_entry({})
            _save_store()
    else:
        _store[gid] = _normalize_entry(_store[gid])


def _guild_lists(ctx):
    """Return (gid, movie_list, watched_list) for the current guild/DM."""
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


def _get_auto_delete_enabled(gid: str) -> bool:
    return _store.get(gid, {}).get("auto_delete_enabled", True)


def _set_auto_delete_enabled(gid: str, enabled: bool):
    if gid not in _store:
        _store[gid] = _normalize_entry({})
    _store[gid]["auto_delete_enabled"] = enabled
    _save_store()


def _safe_delete_after(ctx, seconds):
    gid, _, _ = _guild_lists(ctx)
    return seconds if _get_auto_delete_enabled(gid) else None


def _is_blocked(ctx) -> bool:
    if ctx.guild is None:
        return False
    gid = str(ctx.guild.id)
    return ctx.author.id in _store.get(gid, {}).get("blocked_users", [])


def _is_locked(gid: str) -> bool:
    return _store.get(gid, {}).get("locked", False)


# ========== TMDB core ==========

async def _tmdb_get(endpoint: str, **params):
    """Generic async TMDB GET. Returns parsed JSON dict or None on failure."""
    tmdb_key = os.getenv("TMDB_API_KEY")
    if not tmdb_key:
        return None
    url            = f"https://api.themoviedb.org/3{endpoint}"
    params["api_key"] = tmdb_key
    try:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            None, lambda: requests.get(url, params=params, timeout=10)
        )
        return resp.json()
    except Exception:
        return None


async def search_movie(query: str):
    """Search TMDB and return the top result dict, or an __error__ dict, or None."""
    tmdb_key = os.getenv("TMDB_API_KEY")
    if not tmdb_key:
        return {"__error__": "TMDB_API_KEY is missing (not loaded from .env)"}

    data = await _tmdb_get("/search/movie", query=query)
    if data is None:
        return {"__error__": "TMDB request failed"}

    if data.get("success") is False:
        return {"__error__": data.get("status_message", "TMDB error")}
    if data.get("status_code") and not data.get("results"):
        return {"__error__": data.get("status_message", "TMDB error")}
    if data.get("results"):
        return data["results"][0]
    return None


async def get_movie_details(movie_id: int) -> dict | None:
    """Fetch full movie details (runtime, genres, etc.) by TMDB ID."""
    return await _tmdb_get(f"/movie/{movie_id}")


async def get_popular_movies(page: int = 1) -> list:
    """Return a list of popular movies from TMDB."""
    data = await _tmdb_get("/movie/popular", page=page)
    return data.get("results", []) if data else []


# ========== Movie Night helpers ==========

WEEKDAYS = {
    "monday": 0,    "mon": 0,
    "tuesday": 1,   "tue": 1,   "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3,  "thu": 3,   "thur": 3,  "thurs": 3,
    "friday": 4,    "fri": 4,
    "saturday": 5,  "sat": 5,
    "sunday": 6,    "sun": 6,
}


def _parse_time_str(s: str):
    """Accept: 8pm, 8:30pm, 20:00, 20"""
    s = s.strip().lower().replace(" ", "")
    ampm = None
    if s.endswith("am"):
        ampm, s = "am", s[:-2]
    elif s.endswith("pm"):
        ampm, s = "pm", s[:-2]

    hh, mm = s.split(":", 1) if ":" in s else (s, "0")
    hour, minute = int(hh), int(mm)

    if ampm:
        if hour == 12:
            hour = 0
        if ampm == "pm":
            hour += 12

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("invalid time")
    return hour, minute


def _next_datetime_for(day_name: str, day_num: int, time_str: str, tz_name: str) -> datetime:
    tz  = ZoneInfo(tz_name)
    now = datetime.now(tz)

    wanted_wd    = WEEKDAYS.get(day_name.lower())
    hour, minute = _parse_time_str(time_str)
    year, month  = now.year, now.month

    def make_candidate(y, m):
        last_day = calendar.monthrange(y, m)[1]
        if day_num < 1 or day_num > last_day:
            raise ValueError(f"day must be 1..{last_day} for {y}-{m:02d}")
        return datetime(y, m, day_num, hour, minute, tzinfo=tz)

    cand = make_candidate(year, month)
    if cand <= now:
        month = month % 12 + 1
        if month == 1:
            year += 1
        cand = make_candidate(year, month)

    if wanted_wd is not None:
        while cand.weekday() != wanted_wd:
            cand += timedelta(days=1)

    return cand


def _format_countdown(dt: datetime, tz_name: str) -> str:
    tz    = ZoneInfo(tz_name)
    now   = datetime.now(tz)
    if dt <= now:
        return "now"
    delta   = dt - now
    days    = delta.days
    seconds = delta.seconds
    hours   = seconds // 3600
    minutes = (seconds % 3600) // 60
    if days > 0:
        return f"in {days}d {hours}h {minutes}m"
    if hours > 0:
        return f"in {hours}h {minutes}m"
    return f"in {minutes}m"


# ========== General helpers ==========

def _find_title_index_insensitive(items, title: str):
    t = title.strip().lower()
    for i, v in enumerate(items):
        if v.strip().lower() == t:
            return i
    return None


def is_owner_or_admin():
    """Check: passes if the invoker is the bot owner (OWNER_ID in .env) OR a server admin."""
    async def predicate(ctx):
        try:
            owner_id = int(os.getenv("OWNER_ID", "0") or "0")
        except ValueError:
            owner_id = 0
        if owner_id and ctx.author.id == owner_id:
            return True
        if ctx.guild and ctx.author.guild_permissions.administrator:
            return True
        raise commands.CheckFailure("no_permission")
    return commands.check(predicate)


def _make_footer(ctx, base: str = "") -> str:
    """Build a consistent embed footer.
    Shows: [base •] [Auto-deletes in Xs •] Requested by @name
    Auto-delete text is omitted when auto-delete is disabled for the guild.
    """
    gid  = str(ctx.guild.id) if ctx.guild else f"dm_{ctx.author.id}"
    auto = _store.get(gid, {}).get("auto_delete_enabled", True)
    parts = [base] if base else []
    if auto:
        parts.append(f"Auto-deletes in {AUTO_DELETE_AFTER}s")
    parts.append(f"Requested by @{ctx.author.display_name}")
    return " • ".join(parts)


async def _confirm(ctx, prompt: str) -> bool:
    """Post a ✅/❌ reaction prompt. Returns True if the author confirms within 15 s."""
    embed = discord.Embed(
        title=prompt,
        description="React ✅ to confirm or ❌ to cancel.",
        color=WARNING_COLOR,
    )
    msg = await ctx.send(embed=embed)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    def check(reaction, user):
        return (
            user == ctx.author
            and str(reaction.emoji) in ("✅", "❌")
            and reaction.message.id == msg.id
        )

    try:
        reaction, _ = await ctx.bot.wait_for("reaction_add", timeout=15.0, check=check)
        try:
            await msg.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass
        return str(reaction.emoji) == "✅"
    except asyncio.TimeoutError:
        try:
            await msg.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass
        return False
