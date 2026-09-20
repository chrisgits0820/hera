import sqlite3
import os

# Create the folder if it doesn't exist
os.makedirs(r"C:\Hera\Data", exist_ok=True)

# Connect to the database and force it to build the missing tables
conn = sqlite3.connect(r"C:\Hera\Data\hera.db")
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
conn.commit()
conn.close()

print("DATABASE FIXED! You can now run your app.")