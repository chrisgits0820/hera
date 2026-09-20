# hera.py — v4.1.7
# Standalone NFL live game tracker — PC/Windows build
# C:\Users\chris\Hera\Script\hera.py

import multiprocessing

multiprocessing.freeze_support()

import sys
import os
import sqlite3
import requests
import time
import traceback
from functools import partial

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QStackedWidget,
    QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QGridLayout, QLineEdit, QFrame, QSizePolicy, QDialog,
    QDialogButtonBox, QProgressBar, QSpacerItem
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QPixmap, QColor, QPalette, QPainter
import re
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────
VERSION = "4.2.0"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HERA_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
DATA_DIR = os.path.join(HERA_DIR, "Data")
FONT_PATH = os.path.join(HERA_DIR, "BebasNeue-Regular.ttf")
LOGO_ORIG = os.path.join(HERA_DIR, "hera_loading_screen.png")
LOGO_NOBG = os.path.join(DATA_DIR, "hera_nobg.png")
DB_PATH = os.path.join(DATA_DIR, "hera.db")
LOGO_DIR = os.path.join(HERA_DIR, "NFL LOGOS")
COLOR_CSV = os.path.join(DATA_DIR, "Hera_Color_Hex_Codes_v3_00b8.csv")

os.makedirs(DATA_DIR, exist_ok=True)

TEAM_COLORS = {}  # lowercase full name -> (bg_hex, fg_hex)


def load_team_colors():
    """Load background/font hex from the Hera color CSV (full team names)."""
    TEAM_COLORS.clear()
    if not os.path.exists(COLOR_CSV):
        return
    try:
        with open(COLOR_CSV, encoding="utf-8-sig") as f:
            for line in f:
                parts = [p.strip() for p in line.strip().split(",")]
                if not parts or not parts[0]:
                    continue
                head = parts[0].upper()
                if head.startswith("TEAM ABBREVIATION") or head.startswith("OFFENSE"):
                    break
                if head.startswith("FULL TEAM"):
                    continue
                if len(parts) < 3:
                    continue
                bg, fg = parts[1], parts[2]
                if bg.startswith("#") and fg.startswith("#"):
                    TEAM_COLORS[parts[0].lower()] = (bg, fg)
    except Exception:
        pass

# ─────────────────────────────────────────────
# COLORS
# ─────────────────────────────────────────────
BG = "#2d2d2d"
CARD = "#2d2d2d"
CARD2 = "#2d2d2d"
BORDER = "#3d3d3d"
BORDER2 = "#363636"
GREEN = "#1cbe1c"
GREEN_DIM = "#0e5e0e"
GREEN_HL = "#1c2a0a"  # bet-player row highlight
SCORE_HL = "#1a2510"  # scoring play highlight
RED = "#e24b4a"
GOLD = "#f0c040"
TEXT = "#e0e0e0"
TEXT_MID = "#cccccc"
TEXT_DIM = "#888888"
TEXT_DARK = "#666666"
TEXT_XDRK = "#555555"
NAV_BG = "#222222"
HDR_BG = "#333333"

POS_STYLE = {
    "QB": "background:#9900ff; color:#ffffff;",
    "WR": "background:#ff0000; color:#ffffff;",
    "RB": "background:#ff9900; color:#000000;",
    "TE": "background:#ffff00; color:#000000;",
    "K": "background:#444444; color:#cccccc;",
    "P": "background:#444444; color:#cccccc;",
}
# (bg, fg) tuples used when we need the values individually
POS_COLORS = {
    "QB": ("#9900ff", "#ffffff"),
    "WR": ("#ff0000", "#ffffff"),
    "RB": ("#ff9900", "#000000"),
    "TE": ("#ffff00", "#000000"),
    "K": ("#444444", "#cccccc"),
    "P": ("#444444", "#cccccc"),
}

BOOKS = [
    "FANDUEL", "DRAFTKINGS", "CAESARS", "BET MGM", "BET365", "BALLY", "BETR",
    "COURTSIDE", "DABBLE", "DDC", "FANATICS", "HARD ROCK", "ONYX", "PICK 6",
    "POLYMARKET", "SCORE", "SLEEPER", "UNDERDOG", "OTHER"
]

MARKETS = [
    "ML", "SPREAD", "TOT", "ATD", "PS YDS", "PS TD", "COMP", "PS ATT", "INT",
    "LNG PS", "REC YDS", "REC", "TAR", "LNG REC", "RSH ATT", "RSH YDS", "T+A", "SCK", "INT REC",
    "K PTS", "EPM", "FGM", "1TD", "LTD", "1H SPD", "1H ML", "1H TOT",
    "2H SPD", "2H ML", "2H TOT", "1Q SPD", "1Q ML", "1Q TOT", "2Q SPD",
    "2Q ML", "2Q TOT", "3Q SPD", "3Q ML", "3Q TOT", "4Q SPD", "4Q ML",
    "4Q TOT", "TM TOT"
]

MARKET_STAT_MAP = {
    "PS YDS": "passingYards",
    "PS TD": "passingTouchdowns",
    "COMP": "completions",
    "PS ATT": "attempts",
    "INT": "interceptions",
    "LNG PS": "longPassingYards",
    "REC YDS": "receivingYards",
    "REC": "receptions",
    "TAR": "receivingTargets",
    "LNG REC": "longReception",
    "RSH ATT": "rushingAttempts",
    "RSH YDS": "rushingYards",
    "SCK": "sacks",
    "T+A": "totalTackles",
    "INT REC": "interceptions",
    "K PTS": "kickingPoints",
    "FGM": "fieldGoalsMade",
    "EPM": "extraPointsMade",
}

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
ESPN_CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"


def et_to_pt(detail: str) -> str:
    """Convert Eastern time string to Pacific in ESPN detail strings like '9/17 - 8:15 PM EDT'."""
    m = re.search(r'(\d{1,2}:\d{2}\s*[AP]M)\s*(E[DS]T)', detail, re.IGNORECASE)
    if not m:
        return detail
    time_str, tz = m.group(1).strip(), m.group(2).upper()
    offset = -3  # EDT→PDT or EST→PST both subtract 3 hours
    new_tz = 'PDT' if tz == 'EDT' else 'PST'
    try:
        t = datetime.strptime(time_str.upper(), '%I:%M %p')
        t2 = t + timedelta(hours=offset)
        pac = t2.strftime('%I:%M %p').lstrip('0') + f' {new_tz}'
        return detail[:m.start()] + pac
    except Exception:
        return detail


# ─────────────────────────────────────────────
# FONT
# ─────────────────────────────────────────────
_FF = "Arial"


def load_font():
    global _FF
    if os.path.exists(FONT_PATH):
        fid = QFontDatabase.addApplicationFont(FONT_PATH)
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            _FF = fams[0]


def bb(size=12):
    return QFont(_FF, round(size * 1.39))


# ─────────────────────────────────────────────
# STYLE HELPERS
# ─────────────────────────────────────────────
def card_ss(r=0):
    return f"background:{CARD}; border:none;"


def combo_ss():
    return (f"QComboBox{{background:#2a2a2a;color:{TEXT};border:0.5px solid #444;"
            f"border-radius:0px;padding:5px 10px;}}"
            f"QComboBox::drop-down{{border:none;}}"
            f"QComboBox QAbstractItemView{{background:#2a2a2a;color:{TEXT};"
            f"border:1px solid {BORDER};selection-background-color:{GREEN_DIM};}}")


def input_ss():
    return (f"QLineEdit{{background:#2a2a2a;color:{TEXT};border:0.5px solid #444;"
            f"border-radius:0px;padding:5px 10px;}}")


def table_ss():
    return (f"QTableWidget{{background:{CARD};color:{TEXT};border:none;"
            f"gridline-color:{BORDER2};outline:none;}}"
            f"QTableWidget::item{{padding:4px 8px;border-bottom:0.5px solid {BORDER2};}}"
            f"QTableWidget::item:selected{{background:{GREEN_DIM};color:{TEXT};}}"
            f"QHeaderView::section{{background:{HDR_BG};color:{TEXT_MID};border:none;"
            f"border-bottom:0.5px solid {BORDER2};padding:4px 8px;font-size:10px;letter-spacing:2px;}}"
            f"QScrollBar:vertical{{background:{BG};width:5px;border:none;}}"
            f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:2px;}}"
            f"QScrollBar:horizontal{{background:{BG};height:5px;border:none;}}"
            f"QScrollBar::handle:horizontal{{background:{BORDER};border-radius:2px;}}")


def btn_ss(bg=GREEN, fg="#000", r=0):
    def adj(h, a):
        c = h.lstrip("#")
        try:
            rv, gv, bv = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
            return "#{:02x}{:02x}{:02x}".format(max(0, min(255, rv + a)), max(0, min(255, gv + a)),
                                                max(0, min(255, bv + a)))
        except Exception:
            return h

    return (f"QPushButton{{background:{bg};color:{fg};border:none;border-radius:{r}px;padding:5px 14px;}}"
            f"QPushButton:hover{{background:{adj(bg, 20)};}}"
            f"QPushButton:pressed{{background:{adj(bg, -20)};}}")


def ghost_ss(fg=TEXT_DIM, r=0):
    return (f"QPushButton{{background:transparent;color:{fg};border:none;"
            f"padding:5px 14px;}}"
            f"QPushButton:hover{{color:{TEXT};}}")


def nav_active_ss():
    return (f"QPushButton{{background:transparent;color:{TEXT};border:none;"
            f"border-bottom:2px solid {GREEN};padding:4px 16px;}}")


def nav_inactive_ss():
    return (f"QPushButton{{background:transparent;color:{TEXT_DIM};border:none;"
            f"border-bottom:2px solid transparent;padding:4px 16px;}}"
            f"QPushButton:hover{{color:{GREEN};border-bottom:2px solid {GREEN};}}")


def filter_active_ss():
    return (f"QPushButton{{background:{GREEN};color:#000;border:none;border-radius:0px;padding:2px 8px;}}")


def filter_inactive_ss():
    return (f"QPushButton{{background:transparent;color:{TEXT_DIM};border:none;padding:2px 8px;}}"
            f"QPushButton:hover{{color:{TEXT};}}")


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS parlays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parlay_label TEXT NOT NULL,
            book TEXT,
            stake REAL DEFAULT 0,
            boost_pct REAL DEFAULT 0,
            status TEXT DEFAULT 'PENDING',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS legs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parlay_id INTEGER NOT NULL,
            game_id TEXT,
            game_display TEXT,
            team TEXT,
            player TEXT,
            market TEXT,
            ou TEXT,
            line TEXT,
            odds TEXT,
            live_stat TEXT,
            leg_status TEXT DEFAULT 'PENDING',
            FOREIGN KEY(parlay_id) REFERENCES parlays(id)
        );
    """)
    c = conn.cursor()
    c.execute("PRAGMA table_info(legs)")
    cols = [row[1] for row in c.fetchall()]
    try:
        if "leg_status" not in cols and "status" in cols:
            conn.execute("ALTER TABLE legs RENAME COLUMN status TO leg_status")
        elif "leg_status" not in cols:
            conn.execute("ALTER TABLE legs ADD COLUMN leg_status TEXT DEFAULT 'PENDING'")
    except Exception:
        if "leg_status" not in cols:
            try:
                conn.execute("ALTER TABLE legs ADD COLUMN leg_status TEXT DEFAULT 'PENDING'")
            except Exception:
                pass
    conn.commit()
    conn.close()


def db():
    return sqlite3.connect(DB_PATH)


# ─────────────────────────────────────────────
# ESPN HELPERS
# ─────────────────────────────────────────────
def espn_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def fetch_scoreboard(week=None, seasontype=2):
    params = {"seasontype": seasontype}
    if week is not None:
        params["week"] = week
    data = espn_get(ESPN_SCOREBOARD, params=params)
    if not data:
        return [], None
    # Extract current week from response
    week_num = None
    try:
        week_num = data.get("week", {}).get("number")
    except Exception:
        pass
    games = []
    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        away = next((t for t in competitors if t.get("homeAway") == "away"), {})
        home = next((t for t in competitors if t.get("homeAway") == "home"), {})
        status = event.get("status", {})
        odds_list = comp.get("odds", [])
        odds = odds_list[0] if odds_list else {}

        def ti(t):
            tm = t.get("team", {})
            name = tm.get("displayName", "")
            color = "#" + str(tm.get("color", "333333")).lstrip("#")
            alt = "#" + str(tm.get("alternateColor", "ffffff")).lstrip("#")
            csv_pair = TEAM_COLORS.get(name.lower())
            if csv_pair:
                color, alt = csv_pair
            recs = t.get("records") or []
            rec = recs[0].get("summary", "") if recs and isinstance(recs[0], dict) else ""
            return {
                "id": str(tm.get("id", "")),
                "name": name,
                "abbr": tm.get("abbreviation", ""),
                "color": color,
                "alt": alt,
                "score": t.get("score", "0"),
                "record": rec,
            }

        games.append({
            "id": str(event.get("id", "")),
            "short": event.get("shortName", ""),
            "state": status.get("type", {}).get("state", "pre"),
            "detail": status.get("type", {}).get("shortDetail", ""),
            "clock": status.get("displayClock", "0:00"),
            "period": status.get("period", 0),
            "away": ti(away),
            "home": ti(home),
            "spread": odds.get("details", "—"),
            "ou": odds.get("overUnder", "—"),
            "home_ml": odds.get("homeTeamOdds", {}).get("moneyLine", "—"),
            "away_ml": odds.get("awayTeamOdds", {}).get("moneyLine", "—"),
        })
    return games, week_num


def fetch_summary(game_id):
    return espn_get(ESPN_SUMMARY, params={"event": game_id})


def fetch_linescores(game_id, team_id):
    url = f"{ESPN_CORE}/events/{game_id}/competitions/{game_id}/competitors/{team_id}/linescores"
    data = espn_get(url)
    if not data:
        return {}
    scores = {}
    for item in data.get("items", []):
        p = item.get("period", 0)
        if isinstance(p, dict):
            p = p.get("number", 0)
        try:
            scores[int(p)] = item.get("displayValue", "—")
        except Exception:
            pass
    return scores


def fetch_plays(game_id, limit=300):
    url = f"{ESPN_CORE}/events/{game_id}/competitions/{game_id}/plays"
    data = espn_get(url, params={"limit": limit})
    if not data:
        return []
    plays = []
    for item in data.get("items", []):
        p = item.get("period", {})
        period = p.get("number", 0) if isinstance(p, dict) else p
        clk = item.get("clock", {})
        clock = clk.get("displayValue", "") if isinstance(clk, dict) else ""
        team_obj = item.get("team", {})
        team_obj = team_obj if isinstance(team_obj, dict) else {}
        team_id = str(team_obj.get("id", ""))
        if not team_id:
            ref = team_obj.get("$ref", "")
            m = re.search(r"/teams/(\d+)", ref)
            if m:
                team_id = m.group(1)
        is_penalty = "penalty" in item.get("text", "").lower()
        plays.append({
            "seq": item.get("sequenceNumber", 0),
            "text": item.get("text", ""),
            "period": period,
            "clock": clock,
            "scoring": item.get("scoringPlay", False),
            "team_id": team_id,
            "penalty": is_penalty,
        })
    return list(reversed(plays))


def fetch_roster(game_id, team_id):
    """Fetch team roster — tries live game endpoint first, falls back to team roster."""
    # Try game-specific roster
    url = f"{ESPN_CORE}/events/{game_id}/competitions/{game_id}/competitors/{team_id}/roster"
    data = espn_get(url)
    players = _parse_roster_entries(data.get("entries", []) if data else [])
    if players:
        return players
    # Fallback: team season roster
    url2 = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster"
    data2 = espn_get(url2)
    if not data2:
        return []
    entries = []
    for group in data2.get("athletes", []):
        entries.extend(group.get("items", []) if isinstance(group, dict) and "items" in group else (
            [group] if isinstance(group, dict) else []))
    return _parse_roster_entries(entries)


def _parse_roster_entries(entries):
    players = []
    for entry in entries:
        # game roster wraps athlete; team roster IS the athlete
        ath = entry.get("athlete", entry)
        pos = ath.get("position", {})
        pos_abbr = pos.get("abbreviation", "") if isinstance(pos, dict) else ""
        players.append({
            "jersey": ath.get("jersey", ""),
            "name": ath.get("displayName", ath.get("fullName", "")),
            "position": pos_abbr,
            "active": entry.get("active", True),
        })
    return [p for p in players if p["name"]]


def _name_match(player_name, athlete_name):
    if not player_name or not athlete_name:
        return False
    a = player_name.lower().strip()
    b = athlete_name.lower().strip()
    if a in b or b in a:
        return True
    a_parts = a.split()
    b_parts = b.split()
    return bool(a_parts and b_parts and a_parts[-1] == b_parts[-1] and len(a_parts[-1]) > 2)


def get_live_stat(summary, player_name, market, team_id):
    if not summary or not player_name or market not in MARKET_STAT_MAP:
        return "—"
    stat_key = MARKET_STAT_MAP[market]
    blocks = (summary.get("boxscore") or {}).get("players") or []

    def scan(require_team):
        for block in blocks:
            bid = str((block.get("team") or {}).get("id", ""))
            if require_team and team_id and bid != str(team_id):
                continue
            for group in block.get("statistics") or []:
                keys = group.get("keys") or []
                if stat_key not in keys:
                    continue
                idx = keys.index(stat_key)
                for ath in group.get("athletes") or []:
                    name = (ath.get("athlete") or {}).get("displayName", "")
                    if _name_match(player_name, name):
                        stats = ath.get("stats") or []
                        if idx < len(stats) and stats[idx] not in (None, ""):
                            return str(stats[idx])
        return None

    hit = scan(True)
    if hit is None:
        hit = scan(False)
    return hit if hit is not None else "—"


def settle_leg(ou, line, live_val, game_state, current_status):
    """Return WON / LOST / existing status from live stat vs line."""
    if current_status in ("WON", "LOST"):
        return current_status
    try:
        cur = float(str(live_val).replace(",", ""))
        tgt = float(str(line).replace(",", ""))
    except Exception:
        return current_status or "PENDING"
    ou_u = (ou or "").upper()
    if ou_u == "OVER":
        if cur > tgt:
            return "WON"
        if game_state == "post":
            return "LOST"
    elif ou_u == "UNDER":
        if cur > tgt:
            return "LOST"
        if game_state == "post" and cur < tgt:
            return "WON"
    return current_status or "PENDING"


def persist_leg_live(leg_id, live_val, status):
    try:
        conn = db()
        conn.execute(
            "UPDATE legs SET live_stat=?, leg_status=? WHERE id=?",
            (str(live_val), status, leg_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_stat_group(summary, team_id, stat_name):
    """Extract a named stat group from the ESPN summary boxscore for a team."""
    for block in (summary or {}).get("boxscore", {}).get("players", []):
        if str(block.get("team", {}).get("id", "")) != str(team_id):
            continue
        for group in block.get("statistics", []):
            if group.get("name", "").lower().startswith(stat_name.lower()):
                return group
    return None


def build_pos_lookup(summary):
    """Build {team_id: {jersey: pos_abbr}} from summary rosters.
    ESPN boxscore stat athletes often omit position; rosters have it."""
    lookup = {}
    for entry in (summary or {}).get("rosters", []):
        team_id = str(entry.get("team", {}).get("id", ""))
        if not team_id:
            continue
        jersey_map = {}
        for r in entry.get("roster", []):
            ath = r.get("athlete", {})
            j = str(ath.get("jersey", "")).strip()
            pos_obj = ath.get("position", {})
            pos = pos_obj.get("abbreviation", "") if isinstance(pos_obj, dict) else ""
            if j and pos:
                jersey_map[j] = pos
        lookup[team_id] = jersey_map
    return lookup


def logo_path(team_name):
    """Return the path to a team logo PNG given the full display name."""
    slug = team_name.lower().replace(" ", "-")
    return os.path.join(LOGO_DIR, f"{slug}-logo.png")


def load_logo(label, team_name, size=64):
    """Load team logo into a QLabel, scaled to size×size."""
    path = logo_path(team_name)
    if os.path.exists(path):
        pm = QPixmap(path)
        label.setPixmap(pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))


# ─────────────────────────────────────────────
# ODDS CALC
# ─────────────────────────────────────────────
def to_decimal(s):
    try:
        v = float(str(s).replace("+", "").strip())
        return (v / 100) + 1 if v > 0 else (100 / abs(v)) + 1
    except Exception:
        return 1.0


def to_american(dec):
    try:
        if dec >= 2.0:
            return f"+{int(round((dec - 1) * 100))}"
        else:
            return str(int(round(-100 / (dec - 1))))
    except Exception:
        return "—"


def calc_parlay(odds_list, stake, boost_pct):
    if not odds_list:
        return {"parlay": "—", "boosted": "—", "to_win": 0.0, "payout": 0.0}
    dec = 1.0
    for o in odds_list:
        dec *= to_decimal(o)
    boost = float(boost_pct) / 100.0 if boost_pct else 0.0
    boosted = dec * (1 + boost) if boost > 0 else dec
    return {
        "parlay": to_american(dec),
        "boosted": to_american(boosted) if boost > 0 else "—",
        "to_win": round(stake * (dec - 1), 2),
        "payout": round(stake + stake * (boosted - 1), 2),
    }


# ─────────────────────────────────────────────
# LOADING SCREEN
# ─────────────────────────────────────────────
class BootWorker(QThread):
    progress = Signal(int, str)
    finished_ok = Signal(object, object)
    failed = Signal(str)

    def run(self):
        try:
            self.progress.emit(8, "LOADING ASSETS")
            load_team_colors()
            self.progress.emit(22, "OPENING DATABASE")
            init_db()
            self.progress.emit(45, "FETCHING NFL SCHEDULE")
            games, week_num = fetch_scoreboard()
            self.progress.emit(78, "LOADING TEAM COLORS")
            load_team_colors()
            self.progress.emit(100, "SYSTEM READY")
            self.finished_ok.emit(games or [], week_num)
        except Exception:
            self.failed.emit(traceback.format_exc())


class LoadingScreen(QWidget):
    """Full-bleed splash matching the Hera statue mockup: no photo card."""
    ready = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(720, 960)
        self.setStyleSheet("background:#0a0a0a;")
        self._pct = 0
        self._status = "STARTING"
        self._pending = None
        self._started_at = time.monotonic()
        self._statue = QPixmap()
        src = LOGO_NOBG if os.path.exists(LOGO_NOBG) else LOGO_ORIG
        if os.path.exists(src):
            self._statue = QPixmap(src)
        self._worker = BootWorker()
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_ready)
        self._worker.failed.connect(self._on_fail)

    def start(self):
        self._center()
        self.show()
        self._started_at = time.monotonic()
        self._worker.start()

    def _center(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2,
                      geo.center().y() - self.height() // 2)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#0a0a0a"))

        # Statue — transparent PNG, no backing card
        if not self._statue.isNull():
            sw, sh = 340, 454
            pm = self._statue.scaled(sw, sh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = (self.width() - pm.width()) // 2
            y = 88
            p.drawPixmap(x, y, pm)
            statue_bottom = y + pm.height()
        else:
            statue_bottom = 520

        t = max(0, min(100, self._pct)) / 100.0
        # Glow from dim forest to neon as the bar fills (one word, all letters together)
        r = int(8 + (39 - 8) * t)
        g = int(32 + (255 - 32) * t)
        b = int(8 + (60 - 8) * t)
        glow = QColor(r, g, b)
        word = "HERA"
        font = bb(64)
        p.setFont(font)
        p.setPen(Qt.NoPen)
        # soft glow passes
        for spread, alpha in ((18, 28), (10, 55), (4, 90)):
            c = QColor(glow)
            c.setAlpha(int(alpha * t + 8))
            p.setPen(c)
            p.drawText(self.rect().adjusted(0, statue_bottom + 28 - spread // 2, 0, 0),
                       Qt.AlignHCenter | Qt.AlignTop, word)
        p.setPen(glow)
        p.drawText(self.rect().adjusted(0, statue_bottom + 36, 0, 0),
                   Qt.AlignHCenter | Qt.AlignTop, word)

        # Status
        p.setFont(bb(11))
        p.setPen(QColor("#8a8a8a"))
        p.drawText(self.rect().adjusted(0, statue_bottom + 130, 0, 0),
                   Qt.AlignHCenter | Qt.AlignTop, self._status)

        # Hairline progress bar
        bar_y = statue_bottom + 168
        margin = 48
        bar_w = self.width() - margin * 2
        p.fillRect(margin, bar_y, bar_w, 2, QColor("#1c1c1c"))
        fill = max(2, int(bar_w * t))
        p.fillRect(margin, bar_y, fill, 2, QColor(GREEN))

        p.setFont(bb(9))
        p.setPen(QColor("#555555"))
        p.drawText(self.rect().adjusted(0, bar_y + 14, 0, 0),
                   Qt.AlignHCenter | Qt.AlignTop, f"{int(self._pct)}%")
        p.end()

    def _on_progress(self, pct, msg):
        self._pct = pct
        self._status = msg
        self.update()

    def _on_ready(self, games, week_num):
        self._pending = (games, week_num)
        remain_ms = max(0, int((30 - (time.monotonic() - self._started_at)) * 1000))
        QTimer.singleShot(remain_ms, self._finish)

    def _finish(self):
        games, week_num = self._pending if self._pending is not None else ([], None)
        self.ready.emit(games, week_num)
        self.close()

    def _on_fail(self, err):
        self._status = "STARTUP FAILED"
        self.update()
        print("FATAL ERROR:\n", err)


class BadgeLabel(QLabel):
    """QLabel that paints its own colored background via QPainter,
    bypassing Qt's stylesheet cascade so the color always shows
    regardless of what the parent widget's stylesheet says."""

    def __init__(self, text, bg_hex, fg_hex, parent=None):
        super().__init__(text, parent)
        self._bg = QColor(bg_hex)
        self._fg = QColor(fg_hex)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
        except AttributeError:
            p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.GlobalColor.transparent)
        p.setBrush(self._bg)
        r = self.rect()
        p.drawRoundedRect(r, 3, 3)
        p.setPen(self._fg)
        p.setFont(self.font())
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), self.text())
        p.end()


# ─────────────────────────────────────────────
class NavBar(QWidget):
    tab_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(61)
        self.setStyleSheet(f"background:{NAV_BG}; border-bottom:0.5px solid {BORDER};")
        self._btns = []
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(0)

        name = QLabel("HERA")
        name.setFont(bb(22))
        name.setStyleSheet(f"color:{GREEN}; background:transparent; border:none; letter-spacing:4px;")
        lay.addWidget(name)
        lay.addStretch()

        for i, t in enumerate(["GAME TRACKER", "PLAY BY PLAY", "BET ENTRY", "ACTIVE LEGS", "ARCHIVE"]):
            btn = QPushButton(t)
            btn.setFont(bb(11))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(partial(self._select, i))
            self._btns.append(btn)
            lay.addWidget(btn)
            if i < 4:
                lay.addSpacing(2)

        self._select(0)

    def _select(self, idx):
        for i, btn in enumerate(self._btns):
            btn.setStyleSheet(nav_active_ss() if i == idx else nav_inactive_ss())
        self.tab_changed.emit(idx)


# ─────────────────────────────────────────────
# SECTION HEADER FACTORY
# ─────────────────────────────────────────────
def sec_hdr(left, right="", right_color=GREEN):
    w = QWidget()
    w.setFixedHeight(41)
    w.setStyleSheet(f"background:{HDR_BG}; border-bottom:0.5px solid {BORDER};")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(14, 0, 14, 0)
    l = QLabel(left)
    l.setFont(bb(10))
    l.setStyleSheet(f"color:{TEXT_DIM}; letter-spacing:3px; background:transparent;")
    lay.addWidget(l)
    lay.addStretch()
    if right:
        r = QLabel(right)
        r.setFont(bb(10))
        r.setStyleSheet(f"color:{right_color}; background:transparent;")
        lay.addWidget(r)
    return w


# ─────────────────────────────────────────────
# SCORE HEADER  (3-panel broadcast layout)
# ─────────────────────────────────────────────
class ScoreHeader(QWidget):
    """
    Three-panel score header matching hera_mockup.html .score-hdr:
      AWAY  [team-bg | logo+name+record LEFT | score RIGHT at 72px]
      CENTER [dark | ● LIVE | clock 38px | quarter | situation]
      HOME  [team-bg | score LEFT at 72px | logo+name+record RIGHT]
    """

    def __init__(self):
        super().__init__()
        self.setFixedHeight(223)
        self.setStyleSheet(f"background:{BG};")
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── AWAY PANEL ──────────────────────────────
        self._away_panel = QWidget()
        self._away_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        away_lay = QHBoxLayout(self._away_panel)
        away_lay.setContentsMargins(16, 16, 20, 16)
        away_lay.setSpacing(0)

        # Left side: info column (logo, name, record)
        away_info = QVBoxLayout()
        away_info.setSpacing(4)
        away_info.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        self._away_logo = QLabel()
        self._away_logo.setFixedSize(81, 81)
        self._away_logo.setStyleSheet("background:transparent;")
        self._away_logo.setScaledContents(False)

        self._away_name = QLabel("AWAY TEAM")
        self._away_name.setFont(bb(13))
        self._away_name.setStyleSheet(f"color:{TEXT}; background:transparent; letter-spacing:1px;")

        self._away_rec = QLabel("")
        self._away_rec.setFont(bb(10))
        self._away_rec.setStyleSheet(f"color:{TEXT_DIM}; background:transparent;")

        away_info.addWidget(self._away_logo)
        away_info.addWidget(self._away_name)
        away_info.addWidget(self._away_rec)

        # Right side: score
        self._away_score = QLabel("0")
        self._away_score.setFont(bb(72))
        self._away_score.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._away_score.setStyleSheet(f"color:{TEXT}; background:transparent;")
        self._away_score.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        away_lay.addLayout(away_info)
        away_lay.addStretch()
        away_lay.addWidget(self._away_score)

        # ── CENTER PANEL ─────────────────────────────
        self._center = QWidget()
        self._center.setFixedWidth(180)
        self._center.setStyleSheet(f"background:{BG};")
        center_lay = QVBoxLayout(self._center)
        center_lay.setAlignment(Qt.AlignCenter)
        center_lay.setSpacing(4)
        center_lay.setContentsMargins(8, 12, 8, 12)

        self._live_dot = QLabel("● LIVE")
        self._live_dot.setFont(bb(11))
        self._live_dot.setAlignment(Qt.AlignCenter)
        self._live_dot.setStyleSheet(f"color:{GREEN}; background:transparent; letter-spacing:3px;")

        self._clock_lbl = QLabel("0:00")
        self._clock_lbl.setFont(bb(38))
        self._clock_lbl.setAlignment(Qt.AlignCenter)
        self._clock_lbl.setStyleSheet(f"color:{TEXT}; background:transparent;")

        self._quarter_lbl = QLabel("")
        self._quarter_lbl.setFont(bb(12))
        self._quarter_lbl.setAlignment(Qt.AlignCenter)
        self._quarter_lbl.setStyleSheet(f"color:{TEXT_MID}; background:transparent; letter-spacing:2px;")

        self._sit_lbl = QLabel("")
        self._sit_lbl.setFont(bb(10))
        self._sit_lbl.setAlignment(Qt.AlignCenter)
        self._sit_lbl.setWordWrap(True)
        self._sit_lbl.setStyleSheet(f"color:{TEXT_DIM}; background:transparent;")

        center_lay.addWidget(self._live_dot)
        center_lay.addWidget(self._clock_lbl)
        center_lay.addWidget(self._quarter_lbl)
        center_lay.addWidget(self._sit_lbl)

        # ── HOME PANEL ───────────────────────────────
        self._home_panel = QWidget()
        self._home_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        home_lay = QHBoxLayout(self._home_panel)
        home_lay.setContentsMargins(20, 16, 16, 16)
        home_lay.setSpacing(0)

        # Left side: score
        self._home_score = QLabel("0")
        self._home_score.setFont(bb(72))
        self._home_score.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._home_score.setStyleSheet(f"color:{TEXT}; background:transparent;")
        self._home_score.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        # Right side: info column (logo, name, record)
        home_info = QVBoxLayout()
        home_info.setSpacing(4)
        home_info.setAlignment(Qt.AlignVCenter | Qt.AlignRight)

        self._home_logo = QLabel()
        self._home_logo.setFixedSize(81, 81)
        self._home_logo.setStyleSheet("background:transparent;")
        self._home_logo.setScaledContents(False)
        self._home_logo.setAlignment(Qt.AlignRight)

        self._home_name = QLabel("HOME TEAM")
        self._home_name.setFont(bb(13))
        self._home_name.setAlignment(Qt.AlignRight)
        self._home_name.setStyleSheet(f"color:{TEXT}; background:transparent; letter-spacing:1px;")

        self._home_rec = QLabel("")
        self._home_rec.setFont(bb(10))
        self._home_rec.setAlignment(Qt.AlignRight)
        self._home_rec.setStyleSheet(f"color:{TEXT_DIM}; background:transparent;")

        home_info.addWidget(self._home_logo, 0, Qt.AlignRight)
        home_info.addWidget(self._home_name)
        home_info.addWidget(self._home_rec)

        home_lay.addWidget(self._home_score)
        home_lay.addStretch()
        home_lay.addLayout(home_info)

        # Assemble root
        root.addWidget(self._away_panel, 1)
        root.addWidget(self._center)
        root.addWidget(self._home_panel, 1)

    def refresh(self, game, summary=None):
        away = game["away"]
        home = game["home"]

        # Away panel
        self._away_panel.setStyleSheet(f"background:{away['color']};")
        alt_a = away["alt"]
        self._away_score.setText(str(away["score"]))
        self._away_score.setStyleSheet(f"color:{alt_a}; background:transparent;")
        self._away_name.setText(away["name"].upper())
        self._away_name.setStyleSheet(f"color:{alt_a}; background:transparent; letter-spacing:1px;")
        rec_a = f"{away['record']} · AWAY" if away["record"] else "AWAY"
        self._away_rec.setText(rec_a)
        self._away_rec.setStyleSheet(f"color:{alt_a}; opacity:0.8; background:transparent;")
        load_logo(self._away_logo, away["name"], 81)

        # Home panel
        self._home_panel.setStyleSheet(f"background:{home['color']};")
        alt_h = home["alt"]
        self._home_score.setText(str(home["score"]))
        self._home_score.setStyleSheet(f"color:{alt_h}; background:transparent;")
        self._home_name.setText(home["name"].upper())
        self._home_name.setStyleSheet(f"color:{alt_h}; background:transparent; letter-spacing:1px;")
        rec_h = f"{home['record']} · HOME" if home["record"] else "HOME"
        self._home_rec.setText(rec_h)
        self._home_rec.setStyleSheet(f"color:{alt_h}; background:transparent;")
        load_logo(self._home_logo, home["name"], 81)

        # Center panel — game status
        state = game["state"]
        period = game["period"]
        clock = game["clock"]
        qmap = {1: "1ST QUARTER", 2: "2ND QUARTER", 3: "3RD QUARTER", 4: "4TH QUARTER", 5: "OVERTIME"}

        if state == "in":
            self._live_dot.setText("● LIVE")
            self._live_dot.setStyleSheet(f"color:{GREEN}; background:transparent; letter-spacing:3px;")
            self._clock_lbl.setText(clock)
            self._clock_lbl.setVisible(True)
            self._quarter_lbl.setText(qmap.get(period, f"Q{period}"))
        elif state == "post":
            self._live_dot.setText("FINAL")
            self._live_dot.setStyleSheet(f"color:{TEXT_DIM}; background:transparent; letter-spacing:3px;")
            self._clock_lbl.setVisible(False)
            self._quarter_lbl.setText("GAME OVER")
        else:
            self._live_dot.setText(et_to_pt(game.get("detail", "UPCOMING")))
            self._live_dot.setStyleSheet(f"color:{TEXT_DIM}; background:transparent; letter-spacing:2px;")
            self._clock_lbl.setVisible(False)
            self._quarter_lbl.setText("")

        if summary:
            sit = summary.get("situation") or {}
            if not isinstance(sit, dict):
                sit = {}
            self._sit_lbl.setText(sit.get("downDistanceText", "") or "")
        else:
            self._sit_lbl.setText("")


# ─────────────────────────────────────────────
# BOX SCORE  (linescore table)
# ─────────────────────────────────────────────
class BoxScore(QWidget):
    """Full-width linescore — pure QWidget rows, matches mockup exactly."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background:{BG}; border:none;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._build()

    def _build(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 8)
        outer.setSpacing(0)
        outer.addStretch(1)

        card = QWidget()
        card.setStyleSheet(
            f"background:{CARD}; border:1px solid {BORDER}; border-radius:4px;")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.setSpacing(0)

        # ── "BOXSCORE" title ──────────────────────────────────────────
        title = QLabel("BOXSCORE")
        title.setFont(bb(9))
        title.setAlignment(Qt.AlignCenter)
        title.setFixedHeight(33)
        title.setStyleSheet(
            f"color:{TEXT_DIM}; letter-spacing:4px; background:{HDR_BG}; border:none;")
        card_lay.addWidget(title)

        # ── Q header row ──────────────────────────────────────────────
        q_hdr = QWidget()
        q_hdr.setFixedHeight(39)
        q_hdr.setStyleSheet(
            f"background:{HDR_BG}; border:none;")
        ql = QHBoxLayout(q_hdr)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.setSpacing(0)

        blank = QLabel("")
        blank.setFixedWidth(127)
        blank.setStyleSheet("background:transparent;")
        ql.addWidget(blank)

        for q_name in ["Q1", "Q2", "Q3", "Q4"]:
            ql.addWidget(self._q_label(q_name, stretch=True))

        ql.addWidget(self._q_label("TOTAL", width=113))

        card_lay.addWidget(q_hdr)

        # ── Team rows (rebuilt in refresh()) ─────────────────────────
        self._row_widgets = []
        for i in range(2):
            row = QWidget()
            row.setFixedHeight(53)
            # only first row gets a bottom border (separator between teams)
            border = f"border-bottom:1px solid {BORDER};" if i == 0 else ""
            row.setStyleSheet(f"background:{BG}; border:none; {border}")
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(0)
            card_lay.addWidget(row)
            self._row_widgets.append(row)

        outer.addWidget(card, 6)
        outer.addStretch(1)

    def _q_label(self, text, stretch=False, width=None):
        l = QLabel(text)
        l.setFont(bb(10))
        l.setAlignment(Qt.AlignCenter)
        l.setStyleSheet(
            f"color:{TEXT_DIM}; letter-spacing:2px; background:transparent;")
        if stretch:
            l.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            l.setFixedWidth(width or 124)
        return l

    def refresh(self, game, away_ls=None, home_ls=None):
        for row_w, (team, ls) in zip(
                self._row_widgets,
                [(game["away"], away_ls or {}), (game["home"], home_ls or {})]):

            lay = row_w.layout()
            while lay.count():
                item = lay.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            # Colored badge
            badge = QWidget()
            badge.setFixedSize(127, 49)
            badge.setStyleSheet(
                f"background:{team['color']}; border:none;")
            bl = QHBoxLayout(badge)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(0)
            bl.addStretch()
            logo_lbl = QLabel()
            logo_lbl.setFixedSize(28, 28)
            logo_lbl.setStyleSheet("background:transparent;")
            load_logo(logo_lbl, team["name"], 28)
            bl.addWidget(logo_lbl)
            bl.addStretch()
            lay.addWidget(badge)

            # Q1-Q4 scores
            for q in range(1, 5):
                val = str(ls.get(q, "—")) if ls else "—"
                sc = QLabel(val)
                sc.setFont(bb(13))
                sc.setAlignment(Qt.AlignCenter)
                sc.setStyleSheet(f"color:{TEXT}; background:transparent;")
                sc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                sc.setFixedHeight(53)
                lay.addWidget(sc)

            # Total
            tot = QLabel(str(team["score"]))
            tot.setFont(bb(15))
            tot.setAlignment(Qt.AlignCenter)
            tot.setFixedSize(113, 49)
            tot.setStyleSheet(f"color:{TEXT}; background:transparent;")
            lay.addWidget(tot)


# ─────────────────────────────────────────────
# WIN PROBABILITY BAR
# ─────────────────────────────────────────────
class WinProbBar(QWidget):
    """
    Full-width 6px split bar with % labels.
    Tries to read homeWinPercentage from summary.winprobability[].
    Falls back to 50/50.
    """

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background:{BG};")
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 4)
        lay.setSpacing(4)

        # Label row: away% | "WIN PROBABILITY" | home%
        lbl_row = QHBoxLayout()
        self._away_pct = QLabel("—")
        self._away_pct.setFont(bb(11))
        self._away_pct.setStyleSheet(f"color:{TEXT_DIM}; background:transparent;")

        center_lbl = QLabel("WIN PROBABILITY")
        center_lbl.setFont(bb(9))
        center_lbl.setAlignment(Qt.AlignCenter)
        center_lbl.setStyleSheet(f"color:{TEXT_DARK}; letter-spacing:2px; background:transparent;")

        self._home_pct = QLabel("—")
        self._home_pct.setFont(bb(11))
        self._home_pct.setAlignment(Qt.AlignRight)
        self._home_pct.setStyleSheet(f"color:{TEXT_DIM}; background:transparent;")

        lbl_row.addWidget(self._away_pct)
        lbl_row.addStretch()
        lbl_row.addWidget(center_lbl)
        lbl_row.addStretch()
        lbl_row.addWidget(self._home_pct)
        lay.addLayout(lbl_row)

        # 6px bar
        bar_frame = QWidget()
        bar_frame.setFixedHeight(16)
        bar_frame.setStyleSheet(f"background:{BORDER}; border-radius:0px;")
        bar_lay = QHBoxLayout(bar_frame)
        bar_lay.setContentsMargins(0, 0, 0, 0)
        bar_lay.setSpacing(0)

        self._away_fill = QWidget()
        self._away_fill.setStyleSheet(f"background:#e42138; border-radius:0px;")
        self._home_fill = QWidget()
        self._home_fill.setStyleSheet(f"background:#128e5a; border-radius:0px;")
        bar_lay.addWidget(self._away_fill, 50)
        bar_lay.addWidget(self._home_fill, 50)

        self._bar_frame = bar_frame
        lay.addWidget(bar_frame)

    def refresh(self, game, summary=None):
        away = game["away"]
        home = game["home"]

        # Read win probability from ESPN summary
        away_pct = 50
        home_pct = 50
        if summary:
            wp_list = summary.get("winprobability") or []
            if isinstance(wp_list, list) and wp_list:
                last = wp_list[-1]
                if isinstance(last, dict):
                    raw = last.get("homeWinPercentage", 0.5)
                    try:
                        home_pct = int(round(float(raw) * 100))
                        away_pct = 100 - home_pct
                    except Exception:
                        pass

        self._away_pct.setText(f"{away_pct}%  {away['abbr']}")
        self._away_pct.setStyleSheet(f"color:{away['alt']}; background:transparent;")
        self._home_pct.setText(f"{home['abbr']}  {home_pct}%")
        self._home_pct.setStyleSheet(f"color:{home['alt']}; background:transparent;")

        self._away_fill.setStyleSheet(f"background:{away['alt']}; border-radius:0px;")
        self._home_fill.setStyleSheet(f"background:{home['alt']}; border-radius:0px;")

        bar_lay = self._bar_frame.layout()
        bar_lay.setStretch(0, max(1, away_pct))
        bar_lay.setStretch(1, max(1, home_pct))


# ─────────────────────────────────────────────
# ODDS STRIP
# ─────────────────────────────────────────────
class OddsStrip(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(card_ss())
        self._cells = {}
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for i, key in enumerate(["SPREAD", "TOTAL", "MONEYLINE"]):
            cell = QWidget()
            rb = f"border-right:0.5px solid {BORDER2};" if i < 2 else ""
            cell.setStyleSheet(f"background:transparent;{rb}")
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(14, 8, 14, 8)
            cl.setSpacing(2)
            lbl = QLabel(key)
            lbl.setFont(bb(10))
            lbl.setStyleSheet(f"color:{TEXT_DARK}; letter-spacing:3px; background:transparent;")
            val = QLabel("—")
            val.setFont(bb(14))
            val.setStyleSheet(f"color:{TEXT}; background:transparent;")
            det = QLabel("")
            det.setFont(bb(11))
            det.setStyleSheet(f"color:{TEXT_DIM}; background:transparent;")
            cl.addWidget(lbl);
            cl.addWidget(val);
            cl.addWidget(det)
            self._cells[key] = (val, det)
            lay.addWidget(cell, 1)

    def refresh(self, game):
        def fmt(v):
            try:
                iv = int(v)
                return f"+{iv}" if iv > 0 else str(iv)
            except Exception:
                return str(v)

        self._cells["SPREAD"][0].setText(str(game.get("spread", "—")))
        ou = game.get("ou", "—")
        self._cells["TOTAL"][0].setText(f"O/U {ou}" if ou and ou != "—" else "—")
        try:
            pts = int(game["away"]["score"] or 0) + int(game["home"]["score"] or 0)
            self._cells["TOTAL"][1].setText(f"Current: {pts} pts")
        except Exception:
            pass
        self._cells["MONEYLINE"][0].setText(f"{game['home']['abbr']} {fmt(game.get('home_ml', '—'))}")
        self._cells["MONEYLINE"][1].setText(f"{game['away']['abbr']} {fmt(game.get('away_ml', '—'))}")


# ─────────────────────────────────────────────
# ACTIVE BETS PANEL  (game-tracker table format)
# ─────────────────────────────────────────────
class ActiveBetsPanel(QWidget):
    """
    Table-format active bets panel shown inside the game tracker.
    Columns: TEAM | PLAYER | PROP | O/U | LINE | CURRENT | NEEDS | STATUS
    WON rows  → full row green text
    LOST rows → full row red text
    """

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background:{BG}; border:none;")
        self._game_id = None
        self._games = []
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header bar
        self._hdr = QWidget()
        self._hdr.setFixedHeight(41)
        self._hdr.setStyleSheet(f"background:{HDR_BG};")
        hl = QHBoxLayout(self._hdr)
        hl.setContentsMargins(12, 0, 12, 0)
        self._title_lbl = QLabel("MY ACTIVE BETS")
        self._title_lbl.setFont(bb(10))
        self._title_lbl.setStyleSheet(f"color:{TEXT}; letter-spacing:2px; background:transparent;")
        self._info_lbl = QLabel("")
        self._info_lbl.setFont(bb(9))
        self._info_lbl.setStyleSheet(f"color:{TEXT_DIM}; background:transparent;")
        hl.addWidget(self._title_lbl)
        hl.addStretch()
        hl.addWidget(self._info_lbl)
        lay.addWidget(self._hdr)

        # Table
        self._tbl = QTableWidget(0, 8)
        self._tbl.setHorizontalHeaderLabels(
            ["TEAM", "PLAYER", "PROP", "O/U", "LINE", "CURRENT", "NEEDS", "STATUS"])
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tbl.setSelectionMode(QTableWidget.NoSelection)
        self._tbl.setStyleSheet(table_ss())
        self._tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._tbl.setShowGrid(False)
        lay.addWidget(self._tbl)

        # Empty state label
        self._empty = QLabel("NO ACTIVE BETS FOR THIS GAME")
        self._empty.setFont(bb(11))
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet(
            f"color:{TEXT_DIM}; padding:14px; background:transparent;")
        lay.addWidget(self._empty)
        self._empty.setVisible(True)
        self._tbl.setVisible(False)

    def set_game(self, game_id, games):
        self._game_id = game_id
        self._games = games

    def refresh(self, game=None, summary=None):
        if not self._game_id:
            return

        # Update header title with matchup
        if game:
            self._title_lbl.setText(
                f"MY ACTIVE BETS — {game['away']['abbr']}@{game['home']['abbr']}")

        conn = db()
        c = conn.cursor()
        c.execute("""
            SELECT l.id, p.parlay_label, p.book,
                   l.team, l.player, l.market, l.ou,
                   l.line, l.odds, l.live_stat, l.leg_status
            FROM legs l JOIN parlays p ON l.parlay_id = p.id
            WHERE CAST(l.game_id AS TEXT) = CAST(? AS TEXT)
              AND p.status IN ('LIVE','PENDING')
            ORDER BY l.id
        """, (self._game_id,))
        legs = c.fetchall()
        conn.close()

        if not legs:
            self._tbl.setRowCount(0)
            self._tbl.setVisible(False)
            self._empty.setVisible(True)
            self._info_lbl.setText("")
            return

        self._tbl.setVisible(True)
        self._empty.setVisible(False)
        self._info_lbl.setText(f"{len(legs)} LEGS TRACKED")
        self._tbl.setRowCount(len(legs))

        for r, leg in enumerate(legs):
            lid, plabel, book, team, player, market, ou, line, odds, live_stat, leg_status = leg

            # Pull live stat value
            live_val = live_stat or "—"
            if summary and player and game:
                away = game.get("away") or {}
                home = game.get("home") or {}
                if team == away.get("abbr"):
                    tid = away.get("id")
                elif team == home.get("abbr"):
                    tid = home.get("id")
                else:
                    tid = ""
                v = get_live_stat(summary, player, market, tid)
                if v != "—":
                    live_val = v
            state = (game or {}).get("state", "")
            new_status = settle_leg(ou, line, live_val, state, leg_status)
            if live_val != (live_stat or "—") or new_status != leg_status:
                persist_leg_live(lid, live_val, new_status)
                leg_status = new_status

            # Calculate "NEEDS" (remaining to hit the line)
            needs = "—"
            try:
                cur = float(str(live_val).replace(",", ""))
                tgt = float(str(line).replace(",", ""))
                if (ou or "").upper() == "OVER":
                    needs = str(max(0, round(tgt - cur + 0.5, 1)))
                elif (ou or "").upper() == "UNDER":
                    needs = str(max(0, round(tgt - cur, 1))) if cur <= tgt else "0"
            except Exception:
                pass

            is_won = leg_status == "WON"
            is_lost = leg_status == "LOST"

            if is_won:
                row_color = GREEN
            elif is_lost:
                row_color = RED
            else:
                row_color = TEXT

            status_text = leg_status if leg_status else "PENDING"
            vals = [
                team or "—", player or "—", market or "—", ou or "—",
                str(line) if line else "—", str(live_val), str(needs), status_text
            ]

            for ci, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                it.setFont(bb(11))
                it.setForeground(QColor(row_color))
                it.setTextAlignment(Qt.AlignCenter)
                self._tbl.setItem(r, ci, it)

            self._tbl.setRowHeight(r, 28)

        self._tbl.setFixedHeight(39 * len(legs) + 41)


# ─────────────────────────────────────────────
# STAT SECTION  (one PASSING / RUSHING / RECEIVING block)
# ─────────────────────────────────────────────
class StatSection(QWidget):
    """
    A single stat category (PASSING / RUSHING / RECEIVING) for one team.
    Pure-QWidget implementation — no QTableWidget so no stylesheet override issues.
    """

    def __init__(self, label, side):
        super().__init__()
        self._label = label
        self._side = side
        # ID selector so background doesn't cascade to child badge labels
        _n = f"ss{id(self)}"
        self.setObjectName(_n)
        self.setStyleSheet(f"QWidget#{_n} {{ background:{BG}; border:none; }}")
        self._build()

    # ── widths must match between header row and player rows ──
    W_NUM = 37  # # column
    W_POS = 61  # POS column
    W_STAT = 64  # each stat column

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Team-colored header strip (PASSING / RUSHING / RECEIVING)
        self._hdr_w = QWidget()
        self._hdr_w.setFixedHeight(39)
        self._hdr_w.setStyleSheet(f"background:{HDR_BG};")
        hl = QHBoxLayout(self._hdr_w)
        hl.setContentsMargins(10, 0, 10, 0)
        hl.setSpacing(0)
        self._arrow_lbl = QLabel(self._label)
        self._arrow_lbl.setFont(bb(10))
        self._arrow_lbl.setStyleSheet(
            f"color:{TEXT}; background:transparent; letter-spacing:2px;")
        if self._side == "away":
            hl.addWidget(self._arrow_lbl)
            hl.addStretch()
        else:
            hl.addStretch()
            hl.addWidget(self._arrow_lbl)
        lay.addWidget(self._hdr_w)

        # Rows container — col-header row + player rows live here
        self._rows = QWidget()
        self._rows.setStyleSheet(f"background:{BG};")
        self._rows_lay = QVBoxLayout(self._rows)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(0)
        lay.addWidget(self._rows)

    def set_color(self, color, alt, team_name):
        self._hdr_w.setStyleSheet(f"background:{color};")
        self._arrow_lbl.setStyleSheet(
            f"color:{alt}; background:transparent; letter-spacing:2px;")

    # ── helpers ──────────────────────────────────────────────────

    def _clear_rows(self):
        while self._rows_lay.count():
            item = self._rows_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _row_widget(self, bg, h=32):
        w = QWidget()
        w.setFixedHeight(h)
        # Use an ID selector so the stylesheet only targets this widget,
        # not its children — otherwise Qt cascades background to all descendants
        # and overrides child QLabel background-color styling (the badge bug).
        name = f"r{id(w)}"
        w.setObjectName(name)
        w.setStyleSheet(
            f"QWidget#{name} {{ background:{bg}; border-bottom:1px solid {BORDER2}; }}")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        return w, lay

    def _cell(self, text, width, font, color, align=Qt.AlignCenter, expand=False):
        lbl = QLabel(text)
        lbl.setFont(font)
        lbl.setAlignment(align)
        lbl.setStyleSheet(f"color:{color}; background:transparent;")
        if expand:
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            lbl.setFixedWidth(width)
        return lbl

    # ── populate ─────────────────────────────────────────────────

    def load(self, group, pos_lookup=None):
        self._clear_rows()
        self._content_h = 39  # always at least the color header (_hdr_w height)
        if not group:
            return

        labels = group.get("labels", group.get("keys", []))
        athletes = group.get("athletes", [])
        totals = group.get("totals", [])
        stat_labels = labels[:7]

        # Column-header row
        hdr_w, hdr_lay = self._row_widget(HDR_BG, h=32)
        hdr_w.setStyleSheet(
            f"background:{HDR_BG}; border-bottom:1px solid {BORDER};")
        hdr_lay.addWidget(self._cell("#", self.W_NUM, bb(8), TEXT_MID))
        hdr_lay.addWidget(self._cell("POS", self.W_POS, bb(8), TEXT_MID))
        hdr_lay.addWidget(self._cell("PLAYER", 0, bb(8), TEXT_MID,
                                     Qt.AlignVCenter | Qt.AlignLeft, expand=True))
        for sl in stat_labels:
            hdr_lay.addWidget(self._cell(sl, self.W_STAT, bb(8), TEXT_MID))
        self._rows_lay.addWidget(hdr_w)
        self._content_h += 32

        # Filter athletes with non-zero stats
        valid = []
        for ae in athletes:
            s = ae.get("stats", [])
            if s and any(v not in ("0", "0.0", "0/0", "—", "") for v in s):
                valid.append(ae)

        # Player rows
        for ae in valid:
            ath = ae.get("athlete", {})
            jersey = ath.get("jersey", "")
            pos_obj = ath.get("position", {})
            pos = pos_obj.get("abbreviation", "") if isinstance(pos_obj, dict) else ""
            # Fallback 1: ESPN boxscore athletes often omit position — look up from roster
            if not pos and pos_lookup and jersey:
                pos = pos_lookup.get(str(jersey).strip(), "")
            # Fallback 2: infer from stat section so badge always shows something
            if not pos:
                pos = {"PASSING": "QB", "RUSHING": "RB", "RECEIVING": "WR"}.get(self._label, "")
            name = ath.get("displayName", "")
            stats = ae.get("stats", [])

            row_w, row_lay = self._row_widget(BG, h=32)

            # Jersey #
            row_lay.addWidget(self._cell(jersey, self.W_NUM, bb(10), TEXT_DARK))

            # POS badge — BadgeLabel paints its own bg via QPainter,
            # immune to parent stylesheet cascade
            pos_bg, pos_fg = POS_COLORS.get(pos, ("#252525", TEXT_DIM))
            pb = BadgeLabel(pos, pos_bg, pos_fg)
            pb.setFont(bb(9))
            pb.setFixedWidth(self.W_POS - 8)
            pb.setFixedHeight(23)
            pc = QWidget()
            pc.setFixedWidth(self.W_POS)
            pc.setFixedHeight(32)
            pcl = QHBoxLayout(pc)
            pcl.setContentsMargins(4, 3, 4, 3)
            pcl.setSpacing(0)
            pcl.addWidget(pb)
            row_lay.addWidget(pc)

            # Player name
            nm = QLabel(name)
            nm.setFont(bb(10))
            nm.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            nm.setStyleSheet(f"color:{TEXT_MID}; background:transparent;")
            nm.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            row_lay.addWidget(nm)

            # Stat values
            for val in stats[:len(stat_labels)]:
                row_lay.addWidget(
                    self._cell(str(val) if val is not None else "—",
                               self.W_STAT, bb(10), TEXT))

            self._rows_lay.addWidget(row_w)
            self._content_h += 32

        # Totals row
        if totals:
            tot_w = QWidget()
            tot_w.setFixedHeight(28)
            tot_w.setStyleSheet(f"background:{HDR_BG};")
            tl = QHBoxLayout(tot_w)
            tl.setContentsMargins(0, 0, 0, 0)
            tl.setSpacing(0)
            # fixed spacer matching # + POS so stat values line up with player rows
            tl.addWidget(self._cell("", self.W_NUM + self.W_POS, bb(9), TEXT_DARK))
            tl.addWidget(self._cell("TOTALS", 0, bb(9), TEXT_DARK,
                                    Qt.AlignVCenter | Qt.AlignLeft, expand=True))
            for val in totals[:len(stat_labels)]:
                tl.addWidget(
                    self._cell(str(val) if val is not None else "—",
                               self.W_STAT, bb(9), TEXT_DARK))
            self._rows_lay.addWidget(tot_w)
            self._content_h += 28


class StatBox(QWidget):
    """
    Contains PASSING, RUSHING, and RECEIVING StatSection widgets for one team.
    """

    def __init__(self, side):
        """side: 'away' | 'home'"""
        super().__init__()
        self._side = side
        self.setStyleSheet(f"background:{BG}; border:none;")
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._pass_sec = StatSection("PASSING", self._side)
        self._rush_sec = StatSection("RUSHING", self._side)
        self._recv_sec = StatSection("RECEIVING", self._side)

        lay.addWidget(self._pass_sec)
        lay.addWidget(self._rush_sec)
        lay.addWidget(self._recv_sec)
        lay.addStretch()

    def load(self, team_color, team_alt, team_name,
             pass_group, rush_group, recv_group, pos_lookup=None):
        """Apply team colors and populate all three stat sections."""
        for sec in [self._pass_sec, self._rush_sec, self._recv_sec]:
            sec.set_color(team_color, team_alt, team_name)

        self._pass_sec.load(pass_group, pos_lookup=pos_lookup)
        self._rush_sec.load(rush_group, pos_lookup=pos_lookup)
        self._recv_sec.load(recv_group, pos_lookup=pos_lookup)


# ─────────────────────────────────────────────
# PLAY BY PLAY
# ─────────────────────────────────────────────
class PBPWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background:{BG};")
        self._plays = []
        self._filter = "ALL PLAYS"
        self._away = {}
        self._home = {}
        self._bet_players = set()
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Filter header
        hdr = QWidget()
        hdr.setFixedHeight(41)
        hdr.setStyleSheet(f"background:{BG};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.setSpacing(6)
        self._fbtns = {}
        for lbl in ["ALL PLAYS", "SCORING PLAYS", "Q1", "Q2", "Q3", "Q4"]:
            btn = QPushButton(lbl)
            btn.setFont(bb(9))
            btn.setFixedHeight(28)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(partial(self._set_f, lbl))
            self._fbtns[lbl] = btn
            hl.addWidget(btn)
        hl.addStretch()
        self._live_lbl = QLabel("LIVE")
        self._live_lbl.setFont(bb(9))
        self._live_lbl.setStyleSheet(f"color:{GREEN}; background:transparent;")
        hl.addWidget(self._live_lbl)
        self._live_lbl.setVisible(False)
        lay.addWidget(hdr)

        # Scrollable play list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{border:none;background:{BG};}}")
        scroll.viewport().setStyleSheet(f"background:{BG};")
        self._inner = QWidget()
        self._inner.setStyleSheet(f"background:{BG};")
        self._il = QVBoxLayout(self._inner)
        self._il.setContentsMargins(0, 0, 0, 0)
        self._il.setSpacing(0)
        self._il.addStretch()
        scroll.setWidget(self._inner)
        lay.addWidget(scroll)

        self._set_f("ALL PLAYS")

    def set_live(self, is_live: bool):
        self._live_lbl.setVisible(is_live)

    def _set_f(self, f):
        self._filter = f
        for k, btn in self._fbtns.items():
            btn.setStyleSheet(filter_active_ss() if k == f else filter_inactive_ss())
        self._render()

    def load(self, plays, away, home):
        self._plays = plays
        self._away = away
        self._home = home
        self._render()

    def set_bet_players(self, player_names):
        """Pass a set of tracked player names for row highlighting."""
        self._bet_players = set(n.lower().strip() for n in player_names if n)

    def _render(self):
        while self._il.count() > 1:
            item = self._il.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        plays = self._plays
        if self._filter == "SCORING PLAYS":
            plays = [p for p in plays if p.get("scoring")]
        elif self._filter in ["Q1", "Q2", "Q3", "Q4"]:
            q = int(self._filter[1])
            plays = [p for p in plays if p.get("period") == q]

        for play in plays[:60]:
            self._il.insertWidget(self._il.count() - 1, self._make_row(play))

    def _make_row(self, play):
        is_score = play.get("scoring", False)
        txt = play.get("text", "")
        txt_low = txt.lower()

        # Highlight if a tracked bet player appears in this play
        is_hl = bool(self._bet_players) and any(p in txt_low for p in self._bet_players)
        is_penalty = play.get("penalty", False)

        if is_hl:
            bg = GREEN_HL
        elif is_score:
            bg = SCORE_HL
        elif is_penalty:
            bg = "#3d3300"
        else:
            bg = CARD

        row = QWidget()
        _rn = f"pbpr{id(row)}"
        row.setObjectName(_rn)
        row.setStyleSheet(f"QWidget#{_rn} {{ background:{bg}; border-bottom:1px solid {BORDER2}; }}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(14, 5, 14, 5)
        rl.setSpacing(8)

        # Clock/period column (fixed 42px)
        tw = QWidget()
        tw.setFixedWidth(59)
        tw.setStyleSheet("background:transparent;")
        tl = QVBoxLayout(tw)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        ck = QLabel(play.get("clock", ""))
        ck.setFont(bb(11))
        ck.setStyleSheet(f"color:{TEXT_DARK}; background:transparent;")
        qt = QLabel(f"Q{play.get('period', '')}")
        qt.setFont(bb(9))
        qt.setStyleSheet(f"color:{TEXT_XDRK}; background:transparent;")
        tl.addWidget(ck)
        tl.addWidget(qt)
        rl.addWidget(tw)

        # Team tag (fixed 40px)
        tagw = QWidget()
        tagw.setFixedWidth(55)
        tagw.setStyleSheet("background:transparent;")
        tagl = QVBoxLayout(tagw)
        tagl.setContentsMargins(0, 0, 0, 0)
        tagl.setAlignment(Qt.AlignTop)

        def _lum(hex_c):
            """Perceived luminance 0-1 from hex color string."""
            try:
                r = int(hex_c[1:3], 16) / 255
                g = int(hex_c[3:5], 16) / 255
                b = int(hex_c[5:7], 16) / 255
                return 0.299 * r + 0.587 * g + 0.114 * b
            except Exception:
                return 0.0

        play_team_id = play.get("team_id", "")
        away_id = str(self._away.get("id", ""))
        home_id = str(self._home.get("id", ""))
        away_abbr = self._away.get("abbr", "")
        home_abbr = self._home.get("abbr", "")
        txt_up = txt.upper()

        # Identify team: prefer team_id from play data, fall back to text scan
        if play_team_id and play_team_id == away_id:
            tag_team = self._away
        elif play_team_id and play_team_id == home_id:
            tag_team = self._home
        elif away_abbr and away_abbr.upper() in txt_up:
            tag_team = self._away
        elif home_abbr and home_abbr.upper() in txt_up:
            tag_team = self._home
        else:
            tag_team = None

        if tag_team:
            tag_text = tag_team.get("abbr", "")
            tag_bg = tag_team.get("color", "#444444")
            tag_fg = tag_team.get("alt", "#ffffff")
            t = QLabel(tag_text)
            t.setFont(bb(9))
            t.setAlignment(Qt.AlignCenter)
            t.setFixedHeight(23)
            _tn = f"tag{id(t)}"
            t.setObjectName(_tn)
            t.setStyleSheet(
                f"QLabel#{_tn} {{ background:{tag_bg}; color:{tag_fg};"
                f" border-radius:3px; padding:1px 3px; }}"
            )
            tagl.addWidget(t)
        rl.addWidget(tagw)

        # Description (stretches)
        desc_color = GREEN if is_hl else (GOLD if is_penalty else TEXT)
        desc = QLabel(txt)
        desc.setFont(bb(11))
        desc.setStyleSheet(f"color:{desc_color}; background:transparent;")
        desc.setWordWrap(True)
        rl.addWidget(desc, 1)

        row.setMinimumHeight(34)
        return row


# ─────────────────────────────────────────────
# PLAY BY PLAY TAB
# ─────────────────────────────────────────────
class PlayByPlayTab(QWidget):
    """Mirrors the current game from GameTrackerTab but shows PBP instead of stats."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background:{BG};")
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Follow label bar ─────────────────────────
        follow_bar = QWidget()
        follow_bar.setStyleSheet(f"background:{HDR_BG}; border-bottom:1px solid {BORDER};")
        follow_lay = QHBoxLayout(follow_bar)
        follow_lay.setContentsMargins(12, 6, 12, 6)
        self._follow_lbl = QLabel("— NO GAME SELECTED —")
        self._follow_lbl.setFont(bb(10))
        self._follow_lbl.setAlignment(Qt.AlignCenter)
        self._follow_lbl.setStyleSheet(f"color:{TEXT_DIM}; letter-spacing:3px; background:transparent;")
        follow_lay.addStretch()
        follow_lay.addWidget(self._follow_lbl)
        follow_lay.addStretch()
        outer.addWidget(follow_bar)

        # ── Play by play ─────────────────────────────
        self._pbp = PBPWidget()
        self._pbp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        outer.addWidget(self._pbp, 1)  # stretch=1: fills all remaining height

    def sync(self, game, summary, plays, away_ls, home_ls, bet_players):
        """Called whenever GameTrackerTab loads or polls a game."""
        away = game["away"]
        home = game["home"]

        self._follow_lbl.setText(f"TRACKING  ·  {away['abbr']} @ {home['abbr']}")

        self._pbp.set_bet_players(bet_players)
        self._pbp.load(plays, away, home)
        self._pbp.set_live(game["state"] == "in")


# ─────────────────────────────────────────────
# GAME TRACKER TAB
# ─────────────────────────────────────────────
class GameTrackerTab(QWidget):
    game_updated = Signal(object, object, object, object, object, object)

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background:{BG};")
        self._games = []
        self._current = None
        self._summary = None
        self._last_seq = -1
        self._week = None  # None = current week (ESPN default)
        self._week_num = None  # actual week number from ESPN
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.setInterval(5000)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Week navigation bar ──────────────────────
        wk_bar = QWidget()
        wk_bar.setStyleSheet(f"background:{HDR_BG}; border-bottom:1px solid {BORDER};")
        wk_lay = QHBoxLayout(wk_bar)
        wk_lay.setContentsMargins(12, 4, 12, 4)
        wk_lay.setSpacing(6)

        self._prev_wk_btn = QPushButton("◄ PREV")
        self._prev_wk_btn.setFont(bb(10))
        self._prev_wk_btn.setStyleSheet(ghost_ss(TEXT_DIM))
        self._prev_wk_btn.setFixedHeight(37)
        self._prev_wk_btn.clicked.connect(self._prev_week)

        self._wk_lbl = QLabel("WEEK —")
        self._wk_lbl.setFont(bb(11))
        self._wk_lbl.setAlignment(Qt.AlignCenter)
        self._wk_lbl.setStyleSheet(f"color:{TEXT}; background:transparent; letter-spacing:2px;")

        self._next_wk_btn = QPushButton("NEXT ►")
        self._next_wk_btn.setFont(bb(10))
        self._next_wk_btn.setStyleSheet(ghost_ss(TEXT_DIM))
        self._next_wk_btn.setFixedHeight(37)
        self._next_wk_btn.clicked.connect(self._next_week)

        wk_lay.addWidget(self._prev_wk_btn)
        wk_lay.addStretch()
        wk_lay.addWidget(self._wk_lbl)
        wk_lay.addStretch()
        wk_lay.addWidget(self._next_wk_btn)
        outer.addWidget(wk_bar)

        # ── Game selector bar ────────────────────────
        sel_bar = QWidget()
        sel_bar.setStyleSheet(f"background:{BG};")
        sel_lay = QHBoxLayout(sel_bar)
        sel_lay.setContentsMargins(12, 8, 12, 8)
        sel_lay.setSpacing(8)

        lbl = QLabel("GAME")
        lbl.setFont(bb(10))
        lbl.setStyleSheet(f"color:{TEXT_DIM}; letter-spacing:3px; background:transparent;")

        self._combo = QComboBox()
        self._combo.setFont(bb(12))
        self._combo.setStyleSheet(combo_ss())
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo.currentIndexChanged.connect(self._on_sel)

        self._track_btn = QPushButton("TRACK")
        self._track_btn.setFont(bb(12))
        self._track_btn.setMinimumWidth(80)
        self._track_btn.setStyleSheet(btn_ss(GREEN, "#000"))
        self._track_btn.clicked.connect(self._on_track)

        sel_lay.addWidget(lbl)
        sel_lay.addWidget(self._combo)
        sel_lay.addWidget(self._track_btn)
        outer.addWidget(sel_bar)

        # ── Score header (3-panel, 160px) ────────────
        self._score_hdr = ScoreHeader()
        outer.addWidget(self._score_hdr)

        # ── Linescore / boxscore ─────────────────────
        self._boxscore = BoxScore()
        outer.addWidget(self._boxscore)

        # ── Win probability bar ──────────────────────
        self._winprob = WinProbBar()
        outer.addWidget(self._winprob)

        # ── Active bets panel ────────────────────────
        self._legs_panel = ActiveBetsPanel()
        outer.addWidget(self._legs_panel)

        # ── Stats label row ───────────────────────────
        stats_lbl_bar = QWidget()
        stats_lbl_bar.setStyleSheet(f"background:{BG};")
        stats_lbl_lay = QHBoxLayout(stats_lbl_bar)
        stats_lbl_lay.setContentsMargins(12, 8, 12, 4)
        slbl = QLabel("PLAYER STATS")
        slbl.setFont(bb(10))
        slbl.setStyleSheet(f"color:{TEXT_DIM}; letter-spacing:3px; background:transparent;")
        stats_lbl_lay.addWidget(slbl)
        stats_lbl_lay.addStretch()
        outer.addWidget(stats_lbl_bar)

        # ── Stat boxes row (away LEFT | home RIGHT) ──
        sb_container = QWidget()
        sb_container.setStyleSheet(f"background:{BG};")
        sb_lay = QHBoxLayout(sb_container)
        sb_lay.setContentsMargins(8, 0, 8, 8)
        sb_lay.setSpacing(8)

        self._away_stats = StatBox("away")
        self._home_stats = StatBox("home")
        sb_lay.addWidget(self._away_stats, 1)
        sb_lay.addWidget(self._home_stats, 1)
        outer.addWidget(sb_container)

        outer.addStretch()

    def set_games(self, games, week_num=None):
        self._games = games
        if week_num is not None:
            self._week_num = week_num
            self._week = week_num
        if self._week_num:
            self._wk_lbl.setText(f"WEEK {self._week_num}")
        self._combo.blockSignals(True)
        self._combo.clear()
        for g in games:
            if g["state"] == "in":
                suffix = f" — Q{g['period']} {g['clock']}"
            elif g["state"] == "post":
                suffix = " — FINAL"
            else:
                suffix = f" — {et_to_pt(g.get('detail', ''))}"
            self._combo.addItem(f"{g['away']['abbr']} @ {g['home']['abbr']}{suffix}")
        self._combo.blockSignals(False)
        if games:
            self._load(games[0])

    def _prev_week(self):
        cur = self._week_num or 1
        if cur > 1:
            self._load_week(cur - 1)

    def _next_week(self):
        cur = self._week_num or 1
        self._load_week(cur + 1)

    def _load_week(self, week):
        self._timer.stop()
        games, wk = fetch_scoreboard(week=week, seasontype=2)
        if games is not None:
            self.set_games(games, week_num=wk or week)

    def _on_sel(self, idx):
        if 0 <= idx < len(self._games):
            self._load(self._games[idx])

    def _on_track(self):
        idx = self._combo.currentIndex()
        if 0 <= idx < len(self._games):
            self._load(self._games[idx])
        if not self._timer.isActive():
            self._timer.start()

    def _load(self, game):
        self._current = game
        try:
            summary = fetch_summary(game["id"])
            self._summary = summary

            away_ls = fetch_linescores(game["id"], game["away"]["id"])
            home_ls = fetch_linescores(game["id"], game["home"]["id"])

            self._score_hdr.refresh(game, summary)
            self._boxscore.refresh(game, away_ls, home_ls)
            self._winprob.refresh(game, summary)

            self._legs_panel.set_game(str(game["id"]), self._games)
            self._legs_panel.refresh(game, summary)

            bet_players = self._get_bet_players(game["id"])
            self._load_stat_boxes(game, summary)

            plays = fetch_plays(game["id"])
            if plays:
                self._last_seq = plays[0].get("seq", -1)
            self.game_updated.emit(game, summary, plays or [], away_ls, home_ls, bet_players)
            if not self._timer.isActive():
                self._timer.start()
        except Exception:
            traceback.print_exc()

    def _load_stat_boxes(self, game, summary):
        """Fetch all 6 stat groups and populate the away/home StatBoxes."""
        away = game["away"]
        home = game["home"]

        a_pass = get_stat_group(summary, away["id"], "passing")
        a_rush = get_stat_group(summary, away["id"], "rushing")
        a_recv = get_stat_group(summary, away["id"], "receiving")
        h_pass = get_stat_group(summary, home["id"], "passing")
        h_rush = get_stat_group(summary, home["id"], "rushing")
        h_recv = get_stat_group(summary, home["id"], "receiving")

        # Build jersey->position lookup from rosters (boxscore athletes omit position)
        pos_lookup = build_pos_lookup(summary)
        away_pos = pos_lookup.get(str(away["id"]), {})
        home_pos = pos_lookup.get(str(home["id"]), {})

        self._away_stats.load(
            away["color"], away["alt"], away["name"],
            a_pass, a_rush, a_recv, pos_lookup=away_pos
        )
        self._home_stats.load(
            home["color"], home["alt"], home["name"],
            h_pass, h_rush, h_recv, pos_lookup=home_pos
        )
        # Equalize paired section heights so headers stay aligned
        self._equalize_stat_heights()

    def _equalize_stat_heights(self):
        pairs = [
            (self._away_stats._pass_sec, self._home_stats._pass_sec),
            (self._away_stats._rush_sec, self._home_stats._rush_sec),
            (self._away_stats._recv_sec, self._home_stats._recv_sec),
        ]
        for left, right in pairs:
            h = max(
                getattr(left, "_content_h", 28),
                getattr(right, "_content_h", 28),
            )
            left.setFixedHeight(h)
            right.setFixedHeight(h)

    def _get_bet_players(self, game_id):
        """Return list of tracked player names for the current game."""
        try:
            conn = db()
            c = conn.cursor()
            c.execute("""
                SELECT DISTINCT l.player FROM legs l
                JOIN parlays p ON l.parlay_id = p.id
                WHERE CAST(l.game_id AS TEXT) = CAST(? AS TEXT)
                  AND p.status IN ('LIVE','PENDING')
                  AND l.player IS NOT NULL AND l.player != '' AND l.player != 'N/A'
            """, (game_id,))
            players = [row[0] for row in c.fetchall()]
            conn.close()
            return players
        except Exception:
            return []

    def _poll(self):
        """5-second poll: always refresh scores, stats, and bets for the tracked game."""
        if not self._current:
            return
        try:
            plays = fetch_plays(self._current["id"]) or []
            if plays:
                self._last_seq = plays[0].get("seq", self._last_seq)
            summary = fetch_summary(self._current["id"])
            self._summary = summary

            fresh, _ = fetch_scoreboard(week=self._week)
            for g in (fresh or []):
                if str(g["id"]) == str(self._current["id"]):
                    self._current = g
                    break

            away_ls = fetch_linescores(self._current["id"], self._current["away"]["id"])
            home_ls = fetch_linescores(self._current["id"], self._current["home"]["id"])

            self._score_hdr.refresh(self._current, summary)
            self._boxscore.refresh(self._current, away_ls, home_ls)
            self._winprob.refresh(self._current, summary)
            self._legs_panel.refresh(self._current, summary)
            self._load_stat_boxes(self._current, summary)

            bet_players = self._get_bet_players(self._current["id"])
            self.game_updated.emit(self._current, summary, plays, away_ls, home_ls, bet_players)
        except Exception:
            traceback.print_exc()


# ─────────────────────────────────────────────
# ADD LEG DIALOG
# ─────────────────────────────────────────────
class AddLegDialog(QDialog):
    def __init__(self, games, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ADD LEG")
        self.setMinimumWidth(440)
        self.setStyleSheet(
            f"background:{BG}; color:{TEXT};"
            f"QDialog{{background:{BG};}}"
            f"QLabel{{color:{TEXT}; background:transparent;}}"
            f"QDialogButtonBox QPushButton{{background:{GREEN}; color:#000; border:none;"
            f"border-radius:0px; padding:6px 20px; font-size:13px;}}"
            f"QDialogButtonBox QPushButton[text='Cancel']{{background:{CARD}; color:{TEXT};"
            f"border:0.5px solid {BORDER};}}"
        )
        self._games = games
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)

        def row(lbl_text, widget):
            r = QHBoxLayout()
            l = QLabel(lbl_text)
            l.setFont(bb(10))
            l.setStyleSheet(f"color:{TEXT_DIM}; letter-spacing:2px;")
            l.setFixedWidth(112)
            r.addWidget(l)
            r.addWidget(widget)
            return r

        self._gc = QComboBox();
        self._gc.setFont(bb(12));
        self._gc.setStyleSheet(combo_ss())
        for g in self._games:
            self._gc.addItem(f"{g['away']['abbr']} @ {g['home']['abbr']}")
        self._gc.currentIndexChanged.connect(self._on_game)
        lay.addLayout(row("GAME", self._gc))

        self._tc = QComboBox();
        self._tc.setFont(bb(12));
        self._tc.setStyleSheet(combo_ss())
        self._tc.addItem("N/A");
        self._tc.currentIndexChanged.connect(self._on_team)
        lay.addLayout(row("TEAM", self._tc))

        self._pc = QComboBox();
        self._pc.setFont(bb(12));
        self._pc.setStyleSheet(combo_ss())
        self._pc.addItem("N/A")
        lay.addLayout(row("PLAYER", self._pc))

        self._oc = QComboBox();
        self._oc.setFont(bb(12));
        self._oc.setStyleSheet(combo_ss())
        self._oc.addItems(["OVER", "UNDER", "N/A"])
        lay.addLayout(row("O/U", self._oc))

        self._li = QLineEdit();
        self._li.setFont(bb(12));
        self._li.setStyleSheet(input_ss())
        self._li.setPlaceholderText("249.5")
        lay.addLayout(row("LINE", self._li))

        self._mc = QComboBox();
        self._mc.setFont(bb(12));
        self._mc.setStyleSheet(combo_ss())
        self._mc.addItems(MARKETS)
        lay.addLayout(row("MARKET", self._mc))

        self._oi = QLineEdit();
        self._oi.setFont(bb(12));
        self._oi.setStyleSheet(input_ss())
        self._oi.setPlaceholderText("-115")
        lay.addLayout(row("ODDS", self._oi))

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        if self._games:
            self._on_game(0)

    def _on_game(self, idx):
        if idx < 0 or idx >= len(self._games):
            return
        g = self._games[idx]
        self._tc.blockSignals(True)
        self._tc.clear()
        self._tc.addItem("N/A")
        self._tc.addItem(g["away"]["abbr"])
        self._tc.addItem(g["home"]["abbr"])
        self._tc.blockSignals(False)

    def _on_team(self, idx):
        if idx <= 0:
            self._pc.clear()
            self._pc.addItem("N/A")
            return
        gi = self._gc.currentIndex()
        if gi < 0 or gi >= len(self._games):
            return
        g = self._games[gi]
        abbr = self._tc.currentText()
        tid = g["away"]["id"] if abbr == g["away"]["abbr"] else g["home"]["id"]
        roster = fetch_roster(g["id"], tid)
        self._pc.clear()
        self._pc.addItem("N/A")
        for p in roster:
            self._pc.addItem(p["name"])

    def get_data(self):
        gi = self._gc.currentIndex()
        g = self._games[gi] if 0 <= gi < len(self._games) else {}
        return {
            "game_id": g.get("id", ""),
            "game_display": self._gc.currentText(),
            "team": self._tc.currentText(),
            "player": self._pc.currentText(),
            "ou": self._oc.currentText(),
            "line": self._li.text(),
            "market": self._mc.currentText(),
            "odds": self._oi.text(),
        }


# ─────────────────────────────────────────────
# BET ENTRY TAB
# ─────────────────────────────────────────────
class BetEntryTab(QWidget):
    submitted = Signal()

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background:{BG};")
        self._games = []
        self._parlay_id = None
        self._legs = []
        self._pending_row = False
        self._pending_widgets = {}  # holds widget refs for pending inline row
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        # Header row
        hr = QHBoxLayout()
        al = QLabel("ACTIVE PARLAY")
        al.setFont(bb(16))
        al.setStyleSheet(f"color:{GREEN}; letter-spacing:3px; background:transparent;")
        hr.addWidget(al)
        hr.addStretch()
        self._pcb = QComboBox()
        self._pcb.setFont(bb(12))
        self._pcb.setStyleSheet(combo_ss())
        self._pcb.setFixedWidth(80)
        for i in range(1, 11):
            self._pcb.addItem(f"P{i}")
        self._pcb.currentIndexChanged.connect(self._load_parlay)
        hr.addWidget(self._pcb)
        np_btn = QPushButton("+ NEW PARLAY")
        np_btn.setFont(bb(11))
        np_btn.setStyleSheet(ghost_ss())
        np_btn.setMinimumWidth(110)
        np_btn.clicked.connect(self._new_parlay)
        hr.addSpacing(6)
        hr.addWidget(np_btn)
        outer.addLayout(hr)

        # Info + calc card
        ic = QWidget()
        ic.setStyleSheet(card_ss())
        icl = QGridLayout(ic)
        icl.setContentsMargins(16, 14, 16, 14)
        icl.setSpacing(10)
        icl.setColumnStretch(1, 1)
        icl.setColumnStretch(3, 1)

        def hl(t):
            l = QLabel(t)
            l.setFont(bb(10))
            l.setStyleSheet(f"color:{TEXT_DIM}; letter-spacing:3px; background:transparent;")
            return l

        def fl(t):
            l = QLabel(t)
            l.setFont(bb(11))
            l.setStyleSheet(f"color:{TEXT_DIM}; background:transparent;")
            return l

        icl.addWidget(hl("BET INFO"), 0, 0, 1, 2)
        self._bk = QComboBox()
        self._bk.setFont(bb(12))
        self._bk.setStyleSheet(combo_ss())
        self._bk.addItems(BOOKS)
        icl.addWidget(fl("BOOK"), 1, 0)
        icl.addWidget(self._bk, 1, 1)
        self._sk = QLineEdit("50.00")
        self._sk.setFont(bb(12))
        self._sk.setStyleSheet(input_ss())
        self._sk.textChanged.connect(self._recalc)
        icl.addWidget(fl("STAKE"), 2, 0)
        icl.addWidget(self._sk, 2, 1)
        self._bo = QLineEdit("0")
        self._bo.setFont(bb(12))
        self._bo.setStyleSheet(input_ss())
        self._bo.textChanged.connect(self._recalc)
        icl.addWidget(fl("BOOST %"), 3, 0)
        icl.addWidget(self._bo, 3, 1)

        icl.addWidget(hl("CALCULATIONS"), 0, 2, 1, 2)
        self._cv = {}
        for ri, (field, big) in enumerate([
            ("LEGS", False), ("PARLAY ODDS", False), ("BOOSTED ODDS", False),
            ("STAKE", False), ("TO WIN", False), ("PAYOUT", True)
        ], start=1):
            icl.addWidget(fl(field), ri, 2)
            v = QLabel("—")
            v.setFont(bb(14 if big else 12))
            v.setAlignment(Qt.AlignRight)
            v.setStyleSheet(f"color:{GREEN if big else TEXT}; background:transparent;")
            icl.addWidget(v, ri, 3)
            self._cv[field] = v
        outer.addWidget(ic)

        # Leg table
        lc = QWidget()
        lc.setStyleSheet(card_ss())
        lcl = QVBoxLayout(lc)
        lcl.setContentsMargins(0, 0, 0, 0)
        lcl.setSpacing(0)
        self._lt = QTableWidget(0, 8)
        self._lt.setHorizontalHeaderLabels(["GAME", "TEAM", "PLAYER", "O/U", "LINE", "MARKET", "ODDS", ""])
        self._lt.verticalHeader().setVisible(False)
        self._lt.setEditTriggers(QTableWidget.NoEditTriggers)
        self._lt.setSelectionMode(QTableWidget.NoSelection)
        self._lt.setStyleSheet(table_ss())
        self._lt.setMinimumHeight(100)
        self._lt.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._lt.horizontalHeader().setSectionResizeMode(7, QHeaderView.Fixed)
        self._lt.setColumnWidth(7, 30)
        self._lt.setShowGrid(False)
        lcl.addWidget(self._lt)
        self._el = QLabel("NO LEGS — CLICK + ADD LEG")
        self._el.setFont(bb(11))
        self._el.setAlignment(Qt.AlignCenter)
        self._el.setStyleSheet(f"color:{TEXT_DIM}; padding:20px; background:transparent;")
        lcl.addWidget(self._el)
        outer.addWidget(lc)

        # Buttons
        br = QHBoxLayout()
        ab = QPushButton("+ ADD LEG")
        ab.setFont(bb(12))
        ab.setStyleSheet(ghost_ss())
        ab.setMinimumWidth(100)
        ab.clicked.connect(self._add_leg)
        nb = QPushButton("NEW PARLAY")
        nb.setFont(bb(12))
        nb.setStyleSheet(ghost_ss())
        nb.setMinimumWidth(110)
        nb.clicked.connect(self._new_parlay)
        sb = QPushButton("SUBMIT PARLAY")
        sb.setFont(bb(13))
        sb.setStyleSheet(btn_ss(GREEN, "#000"))
        sb.setMinimumWidth(140)
        sb.clicked.connect(self._submit)
        br.addWidget(ab)
        br.addSpacing(6)
        br.addWidget(nb)
        br.addStretch()
        br.addWidget(sb)
        outer.addLayout(br)
        outer.addStretch()
        self._load_parlay(0)

    def set_games(self, g):
        self._games = g

    def _load_parlay(self, idx=None):
        label = self._pcb.currentText()
        conn = db()
        c = conn.cursor()
        c.execute("SELECT id FROM parlays WHERE parlay_label=? AND status='PENDING'", (label,))
        row = c.fetchone()
        if not row:
            c.execute(
                "INSERT INTO parlays(parlay_label,book,stake,boost_pct,status) VALUES(?,?,?,?,?)",
                (label, BOOKS[0], 50.0, 0.0, "PENDING"))
            conn.commit()
            self._parlay_id = c.lastrowid
        else:
            self._parlay_id = row[0]
        c.execute("SELECT * FROM legs WHERE parlay_id=?", (self._parlay_id,))
        self._legs = c.fetchall()
        conn.close()
        self._refresh_tbl()
        self._recalc()

    def _refresh_tbl(self):
        has = len(self._legs) > 0
        self._el.setVisible(not has)
        self._lt.setRowCount(len(self._legs))
        for r, leg in enumerate(self._legs):
            lid = leg[0]
            vals = [leg[3] or "—", leg[4] or "—", leg[5] or "—",
                    leg[7] or "—", leg[8] or "—", leg[6] or "—", leg[9] or "—"]
            for ci, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                it.setFont(bb(11))
                it.setForeground(QColor(TEXT))
                it.setTextAlignment(Qt.AlignCenter)
                self._lt.setItem(r, ci, it)
            self._lt.setRowHeight(r, 36)
            db_btn = QPushButton("✕")
            db_btn.setFont(bb(11))
            db_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{RED};border:none;}}"
                f"QPushButton:hover{{color:white;}}")
            db_btn.clicked.connect(partial(self._del, lid))
            self._lt.setCellWidget(r, 7, db_btn)

    def _del(self, lid):
        conn = db()
        conn.execute("DELETE FROM legs WHERE id=?", (lid,))
        conn.commit()
        conn.close()
        self._load_parlay()

    def _recalc(self):
        try:
            stake = float(self._sk.text() or 0)
        except Exception:
            stake = 0.0
        try:
            boost = float(self._bo.text() or 0)
        except Exception:
            boost = 0.0
        res = calc_parlay([leg[9] for leg in self._legs if leg[9]], stake, boost)
        self._cv["LEGS"].setText(str(len(self._legs)))
        self._cv["PARLAY ODDS"].setText(res["parlay"])
        self._cv["BOOSTED ODDS"].setText(res["boosted"])
        self._cv["STAKE"].setText(f"${stake:.2f}")
        self._cv["TO WIN"].setText(f"${res['to_win']:.2f}")
        self._cv["PAYOUT"].setText(f"${res['payout']:.2f}")

    def _new_parlay(self):
        label = self._pcb.currentText()
        conn = db()
        conn.execute(
            "DELETE FROM legs WHERE parlay_id IN "
            "(SELECT id FROM parlays WHERE parlay_label=? AND status='PENDING')", (label,))
        conn.execute(
            "DELETE FROM parlays WHERE parlay_label=? AND status='PENDING'", (label,))
        conn.commit()
        conn.close()
        self._legs = []
        self._parlay_id = None
        self._load_parlay()

    def _save_pending(self):
        """Save the current pending inline row to the database."""
        if not self._pending_row or not self._pending_widgets:
            return
        w = self._pending_widgets
        gc = w.get("gc");
        tc = w.get("tc");
        pc = w.get("pc")
        oc = w.get("oc");
        li = w.get("li");
        mc = w.get("mc");
        oi = w.get("oi")
        if gc is None:
            return
        gi = gc.currentIndex()
        g = self._games[gi] if 0 <= gi < len(self._games) else {}
        if not self._parlay_id:
            self._load_parlay()
        conn = db()
        conn.execute(
            "INSERT INTO legs(parlay_id,game_id,game_display,team,player,"
            "market,ou,line,odds,leg_status) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (self._parlay_id, str(g.get("id", "")), gc.currentText(),
             tc.currentText() if tc else "N/A",
             pc.currentText() if pc else "N/A",
             mc.currentText() if mc else "ML",
             oc.currentText() if oc else "N/A",
             li.text() if li else "",
             oi.text() if oi else "",
             "PENDING"))
        conn.commit();
        conn.close()
        self._pending_row = False
        self._pending_widgets = {}
        self._load_parlay()

    def _add_leg(self):
        """Add an inline editable row to the leg table."""
        if self._pending_row:
            self._save_pending()
        self._pending_row = True
        self._pending_widgets = {}
        self._el.setVisible(False)

        row = self._lt.rowCount()
        self._lt.insertRow(row)
        self._lt.setRowHeight(row, 40)

        # GAME combo
        gc = QComboBox();
        gc.setFont(bb(10));
        gc.setStyleSheet(combo_ss())
        for g in self._games:
            gc.addItem(f"{g['away']['abbr']} @ {g['home']['abbr']}", g["id"])
        self._lt.setCellWidget(row, 0, gc)

        # TEAM combo
        tc = QComboBox();
        tc.setFont(bb(10));
        tc.setStyleSheet(combo_ss())
        tc.addItem("N/A")
        self._lt.setCellWidget(row, 1, tc)

        # PLAYER combo
        pc = QComboBox();
        pc.setFont(bb(10));
        pc.setStyleSheet(combo_ss())
        pc.addItem("N/A")
        self._lt.setCellWidget(row, 2, pc)

        # O/U combo
        oc = QComboBox();
        oc.setFont(bb(10));
        oc.setStyleSheet(combo_ss())
        oc.addItems(["OVER", "UNDER", "N/A"])
        self._lt.setCellWidget(row, 3, oc)

        # LINE input
        li = QLineEdit();
        li.setFont(bb(10));
        li.setStyleSheet(input_ss())
        li.setPlaceholderText("e.g. 249.5")
        self._lt.setCellWidget(row, 4, li)

        # MARKET combo
        mc = QComboBox();
        mc.setFont(bb(10));
        mc.setStyleSheet(combo_ss())
        mc.addItems(MARKETS)
        self._lt.setCellWidget(row, 5, mc)

        # ODDS input
        oi = QLineEdit();
        oi.setFont(bb(10));
        oi.setStyleSheet(input_ss())
        oi.setPlaceholderText("-115")
        self._lt.setCellWidget(row, 6, oi)

        # Store widget refs so auto-save can read them
        self._pending_widgets = {"gc": gc, "tc": tc, "pc": pc,
                                 "oc": oc, "li": li, "mc": mc, "oi": oi}

        # CANCEL button (✕) — discards the pending row without saving
        sv = QPushButton("✕")
        sv.setFont(bb(11))
        sv.setStyleSheet(f"QPushButton{{background:transparent;color:{RED};border:none;padding:2px;}}"
                         f"QPushButton:hover{{color:white;}}")
        self._lt.setCellWidget(row, 7, sv)

        def populate_teams(idx):
            if idx < 0 or idx >= len(self._games):
                return
            g = self._games[idx]
            tc.blockSignals(True)
            tc.clear()
            tc.addItem("N/A")
            tc.addItem(g["away"]["abbr"])
            tc.addItem(g["home"]["abbr"])
            tc.blockSignals(False)
            pc.clear();
            pc.addItem("N/A")

        def populate_players(t_idx):
            gi = gc.currentIndex()
            if gi < 0 or gi >= len(self._games) or t_idx <= 0:
                pc.clear();
                pc.addItem("N/A")
                return
            g = self._games[gi]
            abbr = tc.currentText()
            tid = g["away"]["id"] if abbr == g["away"]["abbr"] else g["home"]["id"]
            roster = fetch_roster(g["id"], tid)
            pc.clear();
            pc.addItem("N/A")
            for p in roster:
                pc.addItem(p["name"])

        gc.currentIndexChanged.connect(populate_teams)
        tc.currentIndexChanged.connect(populate_players)
        if self._games:
            populate_teams(0)

        def cancel_leg():
            self._lt.removeRow(row)
            self._pending_row = False
            self._pending_widgets = {}
            if self._lt.rowCount() == 0:
                self._el.setVisible(True)

        sv.clicked.connect(cancel_leg)

    def _submit(self):
        # Save any pending inline row before submitting
        if self._pending_row:
            self._save_pending()
        if not self._legs or not self._parlay_id:
            return
        try:
            stake = float(self._sk.text() or 0)
        except Exception:
            stake = 0.0
        try:
            boost = float(self._bo.text() or 0)
        except Exception:
            boost = 0.0
        conn = db()
        conn.execute(
            "UPDATE parlays SET book=?,stake=?,boost_pct=?,status='LIVE' WHERE id=?",
            (self._bk.currentText(), stake, boost, self._parlay_id))
        conn.commit()
        conn.close()
        self.submitted.emit()
        self._load_parlay()


# ─────────────────────────────────────────────
# ACTIVE LEGS TAB
# ─────────────────────────────────────────────
class ActiveLegsTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background:{BG};")
        self._games = []
        self._scache = {}
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.setInterval(30000)
        self._timer.start()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{border:none;background:{BG};}}")
        self._con = QWidget()
        self._con.setStyleSheet(f"background:{BG};")
        self._il = QVBoxLayout(self._con)
        self._il.setContentsMargins(0, 0, 0, 0)
        self._il.setSpacing(10)
        self._il.addStretch()
        scroll.setWidget(self._con)
        lay.addWidget(scroll)

    def set_games(self, games):
        self._games = games
        self.refresh()

    def refresh(self):
        while self._il.count() > 1:
            item = self._il.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        conn = db()
        c = conn.cursor()
        c.execute("SELECT * FROM parlays WHERE status IN ('LIVE','PENDING') ORDER BY id DESC")
        parlays = c.fetchall()
        conn.close()

        if not parlays:
            el = QLabel("NO ACTIVE LEGS")
            el.setFont(bb(13))
            el.setAlignment(Qt.AlignCenter)
            el.setStyleSheet(f"color:{TEXT_DIM}; padding:40px; background:transparent;")
            self._il.insertWidget(0, el)
            return

        for par in parlays:
            if not par or len(par) < 7:
                continue
            pid, label, book, stake, boost, status, created = par[:7]
            conn = db()
            c = conn.cursor()
            c.execute("SELECT * FROM legs WHERE parlay_id=?", (pid,))
            legs = c.fetchall()
            conn.close()
            if legs:
                self._il.insertWidget(self._il.count() - 1, self._make_block(par, legs))

    def _make_block(self, par, legs):
        pid, label, book, stake, boost, status, created = par
        calc = calc_parlay([leg[9] for leg in legs if leg[9]], stake or 0, boost or 0)
        block = QWidget()
        block.setStyleSheet(card_ss())
        bl = QVBoxLayout(block)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        # Parlay header row
        hdr = QWidget()
        hdr.setFixedHeight(53)
        hdr.setStyleSheet(f"background:{HDR_BG}; border-bottom:0.5px solid {BORDER};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 0, 14, 0)
        hl.setSpacing(14)

        def hl_lbl(t, color=TEXT_DIM):
            l = QLabel(t)
            l.setFont(bb(10))
            l.setStyleSheet(f"color:{color}; background:transparent; letter-spacing:0px;")
            return l

        def hl_sep():
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setFixedWidth(1)
            sep.setFixedHeight(18)
            sep.setStyleSheet(f"background:{BORDER}; border:none;")
            return sep

        hl.addWidget(hl_lbl(f"{label}", TEXT))
        hl.addWidget(hl_sep())
        hl.addWidget(hl_lbl(f"{len(legs)} LEGS"))
        hl.addWidget(hl_sep())

        sb = QLabel(status)
        sb.setFont(bb(10))
        sb.setStyleSheet(
            f"background:{GREEN if status == 'LIVE' else BORDER}; "
            f"color:{'#000' if status == 'LIVE' else TEXT_DIM}; "
            f"border-radius:3px; padding:1px 6px;")
        hl.addWidget(sb)

        if book:
            hl.addWidget(hl_sep())
            hl.addWidget(hl_lbl(f"{book}"))
        if stake:
            hl.addWidget(hl_sep())
            hl.addWidget(hl_lbl(f"{calc['parlay']}", TEXT))
            hl.addWidget(hl_sep())
            hl.addWidget(hl_lbl(f"{int(boost or 0)}%"))
            hl.addWidget(hl_sep())
            hl.addWidget(hl_lbl(f"${stake:.0f}", TEXT))
            hl.addWidget(hl_sep())
            hl.addWidget(hl_lbl(f"${calc['payout']:.0f}", GREEN))

        hl.addStretch()
        ab = QPushButton("ARCHIVE")
        ab.setFont(bb(9))
        ab.setStyleSheet(ghost_ss(TEXT_DARK))
        ab.setFixedWidth(70)
        ab.clicked.connect(partial(self._archive, label))
        hl.addWidget(ab)
        bl.addWidget(hdr)

        # Leg table
        tbl = QTableWidget(len(legs), 10)
        tbl.setHorizontalHeaderLabels(
            ["GAME", "TEAM", "PLAYER", "O/U", "LINE", "MARKET",
             "LIVE STAT", "QUARTER", "SCORE", "STATUS"])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSelectionMode(QTableWidget.NoSelection)
        tbl.setStyleSheet(table_ss())
        tbl.setFixedHeight(39 * len(legs) + 45)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tbl.setShowGrid(False)

        for r, leg in enumerate(legs):
            if len(leg) < 12:
                continue
            lid, pid2, game_id, game_disp, team, player, market, ou, line, odds, live_stat, leg_status = leg[:12]
            gi = next((g for g in self._games if str(g["id"]) == str(game_id)), None)
            quarter = "—"
            score = "—"
            live_val = live_stat or "—"
            is_tracking = False

            if gi:
                p = gi.get("period", 0)
                if p:
                    quarter = f"Q{p}"
                score = f"{gi['away']['score']}-{gi['home']['score']}"
                is_tracking = gi.get("state") == "in"
                gid = str(game_id)
                if gid not in self._scache:
                    s = fetch_summary(gid)
                    if s:
                        self._scache[gid] = s
                s = self._scache.get(gid)
                if s and player and player != "N/A":
                    if team == gi["away"]["abbr"]:
                        tid = gi["away"]["id"]
                    elif team == gi["home"]["abbr"]:
                        tid = gi["home"]["id"]
                    else:
                        tid = ""
                    v = get_live_stat(s, player, market, tid)
                    if v != "—":
                        live_val = v
                    new_status = settle_leg(ou, line, live_val, gi.get("state", ""), leg_status)
                    if live_val != (live_stat or "—") or new_status != leg_status:
                        persist_leg_live(lid, live_val, new_status)
                        leg_status = new_status

            is_won = leg_status == "WON"
            is_lost = leg_status == "LOST"
            rbg = "#1a3a1a" if is_won else ("#3a1a1a" if is_lost else CARD)
            gd = f"• {game_disp}" if is_tracking else (game_disp or "—")
            st = ("WON" if is_won else
                  "LOSS" if is_lost else
                  "LIVE" if is_tracking else "PENDING")

            vals = [gd, team or "—", player or "—", ou or "—", line or "—",
                    market or "—", str(live_val), quarter, score, st]

            for col, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                it.setFont(bb(11))
                it.setBackground(QColor(rbg))
                it.setTextAlignment(Qt.AlignCenter)
                if col == 0 and is_tracking:
                    it.setForeground(QColor(GREEN))
                elif col == 9:
                    it.setForeground(QColor(
                        GOLD if is_won else
                        RED if is_lost else
                        GREEN if is_tracking else TEXT_DIM))
                elif col in (6, 7, 8) and is_tracking:
                    it.setForeground(QColor(GREEN))
                else:
                    it.setForeground(QColor(TEXT))
                tbl.setItem(r, col, it)
            tbl.setRowHeight(r, 28)

        bl.addWidget(tbl)
        return block

    def _archive(self, label):
        conn = db()
        conn.execute(
            "UPDATE parlays SET status='ARCHIVED' "
            "WHERE parlay_label=? AND status IN ('LIVE','PENDING')", (label,))
        conn.commit()
        conn.close()
        self.refresh()


# ─────────────────────────────────────────────
# ARCHIVE TAB
# ─────────────────────────────────────────────
class ArchiveTab(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background:{BG};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        self._tbl = QTableWidget(0, 7)
        self._tbl.setHorizontalHeaderLabels(
            ["PARLAY", "BOOK", "STAKE", "BOOST", "PARLAY ODDS", "PAYOUT", "DATE"])
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self._tbl.setSelectionMode(QTableWidget.NoSelection)
        self._tbl.setStyleSheet(table_ss())
        self._tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._tbl.setShowGrid(False)
        lay.addWidget(self._tbl)
        self.refresh()

    def refresh(self):
        conn = db()
        c = conn.cursor()
        c.execute("SELECT * FROM parlays WHERE status='ARCHIVED' ORDER BY id DESC")
        rows = c.fetchall()
        conn.close()
        self._tbl.setRowCount(len(rows))
        for r, row in enumerate(rows):
            if not row or len(row) < 7:
                continue
            pid, label, book, stake, boost, status, created = row[:7]
            conn = db()
            c2 = conn.cursor()
            c2.execute("SELECT odds FROM legs WHERE parlay_id=?", (pid,))
            leg_odds = [x[0] for x in c2.fetchall() if x[0]]
            conn.close()
            calc = calc_parlay(leg_odds, stake or 0, boost or 0)
            vals = [label, book or "—",
                    f"${stake:.2f}" if stake else "—",
                    f"{int(boost)}%" if boost else "0%",
                    calc["parlay"],
                    f"${calc['payout']:.2f}",
                    created[:10] if created else "—"]
            for ci, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                it.setFont(bb(11))
                it.setForeground(QColor(TEXT))
                it.setTextAlignment(Qt.AlignCenter)
                self._tbl.setItem(r, ci, it)
            self._tbl.setRowHeight(r, 28)


# ─────────────────────────────────────────────
# MAIN WINDOW
# ─────────────────────────────────────────────
class HeraWindow(QMainWindow):
    def __init__(self, games, week_num=None):
        super().__init__()
        self.setWindowTitle(f"HERA v{VERSION}")
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(f"background:{BG};")

        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        self._nav = NavBar()
        self._nav.tab_changed.connect(self._switch)
        ml.addWidget(self._nav)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background:{BG};")

        self._gt = GameTrackerTab()
        self._pbp_tab = PlayByPlayTab()
        self._be = BetEntryTab()
        self._al = ActiveLegsTab()
        self._ar = ArchiveTab()

        self._gt.game_updated.connect(self._pbp_tab.sync)
        self._be.submitted.connect(self._ar.refresh)
        self._be.submitted.connect(self._gt._legs_panel.refresh)
        self._be.submitted.connect(self._al.refresh)

        for tab in [self._gt, self._pbp_tab, self._be, self._al, self._ar]:
            sc = QScrollArea()
            sc.setWidget(tab)
            sc.setWidgetResizable(True)
            sc.setStyleSheet(f"QScrollArea{{border:none;background:{BG};}}")
            sc.viewport().setStyleSheet(f"background:{BG};")
            self._stack.addWidget(sc)

        ml.addWidget(self._stack)

        self._gt.set_games(games, week_num=week_num)
        self._be.set_games(games)
        self._al.set_games(games)

    def _switch(self, idx):
        self._stack.setCurrentIndex(idx)
        if idx == 3:
            self._al.refresh()
        elif idx == 4:
            self._ar.refresh()


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
def main():
    print(f"HERA v{VERSION} starting...")
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor("#1a1a1a"))
        pal.setColor(QPalette.WindowText, QColor(TEXT))
        pal.setColor(QPalette.Base, QColor(CARD))
        pal.setColor(QPalette.AlternateBase, QColor(HDR_BG))
        pal.setColor(QPalette.Text, QColor(TEXT))
        pal.setColor(QPalette.ButtonText, QColor(TEXT))
        pal.setColor(QPalette.Button, QColor(CARD))
        pal.setColor(QPalette.Highlight, QColor(GREEN_DIM))
        pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        app.setPalette(pal)
        load_font()
        app.setFont(bb(12))
        app.setStyleSheet(f"* {{ font-family: '{_FF}'; }}")

        def open_main(games, week_num):
            win = HeraWindow(games or [], week_num)
            win.show()
            app._win = win

        splash = LoadingScreen()
        splash.ready.connect(open_main)
        splash.start()
        app._splash = splash
        sys.exit(app.exec())

    except Exception:
        print("FATAL ERROR:")
        traceback.print_exc()
        try:
            input("Press Enter to close...")
        except Exception:
            pass


if __name__ == "__main__":
    main()