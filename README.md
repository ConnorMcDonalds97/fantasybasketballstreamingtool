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

Output is either `HOLD` or a ranked list of `GAIN  DROP  ADD`. Make the move after your dropped
player's game today, so you keep those points.

Self-check: `.venv/bin/python test_stream.py`
