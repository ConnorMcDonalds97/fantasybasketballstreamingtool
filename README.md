# fantasybasketballstreamingtool
Tool to help me with streaming players for fantasy basketball (ESPN, H2H points).

Run it each day. It pulls your roster, free agents, injuries and the NBA schedule live from ESPN,
then ranks drop/add swaps by how many points they add **from tomorrow to the end of the week**
(a pickup doesn't play until tomorrow, so neither side counts today).

- **pts/g** = last-15-day fantasy points, pulled toward ESPN's projection until there are ~5 games of sample.
- Players listed OUT score 0 until their expected return date.
- Each day only your best `--slots` players count, so a pickup on a crowded day gains little.

## Setup
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
Set these (e.g. in `~/.zshrc`):
```bash
export ESPN_LEAGUE_ID=123456   # leagueId= in your league URL
export ESPN_TEAM_ID=3          # teamId= in your team page URL
export ESPN_S2='...'           # private leagues only: browser cookie espn_s2 on espn.com
export ESPN_SWID='{...}'       # private leagues only: browser cookie SWID
```

## Use
```bash
.venv/bin/python stream.py
```
Options: `--until 2026-11-01` (matchup end if not Sunday), `--slots 10`, `--droppable 3`, `--min-gain 5`.

Output is either `HOLD` or a ranked list of `GAIN  MOVE ON  DROP  ADD`. `MOVE ON` is the best day to
make the move: if the pickup doesn't play for a few days, waiting keeps your dropped player's games
until then. Times are your local time: "after 8:30 PM" = once your dropped player's game is over
(tip-off + 2.5h, `GAME_LENGTH` in stream.py), "anytime" = he doesn't play that day,
"claim before ..." = the pickup is on waivers; your drop happens when the claim clears.

Self-check: `.venv/bin/python test_stream.py`
