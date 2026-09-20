# Hera

NFL live game tracker and parlay entry app (PySide6 desktop).

## Run

From the repo root:

```
pip install PySide6 requests pygame
python Hera/Scripts/hera.py
```

Run the same file in PyCharm if that is how you launch it. Audio is `Hera/HERA_AUDIO.mp3`.

## Bet Entry

- Pick a slot **P1–P10**.
- **+ ADD LEG** adds one editable row immediately. Type odds on each row; **LEGS**, **PARLAY ODDS**, **TO WIN**, and **PAYOUT** update as you type.
- **NEW PARLAY** (bottom of the tab) clears the current slot.
- **SUBMIT PARLAY** saves the ticket as live.
