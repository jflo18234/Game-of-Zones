import os
import discord
from discord.ext import commands, tasks
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
import urllib.request
import json

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
ROSTER_STATS_CHANNEL_ID = 154748286197039515
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
    "out for",
    "questionable",
    "doubtful",
    "ruled out",
    "injured reserve",
    " ir ",
    "will miss",
    "sidelined",
    "surgery",
    "torn",
    "fracture",
    "concussion",
]


def is_injury_headline(text):
    lowered = text.lower()
    return any(keyword in lowered for keyword in INJURY_KEYWORDS)


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

            messages = await get_fantasy_matchup_message(
                current_week
            )

            final_header = (
                "🏁 **NFL FINAL** 🏁\n\n"
                f"🏈 **{away_team}** {away_score} "
                f"— **{home_team}** {home_score}\n\n"
                f"⚔️ **GAME OF ZONES — WEEK "
                f"{current_week} FINAL FANTASY SCORES** ⚔️\n\n"
            )

            if messages:
                messages[0] = (
                    final_header + messages[0]
                )

            for message in messages:
                await send_to_channel(
                    NFL_SCORE_CHANNEL_ID,
                    message
                )

            reported_final_games.add(game_id)
            save_id_set(os.path.join(DATA_DIR, "reported_final_games.json"), reported_final_games)

            print(
                f"🏁 Final fantasy scores posted "
                f"for {away_team} @ {home_team}."
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
    try:
        state_url = "https://api.sleeper.app/v1/state/nfl"
        nfl_state = get_json(state_url)

        current_week = int(
            nfl_state.get("week", 1)
        )

        completed_week = current_week - 1

        if completed_week < 1:
            return

        # Skip if this week's news was already posted (fixes daily repeat-posting)
        if posted_weeks.get("news", 0) >= completed_week:
            return

        news_channel = bot.get_channel(NEWS_CHANNEL_ID)

        if news_channel is None:
            print("Daily Raven: News channel not found.")
            return

        # Reuse the existing !news command logic
        await news.callback(news_channel)

        posted_weeks["news"] = completed_week
        save_posted_weeks(posted_weeks)

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


reported_transactions = load_id_set(os.path.join(DATA_DIR, "reported_transactions.json"))


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

            transaction_id = t.get("transaction_id")

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

            await send_to_channel(WAIVER_WIRE_CHANNEL_ID, message)

            reported_transactions.add(transaction_id)
            save_id_set(os.path.join(DATA_DIR, "reported_transactions.json"), reported_transactions)

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


reported_trades = load_id_set(os.path.join(DATA_DIR, "reported_trades.json"))


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

            transaction_id = t.get("transaction_id")

            if transaction_id in reported_trades:
                continue

            message = format_trade(t, roster_names)

            await send_to_channel(TRADE_BLOCK_CHANNEL_ID, message)

            reported_trades.add(transaction_id)
            save_id_set(os.path.join(DATA_DIR, "reported_trades.json"), reported_trades)

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


@bot.command()
async def rosters(ctx):
    try:
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

        message = "📋 **GAME OF ZONES — FULL ROSTERS** 📋\n\n"

        for roster in rosters_data:
            owner_id = roster.get("owner_id")

            team_name = user_names.get(
                owner_id,
                "Unknown House"
            )

            starters = roster.get("starters", []) or []
            all_players = roster.get("players", []) or []

            bench = [
                p for p in all_players
                if p not in starters
            ]

            starter_names = [
                get_player_name(p)
                for p in starters
                if p and p != "0"
            ]

            bench_names = [
                get_player_name(p)
                for p in bench
                if p and p != "0"
            ]

            message += f"🏰 **{team_name}**\n"

            if starter_names:
                message += (
                    "⚔️ Starters: "
                    + ", ".join(starter_names)
                    + "\n"
                )

            if bench_names:
                message += (
                    "🪑 Bench: "
                    + ", ".join(bench_names)
                    + "\n"
                )

            message += "\n"

        while len(message) > 1900:
            split_at = message.rfind("\n\n", 0, 1900)

            if split_at == -1:
                split_at = 1900

            await send_to_channel(
                ROSTERS_CHANNEL_ID,
                message[:split_at]
            )

            message = message[split_at:].lstrip()

        await send_to_channel(ROSTERS_CHANNEL_ID, message)

    except Exception as e:
        print(f"Rosters error: {e}")
        await send_to_channel(
            ROSTERS_CHANNEL_ID,
            "⚠️ I couldn't retrieve team rosters from Sleeper."
        )


@tasks.loop(minutes=30)
async def roster_checker():
    try:
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

        changed = False

        for roster in rosters_data:
            roster_id = roster.get("roster_id")
            owner_id = roster.get("owner_id")

            team_name = user_names.get(
                owner_id,
                "Unknown House"
            )

            key = str(roster_id)
            current_players = set(
                roster.get("players", []) or []
            )

            if key not in roster_snapshots:
                roster_snapshots[key] = sorted(current_players)
                changed = True
                continue

            previous_players = set(roster_snapshots[key])

            added = current_players - previous_players
            removed = previous_players - current_players

            if added or removed:
                message = (
                    "📋 **ROSTER UPDATE** 📋\n\n"
                    f"🏰 **{team_name}**\n"
                )

                if added:
                    added_names = [
                        get_player_name(p) for p in added
                    ]

                    message += (
                        "✅ Added: "
                        + ", ".join(added_names)
                        + "\n"
                    )

                if removed:
                    removed_names = [
                        get_player_name(p) for p in removed
                    ]

                    message += (
                        "❌ Removed: "
                        + ", ".join(removed_names)
                        + "\n"
                    )

                await send_to_channel(ROSTERS_CHANNEL_ID, message)

                roster_snapshots[key] = sorted(current_players)
                changed = True

        if changed:
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


processed_stat_events = load_id_set(
    os.path.join(DATA_DIR, "processed_stat_events.json")
)


def build_roster_lookup(rosters_data, user_names):
    """
    Returns (name_to_pid, pid_to_team) covering every player on
    every roster in the league, keyed by lowercased player name.
    """
    name_to_pid = {}
    pid_to_team = {}
    pid_to_position = {}

    for roster in rosters_data:
        owner_id = roster.get("owner_id")

        team_name = user_names.get(
            owner_id,
            "Unknown House"
        )

        for pid in roster.get("players", []) or []:
            if not pid or pid == "0":
                continue

            name = get_player_name(pid)
            name_to_pid[name.lower()] = pid
            pid_to_team[pid] = team_name

            player_info = players_cache.get(str(pid), {})
            pid_to_position[pid] = player_info.get("position", "")

    return name_to_pid, pid_to_team, pid_to_position


def extract_game_player_stats(event_id, name_to_pid):
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

                pid = name_to_pid.get(name.lower())

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

        games = get_nfl_games()

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

        name_to_pid, pid_to_team, pid_to_position = (
            build_roster_lookup(rosters_data, user_names)
        )

        week_data = week_player_stats.setdefault(
            current_week,
            {"teams": {}}
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

            if game_id in processed_stat_events:
                continue

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
                name_to_pid
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

                    await send_to_channel(
                        ROSTER_STATS_CHANNEL_ID,
                        message[:split_at]
                    )

                    message = message[split_at:].lstrip()

                await send_to_channel(
                    ROSTER_STATS_CHANNEL_ID,
                    message
                )

                save_week_player_stats(week_player_stats)

            processed_stat_events.add(game_id)
            save_id_set(
                os.path.join(
                    DATA_DIR, "processed_stat_events.json"
                ),
                processed_stat_events
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

                    await send_to_channel(
                        ROSTER_STATS_CHANNEL_ID,
                        message[:split_at]
                    )

                    message = message[split_at:].lstrip()

                await send_to_channel(
                    ROSTER_STATS_CHANNEL_ID,
                    message
                )

            posted_weeks["player_stats_summary"] = int(
                current_week
            )
            save_posted_weeks(posted_weeks)

    except Exception as e:
        print(f"Player stats checker error: {e}")


bot.run(TOKEN)
