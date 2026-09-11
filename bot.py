import os
import discord
from discord.ext import commands, tasks
from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo
import urllib.request
import json
import re
import unicodedata

TOKEN = os.getenv("DISCORD_TOKEN")

# All persisted tracking files (waivers, trades, achievements, etc.) are
# saved here. Locally this is just the bot's own folder. On Railway, set
# the DATA_DIR environment variable to your mounted volume's path (e.g.
# /data) so this data survives redeploys.
DATA_DIR = os.getenv("DATA_DIR", ".")

LEAGUE_ID = "1400359679598563328"

STANDINGS_CHANNEL_ID = 1545160833594695811
MATCHUPS_CHANNEL_ID = 1544776021545455636
NEWS_CHANNEL_ID = 1544775954658889829
STATS_CHANNEL_ID = 1545276612193550356
RECORDS_CHANNEL_ID = 1544776459812348004

WAIVER_WIRE_CHANNEL_ID = 1545161524178587729
TRADE_BLOCK_CHANNEL_ID = 1545164437978091550

NFL_NEWS_CHANNEL_ID = 1545165052858863729
NFL_SCORES_CHANNEL_ID = 1546461175171129365
INJURY_NEWS_CHANNEL_ID = 1545164635962085447

CHAMPIONSHIP_HISTORY_CHANNEL_ID = 1545273956603404338
WEEKLY_WINNERS_CHANNEL_ID = 1545275463008784514
ACHIEVEMENTS_CHANNEL_ID = 1545275659918512208
ROSTERS_CHANNEL_ID = 1547130031749464144
ROSTER_STATS_CHANNEL_ID = 1547482861970395156
POWER_RANKINGS_CHANNEL_ID = 1545275818131853413
NFL_SCORES_CHANNEL_ID = 1546461175171129365

# NFL game-day score tracker
NFL_SCORE_CHANNEL_ID = NFL_SCORES_CHANNEL_ID
NFL_CHECK_INTERVAL = 10

central = ZoneInfo("America/Chicago")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# --- Persisted "already posted" tracker (fixes daily_raven repeat-posting) ---
POSTED_WEEKS_FILE = os.path.join(DATA_DIR, "posted_weeks.json")


def load_posted_weeks():
    if os.path.exists(POSTED_WEEKS_FILE):
        with open(POSTED_WEEKS_FILE, "r") as f:
            return json.load(f)
    return {"news": 0}


def save_posted_weeks(data):
    with open(POSTED_WEEKS_FILE, "w") as f:
        json.dump(data, f)


posted_weeks = load_posted_weeks()


# --- Daily Raven calendar-day tracker. ---
# The old Raven task used the weekly news marker above, which meant the task
# ran every day but only actually posted once per completed fantasy week.
DAILY_RAVEN_FILE = os.path.join(DATA_DIR, "daily_raven.json")


def load_daily_raven_state():
    if os.path.exists(DAILY_RAVEN_FILE):
        try:
            with open(DAILY_RAVEN_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"last_post_date": ""}


def save_daily_raven_state(data):
    with open(DAILY_RAVEN_FILE, "w") as f:
        json.dump(data, f)


daily_raven_state = load_daily_raven_state()


# --- Persisted all-time franchise records, used by the Achievements system ---
ACHIEVEMENTS_FILE = os.path.join(DATA_DIR, "achievements_data.json")


def load_achievements():
    default = {
        "high_score": {"team": None, "score": -1, "week": 0},
        "low_score": {"team": None, "score": None, "week": 0},
        "biggest_margin": {
            "winner": None,
            "loser": None,
            "margin": -1,
            "week": 0
        },
        "closest_game": {
            "team1": None,
            "team2": None,
            "margin": None,
            "week": 0
        },
        "longest_win_streak": {"team": None, "length": 0},
        "longest_loss_streak": {"team": None, "length": 0},
        "current_streaks": {},
        "last_checked_week": 0
    }

    if os.path.exists(ACHIEVEMENTS_FILE):
        with open(ACHIEVEMENTS_FILE, "r") as f:
            saved = json.load(f)
            default.update(saved)

    return default


def save_achievements(data):
    with open(ACHIEVEMENTS_FILE, "w") as f:
        json.dump(data, f)


achievements_data = load_achievements()


# --- Persisted roster snapshots, used to detect any roster composition ---
# --- change (waivers, trades, or manual edits) for the Rosters channel ---
ROSTER_SNAPSHOTS_FILE = os.path.join(DATA_DIR, "roster_snapshots.json")


def load_roster_snapshots():
    if os.path.exists(ROSTER_SNAPSHOTS_FILE):
        with open(ROSTER_SNAPSHOTS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_roster_snapshots(data):
    with open(ROSTER_SNAPSHOTS_FILE, "w") as f:
        json.dump(data, f)


roster_snapshots = load_roster_snapshots()


# --- Persisted Discord message IDs for the Rosters channel. ---
# --- The channel uses a fixed set of full-roster posts. Whenever any team ---
# --- changes, those same posts are edited instead of creating transaction posts. ---
ROSTER_MESSAGE_IDS_FILE = os.path.join(DATA_DIR, "roster_message_ids.json")


def load_roster_message_ids():
    if os.path.exists(ROSTER_MESSAGE_IDS_FILE):
        try:
            with open(ROSTER_MESSAGE_IDS_FILE, "r") as f:
                saved = json.load(f)

            # Older versions stored one message ID per roster in a dict.
            # Do not reuse those scattered message IDs with the new grouped layout.
            if isinstance(saved, list):
                return [str(message_id) for message_id in saved]
        except Exception as e:
            print(f"Could not load roster message IDs: {e}")

    return []


def save_roster_message_ids(data):
    with open(ROSTER_MESSAGE_IDS_FILE, "w") as f:
        json.dump(data, f)


roster_message_ids = load_roster_message_ids()


# --- Persisted championship history, one entry per completed season ---
CHAMPIONS_FILE = os.path.join(DATA_DIR, "champions.json")


def load_champions():
    if os.path.exists(CHAMPIONS_FILE):
        with open(CHAMPIONS_FILE, "r") as f:
            return json.load(f)
    return {"seasons": {}}


def save_champions(data):
    with open(CHAMPIONS_FILE, "w") as f:
        json.dump(data, f)


champions_data = load_champions()


# --- Persisted per-week accumulation of individual player game stats ---
# --- for rostered players only, built up as each NFL game finishes. ---
WEEK_PLAYER_STATS_FILE = os.path.join(DATA_DIR, "week_player_stats.json")


def load_week_player_stats():
    if os.path.exists(WEEK_PLAYER_STATS_FILE):
        with open(WEEK_PLAYER_STATS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_week_player_stats(data):
    with open(WEEK_PLAYER_STATS_FILE, "w") as f:
        json.dump(data, f)


week_player_stats = load_week_player_stats()


# --- Persisted Discord message IDs for the cumulative weekly NFL player-stats feed. ---
# --- Each fantasy week keeps its own fixed set of messages, which are edited in place ---
# --- as more NFL games finish. The dedicated feed contains no emojis. ---
WEEKLY_STATS_MESSAGE_IDS_FILE = os.path.join(
    DATA_DIR, "weekly_stats_message_ids.json"
)


def load_weekly_stats_message_ids():
    if os.path.exists(WEEKLY_STATS_MESSAGE_IDS_FILE):
        try:
            with open(WEEKLY_STATS_MESSAGE_IDS_FILE, "r") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                return {
                    str(week): [str(mid) for mid in ids]
                    for week, ids in saved.items()
                    if isinstance(ids, list)
                }
        except Exception as e:
            print(f"Could not load weekly stats message IDs: {e}")
    return {}


def save_weekly_stats_message_ids(data):
    with open(WEEKLY_STATS_MESSAGE_IDS_FILE, "w") as f:
        json.dump(data, f)


weekly_stats_message_ids = load_weekly_stats_message_ids()


def get_league_info():
    url = f"https://api.sleeper.app/v1/league/{LEAGUE_ID}"
    return get_json(url)


def get_winners_bracket():
    url = (
        f"https://api.sleeper.app/v1/league/"
        f"{LEAGUE_ID}/winners_bracket"
    )
    return get_json(url)


# --- Generic persisted set of "already posted" IDs, used by every ---
# --- auto-checker (waivers, trades, news, live scores) so restarts ---
# --- don't cause re-announcing things that already posted. ---
def load_id_set(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return set(json.load(f))
    return set()


def save_id_set(filename, id_set):
    with open(filename, "w") as f:
        json.dump(list(id_set), f)


def get_json(url):
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode())


# --- Player ID -> name lookup, used by the waiver wire tracker ---
players_cache = {}


def load_players_cache():
    global players_cache
    try:
        url = "https://api.sleeper.app/v1/players/nfl"
        players_cache = get_json(url)
        print(f"✅ Loaded {len(players_cache)} players into cache.")
    except Exception as e:
        print(f"Error loading players cache: {e}")


def get_player_name(player_id):
    if not player_id:
        return "Unknown Player"

    player = players_cache.get(str(player_id))

    if not player:
        return f"Player {player_id}"

    first = player.get("first_name", "")
    last = player.get("last_name", "")
    name = f"{first} {last}".strip()

    return name or f"Player {player_id}"


def get_transactions(week):
    url = (
        f"https://api.sleeper.app/v1/league/"
        f"{LEAGUE_ID}/transactions/{week}"
    )
    return get_json(url)


POSITION_TITLES = {
    "QB": "🖐️ Hand of the King",
    "RB": "⚔️ Master of War",
    "WR": "🏹 Master of Whispers",
    "TE": "🏹 Master of Whispers",
    "K": "💰 Master of Coin",
    "DEF": "🛡️ Kingsguard",
}


def get_mvp_title(position):
    return POSITION_TITLES.get(position, "👑 Player of the Week")


def get_week_mvp(week):
    matchups_url = (
        f"https://api.sleeper.app/v1/league/"
        f"{LEAGUE_ID}/matchups/{week}"
    )

    rosters_url = (
        f"https://api.sleeper.app/v1/league/"
        f"{LEAGUE_ID}/rosters"
    )

    users_url = (
        f"https://api.sleeper.app/v1/league/"
        f"{LEAGUE_ID}/users"
    )

    matchups = get_json(matchups_url)
    rosters = get_json(rosters_url)
    users = get_json(users_url)

    user_names = {}

    for user in users:
        user_names[user["user_id"]] = (
            user.get("metadata", {}).get("team_name")
            or user.get("display_name", "Unknown House")
        )

    roster_names = {}

    for roster in rosters:
        roster_id = roster.get("roster_id")
        owner_id = roster.get("owner_id")

        roster_names[roster_id] = user_names.get(
            owner_id,
            "Unknown House"
        )

    best = None

    for m in matchups:
        roster_id = m.get("roster_id")
        starters = m.get("starters", []) or []
        players_points = m.get("players_points", {}) or {}

        for pid in starters:
            if not pid or pid == "0":
                continue

            pts = players_points.get(pid, 0) or 0

            if best is None or pts > best["points"]:
                best = {
                    "player_id": pid,
                    "points": pts,
                    "team": roster_names.get(
                        roster_id,
                        "Unknown House"
                    )
                }

    if best is None:
        return None

    player_info = players_cache.get(str(best["player_id"]), {})
    position = player_info.get("position", "")

    best["name"] = get_player_name(best["player_id"])
    best["position"] = position
    best["title"] = get_mvp_title(position)

    return best


INJURY_KEYWORDS = [
    "injury",
    "injured",
    "injuries",
    "out for",
    "questionable",
    "doubtful",
    "ruled out",
    "injured reserve",
    "ir",
    "activated from ir",
    "placed on ir",
    "will miss",
    "sidelined",
    "surgery",
    "surgically",
    "torn",
    "tear",
    "fracture",
    "fractured",
    "concussion",
    "concussion protocol",
    "hamstring",
    "quad",
    "quadricep",
    "groin",
    "ankle",
    "knee",
    "shoulder",
    "achilles",
    "acl",
    "mcl",
    "pcl",
    "meniscus",
    "carted off",
    "exits game",
    "leaves game",
    "left the game",
    "day-to-day",
    "week-to-week",
    "banged up",
    "nursing",
    "setback",
    "dnp",
    "did not practice",
    "limited practice",
    "mri",
    "x-ray",
    "xray",
    "hospitalized",
]


def is_injury_headline(text):
    lowered = text.lower()

    for keyword in INJURY_KEYWORDS:
        pattern = r"\b" + re.escape(keyword) + r"\b"

        if re.search(pattern, lowered):
            return True

    return False


def get_nfl_articles(limit=20):
    url = (
        f"https://site.api.espn.com/apis/site/v2/"
        f"sports/football/nfl/news?limit={limit}"
    )

    data = get_json(url)
    return data.get("articles", [])


def format_trade(t, roster_names):
    roster_ids = t.get("roster_ids", [])
    adds = t.get("adds") or {}
    draft_picks = t.get("draft_picks") or []
    waiver_budget = t.get("waiver_budget") or []

    lines = ["🔄 **TRADE COMPLETED** 🔄\n"]

    for roster_id in roster_ids:
        team_name = roster_names.get(roster_id, "Unknown House")

        received_players = [
            get_player_name(pid)
            for pid, rid in adds.items()
            if rid == roster_id
        ]

        received_picks = [
            f"{pick.get('season')} Round {pick.get('round')} Pick"
            for pick in draft_picks
            if pick.get("owner_id") == roster_id
        ]

        received_faab = [
            f"${wb.get('amount')} FAAB"
            for wb in waiver_budget
            if wb.get("receiver") == roster_id
        ]

        received = received_players + received_picks + received_faab

        lines.append(f"🏰 **{team_name}** receives:")

        if received:
            for item in received:
                lines.append(f"  • {item}")
        else:
            lines.append("  • (nothing directly \u2014 see other side)")

        lines.append("")

    return "\n".join(lines)


async def send_to_channel(channel_id, message):
    channel = bot.get_channel(channel_id)

    if channel is None:
        print(f"Could not find Discord channel: {channel_id}")
        return

    await channel.send(message)


def get_player_stats_channel():
    """Resolve the NFL player-stats channel robustly.

    The configured ROSTER_STATS_CHANNEL_ID in older versions of the bot was
    accidentally saved as an 18-digit value, so Discord could not resolve it.
    Prefer the configured ID when valid, otherwise locate the dedicated stats
    channel by its name. As a last-resort safety net, use STATS_CHANNEL_ID so
    completed-game player stats are not silently lost.
    """
    channel = bot.get_channel(ROSTER_STATS_CHANNEL_ID)
    if channel is not None:
        return channel

    preferred_names = {
        "nfl-player-stats",
        "nfl-player-stat",
        "player-stats",
        "roster-stats",
        "nfl-stats",
    }

    # Search every guild the bot can see. Discord channel names are lowercase
    # and usually hyphenated, so normalize spaces/underscores before comparing.
    for guild in bot.guilds:
        for candidate in guild.text_channels:
            normalized = candidate.name.lower().replace("_", "-").replace(" ", "-")
            if normalized in preferred_names:
                print(
                    f"NFL player stats channel auto-detected: "
                    f"#{candidate.name} ({candidate.id})"
                )
                return candidate

    fallback = bot.get_channel(STATS_CHANNEL_ID)
    if fallback is not None:
        print(
            "WARNING: Dedicated NFL player-stats channel could not be found; "
            f"falling back to STATS_CHANNEL_ID ({STATS_CHANNEL_ID})."
        )
        return fallback

    print(
        "ERROR: Could not resolve either the dedicated NFL player-stats "
        "channel or the general stats channel."
    )
    return None


async def send_player_stats_message(message):
    """Send the detailed, game-by-game player-stat post to the normal Stats channel."""
    channel = bot.get_channel(STATS_CHANNEL_ID)
    if channel is None:
        print(f"Could not find detailed player stats channel: {STATS_CHANNEL_ID}")
        return False

    await channel.send(message)
    return True




def normalize_nfl_team_abbr(abbr):
    """Normalize ESPN/Sleeper NFL team abbreviations to the same values."""
    value = str(abbr or "").upper().strip()
    aliases = {
        "LA": "LAR",
        "LAR": "LAR",
        "JAC": "JAX",
        "JAX": "JAX",
        "WSH": "WAS",
        "WAS": "WAS",
        "LV": "LV",
        "OAK": "LV",
    }
    return aliases.get(value, value)


def get_completed_nfl_teams(games):
    """Return NFL team abbreviations whose games are final in the supplied ESPN events."""
    completed_teams = set()

    for game in games or []:
        status = game.get("status", {}).get("type", {}) or {}
        if not status.get("completed", False):
            continue

        competition = (game.get("competitions") or [{}])[0]
        for competitor in competition.get("competitors", []) or []:
            abbr = (competitor.get("team", {}) or {}).get("abbreviation")
            if abbr:
                completed_teams.add(normalize_nfl_team_abbr(abbr))

    return completed_teams


def update_weekly_scores_from_sleeper(
    current_week, rosters_data, user_names, games, week_data, completed_player_ids=None
):
    """Populate the cumulative weekly feed directly from Sleeper matchup scores.

    Sleeper ``players_points`` is the primary source of truth for this clean
    weekly data channel. Positive/negative fantasy scores are accepted directly
    from Sleeper so ESPN player-name/ID matching can never block a completed
    player's fantasy score from appearing.

    For players currently showing exactly 0.00, we only include them when either
    ESPN confirmed that exact player in a completed box score or Sleeper's NFL
    team metadata belongs to a completed game. This avoids filling the weekly
    post with every inactive/unused roster player while still allowing true
    zero-point performances to appear.
    """
    completed_player_ids = {str(pid) for pid in (completed_player_ids or set())}
    completed_teams = get_completed_nfl_teams(games)

    matchup_url = (
        f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/matchups/{current_week}"
    )

    try:
        matchups = get_json(matchup_url)
    except Exception as e:
        print(f"Sleeper matchup stats error for Week {current_week}: {e}")
        return False

    if not isinstance(matchups, list):
        print(
            f"Sleeper matchup stats for Week {current_week} returned an "
            f"unexpected payload: {type(matchups).__name__}"
        )
        return False

    roster_to_team = {}
    for roster in rosters_data:
        roster_id = roster.get("roster_id")
        owner_id = roster.get("owner_id")
        roster_to_team[str(roster_id)] = user_names.get(owner_id, "Unknown House")

    changed = False
    accepted_players = 0
    teams_store = week_data.setdefault("teams", {})

    for matchup in matchups:
        roster_id = str(matchup.get("roster_id"))
        fantasy_team = roster_to_team.get(roster_id, "Unknown House")
        player_points = matchup.get("players_points") or {}

        if not isinstance(player_points, dict):
            continue

        team_entry = teams_store.setdefault(fantasy_team, {})

        for pid, points in player_points.items():
            pid = str(pid)
            player_info = players_cache.get(pid, {}) or {}

            try:
                score = float(points or 0)
            except (TypeError, ValueError):
                continue

            # Sleeper is authoritative for any player who already has a non-zero
            # fantasy score. Do not make ESPN matching a prerequisite.
            include_player = abs(score) > 0.000001

            # Preserve genuine 0.00 performances once the player's game is known
            # to be final. ESPN player matching is helpful here, but no longer
            # required for players who actually scored fantasy points.
            if not include_player:
                if pid in completed_player_ids:
                    include_player = True
                else:
                    nfl_team = normalize_nfl_team_abbr(player_info.get("team"))
                    if nfl_team and nfl_team in completed_teams:
                        include_player = True

            if not include_player:
                continue

            score_text = f"{score:.2f}"
            existing = team_entry.get(pid, {}) or {}
            raw_lines = [
                line for line in (existing.get("lines") or [])
                if not str(line).startswith("Fantasy Points:")
            ]
            lines = [f"Fantasy Points: {score_text}"] + raw_lines

            new_entry = {
                "name": get_player_name(pid),
                "position": player_info.get("position", ""),
                "lines": lines,
            }

            accepted_players += 1
            if team_entry.get(pid) != new_entry:
                team_entry[pid] = new_entry
                changed = True

    if changed:
        save_week_player_stats(week_player_stats)

    print(
        f"Sleeper weekly stats scan for Week {current_week}: "
        f"{len(matchups)} fantasy teams returned, "
        f"{accepted_players} player score(s) eligible for the cumulative feed, "
        f"changed={changed}."
    )

    return changed


def build_weekly_stats_chunks(current_week, rosters_data, user_names, week_data):
    """
    Build the clean cumulative weekly player-stat feed for ROSTER_STATS_CHANNEL_ID.

    Discord text messages are limited to 2,000 characters, so a 32-team league
    cannot fit into one literal message. We therefore maintain the minimum number
    of fixed messages necessary and edit those same messages throughout the week.
    No emojis are used in this feed.
    """
    teams_data = week_data.get("teams", {}) or {}
    team_names = []

    for roster in rosters_data:
        owner_id = roster.get("owner_id")
        team_name = user_names.get(owner_id, "Unknown House")
        if team_name not in team_names:
            team_names.append(team_name)

    blocks = []

    for team_name in team_names:
        players = teams_data.get(team_name, {}) or {}
        lines = [f"**{team_name}**"]

        if players:
            # Keep output stable and easy for another bot to parse.
            player_rows = list(players.values())
            player_rows.sort(key=lambda p: (p.get("position", ""), p.get("name", "")))

            for player in player_rows:
                name = player.get("name", "Unknown Player")
                position = player.get("position", "")
                heading = f"{name} ({position})" if position else name
                lines.append(heading)
                for stat_line in player.get("lines", []) or []:
                    lines.append(stat_line)
        else:
            lines.append("No completed player stats yet.")

        blocks.append("\n".join(lines))

    chunks = []
    current = f"**WEEK {current_week} - NFL PLAYER STATS**\n\n"

    for block in blocks:
        candidate = current + block + "\n\n"
        if len(candidate) <= 1900:
            current = candidate
            continue

        if current.strip():
            chunks.append(current.rstrip())

        current = (
            f"**WEEK {current_week} - NFL PLAYER STATS (CONTINUED)**\n\n"
            + block
            + "\n\n"
        )

        # Safety fallback for an unusually large single team block.
        while len(current) > 1900:
            split_at = current.rfind("\n", 0, 1900)
            if split_at <= 0:
                split_at = 1900
            chunks.append(current[:split_at].rstrip())
            current = (
                f"**WEEK {current_week} - NFL PLAYER STATS (CONTINUED)**\n\n"
                + current[split_at:].lstrip()
            )

    if current.strip():
        chunks.append(current.rstrip())

    return chunks or [f"**WEEK {current_week} - NFL PLAYER STATS**\n\nNo completed player stats yet."]




async def backfill_weekly_stats_from_detailed_channel(current_week, week_data):
    """Seed the cumulative weekly feed from this bot's recent detailed stats posts.

    This is primarily a migration/recovery path. Older versions of the bot could
    successfully post detailed GAME FINAL player stats but fail to persist those
    same stats into week_player_stats.json. Reading our own recent Discord posts
    lets the clean cumulative feed recover those already-published results.
    """
    channel = bot.get_channel(STATS_CHANNEL_ID)
    if channel is None:
        print(f"Could not find detailed stats channel for weekly backfill: {STATS_CHANNEL_ID}")
        return False

    changed = False
    cutoff = datetime.now(central) - timedelta(days=3)

    try:
        async for msg in channel.history(limit=250, after=cutoff, oldest_first=True):
            # Only trust messages created by this bot.
            if bot.user is not None and msg.author.id != bot.user.id:
                continue

            content = msg.content or ""
            if "GAME FINAL:" not in content:
                continue

            current_team = None
            current_player = None
            current_position = ""
            current_lines = []

            def commit_player():
                nonlocal changed, current_player, current_position, current_lines
                if not current_team or not current_player or not current_lines:
                    current_player = None
                    current_position = ""
                    current_lines = []
                    return

                team_entry = week_data.setdefault("teams", {}).setdefault(
                    current_team, {}
                )
                player_key = current_player.lower()
                new_entry = {
                    "name": current_player,
                    "position": current_position,
                    "lines": list(current_lines),
                }
                if team_entry.get(player_key) != new_entry:
                    team_entry[player_key] = new_entry
                    changed = True

                current_player = None
                current_position = ""
                current_lines = []

            for raw_line in content.splitlines():
                line = raw_line.strip()
                if not line:
                    continue

                # Fantasy-team heading from the detailed stats post.
                if line.startswith("🏰 **") and line.endswith("**"):
                    commit_player()
                    current_team = line[len("🏰 **"):-2].strip()
                    continue

                # Player heading, e.g. **Player Name** (WR)
                if line.startswith("**") and "**" in line[2:]:
                    end = line.find("**", 2)
                    candidate_name = line[2:end].strip()
                    remainder = line[end + 2:].strip()
                    if candidate_name and remainder.startswith("(") and remainder.endswith(")"):
                        commit_player()
                        current_player = candidate_name
                        current_position = remainder[1:-1].strip()
                        continue

                if current_player and ":" in line:
                    current_lines.append(line)

            commit_player()

    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"Could not read detailed stats history for weekly backfill: {e}")
        return False

    if changed:
        save_week_player_stats(week_player_stats)
        print(
            f"Recovered completed player stats for Week {current_week} "
            "from recent detailed Stats-channel posts."
        )

    return changed


async def sync_weekly_stats_feed(current_week, rosters_data, user_names, week_data):
    """Edit the dedicated weekly stats feed in place instead of posting new updates."""
    channel = bot.get_channel(ROSTER_STATS_CHANNEL_ID)
    if channel is None:
        print(
            f"Could not find cumulative NFL player stats channel: "
            f"{ROSTER_STATS_CHANNEL_ID}"
        )
        return False

    week_key = str(current_week)
    chunks = build_weekly_stats_chunks(
        current_week, rosters_data, user_names, week_data
    )
    ids = weekly_stats_message_ids.setdefault(week_key, [])
    synced_ids = []

    for index, content in enumerate(chunks):
        message = None

        if index < len(ids):
            try:
                message = await channel.fetch_message(int(ids[index]))
            except discord.NotFound:
                message = None
            except (discord.Forbidden, discord.HTTPException) as e:
                print(
                    f"Could not fetch weekly stats message {ids[index]}: {e}"
                )
                return False

        try:
            if message is None:
                message = await channel.send(content)
            else:
                await message.edit(content=content)
            synced_ids.append(str(message.id))
        except discord.HTTPException as e:
            print(f"Could not sync cumulative weekly stats message: {e}")
            return False

    # If an earlier version used more chunks, remove obsolete extras so stale
    # information is not left behind in the data-feed channel.
    for old_id in ids[len(chunks):]:
        try:
            old_message = await channel.fetch_message(int(old_id))
            await old_message.delete()
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"Could not remove obsolete weekly stats message {old_id}: {e}")

    weekly_stats_message_ids[week_key] = synced_ids
    save_weekly_stats_message_ids(weekly_stats_message_ids)
    print(
        f"Synced Week {current_week} cumulative player stats across "
        f"{len(synced_ids)} fixed Discord message(s)."
    )
    return True

def get_nfl_games():
    url = (
        "https://site.api.espn.com/apis/site/v2/"
        "sports/football/nfl/scoreboard"
    )

    try:
        data = get_json(url)
        return data.get("events", [])
    except Exception as e:
        print(f"NFL scoreboard error: {e}")
        return []


def get_recent_nfl_games(days_back=3):
    """Return ESPN NFL games for today plus recent dates.

    The normal ESPN scoreboard endpoint can roll over to the current day's
    slate, which means a completed game from last night may disappear before
    the player-stats checker sees it.  Querying explicit dates lets the stats
    task backfill finals after a restart or temporary outage.
    """
    events_by_id = {}
    today = datetime.now(central).date()

    for days_ago in range(days_back + 1):
        game_date = today.fromordinal(today.toordinal() - days_ago)
        date_string = game_date.strftime("%Y%m%d")
        url = (
            "https://site.api.espn.com/apis/site/v2/"
            f"sports/football/nfl/scoreboard?dates={date_string}"
        )

        try:
            data = get_json(url)
            for event in data.get("events", []) or []:
                event_id = event.get("id")
                if event_id:
                    events_by_id[str(event_id)] = event
        except Exception as e:
            print(f"NFL scoreboard error for {date_string}: {e}")

    return list(events_by_id.values())


# --- Individual player game stats, pulled from ESPN's box scores. ---
# --- Best-effort: matches players by name since ESPN and Sleeper ---
# --- use different player ID systems. ---
STAT_LABELS_BY_CATEGORY = {
    "passing": ["C/ATT", "YDS", "TD", "INT"],
    "rushing": ["CAR", "YDS", "TD"],
    "receiving": ["REC", "YDS", "TD"],
    "kicking": ["FG", "XP", "PTS"],
    "defensive": ["TOT", "SACKS", "INT", "TD"],
}


reported_final_games = load_id_set(os.path.join(DATA_DIR, "reported_final_games.json"))
last_live_update = None


@tasks.loop(minutes=NFL_CHECK_INTERVAL)
async def nfl_game_checker():
    global last_live_update

    try:
        games = get_nfl_games()

        if not games:
            return

        print("🏈 NFL GAME CHECK")

        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        current_week = int(
            nfl_state.get("week", 1)
        )

        live_game_found = False
        now = datetime.now(central)

        for game in games:
            competition = game.get(
                "competitions",
                [{}]
            )[0]

            status = game.get(
                "status",
                {}
            ).get(
                "type",
                {}
            )

            state = status.get(
                "state",
                "unknown"
            )

            completed = status.get(
                "completed",
                False
            )

            competitors = competition.get(
                "competitors",
                []
            )

            if len(competitors) < 2:
                continue

            away = competitors[1]
            home = competitors[0]

            away_team = away.get(
                "team",
                {}
            ).get(
                "abbreviation",
                "AWAY"
            )

            home_team = home.get(
                "team",
                {}
            ).get(
                "abbreviation",
                "HOME"
            )

            away_score = away.get(
                "score",
                "0"
            )

            home_score = home.get(
                "score",
                "0"
            )

            game_id = game.get("id")

            print(
                f"{away_team} {away_score} "
                f"@ {home_team} {home_score} "
                f"| {state} "
                f"| completed={completed}"
            )

            if state == "in":
                live_game_found = True

            if not completed:
                continue

            if game_id in reported_final_games:
                continue

            # Lock this NFL game BEFORE posting so a later error cannot cause
            # the same final score to be announced again on the next polling
            # cycle. If the final-score send itself fails, remove the lock so
            # the bot can retry later.
            reported_final_games.add(game_id)
            save_id_set(
                os.path.join(DATA_DIR, "reported_final_games.json"),
                reported_final_games
            )

            final_message = (
                "🏁 **NFL FINAL** 🏁\n\n"
                f"🏈 **{away_team}** {away_score} "
                f"— **{home_team}** {home_score}"
            )

            try:
                await send_to_channel(
                    NFL_SCORE_CHANNEL_ID,
                    final_message
                )
            except Exception:
                reported_final_games.discard(game_id)
                save_id_set(
                    os.path.join(DATA_DIR, "reported_final_games.json"),
                    reported_final_games
                )
                raise

            # Fantasy matchup scores can still be posted after the NFL final,
            # but a failure here will NOT make the NFL final post again.
            try:
                messages = await get_fantasy_matchup_message(
                    current_week
                )

                fantasy_header = (
                    f"⚔️ **GAME OF ZONES — WEEK "
                    f"{current_week} FINAL FANTASY SCORES** ⚔️\n\n"
                )

                if messages:
                    messages[0] = fantasy_header + messages[0]

                for message in messages:
                    await send_to_channel(
                        NFL_SCORE_CHANNEL_ID,
                        message
                    )
            except Exception as e:
                print(
                    f"Fantasy score posting error after "
                    f"{away_team} @ {home_team}: {e}"
                )

            print(
                f"🏁 NFL final posted once for "
                f"{away_team} @ {home_team}."
            )

        if live_game_found:
            should_post_live_update = (
                last_live_update is None
                or (
                    now - last_live_update
                ).total_seconds() >= 3600
            )

            if should_post_live_update:
                messages = await get_fantasy_matchup_message(
                    current_week
                )

                live_header = (
                    "🔴 **NFL GAMES ARE LIVE** 🔴\n\n"
                    f"⚔️ **GAME OF ZONES — WEEK "
                    f"{current_week} LIVE FANTASY SCORES** ⚔️\n\n"
                )

                if messages:
                    messages[0] = (
                        live_header + messages[0]
                    )

                for message in messages:
                    await send_to_channel(
                        NFL_SCORE_CHANNEL_ID,
                        message
                    )

                last_live_update = now

                print(
                    "📊 Live fantasy scores posted."
                )

    except Exception as e:
        print(
            f"NFL game checker error: {e}"
        )

async def get_fantasy_matchup_message(week):
    try:
        matchups_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/matchups/{week}"
        )

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        matchups = get_json(matchups_url)
        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        matchup_groups = {}

        for matchup in matchups:
            matchup_id = matchup.get("matchup_id")

            if matchup_id is not None:
                matchup_groups.setdefault(
                    matchup_id,
                    []
                ).append(matchup)

        if not matchup_groups:
            return [
                f"⚔️ **WEEK {week} — FANTASY BATTLES** ⚔️\n\n"
                "No fantasy matchups are available yet."
            ]

        messages = []

        current_message = (
            f"⚔️ **GAME OF ZONES — WEEK {week} "
            f"FANTASY BATTLES** ⚔️\n\n"
        )

        for matchup_id, teams in matchup_groups.items():

            if len(teams) < 2:
                continue

            team1 = teams[0]
            team2 = teams[1]

            name1 = roster_names.get(
                team1.get("roster_id"),
                "Unknown House"
            )

            name2 = roster_names.get(
                team2.get("roster_id"),
                "Unknown House"
            )

            score1 = team1.get(
                "points",
                0
            ) or 0

            score2 = team2.get(
                "points",
                0
            ) or 0

            if score1 > score2:
                result1 = "🏆"
                result2 = "💀"
            elif score2 > score1:
                result1 = "💀"
                result2 = "🏆"
            else:
                result1 = "🤝"
                result2 = "🤝"

            matchup_text = (
                f"{result1} **{name1}** — "
                f"{score1:.2f}\n"
                f"{result2} **{name2}** — "
                f"{score2:.2f}\n\n"
            )

            if len(current_message) + len(matchup_text) > 1900:
                messages.append(current_message)
                current_message = ""

            current_message += matchup_text

        if current_message.strip():
            messages.append(current_message)

        return messages

    except Exception as e:
        print(
            f"Fantasy matchup formatting error: {e}"
        )

        return [
            "⚠️ I couldn't retrieve the fantasy "
            "matchups from Sleeper."
        ]

@bot.command()
async def hello(ctx):
    await ctx.send(
        "🏰 The Game of Zones Bot has arrived! 🏈\n"
        "All hail the fantasy football league!"
    )


@bot.command()
async def teams(ctx):
    url = f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/users"

    try:
        users = get_json(url)

        message = "🏰 **GAME OF ZONES — THE HOUSES** 🏰\n\n"

        for i, user in enumerate(users, start=1):
            team_name = user.get("metadata", {}).get("team_name")

            if not team_name:
                team_name = user.get(
                    "display_name",
                    "Unknown House"
                )

            message += f"**{i}.** {team_name}\n"

        await ctx.send(message)

    except Exception as e:
        print(f"Teams error: {e}")
        await ctx.send(
            "⚠️ I couldn't retrieve the league teams from Sleeper."
        )


@bot.command()
async def standings(ctx):
    rosters_url = (
        f"https://api.sleeper.app/v1/league/"
        f"{LEAGUE_ID}/rosters"
    )

    users_url = (
        f"https://api.sleeper.app/v1/league/"
        f"{LEAGUE_ID}/users"
    )

    try:
        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        standings_list = []

        for roster in rosters:
            owner_id = roster.get("owner_id")
            settings = roster.get("settings", {})

            wins = settings.get("wins", 0)
            losses = settings.get("losses", 0)
            ties = settings.get("ties", 0)
            points = settings.get("fpts", 0)

            team_name = user_names.get(
                owner_id,
                "Unknown House"
            )

            standings_list.append({
                "team": team_name,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "points": points
            })

        standings_list.sort(
            key=lambda x: (
                x["wins"],
                x["points"]
            ),
            reverse=True
        )

        message = (
            "🏆 **GAME OF ZONES — STANDINGS** 🏆\n\n"
        )

        for i, team in enumerate(
            standings_list,
            start=1
        ):
            message += (
                f"**{i}. {team['team']}** — "
                f"{team['wins']}-"
                f"{team['losses']}-"
                f"{team['ties']} "
                f"({team['points']} pts)\n"
            )

        await send_to_channel(
            STANDINGS_CHANNEL_ID,
            message
        )

    except Exception as e:
        print(f"Standings error: {e}")
        await ctx.send(
            "⚠️ I couldn't retrieve the standings from Sleeper."
        )


@bot.command()
async def scores(ctx, week: int = None):
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        if week is None:
            week = nfl_state.get("week", 1)

        matchups_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/matchups/{week}"
        )

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        matchups = get_json(matchups_url)
        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        message = (
            f"🏈 **GAME OF ZONES — WEEK {week} "
            f"SCORES** 🏈\n\n"
        )

        matchup_groups = {}

        for matchup in matchups:
            matchup_id = matchup.get("matchup_id")

            if matchup_id is not None:
                matchup_groups.setdefault(
                    matchup_id,
                    []
                ).append(matchup)

        if not matchup_groups:
            message += "⚔️ No matchups are available yet."

        else:
            for matchup_id, teams in matchup_groups.items():

                if len(teams) < 2:
                    continue

                team1 = teams[0]
                team2 = teams[1]

                roster1 = team1.get("roster_id")
                roster2 = team2.get("roster_id")

                name1 = roster_names.get(
                    roster1,
                    "Unknown House"
                )

                name2 = roster_names.get(
                    roster2,
                    "Unknown House"
                )

                score1 = team1.get(
                    "points",
                    0
                ) or 0

                score2 = team2.get(
                    "points",
                    0
                ) or 0

                message += (
                    f"⚔️ **{name1}** — {score1}\n"
                    f"🆚 **{name2}** — {score2}\n\n"
                )

        await send_to_channel(
            MATCHUPS_CHANNEL_ID,
            message
        )

    except Exception as e:
        print(f"Scores error: {e}")
        await ctx.send(
            "⚠️ I couldn't retrieve the scores from Sleeper."
        )

@bot.command()
async def recap(ctx, week: int = None):
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        if week is None:
            week = int(nfl_state.get("week", 1)) - 1

        if week < 1:
            await send_to_channel(MATCHUPS_CHANNEL_ID,
                "⚔️ There isn't a completed fantasy week to recap yet."
            )
            return

        matchups_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/matchups/{week}"
        )

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        matchups = get_json(matchups_url)
        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        matchup_groups = {}

        for matchup in matchups:
            matchup_id = matchup.get("matchup_id")

            if matchup_id is not None:
                matchup_groups.setdefault(
                    matchup_id,
                    []
                ).append(matchup)

        results = []

        for teams in matchup_groups.values():

            if len(teams) < 2:
                continue

            team1 = teams[0]
            team2 = teams[1]

            name1 = roster_names.get(
                team1.get("roster_id"),
                "Unknown House"
            )

            name2 = roster_names.get(
                team2.get("roster_id"),
                "Unknown House"
            )

            score1 = team1.get("points", 0) or 0
            score2 = team2.get("points", 0) or 0

            results.append({
                "name1": name1,
                "name2": name2,
                "score1": score1,
                "score2": score2
            })

        if not results:
            await ctx.send(
                f"⚔️ No results are available for Week {week} yet."
            )
            return

        highest_score = None
        lowest_score = None
        closest_game = None

        for result in results:

            for name, score in [
                (result["name1"], result["score1"]),
                (result["name2"], result["score2"])
            ]:

                if (
                    highest_score is None
                    or score > highest_score["score"]
                ):
                    highest_score = {
                        "name": name,
                        "score": score
                    }

                if (
                    lowest_score is None
                    or score < lowest_score["score"]
                ):
                    lowest_score = {
                        "name": name,
                        "score": score
                    }

            difference = abs(
                result["score1"] - result["score2"]
            )

            if (
                closest_game is None
                or difference < closest_game["difference"]
            ):
                closest_game = {
                    "name1": result["name1"],
                    "name2": result["name2"],
                    "score1": result["score1"],
                    "score2": result["score2"],
                    "difference": difference
                }

        message = (
            f"📰 **THE RAVEN HAS ARRIVED — "
            f"WEEK {week} RECAP** 📰\n\n"
        )

        message += (
            f"🔥 **Highest Score:** "
            f"{highest_score['name']} — "
            f"{highest_score['score']:.2f} pts\n\n"
        )

        message += (
            f"💀 **Lowest Score:** "
            f"{lowest_score['name']} — "
            f"{lowest_score['score']:.2f} pts\n\n"
        )

        message += (
            f"⚔️ **Battle of the Week:** "
            f"{closest_game['name1']} "
            f"{closest_game['score1']:.2f} — "
            f"{closest_game['score2']:.2f} "
            f"{closest_game['name2']}\n"
            f"📏 Margin: "
            f"{closest_game['difference']:.2f} pts\n"
        )

        await send_to_channel(MATCHUPS_CHANNEL_ID, message)

    except Exception as e:
        print(f"Recap error: {e}")
        await ctx.send(
            "⚠️ I couldn't create the weekly recap."
        )
@bot.command()
async def streaks(ctx):
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        current_week = int(nfl_state.get("week", 1))
        completed_week = current_week - 1

        if completed_week < 1:
            await ctx.send(
                "🔥 **STREAK TRACKER** 🔥\n\n"
                "⚔️ The first battle has not yet been fought."
            )
            return

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        streaks = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")

            streaks[roster_id] = {
                "wins": 0,
                "losses": 0
            }

        for week in range(1, completed_week + 1):

            matchups_url = (
                f"https://api.sleeper.app/v1/league/"
                f"{LEAGUE_ID}/matchups/{week}"
            )

            matchups = get_json(matchups_url)

            matchup_groups = {}

            for matchup in matchups:
                matchup_id = matchup.get("matchup_id")

                if matchup_id is not None:
                    matchup_groups.setdefault(
                        matchup_id,
                        []
                    ).append(matchup)

            for teams in matchup_groups.values():

                if len(teams) < 2:
                    continue

                team1 = teams[0]
                team2 = teams[1]

                roster1 = team1.get("roster_id")
                roster2 = team2.get("roster_id")

                score1 = team1.get("points", 0) or 0
                score2 = team2.get("points", 0) or 0

                if score1 > score2:
                    streaks[roster1]["wins"] += 1
                    streaks[roster1]["losses"] = 0

                    streaks[roster2]["losses"] += 1
                    streaks[roster2]["wins"] = 0

                elif score2 > score1:
                    streaks[roster2]["wins"] += 1
                    streaks[roster2]["losses"] = 0

                    streaks[roster1]["losses"] += 1
                    streaks[roster1]["wins"] = 0

        message = (
            "🔥 **GAME OF ZONES — STREAK TRACKER** 🔥\n\n"
            "⚔️ *The realm remembers every victory and defeat...*\n\n"
        )

        for roster_id, streak in streaks.items():

            team_name = roster_names.get(
                roster_id,
                "Unknown House"
            )

            if streak["wins"] > 0:
                message += (
                    f"🔥 **{team_name}** — "
                    f"{streak['wins']} game "
                    f"winning streak\n"
                )

            elif streak["losses"] > 0:
                message += (
                    f"💀 **{team_name}** — "
                    f"{streak['losses']} game "
                    f"losing streak\n"
                )

            else:
                message += (
                    f"🤝 **{team_name}** — "
                    f"No current streak\n"
                )

        while len(message) > 2000:
            split_at = message.rfind("\n", 0, 2000)

            if split_at == -1:
                split_at = 2000

            await send_to_channel(STATS_CHANNEL_ID, message[:split_at])
            message = message[split_at:].lstrip()

        await send_to_channel(STATS_CHANNEL_ID, message)

    except Exception as e:
        print(f"Streak tracker error: {e}")
        await send_to_channel(
            STATS_CHANNEL_ID,
            "⚠️ I couldn't retrieve the league streaks from Sleeper."
        )

@bot.command()
async def house(ctx):
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        current_week = int(nfl_state.get("week", 1))
        completed_week = current_week - 1

        if completed_week < 1:
            await ctx.send(
                "🏰 **HOUSE OF THE WEEK** 🏰\n\n"
                "⚔️ The realm has not yet completed its first battle."
            )
            return

        matchups_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/matchups/{completed_week}"
        )

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        matchups = get_json(matchups_url)
        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        matchup_groups = {}

        for matchup in matchups:
            matchup_id = matchup.get("matchup_id")

            if matchup_id is not None:
                matchup_groups.setdefault(
                    matchup_id,
                    []
                ).append(matchup)

        results = []

        for teams in matchup_groups.values():

            if len(teams) < 2:
                continue

            team1 = teams[0]
            team2 = teams[1]

            roster1 = team1.get("roster_id")
            roster2 = team2.get("roster_id")

            score1 = team1.get("points", 0) or 0
            score2 = team2.get("points", 0) or 0

            results.append({
                "name1": roster_names.get(
                    roster1,
                    "Unknown House"
                ),
                "name2": roster_names.get(
                    roster2,
                    "Unknown House"
                ),
                "score1": score1,
                "score2": score2
            })

        if not results:
            await ctx.send(
                f"⚔️ No results are available for Week {completed_week}."
            )
            return

        highest_score = None
        lowest_score = None
        closest_game = None

        for result in results:

            for name, score in [
                (result["name1"], result["score1"]),
                (result["name2"], result["score2"])
            ]:

                if (
                    highest_score is None
                    or score > highest_score["score"]
                ):
                    highest_score = {
                        "name": name,
                        "score": score
                    }

                if (
                    lowest_score is None
                    or score < lowest_score["score"]
                ):
                    lowest_score = {
                        "name": name,
                        "score": score
                    }

            difference = abs(
                result["score1"] - result["score2"]
            )

            if (
                closest_game is None
                or difference < closest_game["difference"]
            ):
                closest_game = {
                    "name1": result["name1"],
                    "name2": result["name2"],
                    "score1": result["score1"],
                    "score2": result["score2"],
                    "difference": difference
                }

        mvp = get_week_mvp(completed_week)

        message = (
            f"🏰 **GAME OF ZONES — WEEK {completed_week} "
            f"HONORS** 🏰\n\n"
            f"👑 **HOUSE OF THE WEEK**\n"
            f"**{highest_score['name']}** — "
            f"{highest_score['score']:.2f} pts\n\n"
            f"💀 **NIGHT KING'S VICTIM**\n"
            f"**{lowest_score['name']}** — "
            f"{lowest_score['score']:.2f} pts\n\n"
            f"⚔️ **BATTLE OF THE WEEK**\n"
            f"**{closest_game['name1']}** — "
            f"{closest_game['score1']:.2f}\n"
            f"vs.\n"
            f"**{closest_game['name2']}** — "
            f"{closest_game['score2']:.2f}\n"
            f"📏 Margin: "
            f"{closest_game['difference']:.2f} pts"
        )

        if mvp:
            message += (
                f"\n\n{mvp['title']}\n"
                f"**{mvp['name']}** ({mvp['position']}) — "
                f"{mvp['points']:.2f} pts, {mvp['team']}"
            )

        await send_to_channel(WEEKLY_WINNERS_CHANNEL_ID, message)

    except Exception as e:
        print(f"House of the Week error: {e}")
        await ctx.send(
            "⚠️ I couldn't retrieve the weekly honors from Sleeper."
        )
@bot.command()
async def records(ctx):
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        current_week = int(nfl_state.get("week", 1))
        completed_week = current_week - 1

        if completed_week < 1:
            await ctx.send(
                "📜 **GAME OF ZONES — LEAGUE RECORDS** 📜\n\n"
                "⚔️ The record books are waiting for the first battle."
            )
            return

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        highest_score = {
            "name": "None",
            "score": -1,
            "week": 0
        }

        lowest_score = {
            "name": "None",
            "score": None,
            "week": 0
        }

        biggest_margin = {
            "winner": "None",
            "loser": "None",
            "margin": -1,
            "week": 0
        }

        closest_game = {
            "team1": "None",
            "team2": "None",
            "margin": None,
            "week": 0
        }

        for week in range(1, completed_week + 1):

            matchups_url = (
                f"https://api.sleeper.app/v1/league/"
                f"{LEAGUE_ID}/matchups/{week}"
            )

            matchups = get_json(matchups_url)

            matchup_groups = {}

            for matchup in matchups:
                matchup_id = matchup.get("matchup_id")

                if matchup_id is not None:
                    matchup_groups.setdefault(
                        matchup_id,
                        []
                    ).append(matchup)

            for teams in matchup_groups.values():

                if len(teams) < 2:
                    continue

                team1 = teams[0]
                team2 = teams[1]

                name1 = roster_names.get(
                    team1.get("roster_id"),
                    "Unknown House"
                )

                name2 = roster_names.get(
                    team2.get("roster_id"),
                    "Unknown House"
                )

                score1 = team1.get("points", 0) or 0
                score2 = team2.get("points", 0) or 0

                for name, score in [
                    (name1, score1),
                    (name2, score2)
                ]:

                    if score > highest_score["score"]:
                        highest_score = {
                            "name": name,
                            "score": score,
                            "week": week
                        }

                    if (
                        lowest_score["score"] is None
                        or score < lowest_score["score"]
                    ):
                        lowest_score = {
                            "name": name,
                            "score": score,
                            "week": week
                        }

                margin = abs(score1 - score2)

                if margin > biggest_margin["margin"]:
                    if score1 > score2:
                        winner = name1
                        loser = name2
                    elif score2 > score1:
                        winner = name2
                        loser = name1
                    else:
                        winner = name1
                        loser = name2

                    biggest_margin = {
                        "winner": winner,
                        "loser": loser,
                        "margin": margin,
                        "week": week
                    }

                if (
                    closest_game["margin"] is None
                    or margin < closest_game["margin"]
                ):
                    closest_game = {
                        "team1": name1,
                        "team2": name2,
                        "margin": margin,
                        "week": week
                    }

        message = (
            "📜 **GAME OF ZONES — LEAGUE RECORDS** 📜\n\n"
            "👑 **HIGHEST SINGLE-WEEK SCORE**\n"
            f"{highest_score['name']} — "
            f"{highest_score['score']:.2f} pts "
            f"(Week {highest_score['week']})\n\n"
            "💀 **LOWEST SINGLE-WEEK SCORE**\n"
            f"{lowest_score['name']} — "
            f"{lowest_score['score']:.2f} pts "
            f"(Week {lowest_score['week']})\n\n"
            "⚔️ **BIGGEST VICTORY**\n"
            f"{biggest_margin['winner']} defeated "
            f"{biggest_margin['loser']} by "
            f"{biggest_margin['margin']:.2f} pts "
            f"(Week {biggest_margin['week']})\n\n"
            "🤏 **CLOSEST BATTLE**\n"
            f"{closest_game['team1']} vs. "
            f"{closest_game['team2']} — "
            f"{closest_game['margin']:.2f} pt margin "
            f"(Week {closest_game['week']})"
        )

        await send_to_channel(RECORDS_CHANNEL_ID, message)

    except Exception as e:
        print(f"League records error: {e}")
        await send_to_channel(
            RECORDS_CHANNEL_ID,
            "⚠️ I couldn't retrieve the league records from Sleeper."
        )

@tasks.loop(
    time=dt_time(
        hour=12,
        minute=0,
        tzinfo=central
    )
)
async def weekly_standings():
    try:
        if datetime.now(central).weekday() != 1:
            return

        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        current_week = int(
            nfl_state.get("week", 1)
        )
        completed_week = current_week - 1

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )
        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        standings_list = []

        for roster in rosters:
            owner_id = roster.get("owner_id")
            settings = roster.get("settings", {})

            wins = settings.get("wins", 0) or 0
            losses = settings.get("losses", 0) or 0
            ties = settings.get("ties", 0) or 0
            points = settings.get("fpts", 0) or 0

            team_name = user_names.get(
                owner_id,
                "Unknown House"
            )

            standings_list.append({
                "team": team_name,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "points": points
            })

        standings_list.sort(
            key=lambda x: (
                x["wins"],
                x["points"]
            ),
            reverse=True
        )

        message = (
            f"🏆 **GAME OF ZONES — STANDINGS** 🏆\n"
            f"📜 *Through Week {completed_week}*\n\n"
        )

        for i, team in enumerate(
            standings_list,
            start=1
        ):
            message += (
                f"**{i}. {team['team']}** — "
                f"{team['wins']}-"
                f"{team['losses']}-"
                f"{team['ties']} "
                f"({team['points']:.2f} pts)\n"
            )

        while len(message) > 2000:
            split_at = message.rfind(
                "\n",
                0,
                2000
            )

            if split_at == -1:
                split_at = 2000

            await send_to_channel(
                STANDINGS_CHANNEL_ID,
                message[:split_at]
            )

            message = message[split_at:].lstrip()

        await send_to_channel(
            STANDINGS_CHANNEL_ID,
            message
        )

        print(
            f"🏆 Automatic Tuesday standings "
            f"posted through Week {completed_week}."
        )

    except Exception as e:
        print(
            f"Automatic standings error: {e}"
        )

@tasks.loop(
    time=dt_time(
        hour=12,
        minute=10,
        tzinfo=central
    )
)
async def weekly_streaks():
    try:
        if datetime.now(central).weekday() != 1:
            return

        stats_channel = bot.get_channel(
            STATS_CHANNEL_ID
        )

        if stats_channel is None:
            print("Weekly streaks: channel not found.")
            return

        await streaks.callback(stats_channel)

        print("🔥 Automatic Tuesday streaks posted.")

    except Exception as e:
        print(f"Weekly streaks error: {e}")

@tasks.loop(
    time=dt_time(
        hour=12,
        minute=0,
        tzinfo=central
    )
)
async def weekly_recap():
    try:
        if datetime.now(central).weekday() != 1:
            return

        matchups_channel = bot.get_channel(
            MATCHUPS_CHANNEL_ID
        )

        if matchups_channel is None:
            print("Weekly recap: Matchups channel not found.")
            return

        await recap.callback(matchups_channel)

        print("📜 Automatic Tuesday recap posted.")

    except Exception as e:
        print(f"Weekly recap error: {e}")

@tasks.loop(
    time=dt_time(
        hour=12,
        minute=10,
        tzinfo=central
    )
)
async def daily_raven():
    """Post one Game of Zones league-only Daily Raven every calendar day."""
    try:
        now = datetime.now(central)
        today_key = now.date().isoformat()

        # Exactly one Daily Raven per Central-time calendar day, including
        # across Railway restarts.
        if daily_raven_state.get("last_post_date") == today_key:
            return

        news_channel = bot.get_channel(NEWS_CHANNEL_ID)

        if news_channel is None:
            print("Daily Raven: News channel not found.")
            return

        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)
        current_week = int(nfl_state.get("week", 1) or 1)

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )
        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )
        matchups_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/matchups/{current_week}"
        )

        rosters = get_json(rosters_url)
        users = get_json(users_url)
        matchups = get_json(matchups_url)
        transactions = get_transactions(current_week)

        user_names = {}
        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get("display_name", "Unknown House")
            )

        roster_names = {}
        for roster in rosters:
            roster_names[roster.get("roster_id")] = user_names.get(
                roster.get("owner_id"),
                "Unknown House"
            )

        # Only include league transactions created in roughly the last 24 hours.
        # Sleeper uses millisecond Unix timestamps for transaction creation.
        cutoff_ms = int((now.timestamp() - 86400) * 1000)
        recent_transactions = []
        for transaction in transactions:
            created = transaction.get("created") or 0
            try:
                created = int(created)
            except (TypeError, ValueError):
                created = 0

            if (
                transaction.get("status") == "complete"
                and created >= cutoff_ms
                and transaction.get("type") in ("trade", "waiver", "free_agent")
            ):
                recent_transactions.append(transaction)

        recent_transactions.sort(
            key=lambda t: int(t.get("created") or 0),
            reverse=True
        )

        raven_items = []

        # Trades, waivers, and free-agent moves are the highest-priority news.
        for transaction in recent_transactions[:5]:
            t_type = transaction.get("type")
            roster_ids = transaction.get("roster_ids") or []

            if t_type == "trade":
                houses = [
                    roster_names.get(rid, "Unknown House")
                    for rid in roster_ids
                ]
                houses = list(dict.fromkeys(houses))

                moved_names = []
                adds = transaction.get("adds") or {}
                for player_id in adds.keys():
                    moved_names.append(get_player_name(player_id))

                if houses:
                    line = "Trade pact between " + " and ".join(houses)
                else:
                    line = "A trade pact was struck between unnamed houses"

                if moved_names:
                    line += ": " + ", ".join(moved_names[:6])
                    if len(moved_names) > 6:
                        line += ", and more"

                raven_items.append(line + ".")

            else:
                team_name = (
                    roster_names.get(roster_ids[0], "Unknown House")
                    if roster_ids else "Unknown House"
                )
                adds = transaction.get("adds") or {}
                drops = transaction.get("drops") or {}
                added = [get_player_name(pid) for pid in adds.keys()]
                dropped = [get_player_name(pid) for pid in drops.keys()]

                if t_type == "waiver":
                    line = f"{team_name} won a waiver claim"
                else:
                    line = f"{team_name} made a free-agent move"

                if added:
                    line += " for " + ", ".join(added[:3])
                if dropped:
                    line += "; cast out " + ", ".join(dropped[:3])

                raven_items.append(line + ".")

        # Add a live Week snapshot using only this league's Sleeper matchup data.
        scored_matchups = [
            m for m in matchups
            if (m.get("points") or 0) > 0
        ]

        if scored_matchups:
            leaders = sorted(
                scored_matchups,
                key=lambda m: float(m.get("points") or 0),
                reverse=True
            )[:3]

            leader_text = ", ".join(
                f"{roster_names.get(m.get('roster_id'), 'Unknown House')} "
                f"({float(m.get('points') or 0):.2f})"
                for m in leaders
            )
            raven_items.append(
                f"Week {current_week}'s highest banners at this hour: {leader_text}."
            )

            matchup_groups = {}
            for matchup in matchups:
                matchup_id = matchup.get("matchup_id")
                if matchup_id is not None:
                    matchup_groups.setdefault(matchup_id, []).append(matchup)

            closest = None
            for teams in matchup_groups.values():
                if len(teams) != 2:
                    continue
                score1 = float(teams[0].get("points") or 0)
                score2 = float(teams[1].get("points") or 0)
                if score1 <= 0 and score2 <= 0:
                    continue
                margin = abs(score1 - score2)
                if closest is None or margin < closest[0]:
                    closest = (margin, teams[0], teams[1])

            if closest is not None:
                margin, team1, team2 = closest
                name1 = roster_names.get(team1.get("roster_id"), "Unknown House")
                name2 = roster_names.get(team2.get("roster_id"), "Unknown House")
                score1 = float(team1.get("points") or 0)
                score2 = float(team2.get("points") or 0)
                raven_items.append(
                    f"The fiercest battle is {name1} {score1:.2f} vs "
                    f"{name2} {score2:.2f}, separated by only {margin:.2f}."
                )

        header = (
            "🦅 **GAME OF ZONES — THE DAILY RAVEN** 🦅\n"
            f"📜 **{now.strftime('%A, %B %d, %Y')}**\n\n"
        )

        if raven_items:
            intros = [
                "A raven has arrived from the Seven Kingdoms of Game of Zones. Here is what the realm whispers today:\n\n",
                "The maesters have broken the seals. Today's whispers from the Game of Zones realm are as follows:\n\n",
                "From waiver camps to battlefield scoreboards, the ravens bring word from across our league:\n\n",
            ]
            message = header + intros[now.toordinal() % len(intros)]

            for item in raven_items:
                candidate = message + f"• {item}\n"
                if len(candidate) > 1850:
                    break
                message = candidate

            closers = [
                "\n*The realm remembers every move. Choose your alliances wisely.*",
                "\n*Winter may be coming, but so are the Sunday matchups.*",
                "\n*The Iron Throne is temporary. Dynasty bragging rights are forever.*",
            ]
            message += closers[now.toordinal() % len(closers)]
        else:
            quiet_messages = [
                (
                    "No banners have fallen, no trade pacts were signed, and the waiver wire is quiet. "
                    "For once, the realm appears peaceful. Varys insists this is suspicious.\n\n"
                    "*Enjoy the silence. Someone is probably plotting a trade.*"
                ),
                (
                    "The ravens returned with blank scrolls. No fresh league drama has reached the Citadel today.\n\n"
                    "*Tyrion recommends checking your lineup before celebrating the peace.*"
                ),
                (
                    "No blood on the trade block. No chaos on the waiver wire. No house has made enough noise "
                    "to wake the Night King.\n\n*The realm rests... for now.*"
                ),
                (
                    "Today's council meeting has been canceled for lack of scandal. The league is quiet, "
                    "which can only mean everyone is secretly negotiating in the DMs.\n\n"
                    "*The Master of Whispers is watching.*"
                ),
            ]
            message = header + quiet_messages[now.toordinal() % len(quiet_messages)]

        # Only mark today complete after Discord successfully receives the Raven.
        await news_channel.send(message)
        daily_raven_state["last_post_date"] = today_key
        save_daily_raven_state(daily_raven_state)
        print(f"League-only Daily Raven posted for {today_key}.")

    except Exception as e:
        print(f"Daily Raven error: {e}")

@tasks.loop(
    time=dt_time(
        hour=12,
        minute=15,
        tzinfo=central
    )
)
async def weekly_power_rankings():
    try:
        if datetime.now(central).weekday() != 1:
            return

        power_channel = bot.get_channel(
            POWER_RANKINGS_CHANNEL_ID
        )

        if power_channel is None:
            print("Power Rankings: channel not found.")
            return

        await power.callback(power_channel)

        print("👑 Automatic Tuesday Power Rankings posted.")

    except Exception as e:
        print(f"Power Rankings error: {e}")

@tasks.loop(
    time=dt_time(
        hour=12,
        minute=20,
        tzinfo=central
    )
)
async def weekly_house():
    try:
        if datetime.now(central).weekday() != 1:
            return

        house_channel = bot.get_channel(
            WEEKLY_WINNERS_CHANNEL_ID
        )

        if house_channel is None:
            print("House of the Week: channel not found.")
            return

        await house.callback(house_channel)

        print("🏰 Automatic Tuesday House of the Week posted.")

    except Exception as e:
        print(f"House of the Week error: {e}")


@tasks.loop(
    time=dt_time(
        hour=12,
        minute=25,
        tzinfo=central
    )
)
async def weekly_achievements():
    try:
        if datetime.now(central).weekday() != 1:
            return

        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        current_week = int(nfl_state.get("week", 1))
        completed_week = current_week - 1

        if completed_week < 1:
            return

        if achievements_data.get("last_checked_week", 0) >= completed_week:
            return

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        matchups_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/matchups/{completed_week}"
        )

        rosters = get_json(rosters_url)
        users = get_json(users_url)
        matchups = get_json(matchups_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        matchup_groups = {}

        for matchup in matchups:
            matchup_id = matchup.get("matchup_id")

            if matchup_id is not None:
                matchup_groups.setdefault(
                    matchup_id,
                    []
                ).append(matchup)

        announcements = []
        streaks = achievements_data.setdefault("current_streaks", {})

        for teams in matchup_groups.values():

            if len(teams) < 2:
                continue

            team1 = teams[0]
            team2 = teams[1]

            roster1 = team1.get("roster_id")
            roster2 = team2.get("roster_id")

            name1 = roster_names.get(roster1, "Unknown House")
            name2 = roster_names.get(roster2, "Unknown House")

            score1 = team1.get("points", 0) or 0
            score2 = team2.get("points", 0) or 0

            for name, score in [(name1, score1), (name2, score2)]:

                if score > achievements_data["high_score"]["score"]:
                    achievements_data["high_score"] = {
                        "team": name,
                        "score": score,
                        "week": completed_week
                    }

                    announcements.append(
                        "👑 **NEW ALL-TIME HIGH SCORE!**\n"
                        f"**{name}** just scored **{score:.2f}** "
                        f"points in Week {completed_week} — the "
                        "highest in Game of Zones history!"
                    )

                if (
                    achievements_data["low_score"]["score"] is None
                    or score < achievements_data["low_score"]["score"]
                ):
                    achievements_data["low_score"] = {
                        "team": name,
                        "score": score,
                        "week": completed_week
                    }

                    announcements.append(
                        "💀 **NEW ALL-TIME LOW SCORE!**\n"
                        f"**{name}** managed only **{score:.2f}** "
                        f"points in Week {completed_week} — a new "
                        "low for the realm."
                    )

            margin = abs(score1 - score2)

            if margin > achievements_data["biggest_margin"]["margin"]:
                winner = name1 if score1 > score2 else name2
                loser = name2 if score1 > score2 else name1

                achievements_data["biggest_margin"] = {
                    "winner": winner,
                    "loser": loser,
                    "margin": margin,
                    "week": completed_week
                }

                announcements.append(
                    "⚔️ **NEW BIGGEST VICTORY!**\n"
                    f"**{winner}** crushed **{loser}** by "
                    f"**{margin:.2f}** points in Week "
                    f"{completed_week} — the largest margin "
                    "ever recorded."
                )

            if (
                achievements_data["closest_game"]["margin"] is None
                or margin < achievements_data["closest_game"]["margin"]
            ):
                achievements_data["closest_game"] = {
                    "team1": name1,
                    "team2": name2,
                    "margin": margin,
                    "week": completed_week
                }

                announcements.append(
                    "🤏 **NEW CLOSEST BATTLE!**\n"
                    f"**{name1}** vs **{name2}** decided by "
                    f"just **{margin:.2f}** points in Week "
                    f"{completed_week} — the tightest game in "
                    "league history."
                )

            for roster_id, team_score, opp_score, team_name in [
                (roster1, score1, score2, name1),
                (roster2, score2, score1, name2)
            ]:
                key = str(roster_id)
                streaks.setdefault(key, {"wins": 0, "losses": 0})

                if team_score > opp_score:
                    streaks[key]["wins"] += 1
                    streaks[key]["losses"] = 0

                    if (
                        streaks[key]["wins"]
                        > achievements_data["longest_win_streak"]["length"]
                    ):
                        achievements_data["longest_win_streak"] = {
                            "team": team_name,
                            "length": streaks[key]["wins"]
                        }

                        announcements.append(
                            "🔥 **NEW LONGEST WIN STREAK!**\n"
                            f"**{team_name}** has now won "
                            f"**{streaks[key]['wins']}** games in "
                            "a row — a new franchise record."
                        )

                elif opp_score > team_score:
                    streaks[key]["losses"] += 1
                    streaks[key]["wins"] = 0

                    if (
                        streaks[key]["losses"]
                        > achievements_data["longest_loss_streak"]["length"]
                    ):
                        achievements_data["longest_loss_streak"] = {
                            "team": team_name,
                            "length": streaks[key]["losses"]
                        }

                        announcements.append(
                            "💀 **NEW LONGEST LOSING STREAK!**\n"
                            f"**{team_name}** has now lost "
                            f"**{streaks[key]['losses']}** games "
                            "in a row — banished to the Wall."
                        )

        achievements_data["last_checked_week"] = completed_week
        save_achievements(achievements_data)

        if announcements:
            message = (
                "🏆 **GAME OF ZONES — ACHIEVEMENTS "
                "UNLOCKED** 🏆\n\n"
            )

            message += "\n\n".join(announcements)

            while len(message) > 2000:
                split_at = message.rfind("\n\n", 0, 2000)

                if split_at == -1:
                    split_at = 2000

                await send_to_channel(
                    ACHIEVEMENTS_CHANNEL_ID,
                    message[:split_at]
                )

                message = message[split_at:].lstrip()

            await send_to_channel(ACHIEVEMENTS_CHANNEL_ID, message)

        print(
            f"🏆 Achievement check complete for "
            f"Week {completed_week}."
        )

    except Exception as e:
        print(f"Achievements error: {e}")


@bot.event
async def on_ready():
    print(
        f"🏰 Game of Zones is online as {bot.user}"
    )

    load_players_cache()

    # Make sure every Sleeper team has one permanent roster post as soon
    # as the bot comes online. Existing posts are edited; missing posts are
    # created. This avoids waiting for the 30-minute roster checker.
    try:
        await sync_all_roster_posts()
        print("✅ All permanent roster posts synced on startup.")
    except Exception as e:
        print(f"Startup roster sync error: {e}")

    if not waiver_checker.is_running():
        waiver_checker.start()

    if not trade_checker.is_running():
        trade_checker.start()

    if not roster_checker.is_running():
        roster_checker.start()

    if not weekly_championship_check.is_running():
        weekly_championship_check.start()

    if not player_stats_checker.is_running():
        player_stats_checker.start()

    try:
        for article in get_nfl_articles(limit=20):
            article_id = article.get("id") or article.get("headline")
            reported_news_ids.add(article_id)
    except Exception as e:
        print(f"NFL news seed error: {e}")

    if not nfl_news_checker.is_running():
        nfl_news_checker.start()

    if not weekly_standings.is_running():
        weekly_standings.start()

    if not weekly_recap.is_running():
        weekly_recap.start()

    if not weekly_streaks.is_running():
        weekly_streaks.start()


    if not daily_raven.is_running():
        daily_raven.start()


    if not nfl_game_checker.is_running():
        nfl_game_checker.start()

    if not weekly_power_rankings.is_running():
        weekly_power_rankings.start()

    if not weekly_house.is_running():
        weekly_house.start()

    if not weekly_achievements.is_running():
        weekly_achievements.start()

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is not set."
    )

@bot.command()
async def news(ctx):
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        current_week = int(nfl_state.get("week", 1))
        completed_week = current_week - 1

        if completed_week < 1:
            await send_to_channel(NEWS_CHANNEL_ID,
                "🦅 **THE RAVENS HAVE NO NEWS... YET** 🦅\n\n"
                "⚔️ The first battle of the season has not been fought."
            )
            return

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        matchups_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/matchups/{completed_week}"
        )

        rosters = get_json(rosters_url)
        users = get_json(users_url)
        matchups = get_json(matchups_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        matchup_groups = {}

        for matchup in matchups:
            matchup_id = matchup.get("matchup_id")

            if matchup_id is not None:
                matchup_groups.setdefault(
                    matchup_id,
                    []
                ).append(matchup)

        results = []

        for teams in matchup_groups.values():
            if len(teams) < 2:
                continue

            team1 = teams[0]
            team2 = teams[1]

            name1 = roster_names.get(
                team1.get("roster_id"),
                "Unknown House"
            )

            name2 = roster_names.get(
                team2.get("roster_id"),
                "Unknown House"
            )

            score1 = team1.get("points", 0) or 0
            score2 = team2.get("points", 0) or 0

            if score1 > score2:
                winner = name1
                loser = name2
                winner_score = score1
                loser_score = score2
            else:
                winner = name2
                loser = name1
                winner_score = score2
                loser_score = score1

            results.append({
                "winner": winner,
                "loser": loser,
                "winner_score": winner_score,
                "loser_score": loser_score,
                "margin": abs(score1 - score2)
            })

        if not results:
            await ctx.send(
                "🦅 **THE RAVENS HAVE NO NEWS... YET** 🦅\n\n"
                "⚔️ No completed battles could be found."
            )
            return

        biggest_win = max(
            results,
            key=lambda game: game["margin"]
        )

        highest_score = max(
            results,
            key=lambda game: game["winner_score"]
        )

        closest_battle = min(
            results,
            key=lambda game: game["margin"]
        )

        message = (
            "🦅 **GAME OF ZONES — THE DAILY RAVEN** 🦅\n"
            f"📜 **Week {completed_week} News**\n\n"

            "👑 **HOUSE OF THE WEEK**\n"
            f"{highest_score['winner']} conquered the realm "
            f"with {highest_score['winner_score']:.2f} points.\n\n"

            "🩸 **BIGGEST VICTORY**\n"
            f"{biggest_win['winner']} destroyed "
            f"{biggest_win['loser']} by "
            f"{biggest_win['margin']:.2f} points.\n\n"

            "⚔️ **BATTLE OF THE WEEK**\n"
            f"{closest_battle['winner']} defeated "
            f"{closest_battle['loser']} by only "
            f"{closest_battle['margin']:.2f} points.\n\n"

            "🐉 **THE REALM HAS SPOKEN.**"
        )

        await send_to_channel(NEWS_CHANNEL_ID, message)
    except Exception as e:
        print(f"League news error: {e}")
        await ctx.send(
            "⚠️ The raven failed to deliver the latest league news."
        )
@bot.command(name="commands")
async def command_menu(ctx):
    message = (
        "🏰 **GAME OF ZONES — COMMANDS** 🏰\n\n"

        "⚔️ **LEAGUE**\n"
        "`!teams` — View all 32 Houses\n"
        "`!standings` — View league standings\n"
        "`!scores` — View current matchups\n"
        "`!recap` — View the latest battle recap\n\n"

        "📜 **RECORDS & STATS** 📜\n"
        "`!streaks` — View winning/losing streaks\n"
        "`!house` — View House statistics + weekly MVP\n"
        "`!records` — View league records\n"
        "`!achievements` — View the Hall of Achievements\n"
        "`!champions` — View the Hall of Champions\n\n"

        "📋 **WAIVER WIRE**\n"
        "`!waivers` — View this week's waiver/FA moves\n\n"

        "🛡️ **ROSTERS**\n"
        "`!rosters` — View every team's full roster\n"
        "📊 Player stats post automatically per game, plus a "
        "final weekly summary — no command needed\n\n"

        "🔄 **TRADE BLOCK**\n"
        "`!trades` — View this week's completed trades\n\n"

        "📰 **NFL NEWS**\n"
        "`!nflnews` — View the latest NFL headlines\n\n"

        "🦅 **THE DAILY RAVEN**\n"
        "`!news` — Get the latest league news\n\n"

        "🐉 **Game of Zones**\n"
        "May the strongest House rule the realm."
    )

    await ctx.send(message)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(
            "❓ I don't recognize that command. "
            "Use `!commands` to see what I can do."
        )
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            "⚠️ You're missing something from that command. "
            "Use `!commands` for help."
        )
        return

    print(f"Command error: {error}")

@bot.command()
async def power(ctx):
    try:
        url = f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/rosters"
        users_url = f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/users"

        rosters = get_json(url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user.get("user_id")] = (
                user.get("metadata", {}).get("team_name")
                or user.get("display_name", "Unknown House")
            )

        rankings = []

        for roster in rosters:
            owner_id = roster.get("owner_id")
            wins = roster.get("settings", {}).get("wins", 0)
            losses = roster.get("settings", {}).get("losses", 0)
            fpts = roster.get("settings", {}).get("fpts", 0)

            team_name = user_names.get(
                owner_id,
                f"House {roster.get('roster_id', '?')}"
            )

            rankings.append({
                "name": team_name,
                "wins": wins,
                "losses": losses,
                "fpts": fpts
            })

        rankings.sort(
            key=lambda x: (x["wins"], x["fpts"]),
            reverse=True
        )

        message = "👑 **GAME OF ZONES — POWER RANKINGS** 👑\n\n"

        for i, team in enumerate(rankings, start=1):
            message += (
                f"**{i}. {team['name']}** — "
                f"{team['wins']}-{team['losses']} "
                f"• {team['fpts']:.1f} pts\n"
            )

        await send_to_channel(
            POWER_RANKINGS_CHANNEL_ID,
            message
        )

    except Exception as e:
        print(f"Power rankings error: {e}")
        await ctx.send(
            "⚠️ The Maesters couldn't calculate the Power Rankings."
        )


@bot.command()
async def achievements(ctx):
    try:
        hs = achievements_data.get("high_score", {})
        ls = achievements_data.get("low_score", {})
        bm = achievements_data.get("biggest_margin", {})
        cg = achievements_data.get("closest_game", {})
        lws = achievements_data.get("longest_win_streak", {})
        lls = achievements_data.get("longest_loss_streak", {})

        message = "🏆 **GAME OF ZONES — HALL OF ACHIEVEMENTS** 🏆\n\n"
        has_any = False

        if hs.get("team"):
            has_any = True
            message += (
                "👑 **All-Time High Score**\n"
                f"{hs['team']} — {hs['score']:.2f} pts "
                f"(Week {hs['week']})\n\n"
            )

        if ls.get("team"):
            has_any = True
            message += (
                "💀 **All-Time Low Score**\n"
                f"{ls['team']} — {ls['score']:.2f} pts "
                f"(Week {ls['week']})\n\n"
            )

        if bm.get("winner"):
            has_any = True
            message += (
                "⚔️ **Biggest Victory**\n"
                f"{bm['winner']} defeated {bm['loser']} by "
                f"{bm['margin']:.2f} pts (Week {bm['week']})\n\n"
            )

        if cg.get("team1"):
            has_any = True
            message += (
                "🤏 **Closest Battle**\n"
                f"{cg['team1']} vs {cg['team2']} — "
                f"{cg['margin']:.2f} pt margin "
                f"(Week {cg['week']})\n\n"
            )

        if lws.get("team"):
            has_any = True
            message += (
                "🔥 **Longest Win Streak**\n"
                f"{lws['team']} — {lws['length']} games\n\n"
            )

        if lls.get("team"):
            has_any = True
            message += (
                "💀 **Longest Losing Streak**\n"
                f"{lls['team']} — {lls['length']} games\n\n"
            )

        if not has_any:
            message += (
                "⚔️ No achievements recorded yet — the realm "
                "awaits its first legend."
            )

        await ctx.send(message)

    except Exception as e:
        print(f"Achievements command error: {e}")
        await ctx.send(
            "⚠️ I couldn't retrieve the Hall of Achievements."
        )


@bot.command()
async def waivers(ctx, week: int = None):
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        if week is None:
            week = int(nfl_state.get("week", 1))

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        transactions = get_transactions(week)

        completed = [
            t for t in transactions
            if t.get("status") == "complete"
            and t.get("type") in ("waiver", "free_agent")
        ]

        if not completed:
            await send_to_channel(
                WAIVER_WIRE_CHANNEL_ID,
                f"📋 **WAIVER WIRE — WEEK {week}** 📋\n\n"
                "⚔️ No waiver or free agent moves have been made yet."
            )
            return

        message = (
            f"📋 **GAME OF ZONES — WEEK {week} "
            f"WAIVER WIRE** 📋\n\n"
        )

        for t in completed:
            roster_ids = t.get("roster_ids", [])

            team_name = (
                roster_names.get(roster_ids[0], "Unknown House")
                if roster_ids
                else "Unknown House"
            )

            adds = t.get("adds") or {}
            drops = t.get("drops") or {}

            add_names = [
                get_player_name(pid) for pid in adds.keys()
            ]

            drop_names = [
                get_player_name(pid) for pid in drops.keys()
            ]

            bid = None

            if t.get("type") == "waiver":
                bid = t.get("settings", {}).get("waiver_bid")

            entry = f"🏰 **{team_name}**\n"

            if add_names:
                entry += "✅ Added: " + ", ".join(add_names) + "\n"

            if drop_names:
                entry += "❌ Dropped: " + ", ".join(drop_names) + "\n"

            if bid is not None:
                entry += f"💰 FAAB Bid: ${bid}\n"

            entry += "\n"
            message += entry

        while len(message) > 2000:
            split_at = message.rfind("\n\n", 0, 2000)

            if split_at == -1:
                split_at = 2000

            await send_to_channel(
                WAIVER_WIRE_CHANNEL_ID,
                message[:split_at]
            )

            message = message[split_at:].lstrip()

        await send_to_channel(WAIVER_WIRE_CHANNEL_ID, message)

    except Exception as e:
        print(f"Waivers error: {e}")
        await send_to_channel(
            WAIVER_WIRE_CHANNEL_ID,
            "⚠️ I couldn't retrieve waiver wire moves from Sleeper."
        )


REPORTED_TRANSACTIONS_FILE = os.path.join(DATA_DIR, "reported_transactions.json")
reported_transactions = {str(x) for x in load_id_set(REPORTED_TRANSACTIONS_FILE)}


@tasks.loop(minutes=30)
async def waiver_checker():
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)
        week = int(nfl_state.get("week", 1))

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        transactions = get_transactions(week)

        for t in transactions:
            if t.get("status") != "complete":
                continue

            if t.get("type") not in ("waiver", "free_agent"):
                continue

            transaction_id = str(t.get("transaction_id") or "").strip()

            if not transaction_id:
                # Sleeper transactions should always have an ID. Avoid posting
                # an untrackable transaction that could repeat forever.
                continue

            if transaction_id in reported_transactions:
                continue

            roster_ids = t.get("roster_ids", [])

            team_name = (
                roster_names.get(roster_ids[0], "Unknown House")
                if roster_ids
                else "Unknown House"
            )

            adds = t.get("adds") or {}
            drops = t.get("drops") or {}

            add_names = [
                get_player_name(pid) for pid in adds.keys()
            ]

            drop_names = [
                get_player_name(pid) for pid in drops.keys()
            ]

            bid = None

            if t.get("type") == "waiver":
                bid = t.get("settings", {}).get("waiver_bid")

            message = (
                "📋 **WAIVER WIRE MOVE** 📋\n\n"
                f"🏰 **{team_name}**\n"
            )

            if add_names:
                message += "✅ Added: " + ", ".join(add_names) + "\n"

            if drop_names:
                message += "❌ Dropped: " + ", ".join(drop_names) + "\n"

            if bid is not None:
                message += f"💰 FAAB Bid: ${bid}\n"

            # Reserve the Sleeper transaction ID before sending so a restart
            # or later error cannot cause the same move to be announced again.
            reported_transactions.add(transaction_id)
            save_id_set(REPORTED_TRANSACTIONS_FILE, reported_transactions)

            try:
                await send_to_channel(WAIVER_WIRE_CHANNEL_ID, message)
            except Exception:
                # If Discord itself failed to post, remove the reservation so
                # the checker can retry on its next pass.
                reported_transactions.discard(transaction_id)
                save_id_set(REPORTED_TRANSACTIONS_FILE, reported_transactions)
                raise

    except Exception as e:
        print(f"Waiver checker error: {e}")


@bot.command()
async def trades(ctx, week: int = None):
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        if week is None:
            week = int(nfl_state.get("week", 1))

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        transactions = get_transactions(week)

        completed_trades = [
            t for t in transactions
            if t.get("status") == "complete"
            and t.get("type") == "trade"
        ]

        if not completed_trades:
            await send_to_channel(
                TRADE_BLOCK_CHANNEL_ID,
                f"🔄 **TRADE BLOCK — WEEK {week}** 🔄\n\n"
                "⚔️ No trades have been made yet."
            )
            return

        message = (
            f"🔄 **GAME OF ZONES — WEEK {week} "
            f"TRADES** 🔄\n\n"
        )

        for t in completed_trades:
            message += format_trade(t, roster_names) + "\n"

        while len(message) > 2000:
            split_at = message.rfind("\n\n", 0, 2000)

            if split_at == -1:
                split_at = 2000

            await send_to_channel(
                TRADE_BLOCK_CHANNEL_ID,
                message[:split_at]
            )

            message = message[split_at:].lstrip()

        await send_to_channel(TRADE_BLOCK_CHANNEL_ID, message)

    except Exception as e:
        print(f"Trades error: {e}")
        await send_to_channel(
            TRADE_BLOCK_CHANNEL_ID,
            "⚠️ I couldn't retrieve trades from Sleeper."
        )


REPORTED_TRADES_FILE = os.path.join(DATA_DIR, "reported_trades.json")
reported_trades = {str(x) for x in load_id_set(REPORTED_TRADES_FILE)}


@tasks.loop(minutes=30)
async def trade_checker():
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)
        week = int(nfl_state.get("week", 1))

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        rosters = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        transactions = get_transactions(week)

        for t in transactions:
            if t.get("status") != "complete":
                continue

            if t.get("type") != "trade":
                continue

            transaction_id = str(t.get("transaction_id") or "").strip()

            if not transaction_id:
                continue

            if transaction_id in reported_trades:
                continue

            message = format_trade(t, roster_names)

            # Reserve before posting for true once-only behavior across
            # repeated polling and bot restarts.
            reported_trades.add(transaction_id)
            save_id_set(REPORTED_TRADES_FILE, reported_trades)

            try:
                await send_to_channel(TRADE_BLOCK_CHANNEL_ID, message)
            except Exception:
                reported_trades.discard(transaction_id)
                save_id_set(REPORTED_TRADES_FILE, reported_trades)
                raise

    except Exception as e:
        print(f"Trade checker error: {e}")


@bot.command()
async def nflnews(ctx):
    try:
        articles = get_nfl_articles(limit=5)

        if not articles:
            await ctx.send(
                "⚠️ No NFL news is available right now."
            )
            return

        message = "📰 **LATEST NFL NEWS** 📰\n\n"

        for article in articles:
            headline = article.get("headline", "Untitled")
            url = article.get("links", {}).get("web", {}).get("href", "")

            message += f"🏈 **{headline}**\n"

            if url:
                message += f"{url}\n"

            message += "\n"

        await ctx.send(message)

    except Exception as e:
        print(f"NFL news error: {e}")
        await ctx.send(
            "⚠️ I couldn't retrieve NFL news right now."
        )


reported_news_ids = set()


@tasks.loop(minutes=15)
async def nfl_news_checker():
    try:
        articles = get_nfl_articles(limit=20)

        for article in articles:
            article_id = article.get("id") or article.get("headline")

            if article_id in reported_news_ids:
                continue

            headline = article.get("headline", "Untitled")
            description = article.get("description", "")
            url = article.get("links", {}).get("web", {}).get("href", "")

            combined_text = f"{headline} {description}"

            if is_injury_headline(combined_text):
                message = (
                    "🚑 **INJURY UPDATE** 🚑\n\n"
                    f"🏈 **{headline}**\n"
                )

                if description:
                    message += f"{description}\n"

                if url:
                    message += f"{url}\n"

                await send_to_channel(INJURY_NEWS_CHANNEL_ID, message)

            else:
                message = (
                    "📰 **NFL NEWS** 📰\n\n"
                    f"🏈 **{headline}**\n"
                )

                if description:
                    message += f"{description}\n"

                if url:
                    message += f"{url}\n"

                await send_to_channel(NFL_NEWS_CHANNEL_ID, message)

            reported_news_ids.add(article_id)

    except Exception as e:
        print(f"NFL news checker error: {e}")


def format_roster_entry(roster, team_name):
    """Build one team's compact roster entry with no emojis."""
    starters = roster.get("starters", []) or []
    all_players = roster.get("players", []) or []

    bench = [
        player_id for player_id in all_players
        if player_id not in starters
    ]

    starter_names = [
        get_player_name(player_id)
        for player_id in starters
        if player_id and player_id != "0"
    ]

    bench_names = [
        get_player_name(player_id)
        for player_id in bench
        if player_id and player_id != "0"
    ]

    starters_text = ", ".join(starter_names) if starter_names else "None"
    bench_text = ", ".join(bench_names) if bench_names else "None"

    return (
        f"**{team_name}**\n"
        f"**Starters:** {starters_text}\n"
        f"**Bench:** {bench_text}"
    )


def build_roster_messages(rosters_data, user_names):
    """Build the full league roster list in the original compact format."""
    entries = []

    # Keep every team in Sleeper roster-ID order so the list stays stable.
    sorted_rosters = sorted(
        rosters_data,
        key=lambda roster: roster.get("roster_id") or 0
    )

    for roster in sorted_rosters:
        owner_id = roster.get("owner_id")
        roster_id = roster.get("roster_id")
        team_name = user_names.get(
            owner_id,
            f"House {roster_id}" if roster_id is not None else "Unknown House"
        )
        entries.append(format_roster_entry(roster, team_name))

    # The format the commissioner supplied showed 8 teams per Discord post.
    # A 32-team league therefore stays in four fixed roster posts. Whenever a
    # roster changes, sync_all_roster_posts() edits these same four messages.
    messages = []
    teams_per_post = 8

    for start in range(0, len(entries), teams_per_post):
        group = entries[start:start + teams_per_post]
        content = "\n\n".join(group)

        # Safety fallback in case unusually long names push a group above
        # Discord's 2,000-character message limit. Never drop a team.
        if len(content) <= 1990:
            messages.append(content)
            continue

        current = ""
        for entry in group:
            addition = entry if not current else "\n\n" + entry
            if current and len(current) + len(addition) > 1990:
                messages.append(current)
                current = entry
            else:
                current += addition
        if current:
            messages.append(current)

    return messages


async def sync_all_roster_posts():
    """Edit the permanent full-roster posts so all league teams are represented."""
    rosters_url = (
        f"https://api.sleeper.app/v1/league/"
        f"{LEAGUE_ID}/rosters"
    )

    users_url = (
        f"https://api.sleeper.app/v1/league/"
        f"{LEAGUE_ID}/users"
    )

    rosters_data = get_json(rosters_url)
    users = get_json(users_url)

    user_names = {}

    for user in users:
        user_names[user["user_id"]] = (
            user.get("metadata", {}).get("team_name")
            or user.get("display_name", "Unknown House")
        )

    channel = bot.get_channel(ROSTERS_CHANNEL_ID)
    if channel is None:
        try:
            channel = await bot.fetch_channel(ROSTERS_CHANNEL_ID)
        except discord.HTTPException as e:
            raise RuntimeError(
                f"Could not access Rosters channel {ROSTERS_CHANNEL_ID}: {e}"
            ) from e

    contents = build_roster_messages(rosters_data, user_names)
    updated_ids = []

    for index, content in enumerate(contents):
        message = None

        if index < len(roster_message_ids):
            try:
                message = await channel.fetch_message(
                    int(roster_message_ids[index])
                )
            except (discord.NotFound, ValueError, TypeError):
                message = None
            except discord.Forbidden as e:
                raise RuntimeError(
                    "The bot does not have permission to read/edit roster posts."
                ) from e
            except discord.HTTPException as e:
                print(f"Could not fetch roster post {index + 1}: {e}")
                message = None

        if message is not None:
            await message.edit(content=content)
        else:
            message = await channel.send(content)

        updated_ids.append(str(message.id))

    # If the number of chunks ever becomes smaller, remove only extra posts
    # created by this grouped-roster system so stale roster data is not left behind.
    for old_message_id in roster_message_ids[len(contents):]:
        try:
            old_message = await channel.fetch_message(int(old_message_id))
            await old_message.delete()
        except (discord.NotFound, ValueError, TypeError):
            pass
        except discord.HTTPException as e:
            print(f"Could not remove old roster post {old_message_id}: {e}")

    roster_message_ids[:] = updated_ids
    save_roster_message_ids(roster_message_ids)

    print(
        f"Synced {len(rosters_data)} Sleeper rosters across "
        f"{len(updated_ids)} Discord roster posts."
    )
    return rosters_data


@bot.command()
async def rosters(ctx):
    try:
        rosters_data = await sync_all_roster_posts()

        for roster in rosters_data:
            key = str(roster.get("roster_id"))
            roster_snapshots[key] = {
                "players": sorted(roster.get("players", []) or []),
                "starters": list(roster.get("starters", []) or [])
            }

        save_roster_snapshots(roster_snapshots)

        await ctx.send(
            f"The roster channel has been synced with all "
            f"{len(rosters_data)} Sleeper teams."
        )

    except Exception as e:
        print(f"Rosters error: {e}")
        await ctx.send(
            "I couldn't retrieve or update the team rosters from Sleeper."
        )


@tasks.loop(minutes=30)
async def roster_checker():
    try:
        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        rosters_data = get_json(rosters_url)
        needs_sync = not roster_message_ids

        for roster in rosters_data:
            key = str(roster.get("roster_id"))
            current_players = sorted(roster.get("players", []) or [])
            current_starters = list(roster.get("starters", []) or [])
            previous = roster_snapshots.get(key)

            if isinstance(previous, list):
                previous_players = sorted(previous)
                previous_starters = None
            elif isinstance(previous, dict):
                previous_players = sorted(previous.get("players", []) or [])
                previous_starters = list(previous.get("starters", []) or [])
            else:
                previous_players = None
                previous_starters = None

            if (
                previous_players != current_players
                or (
                    previous_starters is not None
                    and previous_starters != current_starters
                )
            ):
                needs_sync = True

            roster_snapshots[key] = {
                "players": current_players,
                "starters": current_starters
            }

        # Any roster change refreshes the entire grouped roster display, keeping
        # all 32 teams together and preventing one-off transaction messages.
        if needs_sync:
            await sync_all_roster_posts()

        save_roster_snapshots(roster_snapshots)

    except Exception as e:
        print(f"Roster checker error: {e}")


@tasks.loop(
    time=dt_time(
        hour=12,
        minute=30,
        tzinfo=central
    )
)
async def weekly_championship_check():
    try:
        if datetime.now(central).weekday() != 1:
            return

        league_info = get_league_info()

        if league_info.get("status") != "complete":
            return

        season = league_info.get("season")

        if not season or season in champions_data["seasons"]:
            return

        bracket = get_winners_bracket()

        championship_match = next(
            (m for m in bracket if m.get("p") == 1),
            None
        )

        if not championship_match:
            return

        champion_roster_id = championship_match.get("w")
        runner_up_roster_id = championship_match.get("l")

        if champion_roster_id is None:
            return

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        rosters_data = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        roster_names = {}

        for roster in rosters_data:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            roster_names[roster_id] = user_names.get(
                owner_id,
                "Unknown House"
            )

        champion_name = roster_names.get(
            champion_roster_id,
            "Unknown House"
        )

        runner_up_name = roster_names.get(
            runner_up_roster_id,
            "Unknown House"
        ) if runner_up_roster_id is not None else None

        champions_data["seasons"][season] = {
            "champion": champion_name,
            "runner_up": runner_up_name,
            "league_id": LEAGUE_ID
        }

        save_champions(champions_data)

        message = (
            "👑 **A NEW RULER SITS THE IRON THRONE** 👑\n\n"
            f"🏆 **{season} Season Champion:**\n"
            f"**{champion_name}**\n\n"
        )

        if runner_up_name:
            message += (
                f"🥈 **Runner-Up:**\n{runner_up_name}\n\n"
            )

        message += "🐉 *All hail the new Ruler of the Realm.*"

        await send_to_channel(CHAMPIONSHIP_HISTORY_CHANNEL_ID, message)

        print(f"👑 Champion recorded for {season} season.")

    except Exception as e:
        print(f"Championship check error: {e}")


@bot.command()
async def champions(ctx):
    try:
        seasons = champions_data.get("seasons", {})

        if not seasons:
            await send_to_channel(
                CHAMPIONSHIP_HISTORY_CHANNEL_ID,
                "👑 **HALL OF CHAMPIONS** 👑\n\n"
                "⚔️ No champion has been crowned yet — the "
                "realm awaits its first ruler."
            )
            return

        message = "👑 **GAME OF ZONES — HALL OF CHAMPIONS** 👑\n\n"

        for season in sorted(seasons.keys(), reverse=True):
            entry = seasons[season]

            message += (
                f"🏆 **{season}** — {entry.get('champion')}\n"
            )

            if entry.get("runner_up"):
                message += (
                    f"   🥈 Runner-Up: {entry.get('runner_up')}\n"
                )

            message += "\n"

        while len(message) > 1900:
            split_at = message.rfind("\n\n", 0, 1900)

            if split_at == -1:
                split_at = 1900

            await send_to_channel(
                CHAMPIONSHIP_HISTORY_CHANNEL_ID,
                message[:split_at]
            )

            message = message[split_at:].lstrip()

        await send_to_channel(CHAMPIONSHIP_HISTORY_CHANNEL_ID, message)

    except Exception as e:
        print(f"Champions command error: {e}")
        await send_to_channel(
            CHAMPIONSHIP_HISTORY_CHANNEL_ID,
            "⚠️ I couldn't retrieve the Hall of Champions."
        )


# v2 fixes a bug in the original ledger where a completed NFL game could be
# marked processed even when no rostered-player stats were actually posted.
# Using a new ledger lets the bot safely backfill games missed by that bug.
PROCESSED_STAT_EVENTS_FILE = os.path.join(
    DATA_DIR, "processed_stat_events_v2.json"
)
processed_stat_events = load_id_set(PROCESSED_STAT_EVENTS_FILE)


def normalize_player_name(name):
    """Normalize ESPN/Sleeper player names so harmless formatting differences still match."""
    name = unicodedata.normalize("NFKD", str(name or ""))
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = name.lower().replace("’", "'")
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\.?$", "", name).strip()
    name = re.sub(r"[^a-z0-9]+", "", name)
    return name


def build_roster_lookup(rosters_data, user_names):
    """Build robust roster lookup maps for ESPN-to-Sleeper stat matching."""
    name_to_pid = {}
    espn_to_pid = {}
    pid_to_team = {}
    pid_to_position = {}

    for roster in rosters_data:
        owner_id = roster.get("owner_id")
        team_name = user_names.get(owner_id, "Unknown House")

        for pid in roster.get("players", []) or []:
            if not pid or pid == "0":
                continue

            player_info = players_cache.get(str(pid), {}) or {}
            names = {
                get_player_name(pid),
                player_info.get("full_name"),
                player_info.get("first_name") and player_info.get("last_name")
                and f"{player_info.get('first_name')} {player_info.get('last_name')}",
            }

            for name in names:
                if name:
                    normalized = normalize_player_name(name)
                    if normalized:
                        name_to_pid[normalized] = pid

            espn_id = player_info.get("espn_id")
            if espn_id not in (None, ""):
                espn_to_pid[str(espn_id)] = pid

            pid_to_team[pid] = team_name
            pid_to_position[pid] = player_info.get("position", "")

    return name_to_pid, espn_to_pid, pid_to_team, pid_to_position


def extract_game_player_stats(event_id, name_to_pid, espn_to_pid=None):
    """
    Fetches one game's box score and returns a dict of
    pid -> list of stat-line strings, restricted to players
    found in name_to_pid (i.e. players on a fantasy roster).
    """
    matched = {}

    summary_url = (
        f"https://site.api.espn.com/apis/site/v2/"
        f"sports/football/nfl/summary?event={event_id}"
    )

    summary = get_json(summary_url)

    team_blocks = (
        summary.get("boxscore", {}).get("players", []) or []
    )

    for team_block in team_blocks:
        for category in team_block.get("statistics", []) or []:
            cat_name = category.get("name", "")
            wanted_labels = STAT_LABELS_BY_CATEGORY.get(cat_name)

            if not wanted_labels:
                continue

            labels = category.get("labels", []) or []
            athletes = category.get("athletes", []) or []

            for athlete_entry in athletes:
                athlete = athlete_entry.get("athlete", {}) or {}
                name = athlete.get("displayName", "")

                if not name:
                    continue

                espn_id = athlete.get("id")
                pid = None

                if espn_to_pid and espn_id is not None:
                    pid = espn_to_pid.get(str(espn_id))

                if not pid:
                    for candidate in (
                        athlete.get("displayName"),
                        athlete.get("fullName"),
                        athlete.get("shortName"),
                        name,
                    ):
                        normalized = normalize_player_name(candidate)
                        if normalized and normalized in name_to_pid:
                            pid = name_to_pid[normalized]
                            break

                if not pid:
                    continue

                values = athlete_entry.get("stats", []) or []
                pairs = list(zip(labels, values))

                parts = [
                    f"{label} {value}"
                    for label, value in pairs
                    if label in wanted_labels
                ]

                if not parts:
                    continue

                line = f"{cat_name.capitalize()}: " + ", ".join(parts)
                matched.setdefault(pid, []).append(line)

    return matched


@tasks.loop(minutes=15)
async def player_stats_checker():
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)
        current_week = str(int(nfl_state.get("week", 1)))

        # Look back several days so a completed game is not missed just
        # because ESPN's default scoreboard has already rolled to today.
        games = get_recent_nfl_games(days_back=3)

        if not games:
            return

        rosters_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/rosters"
        )

        users_url = (
            f"https://api.sleeper.app/v1/league/"
            f"{LEAGUE_ID}/users"
        )

        rosters_data = get_json(rosters_url)
        users = get_json(users_url)

        user_names = {}

        for user in users:
            user_names[user["user_id"]] = (
                user.get("metadata", {}).get("team_name")
                or user.get(
                    "display_name",
                    "Unknown House"
                )
            )

        name_to_pid, espn_to_pid, pid_to_team, pid_to_position = (
            build_roster_lookup(rosters_data, user_names)
        )

        week_data = week_player_stats.setdefault(
            current_week,
            {"teams": {}}
        )

        # Build the exact set of rostered players whose NFL games are final.
        # The detailed Stats channel already uses this ESPN box-score matching
        # successfully, so the clean weekly feed now reuses the same IDs instead
        # of depending on potentially stale Sleeper team abbreviations.
        completed_player_ids = set()
        for completed_game in games:
            completed_status = (
                completed_game.get("status", {}).get("type", {}) or {}
            )
            if not completed_status.get("completed", False):
                continue

            completed_game_id = completed_game.get("id")
            if not completed_game_id:
                continue

            try:
                completed_matched = extract_game_player_stats(
                    completed_game_id, name_to_pid, espn_to_pid
                )
                completed_player_ids.update(str(pid) for pid in completed_matched)
            except Exception as e:
                print(
                    f"Could not pre-scan completed player stats for "
                    f"{completed_game_id}: {e}"
                )

        update_weekly_scores_from_sleeper(
            current_week, rosters_data, user_names, games, week_data,
            completed_player_ids
        )

        # Keep the dedicated no-emoji weekly data feed present and current.
        await sync_weekly_stats_feed(
            current_week, rosters_data, user_names, week_data
        )

        all_completed = True

        for game in games:
            competition = game.get("competitions", [{}])[0]

            status = game.get("status", {}).get("type", {})
            completed = status.get("completed", False)

            game_id = game.get("id")

            if not completed:
                all_completed = False
                continue

            # Always parse completed games for the cumulative weekly feed, even
            # if the detailed game-by-game post was already sent. This lets the
            # master weekly list rebuild itself after a restart or code update.
            detailed_already_posted = game_id in processed_stat_events

            competitors = competition.get("competitors", [])

            if len(competitors) < 2:
                continue

            away_team = competitors[1].get(
                "team", {}
            ).get("abbreviation", "AWAY")

            home_team = competitors[0].get(
                "team", {}
            ).get("abbreviation", "HOME")

            matched = extract_game_player_stats(
                game_id,
                name_to_pid,
                espn_to_pid
            )

            if matched:
                by_team = {}

                for pid, lines in matched.items():
                    fantasy_team = pid_to_team.get(
                        pid,
                        "Unknown House"
                    )

                    by_team.setdefault(fantasy_team, []).append(
                        {
                            "name": get_player_name(pid),
                            "position": pid_to_position.get(
                                pid, ""
                            ),
                            "lines": lines
                        }
                    )

                    team_entry = week_data["teams"].setdefault(
                        fantasy_team, {}
                    )

                    team_entry[pid] = {
                        "name": get_player_name(pid),
                        "position": pid_to_position.get(pid, ""),
                        "lines": lines
                    }

                # Persist the cumulative data first. The master weekly feed is
                # rebuilt from every completed game, including games whose
                # detailed post was already sent in an earlier run.
                save_week_player_stats(week_player_stats)

                # Re-read Sleeper matchup points before refreshing the master
                # weekly post so the fantasy scores reflect the latest final.
                completed_player_ids.update(str(pid) for pid in matched)
                update_weekly_scores_from_sleeper(
                    current_week, rosters_data, user_names, games, week_data,
                    completed_player_ids
                )

                await sync_weekly_stats_feed(
                    current_week, rosters_data, user_names, week_data
                )

                # The detailed Stats channel remains one post per completed
                # NFL game. Only send it when this game has not been processed.
                if not detailed_already_posted:
                    message = (
                        f"🏈 **GAME FINAL: {away_team} @ "
                        f"{home_team}** 🏈\n\n"
                    )

                    for fantasy_team, players in by_team.items():
                        message += f"🏰 **{fantasy_team}**\n"

                        for p in players:
                            message += (
                                f"**{p['name']}** "
                                f"({p['position']})\n"
                            )
                            message += "\n".join(p["lines"]) + "\n"

                        message += "\n"

                    while len(message) > 1900:
                        split_at = message.rfind("\n\n", 0, 1900)

                        if split_at == -1:
                            split_at = 1900

                        await send_player_stats_message(
                            message[:split_at]
                        )

                        message = message[split_at:].lstrip()

                    await send_player_stats_message(message)

                    processed_stat_events.add(game_id)
                    save_id_set(
                        PROCESSED_STAT_EVENTS_FILE,
                        processed_stat_events
                    )
            else:
                print(
                    f"No rostered player stats found yet for NFL game {game_id}; "
                    "will retry."
                )

        if (
            all_completed
            and posted_weeks.get("player_stats_summary", 0)
            < int(current_week)
        ):
            teams = week_data.get("teams", {})

            if teams:
                message = (
                    f"🏆 **WEEK {current_week} — FINAL PLAYER "
                    f"STATS SUMMARY** 🏆\n\n"
                )

                for fantasy_team, players in teams.items():
                    message += f"🏰 **{fantasy_team}**\n"

                    for pid, p in players.items():
                        message += (
                            f"**{p['name']}** "
                            f"({p['position']})\n"
                        )
                        message += "\n".join(p["lines"]) + "\n"

                    message += "\n"

                while len(message) > 1900:
                    split_at = message.rfind("\n\n", 0, 1900)

                    if split_at == -1:
                        split_at = 1900

                    await send_player_stats_message(
                        message[:split_at]
                    )

                    message = message[split_at:].lstrip()

                await send_player_stats_message(message)

            posted_weeks["player_stats_summary"] = int(
                current_week
            )
            save_posted_weeks(posted_weeks)

    except Exception as e:
        print(f"Player stats checker error: {e}")


bot.run(TOKEN)
