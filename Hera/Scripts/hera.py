# hera.py — v4.3.40
# Standalone NFL live game tracker — PC/Windows build
# Canonical copies:
#   Hera/Script/hera.py   (PyCharm / Windows: C:\Users\chris\Hera\Script\hera.py)
#   Hera/Scripts/hera.py  (launch-hera.bat fallback)

import multiprocessing

multiprocessing.freeze_support()

import sys
import os
import math
import sqlite3
import requests
import time
import traceback
from functools import partial

# PyCharm injects Qt paths from the IDE / other projects (white main window).
# Do not leave QT_PLUGIN_PATH empty — Windows then cannot decode PNG and the
# splash lock (statue + HERA) disappears.
for _k in ("QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_API"):
    os.environ.pop(_k, None)
import PySide6
_pyside_plugins = os.path.join(os.path.dirname(PySide6.__file__), "plugins")
if os.path.isdir(_pyside_plugins):
    os.environ["QT_PLUGIN_PATH"] = _pyside_plugins
os.environ["QT_FFMPEG_DEBUG"] = "0"
os.environ["QT_LOGGING_RULES"] = (
    "qt.multimedia.*=false;qt.multimedia.ffmpeg.*=false;ffmpeg.*=false"
)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QStackedWidget,
    QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView,
    QGridLayout, QLineEdit, QFrame, QSizePolicy, QDialog,
    QDialogButtonBox, QProgressBar, QSpacerItem, QStyledItemDelegate,
    QStyle, QStyleOptionComboBox, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl, QRect, QEvent, QPoint, QSize
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QPixmap, QColor, QPalette, QPainter, QImage, QBrush
import re
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────
VERSION = "4.3.40"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HERA_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))
DATA_DIR = os.path.join(HERA_DIR, "Data")
FONT_PATH = os.path.join(HERA_DIR, "BebasNeue-Regular.ttf")
LOGO_ORIG = os.path.join(HERA_DIR, "hera_loading_screen.png")
LOGO_NOBG = os.path.join(DATA_DIR, "hera_nobg.png")
DB_PATH = os.path.join(DATA_DIR, "hera.db")
CRASH_LOG = os.path.join(DATA_DIR, "hera_crash.log")
LOGO_DIR = os.path.join(HERA_DIR, "NFL LOGOS")
COLOR_CSV = os.path.join(DATA_DIR, "Hera_Color_Hex_Codes_v3_00b8.csv")
AUDIO_PATH = os.path.join(HERA_DIR, "HERA_AUDIO.mp3")
SPLASH_LOCK = os.path.join(HERA_DIR, "hera_splash_lock.png")
CHARCOAL = "#262626"  # CSV APP BACKGROUND / EUTHENIA

os.makedirs(DATA_DIR, exist_ok=True)


def _mute_ffmpeg_console():
    """FFmpeg writes mp3 probe / MFT encoder lines to stderr. Not HERA prints."""
    os.environ["QT_FFMPEG_DEBUG"] = "0"
    try:
        import glob
        import ctypes
        roots = [
            os.path.dirname(PySide6.__file__),
            os.path.join(os.path.dirname(PySide6.__file__), "ffmpeg"),
            os.path.join(os.path.dirname(PySide6.__file__), "plugins", "multimedia"),
        ]
        seen = set()
        for root in roots:
            for path in glob.glob(os.path.join(root, "*avutil*.dll")):
                if path in seen:
                    continue
                seen.add(path)
                try:
                    lib = ctypes.CDLL(path)
                    lib.av_log_set_level(ctypes.c_int(-8))
                except Exception:
                    pass
    except Exception:
        pass


def write_crash(text):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S  ") + text.rstrip() + "\n")
    except Exception:
        pass

TEAM_COLORS = {}  # name/abbr -> (bg_hex, fg_hex)
ROSTER_CACHE = {}  # team_id -> [{name, jersey, position, active}]
_LOGO_PM = {}  # (team_name, size) -> scaled QPixmap

# ESPN + book abbreviations keyed to CSV full names (CSV abbr block is misaligned).
TEAM_NAME_ABBRS = {
    "arizona cardinals": ("ARI", "ARZ"),
    "atlanta falcons": ("ATL",),
    "baltimore ravens": ("BAL",),
    "buffalo bills": ("BUF",),
    "carolina panthers": ("CAR",),
    "chicago bears": ("CHI",),
    "cincinnati bengals": ("CIN",),
    "cleveland browns": ("CLE",),
    "dallas cowboys": ("DAL",),
    "denver broncos": ("DEN",),
    "detroit lions": ("DET",),
    "green bay packers": ("GB", "GNB", "GBP"),
    "houston texans": ("HOU",),
    "indianapolis colts": ("IND",),
    "jacksonville jaguars": ("JAX", "JAC"),
    "kansas city chiefs": ("KC", "KAN"),
    "las vegas raiders": ("LV", "LVR", "OAK"),
    "los angeles chargers": ("LAC", "SD"),
    "los angeles rams": ("LAR", "LA", "STL"),
    "miami dolphins": ("MIA",),
    "minnesota vikings": ("MIN",),
    "new england patriots": ("NE", "NWE"),
    "new orleans saints": ("NO", "NOR"),
    "new york giants": ("NYG",),
    "new york jets": ("NYJ",),
    "philadelphia eagles": ("PHI",),
    "pittsburgh steelers": ("PIT",),
    "san francisco 49ers": ("SF", "SFO"),
    "seattle seahawks": ("SEA",),
    "tampa bay buccaneers": ("TB", "TAM"),
    "tennessee titans": ("TEN",),
    "washington commanders": ("WAS", "WSH", "WFT"),
}


def load_team_colors():
    """Load background/font hex from the CSV full-name table, then attach ESPN abbrs."""
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
                if head.startswith("FULL TEAM"):
                    continue
                if head.startswith("TEAM ABBREVIATION"):
                    break
                if head.startswith("OFFENSE") or head.startswith("DEFENSE"):
                    break
                if len(parts) < 3:
                    continue
                bg, fg = parts[1], parts[2]
                if not (bg.startswith("#") and fg.startswith("#")):
                    continue
                raw = parts[0]
                pair = (bg, fg)
                TEAM_COLORS[raw] = pair
                TEAM_COLORS[raw.lower()] = pair
                TEAM_COLORS[raw.upper()] = pair
                for ab in TEAM_NAME_ABBRS.get(raw.lower(), ()):
                    TEAM_COLORS[ab] = pair
                    TEAM_COLORS[ab.lower()] = pair
                    TEAM_COLORS[ab.upper()] = pair
    except Exception:
        pass


def colors_for_team(team):
    """CSV pair (bg, fg) for a full name or abbreviation, or None."""
    if not TEAM_COLORS:
        load_team_colors()
    if not team:
        return None
    t = str(team).strip()
    if t in ("", "N/A", "—", "-"):
        return None
    hit = TEAM_COLORS.get(t) or TEAM_COLORS.get(t.upper()) or TEAM_COLORS.get(t.lower())
    if hit:
        return hit
    compact = t.replace(".", "").replace(" ", "")
    return TEAM_COLORS.get(compact.upper()) or TEAM_COLORS.get(compact.lower())


def tracking_table_ss():
    """Item backgrounds come from the delegate (team CSV colors), not CSS."""
    return (f"QTableWidget{{background:{CARD};color:{TEXT};border:none;"
            f"gridline-color:{BORDER2};outline:none;}}"
            f"QTableWidget::item{{background:transparent;}}"
            f"QHeaderView::section{{background:{HDR_BG};color:{TEXT_MID};border:none;"
            f"border-bottom:0.5px solid {BORDER2};padding:4px 8px;font-size:10px;letter-spacing:2px;}}"
            f"QScrollBar:vertical{{background:{BG};width:5px;border:none;}}"
            f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:2px;}}")


class _TeamRowDelegate(QStyledItemDelegate):
    """Paints a full row from the TEAM cell (Active Legs, Game Tracker, Archive)."""

    def __init__(self, team_col, parent=None):
        super().__init__(parent)
        self._team_col = team_col

    def paint(self, painter, option, index):
        team = index.sibling(index.row(), self._team_col).data(Qt.DisplayRole)
        if team is None:
            team = index.sibling(index.row(), self._team_col).data(Qt.UserRole)
        pair = colors_for_team(team)
        painter.save()
        painter.setClipRect(option.rect)
        if pair:
            painter.fillRect(option.rect, QColor(pair[0]))
            painter.setPen(QColor(pair[1]))
        else:
            painter.fillRect(option.rect, QColor(CARD))
            painter.setPen(QColor(TEXT))
        fr = index.data(Qt.FontRole)
        painter.setFont(fr if isinstance(fr, QFont) else option.font)
        text = index.data(Qt.DisplayRole)
        painter.drawText(
            option.rect, Qt.AlignCenter | Qt.TextSingleLine,
            "" if text is None else str(text))
        if index.sibling(index.row(), 0).data(int(Qt.UserRole) + 1):
            painter.fillRect(
                option.rect.left(), option.rect.top(),
                option.rect.width(), 2, QColor(BORDER))
        painter.restore()

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
    "PS YDS": {"keys": ("passingYards",)},
    "PS TD": {"keys": ("passingTouchdowns",)},
    "COMP": {"keys": ("completions", "completions/passingAttempts"), "slash": "left"},
    "PS ATT": {"keys": ("attempts", "passingAttempts", "completions/passingAttempts"), "slash": "right"},
    "INT": {"keys": ("interceptions",), "group": "passing"},
    "LNG PS": {"keys": ("longPassingYards", "longPassing")},
    "REC YDS": {"keys": ("receivingYards",)},
    "REC": {"keys": ("receptions",)},
    "TAR": {"keys": ("receivingTargets",)},
    "LNG REC": {"keys": ("longReception",)},
    "RSH ATT": {"keys": ("rushingAttempts",)},
    "RSH YDS": {"keys": ("rushingYards",)},
    "SCK": {"keys": ("sacks",), "group": "defensive"},
    "T+A": {"keys": ("totalTackles",)},
    "INT REC": {"keys": ("interceptions",), "group": "interceptions"},
    "K PTS": {"keys": ("kickingPoints", "totalKickingPoints")},
    "FGM": {"keys": ("fieldGoalsMade", "fieldGoalsMade/fieldGoalAttempts"), "slash": "left"},
    "EPM": {"keys": ("extraPointsMade", "extraPointsMade/extraPointAttempts"), "slash": "left"},
    "ATD": {
        "keys": (
            "rushingTouchdowns", "receivingTouchdowns",
            "kickReturnTouchdowns", "puntReturnTouchdowns",
            "defensiveTouchdowns", "interceptionTouchdowns",
        ),
        "sum": True,
    },
    "1TD": {
        "keys": (
            "rushingTouchdowns", "receivingTouchdowns",
            "kickReturnTouchdowns", "puntReturnTouchdowns",
            "defensiveTouchdowns", "interceptionTouchdowns",
        ),
        "sum": True,
    },
    "LTD": {
        "keys": (
            "rushingTouchdowns", "receivingTouchdowns",
            "kickReturnTouchdowns", "puntReturnTouchdowns",
            "defensiveTouchdowns", "interceptionTouchdowns",
        ),
        "sum": True,
    },
}

PERIOD_MARKETS = {
    "1Q TOT": (1,), "2Q TOT": (2,), "3Q TOT": (3,), "4Q TOT": (4,),
    "1H TOT": (1, 2), "2H TOT": (3, 4),
    "1Q SPD": (1,), "2Q SPD": (2,), "3Q SPD": (3,), "4Q SPD": (4,),
    "1H SPD": (1, 2), "2H SPD": (3, 4),
    "1Q ML": (1,), "2Q ML": (2,), "3Q ML": (3,), "4Q ML": (4,),
    "1H ML": (1, 2), "2H ML": (3, 4),
}
TEAM_SCORE_MARKETS = {"ML", "SPREAD", "TOT", "TM TOT"} | set(PERIOD_MARKETS)

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


def text_px(font, text):
    fm = QFontMetrics(font)
    try:
        return fm.horizontalAdvance(str(text))
    except Exception:
        return fm.boundingRect(str(text)).width()


def force_charcoal(w, color=None):
    """Windows ignores background-only stylesheets unless auto-fill + border:none."""
    color = color or CHARCOAL
    w.setAttribute(Qt.WA_StyledBackground, True)
    w.setAutoFillBackground(True)
    pal = w.palette()
    qc = QColor(color)
    for grp in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        pal.setColor(grp, QPalette.Window, qc)
        pal.setColor(grp, QPalette.Base, qc)
        pal.setColor(grp, QPalette.Button, qc)
    w.setPalette(pal)
    w.setStyleSheet(f"background-color:{color}; border:none;")


# ─────────────────────────────────────────────
# STYLE HELPERS
# ─────────────────────────────────────────────
def card_ss(r=0):
    return f"background:{CARD}; border:none;"


def combo_ss(center=False):
    ss = (f"QComboBox{{background:#2a2a2a;color:#ffffff;border:0.5px solid #444;"
          f"border-radius:0px;padding:2px 6px;}}"
          f"QComboBox::drop-down{{border:none;width:14px;}}"
          f"QComboBox QAbstractItemView{{background:#2a2a2a;color:#ffffff;"
          f"border:1px solid {BORDER};selection-background-color:{GREEN_DIM};}}")
    return ss


def input_ss():
    return (f"QLineEdit{{background:#2a2a2a;color:#ffffff;border:0.5px solid #444;"
            f"border-radius:0px;padding:2px 6px;}}")


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
            f"QPushButton:hover{{color:{GREEN if fg == GREEN else TEXT};}}")


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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS archive_bankroll (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            wagers INTEGER NOT NULL DEFAULT 0,
            bet REAL NOT NULL DEFAULT 0,
            won REAL NOT NULL DEFAULT 0,
            lost REAL NOT NULL DEFAULT 0
        )
    """)
    conn.execute("INSERT OR IGNORE INTO archive_bankroll(id) VALUES(1)")
    conn.commit()
    conn.close()


def db():
    return sqlite3.connect(DB_PATH)


# ─────────────────────────────────────────────
# ESPN HELPERS
# ─────────────────────────────────────────────
def espn_get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=4)
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
            "situation": comp.get("situation") if isinstance(comp.get("situation"), dict) else {},
        })
    return games, week_num


def fetch_summary(game_id):
    return espn_get(ESPN_SUMMARY, params={"event": game_id})


def _sit_blobs(game, summary):
    blobs = []
    if isinstance(game, dict):
        blobs.append(game.get("situation"))
    if isinstance(summary, dict):
        blobs.append(summary.get("situation"))
        hdr = summary.get("header") or {}
        if isinstance(hdr, dict):
            for comp in hdr.get("competitions") or []:
                if isinstance(comp, dict):
                    blobs.append(comp.get("situation"))
        drives = summary.get("drives") or {}
        if isinstance(drives, dict):
            cur = drives.get("current")
            blobs.append(cur)
            if isinstance(cur, dict):
                plays = cur.get("plays") or []
                if plays:
                    blobs.append(plays[-1])
    return [b for b in blobs if isinstance(b, dict)]


def _one_sit_line(text):
    line = " ".join(str(text or "").split()).strip()
    if not line:
        return ""
    up = line.upper()
    half = len(up) // 2
    if half >= 6 and up[:half].strip() == up[half:].strip():
        up = up[:half].strip()
    return up


def down_distance_text(game, summary=None):
    """One line only. Prefer ESPN's single downDistanceText; never stack sources."""
    for sit in _sit_blobs(game, summary):
        raw = sit.get("downDistanceText")
        if raw:
            return _one_sit_line(raw)
        short = sit.get("shortDownDistanceText")
        if short:
            loc = sit.get("possessionText")
            if loc and " at " not in str(short).lower():
                return _one_sit_line(f"{short} at {loc}")
            return _one_sit_line(short)
        down, dist = sit.get("down"), sit.get("distance")
        if down in (None, "", 0, "0") or dist in (None, ""):
            continue
        try:
            d = int(down)
            suf = {1: "ST", 2: "ND", 3: "RD"}.get(d, "TH")
            label = f"{d}{suf} & {dist}"
        except Exception:
            label = f"{down} & {dist}"
        loc = sit.get("possessionText")
        if loc:
            label = f"{label} at {loc}"
        return _one_sit_line(label)
    return ""


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


def fetch_roster(game_id, team_id, force=False):
    """Fetch team roster — tries live game endpoint first, falls back to team roster."""
    key = str(team_id)
    if not force and key in ROSTER_CACHE:
        return ROSTER_CACHE[key]
    url = f"{ESPN_CORE}/events/{game_id}/competitions/{game_id}/competitors/{team_id}/roster"
    data = espn_get(url)
    players = _parse_roster_entries(data.get("entries", []) if data else [])
    if not players:
        url2 = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster"
        data2 = espn_get(url2)
        entries = []
        if data2:
            for group in data2.get("athletes", []):
                entries.extend(group.get("items", []) if isinstance(group, dict) and "items" in group else (
                    [group] if isinstance(group, dict) else []))
        players = _parse_roster_entries(entries)
    ROSTER_CACHE[key] = players
    return players


def roster_by_side(game):
    """Away names A–Z, then home names A–Z. Each item is (name, team_abbr)."""
    if not game:
        return [], []
    away = sorted(fetch_roster(game["id"], game["away"]["id"]) or [],
                  key=lambda p: (p.get("name") or "").lower())
    home = sorted(fetch_roster(game["id"], game["home"]["id"]) or [],
                  key=lambda p: (p.get("name") or "").lower())
    return away, home


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


_NAME_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)[.]?$", re.I)


def _norm_name_parts(name):
    n = (name or "").lower().replace(".", " ").replace("'", "")
    n = n.replace("-", " ")
    n = _NAME_SUFFIX.sub("", n).strip()
    return [p for p in n.split() if p]


def _name_match(player_name, athlete_name):
    if not player_name or not athlete_name:
        return False
    a = _norm_name_parts(player_name)
    b = _norm_name_parts(athlete_name)
    if not a or not b:
        return False
    if a == b:
        return True
    sa, sb = " ".join(a), " ".join(b)
    if sa in sb or sb in sa:
        return True
    if a[-1] != b[-1] or len(a[-1]) <= 2:
        return False
    if len(a) == 1:
        return True
    return a[0][0] == b[0][0]


def _parse_cell(raw, slash=""):
    if raw in (None, ""):
        return None
    s = str(raw).strip().replace(",", "")
    if "/" in s:
        left, right, *_rest = s.split("/")
        s = right if slash == "right" else left
    try:
        return float(s)
    except Exception:
        return None


def _fmt_stat(n):
    if n is None:
        return "—"
    try:
        x = float(n)
    except Exception:
        return str(n)
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return str(round(x, 1))


def _fscore(x):
    try:
        return float(str(x).replace(",", "") or 0)
    except Exception:
        return 0.0


def _ls_period(ls, period):
    if not ls:
        return 0.0
    v = ls.get(int(period))
    if v in (None, "—", ""):
        return 0.0
    return _fscore(v)


def _ls_range(ls, periods):
    return sum(_ls_period(ls, p) for p in periods)


def _team_market_stat(market, game, team_abbr, away_ls, home_ls):
    if market not in TEAM_SCORE_MARKETS or not game:
        return None
    away = game.get("away") or {}
    home = game.get("home") or {}
    ascore, hscore = _fscore(away.get("score")), _fscore(home.get("score"))
    is_away = team_abbr == away.get("abbr")
    is_home = team_abbr == home.get("abbr")
    if market == "TOT":
        return ascore + hscore
    if market == "TM TOT":
        if is_away:
            return ascore
        if is_home:
            return hscore
        return None
    if market == "ML":
        if is_away:
            return ascore
        if is_home:
            return hscore
        return None
    if market == "SPREAD":
        if is_away:
            return ascore - hscore
        if is_home:
            return hscore - ascore
        return None
    pers = PERIOD_MARKETS.get(market)
    if not pers:
        return None
    a = _ls_range(away_ls, pers)
    h = _ls_range(home_ls, pers)
    if market.endswith("TOT"):
        return a + h
    if not (is_away or is_home):
        return None
    ts, os_ = (a, h) if is_away else (h, a)
    if market.endswith("ML"):
        return ts
    return ts - os_


def _read_wanted(keys, stats, wanted, slash=""):
    for wk in wanted:
        raw = None
        use_slash = slash
        if wk in keys:
            i = keys.index(wk)
            raw = stats[i] if i < len(stats) else None
            if "/" in wk and not slash:
                use_slash = "right" if wk.split("/")[-1] in (
                    "passingAttempts", "fieldGoalAttempts", "extraPointAttempts") else "left"
        else:
            for i, k in enumerate(keys):
                parts = str(k).split("/")
                if wk not in parts:
                    continue
                raw = stats[i] if i < len(stats) else None
                use_slash = "left" if parts[0] == wk else "right"
                break
        val = _parse_cell(raw, use_slash if raw is not None and "/" in str(raw) else "")
        if val is not None:
            return val
    return None


def _scan_player_stat(summary, player_name, spec, team_id):
    wanted = spec.get("keys") or ()
    slash = spec.get("slash") or ""
    hint = (spec.get("group") or "").lower()
    do_sum = bool(spec.get("sum"))
    blocks = (summary.get("boxscore") or {}).get("players") or []

    def group_ok(group):
        if not hint:
            return True
        return (group.get("name") or "").lower().startswith(hint)

    def scan(require_team):
        total = 0.0
        any_hit = False
        matched = False
        for block in blocks:
            bid = str((block.get("team") or {}).get("id", ""))
            if require_team and team_id and bid != str(team_id):
                continue
            for group in block.get("statistics") or []:
                if not group_ok(group):
                    continue
                keys = group.get("keys") or []
                for ath in group.get("athletes") or []:
                    name = (ath.get("athlete") or {}).get("displayName", "")
                    if not _name_match(player_name, name):
                        continue
                    matched = True
                    stats = ath.get("stats") or []
                    val = _read_wanted(keys, stats, wanted, slash)
                    if val is None:
                        continue
                    if do_sum:
                        total += val
                        any_hit = True
                    else:
                        return val, True
        if do_sum and any_hit:
            return total, True
        return None, matched

    v, matched = scan(True)
    if v is None:
        v2, m2 = scan(False)
        v, matched = v2, matched or m2
    return v, matched, bool(blocks)


def get_live_stat(summary, player_name, market, team_id, game=None,
                  away_ls=None, home_ls=None, team_abbr=""):
    market_u = (market or "").upper().strip()
    team_val = _team_market_stat(market_u, game, team_abbr, away_ls, home_ls)
    if team_val is not None:
        return _fmt_stat(team_val)
    spec = MARKET_STAT_MAP.get(market_u)
    if not spec:
        return "—"
    state = (game or {}).get("state") or ""
    if not player_name or player_name in ("N/A", "—"):
        return "0" if state != "post" else "—"
    v = matched = has_blocks = None
    if summary:
        v, matched, has_blocks = _scan_player_stat(summary, player_name, spec, team_id)
    if v is not None:
        return _fmt_stat(v)
    if state == "post" and has_blocks and not matched:
        return "—"
    return "0"


def compute_needs(ou, line, live_val, game=None, status=None, market=None):
    """Remaining to strictly exceed (OVER) or remaining cushion (UNDER)."""
    if status == "WON":
        return "HIT"
    if status == "LOST":
        return "DEAD"
    cur = _parse_cell(live_val)
    tgt = _parse_cell(line)
    if cur is None or tgt is None:
        return "—"
    ou_u = (ou or "").upper()
    state = (game or {}).get("state") or ""
    if ou_u == "OVER":
        if cur > tgt:
            return "HIT"
        if state == "post":
            return "DEAD"
        return _fmt_stat(max(0, math.floor(tgt) + 1 - cur))
    if ou_u == "UNDER":
        if cur > tgt:
            return "DEAD"
        cushion = math.floor(tgt) - cur
        if cushion < 0:
            cushion = 0
        if state == "post":
            return "HIT" if cur < tgt else "PUSH"
        return _fmt_stat(cushion)
    return "—"


def settle_leg(ou, line, live_val, game_state, current_status):
    """Return WON / LOST / existing status from live stat vs line."""
    if current_status in ("WON", "LOST"):
        return current_status
    cur = _parse_cell(live_val)
    tgt = _parse_cell(line)
    if cur is None or tgt is None:
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


def _parlay_result(legs, stake, boost):
    """Return ('WON'|'LOST'|'PENDING', profit, stake_lost) for an archived parlay."""
    stake = float(stake or 0)
    statuses = []
    odds = []
    for leg in legs:
        if len(leg) > 9 and leg[9]:
            odds.append(leg[9])
        st = (leg[11] if len(leg) > 11 else "") or "PENDING"
        statuses.append(str(st).upper())
    calc = calc_parlay(odds, stake, boost or 0)
    if statuses and all(s == "WON" for s in statuses):
        return "WON", round(float(calc["payout"]) - stake, 2), 0.0
    if any(s == "LOST" for s in statuses):
        return "LOST", 0.0, stake
    return "PENDING", 0.0, 0.0


def raw_archive_totals():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM parlays WHERE status='ARCHIVED'")
    parlays = c.fetchall()
    wagers = 0
    bet = won = lost = 0.0
    for par in parlays:
        if not par or len(par) < 7:
            continue
        pid, _label, _book, stake, boost = par[0], par[1], par[2], par[3], par[4]
        c.execute("SELECT * FROM legs WHERE parlay_id=?", (pid,))
        legs = c.fetchall()
        wagers += 1
        bet += float(stake or 0)
        _res, profit, stake_lost = _parlay_result(legs, stake, boost)
        won += profit
        lost += stake_lost
    conn.close()
    return {
        "wagers": wagers,
        "bet": round(bet, 2),
        "won": round(won, 2),
        "lost": round(lost, 2),
    }


def archive_bankroll_baseline():
    conn = db()
    c = conn.cursor()
    c.execute("SELECT wagers, bet, won, lost FROM archive_bankroll WHERE id=1")
    row = c.fetchone()
    conn.close()
    if not row:
        return {"wagers": 0, "bet": 0.0, "won": 0.0, "lost": 0.0}
    return {"wagers": int(row[0] or 0), "bet": float(row[1] or 0),
            "won": float(row[2] or 0), "lost": float(row[3] or 0)}


def save_archive_bankroll_baseline(tot):
    conn = db()
    conn.execute(
        "UPDATE archive_bankroll SET wagers=?, bet=?, won=?, lost=? WHERE id=1",
        (int(tot.get("wagers", 0)), float(tot.get("bet", 0)),
         float(tot.get("won", 0)), float(tot.get("lost", 0))))
    conn.commit()
    conn.close()


def display_archive_bankroll():
    try:
        raw = raw_archive_totals()
        base = archive_bankroll_baseline()
        wagers = max(0, raw["wagers"] - base["wagers"])
        bet = max(0.0, round(raw["bet"] - base["bet"], 2))
        won = max(0.0, round(raw["won"] - base["won"], 2))
        lost = max(0.0, round(raw["lost"] - base["lost"], 2))
        return {
            "wagers": wagers,
            "bet": bet,
            "won": won,
            "lost": lost,
            "net": round(won - lost, 2),
        }
    except Exception:
        traceback.print_exc()
        return {"wagers": 0, "bet": 0.0, "won": 0.0, "lost": 0.0, "net": 0.0}


def empty_archive():
    conn = db()
    conn.execute(
        "DELETE FROM legs WHERE parlay_id IN (SELECT id FROM parlays WHERE status='ARCHIVED')")
    conn.execute("DELETE FROM parlays WHERE status='ARCHIVED'")
    conn.commit()
    conn.close()
    save_archive_bankroll_baseline({"wagers": 0, "bet": 0.0, "won": 0.0, "lost": 0.0})


def persist_leg_live(leg_id, live_val, status):
    conn = None
    try:
        conn = db()
        conn.execute(
            "UPDATE legs SET live_stat=?, leg_status=? WHERE id=?",
            (str(live_val), status, leg_id))
        conn.commit()
    except Exception:
        pass
    finally:
        if conn is not None:
            try:
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
    key = (team_name, int(size))
    pm = _LOGO_PM.get(key)
    if pm is None:
        path = logo_path(team_name)
        if not os.path.exists(path):
            return
        src = QPixmap(path)
        pm = src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        _LOGO_PM[key] = pm
    label.setPixmap(pm)


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
    progress = Signal(str)
    finished_ok = Signal(object, object)
    failed = Signal(str)

    def run(self):
        try:
            self.progress.emit("OPENING DATABASE")
            init_db()
            self.progress.emit("LOADING TEAM COLORS")
            load_team_colors()
            self.progress.emit("FETCHING NFL SCHEDULE")
            games, week_num = fetch_scoreboard()
            games = games or []
            n_games = len(games)
            self.progress.emit(f"FETCHING NFL SCHEDULE  {n_games} / {n_games} GAMES")

            teams = {}
            for g in games:
                teams[str(g["away"]["id"])] = g
                teams[str(g["home"]["id"])] = g
            team_ids = list(teams.keys())
            n_teams = max(1, len(team_ids))
            player_count = 0
            est_players = n_teams * 53
            for i, tid in enumerate(team_ids, 1):
                self.progress.emit(f"LOADING TEAMS  {i} / {n_teams}")
                g = teams[tid]
                roster = fetch_roster(g["id"], tid) or []
                player_count += len(roster)
                self.progress.emit(
                    f"LOADING PLAYERS  {player_count} / {est_players}")
            self.progress.emit("SYSTEM READY")
            self.finished_ok.emit(games, week_num)
        except Exception:
            self.failed.emit(traceback.format_exc())


def _colorize_statue(pm, hex_color):
    """Shift to hex_color, keep marble folds (not a silhouette)."""
    if pm.isNull():
        return pm
    img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    tgt = QColor(hex_color)
    tr, tg, tb = tgt.red(), tgt.green(), tgt.blue()
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor.fromRgba(img.pixel(x, y))
            a = c.alpha()
            if a == 0:
                continue
            lum = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255.0
            lum = min(1.0, 0.28 + lum * 0.95)
            img.setPixel(x, y, QColor(int(tr * lum), int(tg * lum), int(tb * lum), a).rgba())
    return QPixmap.fromImage(img)


def _statue_rim(pm, hex_color="#1cbe1c"):
    """Bright #1cbe1c rim around the entire statue outline — not a dark shadow."""
    if pm.isNull():
        return QPixmap()
    src = pm.toImage().convertToFormat(QImage.Format_ARGB32)
    sw, sh = src.width(), src.height()
    step = 2
    mw, mh = (sw + step - 1) // step, (sh + step - 1) // step
    rad = 6
    pad = rad + 3
    mw2, mh2 = mw + pad * 2, mh + pad * 2
    mask = bytearray(mw2 * mh2)
    for y in range(sh):
        my = y // step + pad
        row = my * mw2
        for x in range(sw):
            if (src.pixel(x, y) >> 24) > 80:
                mask[row + (x // step + pad)] = 1
    # dilate (max filter)
    dil = bytearray(mw2 * mh2)
    for y in range(mh2):
        y0, y1 = max(0, y - rad), min(mh2, y + rad + 1)
        for x in range(mw2):
            x0, x1 = max(0, x - rad), min(mw2, x + rad + 1)
            hit = False
            for yy in range(y0, y1):
                base = yy * mw2
                if hit:
                    break
                for xx in range(x0, x1):
                    if mask[base + xx]:
                        hit = True
                        break
            if hit:
                dil[y * mw2 + x] = 1
    ring = QImage(mw2, mh2, QImage.Format_ARGB32)
    ring.fill(0)
    rgb = QColor(hex_color).rgb() & 0x00FFFFFF
    for y in range(mh2):
        base = y * mw2
        for x in range(mw2):
            if dil[base + x] and not mask[base + x]:
                ring.setPixel(x, y, 0xE0000000 | rgb)  # strong green, not 38% mud
    out_w = sw + pad * 2 * step
    out_h = sh + pad * 2 * step
    glow = QPixmap.fromImage(ring).scaled(
        out_w, out_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out = QPixmap(out_w, out_h)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.drawPixmap(0, 0, glow)
    p.drawPixmap(pad * step, pad * step, pm)
    p.end()
    return out


class LoadingScreen(QWidget):
    """Matches the charcoal mockup. 30s hold. HERA_AUDIO.mp3 over the splash."""
    ready = Signal(object, object)

    HERA_HEX = "#1cbe1c"
    MIN_HOLD = 30.0

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setFixedSize(720, 960)
        self.setStyleSheet(f"background:{CHARCOAL};")
        self._pct = 0.0
        self._status = "STARTING"
        self._pending = None
        self._started_at = time.monotonic()
        self._data_done_at = None
        self._player = None
        self._audio_out = None
        self._lock = QPixmap()
        if os.path.exists(SPLASH_LOCK):
            self._lock = QPixmap(SPLASH_LOCK)
        self._worker = BootWorker()
        self._worker.progress.connect(self._on_boot_status)
        self._worker.finished_ok.connect(self._on_ready)
        self._worker.failed.connect(self._on_fail)
        self._clock = QTimer(self)
        self._clock.setInterval(50)
        self._clock.timeout.connect(self._tick)

    def start(self):
        self._center()
        self.show()
        self._started_at = time.monotonic()
        self._start_audio()
        self._clock.start()
        self._worker.start()

    def _start_audio(self):
        if not os.path.exists(AUDIO_PATH):
            print("Missing audio:", AUDIO_PATH)
            return
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            _mute_ffmpeg_console()
            self._audio_out = QAudioOutput(self)
            self._audio_out.setVolume(1.0)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._audio_out)
            self._player.setSource(QUrl.fromLocalFile(os.path.abspath(AUDIO_PATH)))
            self._player.play()
            return
        except Exception as e:
            print("QtMultimedia audio failed:", e)
        try:
            import pygame
            pygame.mixer.init()
            pygame.mixer.music.load(AUDIO_PATH)
            pygame.mixer.music.play()
        except Exception as e:
            print("pygame audio failed:", e)

    def _stop_audio(self):
        try:
            if self._player:
                self._player.stop()
        except Exception:
            pass
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass

    def _center(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2,
                      geo.center().y() - self.height() // 2)

    def _tick(self):
        elapsed = time.monotonic() - self._started_at
        total = self.MIN_HOLD
        if self._data_done_at is not None:
            total = max(self.MIN_HOLD, self._data_done_at - self._started_at)
        self._pct = min(100.0, 100.0 * elapsed / total)
        if self._data_done_at is None:
            self._pct = min(95.0, self._pct)
        elif elapsed >= total:
            self._pct = 100.0
            self._clock.stop()
            self.update()
            self._finish()
            return
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(CHARCOAL))
        w, h = self.width(), self.height()
        hera_c = QColor(self.HERA_HEX)
        t = max(0.0, min(100.0, self._pct)) / 100.0

        if not self._lock.isNull():
            p.drawPixmap(0, 0, self._lock.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        # Cover baked-in status/bar/% so live text is not sitting on the mockup labels
        cover_top = int(h * 0.855)
        p.fillRect(0, cover_top, w, h - cover_top, QColor(CHARCOAL))

        pct_font = QFont(_FF)
        pct_font.setPixelSize(18)
        status_font = QFont(_FF)
        status_font.setPixelSize(22)
        p.setFont(pct_font)
        pct_h = p.fontMetrics().height()
        p.setFont(status_font)
        st_h = p.fontMetrics().height()
        bottom, bar_h = 32, 4
        pct_y = h - bottom - pct_h
        bar_y = pct_y - 14 - bar_h
        status_y = bar_y - 22 - st_h

        p.setFont(status_font)
        p.setPen(QColor("#a8a8a8"))
        p.drawText(QRect(24, status_y, w - 48, st_h + 4),
                   Qt.AlignHCenter | Qt.AlignVCenter, self._status)

        margin = 48
        bar_w = w - margin * 2
        p.fillRect(margin, bar_y, bar_w, bar_h, QColor("#303030"))
        p.fillRect(margin, bar_y, max(1, int(bar_w * t)), bar_h, hera_c)

        p.setFont(pct_font)
        p.setPen(QColor("#969696"))
        p.drawText(QRect(0, pct_y, w, pct_h),
                   Qt.AlignHCenter | Qt.AlignTop, f"{int(self._pct)}%")
        p.end()

    def _on_boot_status(self, msg):
        self._status = msg
        self.update()

    def _on_ready(self, games, week_num):
        self._pending = (games, week_num)
        self._data_done_at = time.monotonic()
        self._status = "SYSTEM READY"

    def _finish(self):
        self._stop_audio()
        games, week_num = self._pending if self._pending is not None else ([], None)
        self.hide()
        try:
            QApplication.processEvents()
        except Exception:
            pass
        self.ready.emit(games, week_num)
        self.close()

    def _on_fail(self, err):
        self._status = "STARTUP FAILED"
        self._data_done_at = time.monotonic()
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
    reset_bankroll = Signal()
    empty_archive = Signal()

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

        self._bank = QWidget()
        self._bank.setStyleSheet("background:transparent; border:none;")
        self._bank.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        bl = QHBoxLayout(self._bank)
        bl.setContentsMargins(10, 0, 6, 0)
        bl.setSpacing(0)

        STAT_F = bb(9)
        WHITE = "#ffffff"
        BET_BLUE = "#3d9eff"
        LOST_C = "#e06666"
        NET_Y = "#ffdc28"

        def lock(lbl):
            lbl.setFixedWidth(text_px(lbl.font(), lbl.text()) + 4)
            lbl.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        def stat_pair(key, color):
            box = QWidget()
            box.setStyleSheet("background:transparent; border:none;")
            box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            hl = QHBoxLayout(box)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(3)
            k = QLabel(key)
            k.setFont(STAT_F)
            k.setStyleSheet(f"color:{WHITE}; background:transparent; letter-spacing:0px;")
            k.setTextFormat(Qt.PlainText)
            lock(k)
            v = QLabel("0")
            v.setFont(STAT_F)
            v.setStyleSheet(f"color:{color}; background:transparent; letter-spacing:0px;")
            v.setTextFormat(Qt.PlainText)
            lock(v)
            hl.addWidget(k)
            hl.addWidget(v)
            return box, v

        def pipe():
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setFixedWidth(1)
            sep.setFixedHeight(14)
            sep.setStyleSheet(f"background:{BORDER}; border:none;")
            return sep

        self._wagers_box, self._wagers_v = stat_pair("WAGERS:", WHITE)
        self._bet_box, self._bet_v = stat_pair("BET:", BET_BLUE)
        self._won_box, self._won_v = stat_pair("WON:", GREEN)
        self._lost_box, self._lost_v = stat_pair("LOST:", LOST_C)
        self._net_box, self._net_v = stat_pair("NET GAIN:", NET_Y)

        for i, wdg in enumerate(
                [self._wagers_box, self._bet_box, self._won_box, self._lost_box, self._net_box]):
            if i:
                bl.addWidget(pipe())
                bl.addSpacing(5)
            bl.addWidget(wdg)
            bl.addSpacing(5)

        bl.addSpacing(4)
        self._reset_btn = QPushButton("RESET")
        self._reset_btn.setFont(STAT_F)
        self._reset_btn.setCursor(Qt.PointingHandCursor)
        self._reset_btn.setFixedHeight(18)
        self._reset_btn.setStyleSheet(
            f"QPushButton{{background:{GREEN};color:#000;border:none;padding:1px 7px;}}"
            f"QPushButton:hover{{background:{GREEN};}}")
        self._reset_btn.clicked.connect(self.reset_bankroll.emit)
        self._empty_btn = QPushButton("EMPTY")
        self._empty_btn.setFont(STAT_F)
        self._empty_btn.setCursor(Qt.PointingHandCursor)
        self._empty_btn.setFixedHeight(18)
        self._empty_btn.setStyleSheet(
            "QPushButton{background:#cc0000;color:#ffffff;border:none;padding:1px 7px;}"
            "QPushButton:hover{background:#cc0000;}")
        self._empty_btn.clicked.connect(self.empty_archive.emit)
        self._reset_btn.setFixedWidth(text_px(STAT_F, "RESET") + 16)
        self._empty_btn.setFixedWidth(text_px(STAT_F, "EMPTY") + 16)
        bl.addWidget(self._reset_btn)
        bl.addSpacing(5)
        bl.addWidget(self._empty_btn)

        self._bank.setVisible(False)
        lay.addWidget(self._bank, 0)
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
        self._bank.setVisible(idx == 4)
        if idx == 4:
            self.refresh_bankroll()
        self.tab_changed.emit(idx)

    def refresh_bankroll(self):
        t = display_archive_bankroll()
        pairs = (
            (self._wagers_v, str(t["wagers"])),
            (self._bet_v, f"${t['bet']:.2f}"),
            (self._won_v, f"${t['won']:.2f}"),
            (self._lost_v, f"${t['lost']:.2f}"),
            (self._net_v, f"${t['net']:.2f}"),
        )
        for lbl, text in pairs:
            lbl.setText(text)
            lbl.setFixedWidth(text_px(lbl.font(), text) + 4)


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
        self._center.setMinimumWidth(100)
        self._center.setMaximumWidth(220)
        self._center.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
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
        self._sit_lbl.setWordWrap(False)
        self._sit_lbl.setStyleSheet(f"color:{TEXT_DIM}; background:transparent;")

        center_lay.addWidget(self._live_dot)
        center_lay.addWidget(self._clock_lbl)
        center_lay.addWidget(self._sit_lbl)
        center_lay.addWidget(self._quarter_lbl)

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

        dd = down_distance_text(game, summary)
        self._sit_lbl.setText(dd)
        self._sit_lbl.setVisible(bool(dd) and state == "in")


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

        # ── Team rows (built once, numbers patched in refresh()) ─────
        self._row_widgets = []
        self._row_cells = []
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
            self._row_cells.append(None)

        self.setMinimumHeight(33 + 39 + 53 + 53 + 16)
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
        for i, (team, ls) in enumerate(
                [(game["away"], away_ls or {}), (game["home"], home_ls or {})]):
            row_w = self._row_widgets[i]
            cells = self._row_cells[i]
            if cells is None:
                lay = row_w.layout()
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

                q_lbls = []
                for q in range(1, 5):
                    val = str(ls.get(q, "—")) if ls else "—"
                    sc = QLabel(val)
                    sc.setFont(bb(13))
                    sc.setAlignment(Qt.AlignCenter)
                    sc.setStyleSheet(f"color:{TEXT}; background:transparent;")
                    sc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    sc.setFixedHeight(53)
                    lay.addWidget(sc)
                    q_lbls.append(sc)

                tot = QLabel(str(team["score"]))
                tot.setFont(bb(15))
                tot.setAlignment(Qt.AlignCenter)
                tot.setFixedSize(113, 49)
                tot.setStyleSheet(f"color:{TEXT}; background:transparent;")
                lay.addWidget(tot)
                self._row_cells[i] = {
                    "team_id": team.get("id"),
                    "badge": badge,
                    "logo": logo_lbl,
                    "q": q_lbls,
                    "tot": tot,
                }
                continue

            if cells.get("team_id") != team.get("id"):
                cells["badge"].setStyleSheet(
                    f"background:{team['color']}; border:none;")
                load_logo(cells["logo"], team["name"], 28)
                cells["team_id"] = team.get("id")
            for q in range(1, 5):
                val = str(ls.get(q, "—")) if ls else "—"
                cells["q"][q - 1].setText(val)
            cells["tot"].setText(str(team["score"]))


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
        self._tbl.setStyleSheet(tracking_table_ss())
        self._tbl.setItemDelegate(_TeamRowDelegate(0, self._tbl))
        self._tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._tbl.setShowGrid(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
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

    def refresh(self, game=None, summary=None, away_ls=None, home_ls=None):
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
            ORDER BY p.id, l.id
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

        prev_par = None
        for r, leg in enumerate(legs):
            lid, plabel, book, team, player, market, ou, line, odds, live_stat, leg_status = leg[:11]
            par_key = plabel
            new_parlay = prev_par is not None and par_key != prev_par
            prev_par = par_key

            live_val = live_stat or "—"
            if game:
                away = game.get("away") or {}
                home = game.get("home") or {}
                if team == away.get("abbr"):
                    tid = away.get("id")
                elif team == home.get("abbr"):
                    tid = home.get("id")
                else:
                    tid = ""
                v = get_live_stat(
                    summary, player, market, tid, game=game,
                    away_ls=away_ls, home_ls=home_ls, team_abbr=team or "")
                if v != "—":
                    live_val = v
            state = (game or {}).get("state", "")
            new_status = settle_leg(ou, line, live_val, state, leg_status)
            if live_val != (live_stat or "—") or new_status != leg_status:
                persist_leg_live(lid, live_val, new_status)
                leg_status = new_status

            needs = compute_needs(
                ou, line, live_val, game=game, status=leg_status, market=market)

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

            pair = colors_for_team(team)
            for ci, val in enumerate(vals):
                it = self._tbl.item(r, ci)
                if it is None:
                    it = QTableWidgetItem()
                    it.setFont(bb(11))
                    it.setTextAlignment(Qt.AlignCenter)
                    self._tbl.setItem(r, ci, it)
                it.setText(str(val))
                if ci == 0:
                    it.setData(Qt.UserRole, team)
                    it.setData(int(Qt.UserRole) + 1, new_parlay)
                if pair:
                    it.setBackground(QColor(pair[0]))
                    it.setForeground(QColor(pair[1]))
                else:
                    it.setForeground(QColor(
                        GREEN if is_won else RED if is_lost else TEXT))

            self._tbl.setRowHeight(r, 28)

        hh = self._tbl.horizontalHeader().height() or 26
        self._tbl.setFixedHeight(hh + 28 * len(legs) + 2)
        self.updateGeometry()


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
    W_NUM = 32  # # column
    W_POS = 48  # POS column
    W_NAME = 88  # PLAYER column floor — remaining width goes to stats
    W_STAT = 36  # each stat column minimum (grows with stretch)

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
        self._fp_struct = None
        self._fp_vals = None
        self._refs = None

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
        lbl.setWordWrap(False)
        lbl.setTextFormat(Qt.PlainText)
        lbl.setStyleSheet(f"color:{color}; background:transparent;")
        if expand:
            lbl.setMinimumWidth(max(1, width))
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        elif width:
            lbl.setFixedWidth(width)
        return lbl

    def sizeHint(self):
        h = max(39, int(getattr(self, "_content_h", 39) or 39))
        n = max(1, int(getattr(self, "_n_cols", 6) or 6))
        w = self.W_NUM + self.W_POS + self.W_NAME + self.W_STAT * n
        return QSize(w, h)

    def minimumSizeHint(self):
        return self.sizeHint()

    # ── populate ─────────────────────────────────────────────────

    def _row_from_athlete(self, ae, pos_lookup):
        ath = ae.get("athlete", {})
        jersey = ath.get("jersey", "")
        pos_obj = ath.get("position", {})
        pos = pos_obj.get("abbreviation", "") if isinstance(pos_obj, dict) else ""
        if not pos and pos_lookup and jersey:
            pos = pos_lookup.get(str(jersey).strip(), "")
        if not pos:
            pos = {"PASSING": "QB", "RUSHING": "RB", "RECEIVING": "WR"}.get(self._label, "")
        name = ath.get("displayName", "")
        stats = ae.get("stats", [])
        key = (str(ath.get("id") or ""), str(jersey), str(name), str(pos))
        return key, jersey, pos, name, stats

    def _lock_h(self):
        h = max(39, int(getattr(self, "_content_h", 39) or 39))
        self.setMinimumHeight(h)
        self.setFixedHeight(h)

    def load(self, group, pos_lookup=None):
        self._content_h = 39  # always at least the color header (_hdr_w height)
        if not group:
            group = {"labels": [], "athletes": [], "totals": []}

        labels = group.get("labels", group.get("keys", []))
        athletes = group.get("athletes", [])
        totals = group.get("totals", [])
        # Show every ESPN column — clipping used to hide INT / LNG / RTG / etc.
        stat_labels = tuple(labels)
        self._n_cols = len(stat_labels)

        packed = []
        for ae in athletes:
            s = ae.get("stats", [])
            if s and any(v not in ("0", "0.0", "0/0", "—", "") for v in s):
                packed.append(self._row_from_athlete(ae, pos_lookup))

        tot_vals = tuple(
            str(val) if val is not None else "—"
            for val in (totals[:len(stat_labels)] if totals else ()))
        struct = (stat_labels, tuple(p[0] for p in packed), bool(totals))
        vals = (tuple(tuple(
            str(v) if v is not None else "—"
            for v in p[4][:len(stat_labels)]) for p in packed), tot_vals)

        refs = getattr(self, "_refs", None)
        if struct == getattr(self, "_fp_struct", None) and refs:
            if vals == getattr(self, "_fp_vals", None):
                self._lock_h()
                return
            for pref, p in zip(refs["players"], packed):
                _key, jersey, pos, name, stats = p
                if pref["jersey"].text() != str(jersey):
                    pref["jersey"].setText(str(jersey))
                if pref["name"].text() != str(name):
                    pref["name"].setText(str(name))
                for lbl, val in zip(pref["stats"], stats[:len(stat_labels)]):
                    txt = str(val) if val is not None else "—"
                    if lbl.text() != txt:
                        lbl.setText(txt)
            if refs.get("totals") and totals:
                for lbl, val in zip(refs["totals"], totals[:len(stat_labels)]):
                    txt = str(val) if val is not None else "—"
                    if lbl.text() != txt:
                        lbl.setText(txt)
            self._fp_vals = vals
            self._content_h = 39 + 32 + 32 * len(packed) + (28 if totals else 0)
            self._lock_h()
            return

        self._clear_rows()
        self._fp_struct = struct
        self._fp_vals = vals
        self._content_h = 39

        # Column-header row
        hdr_w, hdr_lay = self._row_widget(HDR_BG, h=32)
        hdr_w.setStyleSheet(
            f"background:{HDR_BG}; border-bottom:1px solid {BORDER};")
        hdr_lay.addWidget(self._cell("#", self.W_NUM, bb(8), TEXT_MID), 0)
        hdr_lay.addWidget(self._cell("POS", self.W_POS, bb(8), TEXT_MID), 0)
        hdr_lay.addWidget(self._cell("PLAYER", self.W_NAME, bb(8), TEXT_MID,
                                     Qt.AlignVCenter | Qt.AlignLeft, expand=True), 2)
        for sl in stat_labels:
            hdr_lay.addWidget(self._cell(sl, self.W_STAT, bb(8), TEXT_MID, expand=True), 1)
        self._rows_lay.addWidget(hdr_w)
        self._content_h += 32

        player_refs = []
        for _key, jersey, pos, name, stats in packed:
            row_w, row_lay = self._row_widget(BG, h=32)

            jersey_lbl = self._cell(jersey, self.W_NUM, bb(10), TEXT_DARK)
            row_lay.addWidget(jersey_lbl, 0)

            pos_bg, pos_fg = POS_COLORS.get(pos, ("#252525", TEXT_DIM))
            pb = BadgeLabel(pos, pos_bg, pos_fg)
            pb.setFont(bb(9))
            pb.setMinimumWidth(max(28, self.W_POS - 8))
            pb.setFixedHeight(23)
            pc = QWidget()
            pc.setMinimumWidth(self.W_POS)
            pc.setFixedHeight(32)
            pc.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            pcl = QHBoxLayout(pc)
            pcl.setContentsMargins(4, 3, 4, 3)
            pcl.setSpacing(0)
            pcl.addWidget(pb)
            row_lay.addWidget(pc, 0)

            nm = QLabel(name)
            nm.setFont(bb(10))
            nm.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            nm.setWordWrap(False)
            nm.setStyleSheet(f"color:{TEXT_MID}; background:transparent;")
            nm.setMinimumWidth(self.W_NAME)
            nm.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            row_lay.addWidget(nm, 2)

            stat_lbls = []
            row_vals = list(stats[:len(stat_labels)])
            while len(row_vals) < len(stat_labels):
                row_vals.append("—")
            for val in row_vals:
                slbl = self._cell(str(val) if val is not None else "—",
                                  self.W_STAT, bb(10), TEXT, expand=True)
                row_lay.addWidget(slbl, 1)
                stat_lbls.append(slbl)

            self._rows_lay.addWidget(row_w)
            self._content_h += 32
            player_refs.append({"jersey": jersey_lbl, "name": nm, "stats": stat_lbls})

        tot_refs = []
        if totals:
            tot_w = QWidget()
            tot_w.setFixedHeight(28)
            tot_w.setStyleSheet(f"background:{HDR_BG};")
            tl = QHBoxLayout(tot_w)
            tl.setContentsMargins(0, 0, 0, 0)
            tl.setSpacing(0)
            tl.addWidget(self._cell("", self.W_NUM + self.W_POS, bb(9), TEXT_DARK), 0)
            tl.addWidget(self._cell("TOTALS", self.W_NAME, bb(9), TEXT_DARK,
                                    Qt.AlignVCenter | Qt.AlignLeft, expand=True), 2)
            for val in totals[:len(stat_labels)]:
                tlbl = self._cell(str(val) if val is not None else "—",
                                  self.W_STAT, bb(9), TEXT_DARK, expand=True)
                tl.addWidget(tlbl, 1)
                tot_refs.append(tlbl)
            self._rows_lay.addWidget(tot_w)
            self._content_h += 28

        self._refs = {"players": player_refs, "totals": tot_refs}
        self._lock_h()


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
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def load(self, team_color, team_alt, team_name,
             pass_group, rush_group, recv_group, pos_lookup=None):
        """Apply team colors and populate all three stat sections."""
        for sec in [self._pass_sec, self._rush_sec, self._recv_sec]:
            sec.set_color(team_color, team_alt, team_name)

        self._pass_sec.load(pass_group, pos_lookup=pos_lookup)
        self._rush_sec.load(rush_group, pos_lookup=pos_lookup)
        self._recv_sec.load(recv_group, pos_lookup=pos_lookup)
        h = sum(
            max(39, int(getattr(s, "_content_h", 39) or 39))
            for s in (self._pass_sec, self._rush_sec, self._recv_sec)
        )
        self.setMinimumHeight(h)
        self.updateGeometry()

    def sizeHint(self):
        h = sum(
            max(39, int(getattr(s, "_content_h", 39) or 39))
            for s in (self._pass_sec, self._rush_sec, self._recv_sec)
        )
        return QSize(400, h)

    def minimumSizeHint(self):
        return self.sizeHint()


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

    def _filtered_plays(self):
        plays = self._plays
        if self._filter == "SCORING PLAYS":
            plays = [p for p in plays if p.get("scoring")]
        elif self._filter in ["Q1", "Q2", "Q3", "Q4"]:
            q = int(self._filter[1])
            plays = [p for p in plays if p.get("period") == q]
        return plays[:60]

    def _play_fp(self, play):
        return (
            play.get("seq"),
            play.get("clock"),
            play.get("period"),
            play.get("text"),
            bool(play.get("scoring")),
            bool(play.get("penalty")),
            str(play.get("team_id") or ""),
        )

    def _render(self):
        plays = self._filtered_plays()
        fp = (self._filter, tuple(self._play_fp(p) for p in plays),
              frozenset(self._bet_players))
        if fp == getattr(self, "_fp", None) and self._il.count() > 1:
            return
        self._fp = fp
        while self._il.count() > 1:
            item = self._il.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for play in plays:
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
class GameFetchWorker(QThread):
    """Pull ESPN payloads off the UI thread so clicks stay responsive."""
    bundle = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game = None
        self._week = None
        self._pending = None

    def fetch(self, game, week=None):
        job = (game, week)
        if self.isRunning():
            self._pending = job
            return
        self._game, self._week = job
        self.start()

    def run(self):
        game, week = self._game, self._week
        if not game:
            return
        try:
            plays = fetch_plays(game["id"]) or []
            summary = fetch_summary(game["id"])
            fresh, _ = fetch_scoreboard(week=week)
            current = game
            for g in (fresh or []):
                if str(g.get("id")) == str(game.get("id")):
                    current = g
                    break
            away_ls = fetch_linescores(current["id"], current["away"]["id"])
            home_ls = fetch_linescores(current["id"], current["home"]["id"])
            self.bundle.emit({
                "game": current,
                "summary": summary,
                "plays": plays,
                "away_ls": away_ls,
                "home_ls": home_ls,
                "games": fresh,
            })
        except Exception:
            traceback.print_exc()
            self.bundle.emit(None)
        self._game = None

    def take_pending(self):
        job = self._pending
        self._pending = None
        return job


class _FitWidthScroll(QScrollArea):
    """Match body width to the viewport; keep height at content so no fake pad."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_body()

    def _fit_body(self):
        w = self.widget()
        if not w:
            return
        vw = max(1, self.viewport().width())
        w.setFixedWidth(vw)
        lay = w.layout()
        if lay:
            lay.activate()
            h = max(lay.sizeHint().height(), lay.minimumSize().height())
        else:
            h = 0
        h = max(h, w.sizeHint().height(), w.minimumSizeHint().height(), 1)
        if lay:
            stacked = 0
            for i in range(lay.count()):
                item = lay.itemAt(i)
                cw = item.widget() if item else None
                if cw:
                    stacked += max(
                        cw.minimumHeight(),
                        cw.sizeHint().height(),
                        cw.minimumSizeHint().height(),
                    )
            m = lay.contentsMargins()
            stacked += m.top() + m.bottom()
            stacked += max(0, lay.spacing()) * max(0, lay.count() - 1)
            h = max(h, stacked)
        w.setMinimumHeight(h)
        w.setFixedHeight(h)


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
        self._fetch = GameFetchWorker(self)
        self._fetch.bundle.connect(self._apply_bundle)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.setInterval(3000)

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

        # ── Win probability bar ──────────────────────
        self._winprob = WinProbBar()

        # ── Active bets panel ────────────────────────
        self._legs_panel = ActiveBetsPanel()

        # ── Stats label row ───────────────────────────
        stats_lbl_bar = QWidget()
        stats_lbl_bar.setStyleSheet(f"background:{BG};")
        stats_lbl_bar.setFixedHeight(28)
        stats_lbl_lay = QHBoxLayout(stats_lbl_bar)
        stats_lbl_lay.setContentsMargins(12, 4, 12, 0)
        slbl = QLabel("PLAYER STATS")
        slbl.setFont(bb(10))
        slbl.setStyleSheet(f"color:{TEXT_DIM}; letter-spacing:3px; background:transparent;")
        stats_lbl_lay.addWidget(slbl)
        stats_lbl_lay.addStretch()

        # ── Stat boxes row (away LEFT | home RIGHT) ──
        sb_container = QWidget()
        sb_container.setStyleSheet(f"background:{BG};")
        sb_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        sb_lay = QHBoxLayout(sb_container)
        sb_lay.setContentsMargins(8, 0, 8, 8)
        sb_lay.setSpacing(8)
        sb_lay.setAlignment(Qt.AlignTop)

        self._away_stats = StatBox("away")
        self._home_stats = StatBox("home")
        sb_lay.addWidget(self._away_stats, 1)
        sb_lay.addWidget(self._home_stats, 1)

        body = QWidget()
        body.setStyleSheet(f"background:{BG};")
        body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)
        body_lay.setAlignment(Qt.AlignTop)
        body_lay.addWidget(self._boxscore, 0, Qt.AlignTop)
        body_lay.addWidget(self._winprob, 0, Qt.AlignTop)
        body_lay.addWidget(self._legs_panel, 0, Qt.AlignTop)
        body_lay.addWidget(stats_lbl_bar, 0, Qt.AlignTop)
        body_lay.addWidget(sb_container, 0, Qt.AlignTop)

        scroll = _FitWidthScroll()
        scroll.setWidget(body)
        scroll.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea{{border:none;background:{BG};}}")
        scroll.viewport().setStyleSheet(f"background:{BG};")
        self._body = body
        self._gt_scroll = scroll
        outer.addWidget(scroll, 1)

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
        self._fetch.fetch(game, self._week)
        if not self._timer.isActive():
            self._timer.start()

    def _apply_bundle(self, data):
        if not data:
            pending = self._fetch.take_pending()
            if pending:
                self._fetch.fetch(*pending)
            return
        game = data.get("game") or self._current
        if not game:
            return
        self._current = game
        summary = data.get("summary")
        self._summary = summary
        fresh = data.get("games")
        if fresh:
            self._games = fresh
        plays = data.get("plays") or []
        if plays:
            self._last_seq = plays[0].get("seq", -1)
        try:
            self._score_hdr.refresh(game, summary)
            self._boxscore.refresh(game, data.get("away_ls"), data.get("home_ls"))
            self._winprob.refresh(game, summary)
            self._legs_panel.set_game(str(game["id"]), self._games)
            self._legs_panel.refresh(
                game, summary, data.get("away_ls"), data.get("home_ls"))
            self._load_stat_boxes(game, summary)
            bet_players = self._get_bet_players(game["id"])
            self.game_updated.emit(
                game, summary, plays, data.get("away_ls"), data.get("home_ls"), bet_players)
        except Exception:
            traceback.print_exc()
        pending = self._fetch.take_pending()
        if pending:
            self._fetch.fetch(*pending)

    def _poll(self):
        if not self._current:
            return
        self._fetch.fetch(self._current, self._week)

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
        if getattr(self, "_body", None):
            self._body.updateGeometry()
            self._body.adjustSize()
        if getattr(self, "_gt_scroll", None):
            self._gt_scroll._fit_body()

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
            left.setMinimumHeight(h)
            right.setMinimumHeight(h)
            left.setFixedHeight(h)
            right.setFixedHeight(h)
        for box in (self._away_stats, self._home_stats):
            bh = sum(
                max(39, int(s.height() or getattr(s, "_content_h", 39) or 39))
                for s in (box._pass_sec, box._rush_sec, box._recv_sec)
            )
            box.setMinimumHeight(bh)
            box.updateGeometry()

    def _get_bet_players(self, game_id):
        """Return list of tracked player names for the current game."""
        conn = None
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
            return [row[0] for row in c.fetchall()]
        except Exception:
            return []
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass


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
        self._fill_players(g)

    def _on_team(self, idx):
        gi = self._gc.currentIndex()
        g = self._games[gi] if 0 <= gi < len(self._games) else None
        self._fill_players(g)

    def _fill_players(self, game):
        saved = self._pc.currentText()
        self._pc.blockSignals(True)
        self._pc.clear()
        self._pc.addItem("N/A")
        if game:
            away, home = roster_by_side(game)
            for p in away:
                self._pc.addItem(p["name"], game["away"]["abbr"])
            if away and home:
                self._pc.insertSeparator(self._pc.count())
            for p in home:
                self._pc.addItem(p["name"], game["home"]["abbr"])
        if saved:
            i = self._pc.findText(saved)
            if i >= 0:
                self._pc.setCurrentIndex(i)
        self._pc.blockSignals(False)

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
class _CenterCombo(QComboBox):
    """Closed text centered. Popup is a fixed scrollable list inside the window.
    Typing matches the full string (contains), not only the last letter."""

    _POP_W = 200
    _POP_H = 184
    _POP_ITEMS = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(False)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(self._POP_ITEMS)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        v = self.view()
        v.setTextElideMode(Qt.ElideNone)
        v.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        v.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        v.installEventFilter(self)
        self._typed = ""

    def _clear_filter(self):
        self._typed = ""
        v = self.view()
        for i in range(self.count()):
            v.setRowHidden(i, False)

    def _apply_filter(self):
        q = self._typed.lower()
        v = self.view()
        first = -1
        for i in range(self.count()):
            text = self.itemText(i) or ""
            hide = bool(q) and q not in text.lower()
            v.setRowHidden(i, hide)
            if not hide and first < 0 and text:
                first = i
        if first >= 0:
            self.setCurrentIndex(first)
            idx = self.model().index(first, 0)
            v.setCurrentIndex(idx)
            v.scrollTo(idx)

    def _handle_search_key(self, event):
        key = event.key()
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
                   Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Return, Qt.Key_Enter,
                   Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown):
            return False
        if key == Qt.Key_Escape:
            self._clear_filter()
            self.hidePopup()
            return True
        if key == Qt.Key_Backspace:
            if self._typed:
                self._typed = self._typed[:-1]
                if not self.view().isVisible():
                    self.showPopup()
                self._apply_filter()
            return True
        ch = event.text()
        if ch and ch.isprintable() and not event.modifiers() & (
                Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            self._typed += ch
            if not self.view().isVisible():
                self.showPopup()
            self._apply_filter()
            return True
        return False

    def eventFilter(self, obj, ev):
        if obj is self.view() and ev.type() == QEvent.KeyPress:
            if self._handle_search_key(ev):
                return True
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, event):
        if self._handle_search_key(event):
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        text = opt.currentText
        opt.currentText = ""
        opt.elideMode = Qt.ElideNone
        self.style().drawComplexControl(QStyle.CC_ComboBox, opt, painter, self)
        rect = self.rect().adjusted(6, 0, -18, 0)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignCenter | Qt.TextSingleLine, text)

    def showPopup(self):
        super().showPopup()
        QTimer.singleShot(0, self._place_popup)

    def _place_popup(self):
        if not self.view().isVisible():
            return
        popup = self.view().window()
        if popup is None or popup is self.window():
            return
        popup.resize(self._POP_W, self._POP_H)
        origin = self.mapToGlobal(QPoint(0, self.height()))
        win = self.window()
        wg = QRect(win.mapToGlobal(QPoint(0, 0)), win.size())
        x = origin.x()
        y = origin.y()
        if x + self._POP_W > wg.right():
            x = wg.right() - self._POP_W
        if x < wg.left():
            x = wg.left()
        if y + self._POP_H > wg.bottom():
            y = origin.y() - self.height() - self._POP_H
        if y < wg.top():
            y = wg.top()
        popup.move(x, y)

    def hidePopup(self):
        super().hidePopup()
        self._clear_filter()


class BetEntryTab(QWidget):
    submitted = Signal()

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background:{BG};")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._games = []
        self._parlay_id = None
        self._rows = []  # list of {gc,tc,pc,oc,li,mc,oi,lid}
        self._loading = False
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 8, 20, 12)
        outer.setSpacing(0)

        fs = 10
        fnt = bb(fs)
        row_gap = 8

        def fl(t):
            lab = QLabel(t)
            lab.setFont(bb(fs))
            lab.setStyleSheet("color:#ffffff; background:transparent;")
            lab.setTextFormat(Qt.PlainText)
            lab.setWordWrap(False)
            return lab

        labels = [
            "PARLAY ID:", "BOOK", "STAKE", "BOOST %",
            "LEGS", "PARLAY ODDS", "BOOSTED ODDS", "TO WIN", "PAYOUT",
        ]
        lab_w = max(text_px(fnt, t) for t in labels) + 8
        pid_w = text_px(fnt, "P10") + 36
        book_w = text_px(fnt, "POLYMARKET") + 36
        stake_w = text_px(fnt, "000.00") + 20
        pid_block_w = lab_w + 8 + pid_w

        head = QWidget()
        head.setStyleSheet("background:transparent;")
        head.setFixedWidth(pid_block_w)
        hvl = QVBoxLayout(head)
        hvl.setContentsMargins(0, 0, 0, 0)
        hvl.setSpacing(3)
        ht = QLabel("BET INFO")
        ht.setFont(bb(fs))
        ht.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        ht.setStyleSheet("color:#ffffff; letter-spacing:3px; background:transparent;")
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet(f"color:{BORDER}; background:{BORDER}; border:none;")
        hvl.addWidget(ht)
        hvl.addWidget(line)

        self._pcb = _CenterCombo()
        self._pcb.setFont(bb(fs))
        self._pcb.setStyleSheet(combo_ss(center=True))
        self._pcb.setFixedWidth(pid_w)
        self._pcb.view().setMinimumWidth(pid_w)
        for i in range(1, 11):
            self._pcb.addItem(f"P{i}")
        self._pcb.currentIndexChanged.connect(self._on_slot)

        self._bk = _CenterCombo()
        self._bk.setFont(bb(fs))
        self._bk.setStyleSheet(combo_ss(center=True))
        self._bk.addItems(BOOKS)
        self._bk.setFixedWidth(book_w)
        self._bk.view().setMinimumWidth(book_w)

        self._sk = QLineEdit("50.00")
        self._sk.setFont(bb(fs))
        self._sk.setStyleSheet(input_ss())
        self._sk.setAlignment(Qt.AlignCenter)
        self._sk.setFixedWidth(stake_w)
        self._sk.textChanged.connect(self._recalc)

        self._bo = QLineEdit("0")
        self._bo.setFont(bb(fs))
        self._bo.setStyleSheet(input_ss())
        self._bo.setAlignment(Qt.AlignCenter)
        self._bo.setFixedWidth(stake_w)
        self._bo.textChanged.connect(self._recalc)

        fields = QWidget()
        fields.setStyleSheet("background:transparent;")
        fields.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        fg = QGridLayout(fields)
        fg.setContentsMargins(0, 0, 0, 0)
        fg.setHorizontalSpacing(8)
        fg.setVerticalSpacing(row_gap)
        stack = [
            ("PARLAY ID:", self._pcb),
            ("BOOK", self._bk),
            ("STAKE", self._sk),
            ("BOOST %", self._bo),
        ]
        for ri, (name, w) in enumerate(stack):
            lab = fl(name)
            lab.setMinimumWidth(lab_w)
            fg.addWidget(lab, ri, 0, Qt.AlignVCenter | Qt.AlignLeft)
            fg.addWidget(w, ri, 1, Qt.AlignVCenter | Qt.AlignLeft)

        self._cv = {}
        for i, field in enumerate(["LEGS", "PARLAY ODDS", "BOOSTED ODDS", "STAKE", "TO WIN", "PAYOUT"]):
            ri = len(stack) + i
            lab = fl(field)
            lab.setMinimumWidth(lab_w)
            v = QLabel("—")
            v.setFont(bb(fs))
            v.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            color = GREEN if field == "PAYOUT" else "#ffffff"
            v.setStyleSheet(f"color:{color}; background:transparent;")
            v.setMinimumWidth(text_px(fnt, "+$10000.00") + 8)
            fg.addWidget(lab, ri, 0, Qt.AlignVCenter | Qt.AlignLeft)
            fg.addWidget(v, ri, 1, Qt.AlignVCenter | Qt.AlignLeft)
            self._cv[field] = v

        def action_btn(text, filled=False):
            b = QPushButton(text)
            b.setFont(bb(fs))
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            b.setMinimumWidth(text_px(fnt, text) + 28)
            b.setStyleSheet(btn_ss(GREEN, "#000") if filled else ghost_ss(GREEN))
            return b

        acts = QWidget()
        acts.setStyleSheet("background:transparent;")
        alay = QHBoxLayout(acts)
        alay.setContentsMargins(0, 0, 0, 0)
        alay.setSpacing(8)
        alay.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        ab = action_btn("ADD LEG")
        ab.clicked.connect(self._add_leg)
        nb = action_btn("NEW PARLAY")
        nb.clicked.connect(self._new_parlay)
        sb = action_btn("SUBMIT PARLAY", filled=True)
        sb.clicked.connect(self._submit)
        alay.addWidget(ab)
        alay.addWidget(nb)
        alay.addWidget(sb)
        alay.addStretch(1)

        self._lt = QTableWidget(0, 8)
        self._lt.setHorizontalHeaderLabels(["GAME", "TEAM", "PLAYER", "O/U", "LINE", "MARKET", "ODDS", ""])
        self._lt.verticalHeader().setVisible(False)
        self._lt.setEditTriggers(QTableWidget.NoEditTriggers)
        self._lt.setSelectionMode(QTableWidget.NoSelection)
        self._lt.setStyleSheet(table_ss())
        self._lt.setTextElideMode(Qt.ElideNone)
        self._lt.setWordWrap(False)
        self._lt.setShowGrid(False)
        self._lt.setFrameShape(QFrame.NoFrame)
        self._lt.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._lt.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._lt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        hdr = self._lt.horizontalHeader()
        hdr.setMinimumSectionSize(72)
        hdr.setStretchLastSection(False)
        hdr.setDefaultAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        hdr.setTextElideMode(Qt.ElideNone)
        hdr.setFixedHeight(26)
        for i in range(7):
            hdr.setSectionResizeMode(i, QHeaderView.Stretch)
        hdr.setSectionResizeMode(7, QHeaderView.Fixed)
        self._lt.setColumnWidth(7, 40)
        self._sync_table_height()

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(row_gap)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.addWidget(head, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(acts, 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(fields, 1, 0, Qt.AlignTop | Qt.AlignLeft)
        grid.addWidget(self._lt, 1, 1, Qt.AlignTop)
        outer.addLayout(grid)
        outer.addStretch()
        self._load_parlay()

    def set_games(self, g):
        self._games = g or []
        for row in self._rows:
            self._refill_games(row)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress:
            chain = getattr(obj, "_leg_chain", None)
            src = getattr(obj, "_leg_combo", obj)
            if chain:
                key = ev.key()
                if key in (Qt.Key_Right, Qt.Key_Left):
                    if isinstance(src, QLineEdit):
                        pos = src.cursorPosition()
                        n = len(src.text() or "")
                        if key == Qt.Key_Right and pos < n and not src.hasSelectedText():
                            return super().eventFilter(obj, ev)
                        if key == Qt.Key_Left and pos > 0 and not src.hasSelectedText():
                            return super().eventFilter(obj, ev)
                    if isinstance(src, QComboBox):
                        src.hidePopup()
                    self._leg_focus(chain, src, 1 if key == Qt.Key_Right else -1)
                    return True
        return super().eventFilter(obj, ev)

    def _leg_focus(self, chain, obj, delta):
        try:
            i = chain.index(obj)
        except ValueError:
            return
        j = i + delta
        if 0 <= j < len(chain):
            w = chain[j]
            w.setFocus(Qt.TabFocusReason)
            if isinstance(w, QLineEdit):
                w.selectAll()

    def _cell_combo(self, items, min_chars=8):
        c = _CenterCombo()
        c.setFont(bb(8))
        c.setStyleSheet(combo_ss(center=True))
        c.setMinimumHeight(28)
        c.setMaxVisibleItems(8)
        c.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        c.setMinimumContentsLength(1)
        if items:
            c.addItems(items)
        return c

    def _cell_input(self, placeholder, text=""):
        e = QLineEdit(text)
        e.setFont(bb(8))
        e.setStyleSheet(input_ss())
        e.setMinimumHeight(28)
        e.setAlignment(Qt.AlignCenter)
        e.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        e.setPlaceholderText(placeholder)
        return e

    def _fit_popup(self, combo):
        combo.setMaxVisibleItems(8)
        combo.view().setTextElideMode(Qt.ElideNone)
        combo.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        combo.view().setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_legs_table()

    def _layout_legs_table(self):
        if not hasattr(self, "_lt"):
            return
        hdr = self._lt.horizontalHeader()
        hdr.setMinimumSectionSize(48)
        hdr.setStretchLastSection(False)
        hdr.setDefaultAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        for i in range(7):
            hdr.setSectionResizeMode(i, QHeaderView.Stretch)
        hdr.setSectionResizeMode(7, QHeaderView.Fixed)
        self._lt.setColumnWidth(7, 40)

    def _sync_table_height(self):
        hh = self._lt.horizontalHeader().height() or 26
        n = self._lt.rowCount()
        self._lt.setFixedHeight(hh + 38 * max(n, 0))
        for r in range(n):
            self._lt.setRowHeight(r, 38)
        self._layout_legs_table()

    def _set_combo(self, combo, value):
        if not value:
            return
        i = combo.findText(value)
        if i >= 0:
            combo.setCurrentIndex(i)
        else:
            combo.addItem(value)
            combo.setCurrentIndex(combo.count() - 1)

    def _on_slot(self, _idx=None):
        if self._loading:
            return
        self._persist()
        self._load_parlay()

    def _ensure_parlay(self):
        label = self._pcb.currentText()
        conn = db()
        c = conn.cursor()
        c.execute("SELECT id, book, stake, boost_pct FROM parlays WHERE parlay_label=? AND status='PENDING'",
                  (label,))
        row = c.fetchone()
        if not row:
            c.execute(
                "INSERT INTO parlays(parlay_label,book,stake,boost_pct,status) VALUES(?,?,?,?,?)",
                (label, self._bk.currentText() if hasattr(self, "_bk") else BOOKS[0],
                 50.0, 0.0, "PENDING"))
            conn.commit()
            pid = c.lastrowid
            conn.close()
            return pid, BOOKS[0], 50.0, 0.0
        conn.close()
        return row[0], row[1], row[2], row[3]

    def _clear_table(self):
        self._rows = []
        self._lt.setRowCount(0)
        self._sync_table_height()

    def _load_parlay(self, idx=None):
        self._loading = True
        self._parlay_id, book, stake, boost = self._ensure_parlay()
        if book:
            self._set_combo(self._bk, book)
        self._sk.blockSignals(True)
        self._bo.blockSignals(True)
        self._sk.setText(f"{float(stake or 0):.2f}")
        self._bo.setText(str(boost if boost is not None else 0))
        self._sk.blockSignals(False)
        self._bo.blockSignals(False)

        conn = db()
        c = conn.cursor()
        c.execute(
            "SELECT id, game_id, game_display, team, player, market, ou, line, odds "
            "FROM legs WHERE parlay_id=?",
            (self._parlay_id,))
        legs = c.fetchall()
        conn.close()

        self._clear_table()
        for leg in legs:
            self._insert_row({
                "lid": leg[0],
                "game_id": leg[1] or "",
                "game_display": leg[2] or "",
                "team": leg[3] or "N/A",
                "player": leg[4] or "N/A",
                "market": leg[5] or "ML",
                "ou": leg[6] or "N/A",
                "line": leg[7] or "",
                "odds": leg[8] or "",
            })
        self._loading = False
        self._recalc()

    def _refill_games(self, row):
        gc = row["gc"]
        prev = gc.currentText()
        gc.blockSignals(True)
        gc.clear()
        for g in self._games:
            gc.addItem(f"{g['away']['abbr']} @ {g['home']['abbr']}", g["id"])
        if prev:
            self._set_combo(gc, prev)
        gc.blockSignals(False)
        self._on_game(row, gc.currentIndex(), keep=True)

    def _on_game(self, row, idx, keep=False):
        tc, pc = row["tc"], row["pc"]
        saved_team = tc.currentText() if keep else ""
        saved_player = pc.currentText() if keep else ""
        tc.blockSignals(True)
        tc.clear()
        tc.addItem("N/A")
        g = self._games[idx] if 0 <= idx < len(self._games) else None
        if g:
            tc.addItem(g["away"]["abbr"])
            tc.addItem(g["home"]["abbr"])
        if saved_team:
            self._set_combo(tc, saved_team)
        tc.blockSignals(False)
        self._fill_players(row, g, saved_player if keep else "")

    def _fill_players(self, row, game, saved_player=""):
        pc = row["pc"]
        pc.blockSignals(True)
        pc.clear()
        pc.addItem("N/A")
        if game:
            away, home = roster_by_side(game)
            for p in away:
                pc.addItem(p["name"], game["away"]["abbr"])
            if away and home:
                pc.insertSeparator(pc.count())
            for p in home:
                pc.addItem(p["name"], game["home"]["abbr"])
        if saved_player:
            self._set_combo(pc, saved_player)
        pc.blockSignals(False)
        self._fit_popup(pc)
        self._layout_legs_table()

    def _sync_team_from_player(self, row, idx):
        abbr = row["pc"].itemData(idx)
        if abbr:
            self._set_combo(row["tc"], abbr)

    def _populate_teams(self, row, idx, keep_team=False):
        self._on_game(row, idx, keep=keep_team)

    def _populate_players(self, row, t_idx, keep_player=False, saved_player=""):
        gi = row["gc"].currentIndex()
        g = self._games[gi] if 0 <= gi < len(self._games) else None
        self._fill_players(row, g, saved_player if keep_player else "")

    def _insert_row(self, data=None):
        data = data or {}
        r = self._lt.rowCount()
        self._lt.insertRow(r)
        self._lt.setRowHeight(r, 38)

        gc = self._cell_combo([], 12)
        for g in self._games:
            gc.addItem(f"{g['away']['abbr']} @ {g['home']['abbr']}", g["id"])
        self._fit_popup(gc)
        if data.get("game_display"):
            self._set_combo(gc, data["game_display"])

        tc = self._cell_combo(["N/A"], 4)
        pc = self._cell_combo(["N/A"], 8)
        oc = self._cell_combo(["OVER", "UNDER", "N/A"], 6)
        li = self._cell_input("249.5", data.get("line", ""))
        mc = self._cell_combo(MARKETS, 8)
        self._fit_popup(mc)
        oi = self._cell_input("-115", data.get("odds", ""))

        row = {
            "gc": gc, "tc": tc, "pc": pc, "oc": oc, "li": li, "mc": mc, "oi": oi,
            "lid": data.get("lid"),
        }

        self._lt.setCellWidget(r, 0, gc)
        self._lt.setCellWidget(r, 1, tc)
        self._lt.setCellWidget(r, 2, pc)
        self._lt.setCellWidget(r, 3, oc)
        self._lt.setCellWidget(r, 4, li)
        self._lt.setCellWidget(r, 5, mc)
        self._lt.setCellWidget(r, 6, oi)

        xb = QPushButton("✕")
        xb.setFont(bb(10))
        xb.setFixedWidth(32)
        xb.setStyleSheet(
            f"QPushButton{{background:transparent;color:{RED};border:none;}}"
            f"QPushButton:hover{{color:white;}}")
        xb.clicked.connect(lambda: self._del_row(row))
        self._lt.setCellWidget(r, 7, xb)

        chain = [gc, tc, pc, oc, li, mc, oi]
        for w in chain:
            w._leg_chain = chain
            w.installEventFilter(self)
            if isinstance(w, QComboBox):
                w.view()._leg_chain = chain
                w.view()._leg_combo = w
                w.view().installEventFilter(self)

        gc.currentIndexChanged.connect(lambda i, rw=row: self._on_game(rw, i))
        pc.currentIndexChanged.connect(lambda i, rw=row: self._sync_team_from_player(rw, i))
        oi.textChanged.connect(self._recalc)
        self._on_game(row, gc.currentIndex(), keep=True)
        if data.get("team"):
            self._set_combo(tc, data["team"])
        if data.get("player"):
            self._set_combo(pc, data["player"])
        if data.get("ou"):
            self._set_combo(oc, data["ou"])
        if data.get("market"):
            self._set_combo(mc, data["market"])

        self._rows.append(row)
        self._sync_table_height()
        self._recalc()
        return row

    def _row_index(self, row):
        for i, rw in enumerate(self._rows):
            if rw is row:
                return i
        return -1

    def _del_row(self, row):
        idx = self._row_index(row)
        if idx < 0:
            return
        lid = row.get("lid")
        if lid:
            conn = db()
            conn.execute("DELETE FROM legs WHERE id=?", (lid,))
            conn.commit()
            conn.close()
        self._lt.removeRow(idx)
        self._rows.pop(idx)
        self._sync_table_height()
        self._recalc()

    def _collect_odds(self):
        odds = []
        for row in self._rows:
            raw = (row["oi"].text() or "").strip()
            if raw:
                odds.append(raw)
        return odds

    def _recalc(self, *_args):
        try:
            stake = float(self._sk.text() or 0)
        except Exception:
            stake = 0.0
        try:
            boost = float(self._bo.text() or 0)
        except Exception:
            boost = 0.0
        odds = self._collect_odds()
        res = calc_parlay(odds, stake, boost)
        self._cv["LEGS"].setText(str(len(self._rows)))
        self._cv["PARLAY ODDS"].setText(res["parlay"])
        self._cv["BOOSTED ODDS"].setText(res["boosted"])
        self._cv["STAKE"].setText(f"${stake:.2f}")
        self._cv["TO WIN"].setText(f"${res['to_win']:.2f}")
        self._cv["PAYOUT"].setText(f"${res['payout']:.2f}")

    def _snapshot_rows(self):
        out = []
        for row in self._rows:
            gi = row["gc"].currentIndex()
            gid = ""
            if 0 <= gi < len(self._games):
                gid = str(self._games[gi].get("id", ""))
            elif row["gc"].currentData():
                gid = str(row["gc"].currentData())
            out.append({
                "lid": row.get("lid"),
                "game_id": gid,
                "game_display": row["gc"].currentText(),
                "team": row["tc"].currentText(),
                "player": row["pc"].currentText(),
                "market": row["mc"].currentText(),
                "ou": row["oc"].currentText(),
                "line": row["li"].text(),
                "odds": row["oi"].text(),
            })
        return out

    def _persist(self):
        if self._loading or not self._parlay_id:
            return
        try:
            stake = float(self._sk.text() or 0)
        except Exception:
            stake = 0.0
        try:
            boost = float(self._bo.text() or 0)
        except Exception:
            boost = 0.0
        snaps = self._snapshot_rows()
        conn = db()
        conn.execute(
            "UPDATE parlays SET book=?,stake=?,boost_pct=? WHERE id=?",
            (self._bk.currentText(), stake, boost, self._parlay_id))
        conn.execute("DELETE FROM legs WHERE parlay_id=?", (self._parlay_id,))
        for s in snaps:
            cur = conn.execute(
                "INSERT INTO legs(parlay_id,game_id,game_display,team,player,"
                "market,ou,line,odds,leg_status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (self._parlay_id, s["game_id"], s["game_display"], s["team"], s["player"],
                 s["market"], s["ou"], s["line"], s["odds"], "PENDING"))
            s["lid"] = cur.lastrowid
        conn.commit()
        conn.close()
        for row, s in zip(self._rows, snaps):
            row["lid"] = s["lid"]

    def _live_labels(self):
        conn = db()
        c = conn.cursor()
        c.execute("SELECT DISTINCT parlay_label FROM parlays WHERE status='LIVE'")
        labels = {r[0] for r in c.fetchall()}
        conn.close()
        return labels

    def _next_free_label(self):
        live = self._live_labels()
        try:
            start = int(str(self._pcb.currentText()).lstrip("Pp") or 1)
        except Exception:
            start = 1
        for off in range(0, 10):
            n = (start - 1 + off) % 10 + 1
            lab = f"P{n}"
            if lab not in live:
                return lab
        return self._pcb.currentText()

    def _select_label(self, label):
        i = self._pcb.findText(label)
        if i < 0:
            return
        self._loading = True
        self._pcb.setCurrentIndex(i)
        self._loading = False

    def _new_parlay(self):
        self._persist()
        nxt = self._next_free_label()
        conn = db()
        conn.execute(
            "DELETE FROM legs WHERE parlay_id IN "
            "(SELECT id FROM parlays WHERE parlay_label=? AND status='PENDING')", (nxt,))
        conn.execute(
            "DELETE FROM parlays WHERE parlay_label=? AND status='PENDING'", (nxt,))
        conn.commit()
        conn.close()
        self._parlay_id = None
        self._select_label(nxt)
        self._sk.setText("50.00")
        self._bo.setText("0")
        self._bk.setCurrentIndex(0)
        self._clear_table()
        self._parlay_id, _, _, _ = self._ensure_parlay()
        self._recalc()

    def _add_leg(self):
        if not self._parlay_id:
            self._parlay_id, _, _, _ = self._ensure_parlay()
        self._insert_row()

    def _submit(self):
        if not self._parlay_id:
            self._parlay_id, _, _, _ = self._ensure_parlay()
        self._persist()
        if not self._rows:
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
        self._parlay_id = None
        self._clear_table()
        self._sk.setText("50.00")
        self._bo.setText("0")
        self._select_label(self._next_free_label())
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
        self._al_fp = None
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
        self._il.setSpacing(8)
        self._il.addStretch()
        scroll.setWidget(self._con)
        lay.addWidget(scroll)

    def set_games(self, games):
        self._games = games or []
        self.refresh()

    def sync_games(self, games):
        self._games = games or []

    def refresh(self):
        conn = db()
        c = conn.cursor()
        c.execute("SELECT * FROM parlays WHERE status IN ('LIVE','PENDING') ORDER BY id DESC")
        parlays = c.fetchall()
        conn.close()

        blocks = []
        any_live = False
        for par in parlays:
            if not par or len(par) < 7:
                continue
            pid = par[0]
            conn = db()
            c = conn.cursor()
            c.execute("SELECT * FROM legs WHERE parlay_id=?", (pid,))
            legs = c.fetchall()
            conn.close()
            if not legs:
                continue
            blocks.append((par, legs))
            for leg in legs:
                if len(leg) < 3:
                    continue
                gi = next((g for g in self._games if str(g["id"]) == str(leg[2])), None)
                if gi and gi.get("state") == "in":
                    any_live = True

        fp = tuple(
            (par[0], par[5],
             tuple((leg[0], str(leg[10] if len(leg) > 10 else ""),
                    str(leg[11] if len(leg) > 11 else "")) for leg in legs))
            for par, legs in blocks
        )
        if (not any_live and fp == getattr(self, "_al_fp", None)
                and self._il.count() > 1):
            return
        self._al_fp = fp

        while self._il.count() > 1:
            item = self._il.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not blocks:
            el = QLabel("NO ACTIVE LEGS")
            el.setFont(bb(13))
            el.setAlignment(Qt.AlignCenter)
            el.setStyleSheet(f"color:{TEXT_DIM}; padding:40px; background:transparent;")
            self._il.insertWidget(0, el)
            return

        for par, legs in blocks:
            self._il.insertWidget(self._il.count() - 1, self._make_block(par, legs))

    def _make_block(self, par, legs):
        pid, label, book, stake, boost, status, created = par
        calc = calc_parlay([leg[9] for leg in legs if leg[9]], stake or 0, boost or 0)
        any_live = False
        for leg in legs:
            if len(leg) < 3:
                continue
            gi = next((g for g in self._games if str(g["id"]) == str(leg[2])), None)
            if gi and gi.get("state") == "in":
                any_live = True
                break
        phase = "LIVE" if any_live else "UPCOMING"

        block = QWidget()
        block.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(block)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        block.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        hdr = QWidget()
        hdr.setFixedHeight(28)
        hdr.setStyleSheet(f"background:transparent; border:none; border-bottom:1px solid {BORDER};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 0, 8, 0)
        hl.setSpacing(10)

        def hl_lbl(t, color="#ffffff"):
            l = QLabel(t)
            l.setFont(bb(10))
            l.setStyleSheet(f"color:{color}; background:transparent; letter-spacing:0px;")
            return l

        def hl_sep():
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setFixedWidth(1)
            sep.setFixedHeight(16)
            sep.setStyleSheet(f"background:{BORDER}; border:none;")
            return sep

        hl.addWidget(hl_lbl(f"{label}", TEXT))
        hl.addWidget(hl_sep())
        hl.addWidget(hl_lbl(f"{len(legs)} LEGS"))
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
        ab.setStyleSheet(ghost_ss("#ffffff"))
        ab.setFixedWidth(70)
        ab.clicked.connect(partial(self._archive, pid))
        hl.addWidget(ab)
        hl.addWidget(hl_sep())
        sb = QLabel(phase)
        sb.setFont(bb(10))
        if phase == "LIVE":
            sb.setStyleSheet(
                f"background:{GREEN}; color:#000; border-radius:3px; padding:1px 8px;")
        else:
            sb.setStyleSheet(
                f"background:transparent; color:{TEXT_DIM}; border:0.5px solid {BORDER}; "
                f"border-radius:3px; padding:1px 8px;")
        hl.addWidget(sb)
        bl.addWidget(hdr)

        tbl = QTableWidget(len(legs), 10)
        tbl.setHorizontalHeaderLabels(
            ["GAME", "TEAM", "PLAYER", "O/U", "LINE", "MARKET",
             "LIVE STAT", "QUARTER", "SCORE", "STATUS"])
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSelectionMode(QTableWidget.NoSelection)
        tbl.setStyleSheet(tracking_table_ss())
        tbl.setItemDelegate(_TeamRowDelegate(1, tbl))
        tbl.setShowGrid(False)
        tbl.setFrameShape(QFrame.NoFrame)
        tbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tbl.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setFixedHeight(22)
        tbl.setFixedHeight(22 + 26 * max(len(legs), 1) + 2)
        tbl.setContentsMargins(0, 0, 0, 0)

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
                pack = self._scache.get(str(game_id)) or {}
                if not isinstance(pack, dict):
                    pack = {"summary": pack}
                s = pack.get("summary")
                away_ls = pack.get("away_ls")
                home_ls = pack.get("home_ls")
                if team == gi["away"]["abbr"]:
                    tid = gi["away"]["id"]
                elif team == gi["home"]["abbr"]:
                    tid = gi["home"]["id"]
                else:
                    tid = ""
                v = get_live_stat(
                    s, player, market, tid, game=gi,
                    away_ls=away_ls, home_ls=home_ls, team_abbr=team or "")
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
                it.setTextAlignment(Qt.AlignCenter)
                pair = colors_for_team(team)
                if pair:
                    it.setBackground(QColor(pair[0]))
                    it.setForeground(QColor(pair[1]))
                else:
                    it.setBackground(QColor(rbg))
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
            tbl.setRowHeight(r, 26)

        bl.addWidget(tbl)
        return block

    def _archive(self, pid):
        conn = db()
        conn.execute(
            "UPDATE parlays SET status='ARCHIVED' WHERE id=? AND status IN ('LIVE','PENDING')",
            (pid,))
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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea{{border:none;background:{BG};}}")
        self._con = QWidget()
        self._con.setStyleSheet(f"background:{BG};")
        self._il = QVBoxLayout(self._con)
        self._il.setContentsMargins(0, 0, 0, 0)
        self._il.setSpacing(14)
        self._il.addStretch()
        scroll.setWidget(self._con)
        lay.addWidget(scroll)
        self.refresh()

    def refresh(self):
        while self._il.count() > 1:
            item = self._il.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        conn = db()
        c = conn.cursor()
        c.execute("SELECT * FROM parlays WHERE status='ARCHIVED' ORDER BY id DESC")
        rows = c.fetchall()
        conn.close()
        if not rows:
            el = QLabel("NO ARCHIVED PARLAYS")
            el.setFont(bb(13))
            el.setAlignment(Qt.AlignCenter)
            el.setStyleSheet(f"color:{TEXT_DIM}; padding:40px; background:transparent;")
            self._il.insertWidget(0, el)
            return
        for row in rows:
            if not row or len(row) < 7:
                continue
            pid = row[0]
            conn = db()
            c2 = conn.cursor()
            c2.execute("SELECT * FROM legs WHERE parlay_id=?", (pid,))
            legs = c2.fetchall()
            conn.close()
            self._il.insertWidget(self._il.count() - 1, self._make_block(row, legs))

    def _make_block(self, par, legs):
        pid, label, book, stake, boost, status, created = par[:7]
        calc = calc_parlay([leg[9] for leg in legs if len(leg) > 9 and leg[9]], stake or 0, boost or 0)
        block = QWidget()
        block.setStyleSheet("background:transparent;")
        bl = QVBoxLayout(block)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        block.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        hdr = QWidget()
        hdr.setFixedHeight(28)
        hdr.setStyleSheet(f"background:transparent; border:none; border-bottom:1px solid {BORDER};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 0, 8, 0)
        hl.setSpacing(10)

        def hl_lbl(t, color="#ffffff"):
            l = QLabel(t)
            l.setFont(bb(10))
            l.setStyleSheet(f"color:{color}; background:transparent;")
            return l

        def hl_sep():
            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setFixedWidth(1)
            sep.setFixedHeight(16)
            sep.setStyleSheet(f"background:{BORDER}; border:none;")
            return sep

        hl.addWidget(hl_lbl(label or "—", TEXT))
        hl.addWidget(hl_sep())
        hl.addWidget(hl_lbl(f"{len(legs)} LEGS"))
        hl.addWidget(hl_sep())
        hl.addWidget(hl_lbl(book or "—"))
        hl.addWidget(hl_sep())
        hl.addWidget(hl_lbl(calc["parlay"], TEXT))
        hl.addWidget(hl_sep())
        hl.addWidget(hl_lbl(f"{int(boost or 0)}%"))
        hl.addWidget(hl_sep())
        hl.addWidget(hl_lbl(f"${stake:.0f}" if stake else "—", TEXT))
        hl.addWidget(hl_sep())
        hl.addWidget(hl_lbl(f"${calc['payout']:.2f}", GREEN))
        hl.addStretch()
        hl.addWidget(hl_lbl(created[:10] if created else "—"))
        bl.addWidget(hdr)

        cols = ["GAME", "TEAM", "PLAYER", "O/U", "LINE", "MARKET", "ODDS", "STATUS"]
        tbl = QTableWidget(max(len(legs), 0), len(cols))
        tbl.setHorizontalHeaderLabels(cols)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.setSelectionMode(QTableWidget.NoSelection)
        tbl.setStyleSheet(tracking_table_ss())
        tbl.setItemDelegate(_TeamRowDelegate(1, tbl))
        tbl.setShowGrid(False)
        tbl.setFrameShape(QFrame.NoFrame)
        tbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tbl.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setFixedHeight(22)
        if not legs:
            tbl.setRowCount(1)
            it = QTableWidgetItem("NO LEGS")
            it.setFont(bb(11))
            it.setForeground(QColor(TEXT_DIM))
            it.setTextAlignment(Qt.AlignCenter)
            tbl.setItem(0, 0, it)
            tbl.setSpan(0, 0, 1, len(cols))
            tbl.setFixedHeight(60)
        else:
            tbl.setFixedHeight(22 + 26 * len(legs) + 2)
            for r, leg in enumerate(legs):
                vals = [
                    leg[3] if len(leg) > 3 else "—",
                    leg[4] if len(leg) > 4 else "—",
                    leg[5] if len(leg) > 5 else "—",
                    leg[7] if len(leg) > 7 else "—",
                    leg[8] if len(leg) > 8 else "—",
                    leg[6] if len(leg) > 6 else "—",
                    leg[9] if len(leg) > 9 else "—",
                    (leg[11] if len(leg) > 11 else "—") or "—",
                ]
                for ci, val in enumerate(vals):
                    it = QTableWidgetItem(str(val or "—"))
                    it.setFont(bb(11))
                    it.setTextAlignment(Qt.AlignCenter)
                    tbl.setItem(r, ci, it)
                tbl.setRowHeight(r, 26)
        bl.addWidget(tbl)
        return block


# ─────────────────────────────────────────────
# MAIN WINDOW
# ─────────────────────────────────────────────
class HeraWindow(QMainWindow):
    def __init__(self, games, week_num=None):
        super().__init__()
        self.setWindowTitle(f"HERA v{VERSION}")
        self.resize(1280, 820)
        self.setMinimumSize(640, 480)
        force_charcoal(self, CHARCOAL)

        central = QWidget()
        force_charcoal(central, CHARCOAL)
        self.setCentralWidget(central)
        ml = QVBoxLayout(central)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        self._nav = NavBar()
        self._nav.tab_changed.connect(self._switch)
        self._nav.reset_bankroll.connect(self._reset_bankroll)
        self._nav.empty_archive.connect(self._empty_archive)
        ml.addWidget(self._nav)

        self._stack = QStackedWidget()
        force_charcoal(self._stack, BG)

        self._gt = GameTrackerTab()
        self._pbp_tab = PlayByPlayTab()
        self._be = BetEntryTab()
        self._al = ActiveLegsTab()
        self._ar = ArchiveTab()

        self._gt.game_updated.connect(self._pbp_tab.sync)
        self._gt.game_updated.connect(self._on_tracker_update)
        self._be.submitted.connect(self._ar.refresh)
        self._be.submitted.connect(self._gt._legs_panel.refresh)
        self._be.submitted.connect(self._al.refresh)

        force_charcoal(self._gt, BG)
        self._stack.addWidget(self._gt)
        for tab in [self._pbp_tab, self._be, self._al, self._ar]:
            force_charcoal(tab, BG)
            sc = QScrollArea()
            sc.setWidget(tab)
            sc.setWidgetResizable(True)
            sc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            sc.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            sc.setStyleSheet(f"QScrollArea{{border:none;background-color:{BG};}}")
            force_charcoal(sc, BG)
            force_charcoal(sc.viewport(), BG)
            self._stack.addWidget(sc)

        ml.addWidget(self._stack)

        self._gt.set_games(games, week_num=week_num)
        self._be.set_games(games)
        self._al.set_games(games)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(CHARCOAL))
        p.end()
        super().paintEvent(event)

    def _on_tracker_update(self, game, summary, plays, away_ls, home_ls, bet_players):
        if game:
            self._al._scache[str(game["id"])] = {
                "summary": summary,
                "away_ls": away_ls,
                "home_ls": home_ls,
            }
        self._al.sync_games(self._gt._games)

    def _switch(self, idx):
        self._stack.setCurrentIndex(idx)
        if idx == 3:
            self._al.refresh()
        elif idx == 4:
            self._ar.refresh()
            self._nav.refresh_bankroll()

    def _reset_bankroll(self):
        save_archive_bankroll_baseline(raw_archive_totals())
        self._nav.refresh_bankroll()

    def _empty_archive(self):
        empty_archive()
        self._ar.refresh()
        self._nav.refresh_bankroll()


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
def main():
    print(f"HERA v{VERSION} starting...")
    def _hook(et, ev, tb):
        err = "".join(traceback.format_exception(et, ev, tb))
        print("FATAL ERROR:\n", err)
        write_crash(err)
        sys.__excepthook__(et, ev, tb)
    sys.excepthook = _hook
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
        pal.setColor(QPalette.Window, QColor(CHARCOAL))
        pal.setColor(QPalette.WindowText, QColor(TEXT))
        pal.setColor(QPalette.Base, QColor(CARD))
        pal.setColor(QPalette.AlternateBase, QColor(HDR_BG))
        pal.setColor(QPalette.Text, QColor(TEXT))
        pal.setColor(QPalette.ButtonText, QColor(TEXT))
        pal.setColor(QPalette.Button, QColor(CARD))
        pal.setColor(QPalette.Highlight, QColor(GREEN_DIM))
        pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        pal.setColor(QPalette.Light, QColor(CHARCOAL))
        pal.setColor(QPalette.Mid, QColor(CHARCOAL))
        pal.setColor(QPalette.Dark, QColor(CHARCOAL))
        for grp in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            pal.setColor(grp, QPalette.Window, QColor(CHARCOAL))
            pal.setColor(grp, QPalette.WindowText, QColor(TEXT))
            pal.setColor(grp, QPalette.Base, QColor(CARD))
            pal.setColor(grp, QPalette.Button, QColor(CARD))
        app.setPalette(pal)
        load_font()
        # Do not app.setFont / "* { font-family }" — Windows then paints the
        # main window white after splash. Widgets already call bb() locally.
        app.setStyleSheet(
            f"QMainWindow {{ background-color:{CHARCOAL}; color:{TEXT}; border:none; }}"
            f"QStackedWidget, QScrollArea, QScrollArea > QWidget {{"
            f" background-color:{BG}; color:{TEXT}; border:none; }}"
        )

        def open_main(games, week_num):
            try:
                win = HeraWindow(games or [], week_num)
                win.show()
                win.raise_()
                win.activateWindow()
                win.repaint()
                app._win = win
            except Exception:
                err = traceback.format_exc()
                print("FATAL ERROR:\n", err)
                write_crash(err)
                box = QMessageBox()
                box.setWindowTitle("HERA")
                box.setText("HERA failed to open after the loading screen.")
                box.setInformativeText(f"Wrote {CRASH_LOG}")
                box.setDetailedText(err)
                box.exec()

        splash = LoadingScreen()
        splash.ready.connect(open_main)
        splash.start()
        app._splash = splash
        sys.exit(app.exec())

    except Exception:
        print("FATAL ERROR:")
        traceback.print_exc()
        write_crash(traceback.format_exc())
        try:
            input("Press Enter to close...")
        except Exception:
            pass


if __name__ == "__main__":
    main()