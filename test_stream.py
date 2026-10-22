import datetime as dt
from types import SimpleNamespace

from stream import best_swaps, per_game, plays, team_points

D = [dt.date(2026, 10, 23) + dt.timedelta(n) for n in range(3)]


def player(name, team, pts, status="ACTIVE", back=None):
    return SimpleNamespace(name=name, proTeam=team, injuryStatus=status, expected_return_date=back,
                           stats={"2027_projected": {"applied_avg": pts}})


# no recent games -> pure projection; 15 recent games at 40 -> pulled most of the way to 40
assert per_game(player("a", "X", 20), 2027) == 20
p = player("b", "X", 20)
p.stats["2027_last_15"] = {"applied_total": 600, "total": {"GP": 15}}
assert per_game(p, 2027) == (600 + 5 * 20) / 20

games = {"BUSY": set(D), "ONE": {D[0]}}
# OUT players play only from their expected return date
assert not plays(player("c", "BUSY", 30, "OUT"), D[0], games)
assert plays(player("c", "BUSY", 30, "OUT", back=D[1]), D[1], games)

# 2 slots, three players on BUSY: the third one's games are wasted
roster = [player("s1", "BUSY", 40), player("s2", "BUSY", 35), player("weak", "ONE", 10)]
vals = {p.name: p.stats["2027_projected"]["applied_avg"] for p in roster}
assert team_points(roster, D, games, vals, 2) == 3 * 75

# with 3 slots, a 3-game streamer beats a better 1-game player
fa = [player("streamer", "BUSY", 15)]
vals["streamer"] = 15
gain, drop, add = best_swaps(roster, fa, D, games, vals, 3, 1)[0]
assert (drop.name, add.name, gain) == ("weak", "streamer", 3 * 15 - 10)
print("ok")
