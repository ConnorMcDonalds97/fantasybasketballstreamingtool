"""Rank ESPN H2H-points streaming moves: who to drop, who to add, and whether it's worth it.

Everything is pulled live on each run; nothing is cached. A pickup only plays from
tomorrow, so both sides of every swap are scored from tomorrow to the end of the week.
"""
import argparse
import contextlib
import datetime as dt
import itertools
import json
import os
import sys
import threading

from espn_api.basketball import League, Player
from espn_api.basketball.constant import PRO_TEAM_MAP

SHRINK_GAMES = 5  # recent form needs this many games before it outweighs ESPN's projection
OUT = {"OUT", "SUSPENSION"}
GAME_LENGTH = dt.timedelta(hours=2.5)  # tip-off to final buzzer; bump it if overtime keeps catching you
ONE_DAY = dt.timedelta(days=1)


# ---------- How good is a player, and does he play on a given day? ----------

def per_game(player, year):
    """Fantasy points we expect from one game.

    Mostly his last 15 days. But a few games can be luck, so we mix in ESPN's guess
    as if it were SHRINK_GAMES extra games. More real games = ESPN's guess matters less.
    """
    espn_guess = player.stats.get(f"{year}_projected", {}).get("applied_avg", 0)
    last_15_days = player.stats.get(f"{year}_last_15", {})
    games_played = (last_15_days.get("total") or {}).get("GP", 0)
    points_scored = last_15_days.get("applied_total", 0)
    return (points_scored + SHRINK_GAMES * espn_guess) / (games_played + SHRINK_GAMES)


def plays(player, day, game_times):
    """True if the player's team has a game that day and he isn't hurt."""
    if day not in game_times.get(player.proTeam, ()):
        return False
    if player.injuryStatus in OUT:
        # Hurt players only play once they're back.
        return bool(player.expected_return_date and day >= player.expected_return_date)
    return True


# ---------- How many points would a team score? ----------

def team_points(team, days, game_times, points_per_game, slots):
    """Points the team scores over these days.

    Only `slots` players can start each day. If more play, the best ones start
    and the rest sit on the bench and score nothing.
    """
    total = 0
    for day in days:
        playing_today = [points_per_game[p.name] for p in team if plays(p, day, game_times)]
        best_first = sorted(playing_today, reverse=True)
        total += sum(best_first[:slots])
    return total


# ---------- Which drop/add moves help the most? ----------

def start_options(pickup, days):
    """Every way the move can happen, as two positions in `days`:
    (first day the dropped player is gone, first day the pickup plays).

    Free agent: you choose the day. Drop him and the pickup plays the next day, so both are the same.
    Waiver player: no choice. Your player is gone on the day the claim clears,
    and the pickup plays from the day after. On that one day, neither plays for you.
    """
    if pickup.clears:
        clear_day = pickup.clears.date()
        days_before_clearing = sum(day < clear_day for day in days)
        days_up_to_clearing = sum(day <= clear_day for day in days)
        return [(days_before_clearing, days_up_to_clearing)]
    return [(i, i) for i in range(len(days))]


def best_swaps(roster, pickups, days, game_times, points_per_game, slots, droppable):
    """Try every (drop, add) pair. Returns (gain, drop, add, first day the add plays), best first.

    For each pair we try every possible day and keep the best one. Waiting can be better,
    because the player you drop keeps playing until then. If two days are equally good,
    the earlier one wins, so nobody else grabs the pickup first.
    """
    def points(team, some_days):
        return team_points(team, some_days, game_times, points_per_game, slots)

    points_if_we_do_nothing = points(roster, days)
    worst_players = sorted(roster, key=lambda p: points_per_game[p.name])[:droppable]

    swaps = []
    for drop in worst_players:
        roster_without_drop = [p for p in roster if p is not drop]
        for add in pickups:
            best = None  # (gain, first day the add plays)
            for drop_gone, add_plays in start_options(add, days):
                if add_plays >= len(days):
                    continue  # the pickup wouldn't play before the week ends
                points_with_move = (
                    points(roster, days[:drop_gone])                          # before: old team
                    + points(roster_without_drop, days[drop_gone:add_plays])  # waiver day: neither plays
                    + points(roster_without_drop + [add], days[add_plays:])   # after: new team
                )
                gain = round(points_with_move - points_if_we_do_nothing, 1)
                if best is None or gain > best[0]:  # only a bigger gain replaces it, so ties keep the earlier day
                    best = (gain, add_plays)
            if best is not None:
                gain, add_plays = best
                swaps.append((gain, drop, add, days[add_plays]))

    swaps.sort(key=lambda swap: swap[0], reverse=True)
    return swaps


# ---------- Getting data from ESPN ----------

def free_agents(league, size):
    """league.free_agents(), but keeping when waiver players clear (espn_api drops it)."""
    filters = {"players": {"filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}, "limit": size,
                           "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}}
    data = league.espn_request.league_get(params={"view": "kona_player_info", "scoringPeriodId": league.scoringPeriodId},
                                          headers={"x-fantasy-filter": json.dumps(filters)})
    players = []
    for raw in data["players"]:
        player = Player(raw, league.year)
        on_waivers = raw.get("status") == "WAIVERS"
        clears_ms = raw.get("waiverProcessDate") if on_waivers else None
        player.clears = dt.datetime.fromtimestamp(clears_ms / 1000) if clears_ms else None  # None = free agent
        players.append(player)
    return players


def schedule(league):
    """Team name -> {game day: tip-off time}, in your local time."""
    game_times = {}
    for team_id, games_by_period in league.pro_schedule.items():
        if team_id not in PRO_TEAM_MAP:
            continue
        tip_offs = [dt.datetime.fromtimestamp(g[0]["date"] / 1000) for g in games_by_period.values() if g]
        game_times[PRO_TEAM_MAP[team_id]] = {tip.date(): tip for tip in tip_offs}
    return game_times


# ---------- Printing ----------

@contextlib.contextmanager
def cooking():
    """Spin a little circle with 'Cooking...' while the slow stuff runs, then wipe it away."""
    if not sys.stderr.isatty():  # output is going to a file or pipe: skip the animation
        yield
        return
    done = threading.Event()

    def spin():
        for circle in itertools.cycle("◐◓◑◒"):
            sys.stderr.write(f"\r{circle} Cooking...")
            sys.stderr.flush()
            if done.wait(0.1):
                break
        sys.stderr.write("\r" + " " * 12 + "\r")
        sys.stderr.flush()

    spinner = threading.Thread(target=spin, daemon=True)
    spinner.start()
    try:
        yield
    finally:  # stop it even if something breaks, so errors print on a clean line
        done.set()
        spinner.join()


def when_to_move(drop, add, add_plays, today, game_times):
    """Plain words for when to make the move, e.g. 'today, anytime' or 'Sat Oct 24 after 8:30 PM'."""
    if add.clears:
        return f"claim before {add.clears:%a %-I:%M %p}"
    move_day = add_plays - ONE_DAY
    day_name = "today" if move_day == today else f"{move_day:%a %b %d}"
    if plays(drop, move_day, game_times):
        game_over = game_times[drop.proTeam][move_day] + GAME_LENGTH
        return f"{day_name} after {game_over:%-I:%M %p}"
    return f"{day_name}, anytime"


def main():
    today = dt.date.today()
    tomorrow = today + ONE_DAY
    coming_sunday = tomorrow + dt.timedelta(days=6 - tomorrow.weekday())

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--until", type=dt.date.fromisoformat, default=coming_sunday,
                    help="last day of the matchup, YYYY-MM-DD (default: coming Sunday)")
    ap.add_argument("--slots", type=int, default=10, help="active lineup slots per day (default 10)")
    ap.add_argument("--droppable", type=int, default=3, help="consider dropping your N lowest-value players")
    ap.add_argument("--min-gain", type=float, default=5, help="ignore swaps gaining fewer points than this")
    ap.add_argument("--pool", type=int, default=100, help="free agents to scan (by %% owned)")
    args = ap.parse_args()

    with cooking():
        # 1. Get everything fresh from ESPN.
        env = os.environ
        year = int(env.get("ESPN_YEAR", 2027))
        league = League(int(env["ESPN_LEAGUE_ID"]), year, env.get("ESPN_S2"), env.get("ESPN_SWID"))
        my_team = next(t for t in league.teams if t.team_id == int(env["ESPN_TEAM_ID"]))
        roster = [p for p in my_team.roster if p.lineupSlot != "IR"]  # injured-reserve players can't play
        pickups = free_agents(league, args.pool)
        game_times = schedule(league)

        # 2. Work out the days that matter, how good everyone is, and the best moves.
        days = [tomorrow + dt.timedelta(n) for n in range((args.until - tomorrow).days + 1)]
        points_per_game = {p.name: per_game(p, year) for p in roster + pickups}
        swaps = best_swaps(roster, pickups, days, game_times, points_per_game, args.slots, args.droppable)

    def games_left(player, from_day=tomorrow):
        return sum(plays(player, day, game_times) for day in days if day >= from_day)

    # 3. Show my roster, worst player first.
    print(f"Window: {days[0]} -> {days[-1]} ({len(days)} days, {args.slots} slots/day)\n")
    print(f"{'YOUR ROSTER':26}{'team':6}{'status':12}{'pts/g':>7}{'games':>7}")
    for p in sorted(roster, key=lambda p: points_per_game[p.name]):
        print(f"{p.name:26}{p.proTeam:6}{p.injuryStatus or '':12}{points_per_game[p.name]:7.1f}{games_left(p):7}")

    # 4. Show the best moves, or say to hold.
    good_swaps = [s for s in swaps if s[0] >= args.min_gain]
    print()
    if not good_swaps:
        print(f"HOLD: no swap gains {args.min_gain}+ points this window.")
        return
    print(f"{'GAIN':>6}  {'MOVE ON':28}{'DROP':26}{'ADD':26}{'team':6}{'pts/g':>7}{'games':>7}")
    for gain, drop, add, add_plays in good_swaps[:10]:
        when = when_to_move(drop, add, add_plays, today, game_times)
        print(f"{gain:6.1f}  {when:28}{drop.name:26}{add.name:26}{add.proTeam:6}"
              f"{points_per_game[add.name]:7.1f}{games_left(add, add_plays):7}")
    print("\nMOVE ON: 'after' = once your dropped player's game is over (tip-off + 2.5h). Pickups play from the next day;"
          "\nwaiting longer than needed risks someone else grabbing them.")


if __name__ == "__main__":
    main()
