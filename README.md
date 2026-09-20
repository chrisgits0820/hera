# Hera

NFL live game tracker and parlay entry app (PySide6 desktop).

## Run

From the repo root:

```
pip install PySide6 requests pygame
python Hera/Scripts/hera.py
```

Run the same file in PyCharm if that is how you launch it. Audio is `Hera/HERA_AUDIO.mp3`.

## Live tracking

**TRACK** reloads the selected game and polls ESPN every 3 seconds (scoreboard, summary/boxscore, plays, both linescores in parallel). Game Tracker **CURRENT** is the live stat (0 before the boxscore exists). **NEEDS** is remaining to strictly exceed the line on OVER, or remaining cushion on UNDER, with clock/time remaining while the game is in progress.

## Bet Entry

- Pick a slot **P1–P10**.
- **+ ADD LEG** adds one editable row immediately. Type odds on each row; **LEGS**, **PARLAY ODDS**, **TO WIN**, and **PAYOUT** update as you type.
- **NEW PARLAY** (bottom of the tab) clears the current slot.
- **SUBMIT PARLAY** saves the ticket as live.
