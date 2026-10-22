"""Rank ESPN H2H-points streaming moves: who to drop, who to add, and whether it's worth it.

Everything is pulled live on each run; nothing is cached. A pickup only plays from
tomorrow, so both sides of every swap are scored from tomorrow to the end of the week.
"""
import argparse
import datetime as dt
import os

from espn_api.basketball import League
from espn_api.basketball.constant import PRO_TEAM_MAP

SHRINK_GAMES = 5  # recent form needs this many games before it outweighs ESPN's projection
OUT = {"OUT", "SUSPENSION"}


def per_game(p, year):
    """Fantasy points per game: last-15-day form, shrunk toward ESPN's projection on small samples."""
    proj = p.stats.get(f"{year}_projected", {}).get("applied_avg", 0)
    recent = p.stats.get(f"{year}_last_15", {})
    gp = (recent.get("total") or {}).get("GP", 0)
    return (recent.get("applied_total", 0) + SHRINK_GAMES * proj) / (gp + SHRINK_GAMES)


def plays(p, day, games):
    if day not in games.get(p.proTeam, ()):
        return False
    if p.injuryStatus in OUT:
        return bool(p.expected_return_date and day >= p.expected_return_date)
    return True


def team_points(roster, days, games, values, slots):
    """Projected points, counting only the best `slots` players on each day (extra games are wasted)."""
    total = 0
    for day in days:
        playing = sorted((values[p.name] for p in roster if plays(p, day, games)), reverse=True)
        total += sum(playing[:slots])
    return total


def best_swaps(roster, free_agents, days, games, values, slots, droppable):
    base = team_points(roster, days, games, values, slots)
    drops = sorted(roster, key=lambda p: values[p.name])[:droppable]
    swaps = []
    for d in drops:
        rest = [p for p in roster if p is not d]
        for a in free_agents:
            gain = team_points(rest + [a], days, games, values, slots) - base
            swaps.append((gain, d, a))
    return sorted(swaps, key=lambda s: s[0], reverse=True)


def schedule(league):
    """Pro team abbrev -> set of local game dates, straight from ESPN."""
    return {
        PRO_TEAM_MAP[team_id]: {
            dt.datetime.fromtimestamp(g[0]["date"] / 1000).date() for g in periods.values() if g
        }
        for team_id, periods in league.pro_schedule.items()
        if team_id in PRO_TEAM_MAP
    }


def main():
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--until", type=dt.date.fromisoformat,
                    default=tomorrow + dt.timedelta(days=6 - tomorrow.weekday()),
                    help="last day of the matchup, YYYY-MM-DD (default: coming Sunday)")
    ap.add_argument("--slots", type=int, default=10, help="active lineup slots per day (default 10)")
    ap.add_argument("--droppable", type=int, default=3, help="consider dropping your N lowest-value players")
    ap.add_argument("--min-gain", type=float, default=5, help="ignore swaps gaining fewer points than this")
    ap.add_argument("--pool", type=int, default=100, help="free agents to scan (by %% owned)")
    args = ap.parse_args()

    env = os.environ
    year = int(env.get("ESPN_YEAR", 2027))
    league = League(int(env["ESPN_LEAGUE_ID"]), year, env.get("ESPN_S2"), env.get("ESPN_SWID"))
    team = next(t for t in league.teams if t.team_id == int(env["ESPN_TEAM_ID"]))
    roster = [p for p in team.roster if p.lineupSlot != "IR"]
    free_agents = league.free_agents(size=args.pool)

    games = schedule(league)
    days = [tomorrow + dt.timedelta(n) for n in range((args.until - tomorrow).days + 1)]
    values = {p.name: per_game(p, year) for p in roster + free_agents}

    print(f"Window: {days[0]} -> {days[-1]} ({len(days)} days, {args.slots} slots/day)\n")
    print(f"{'YOUR ROSTER':26}{'team':6}{'status':12}{'pts/g':>7}{'games':>7}")
    for p in sorted(roster, key=lambda p: values[p.name]):
        n = sum(plays(p, d, games) for d in days)
        print(f"{p.name:26}{p.proTeam:6}{p.injuryStatus or '':12}{values[p.name]:7.1f}{n:7}")

    swaps = [s for s in best_swaps(roster, free_agents, days, games, values, args.slots, args.droppable)
             if s[0] >= args.min_gain]
    print()
    if not swaps:
        print(f"HOLD: no swap gains {args.min_gain}+ points this window.")
        return
    print(f"{'GAIN':>6}  {'DROP':26}{'ADD':26}{'team':6}{'pts/g':>7}{'games':>7}")
    for gain, d, a in swaps[:10]:
        n = sum(plays(a, day, games) for day in days)
        print(f"{gain:6.1f}  {d.name:26}{a.name:26}{a.proTeam:6}{values[a.name]:7.1f}{n:7}")


if __name__ == "__main__":
    main()
