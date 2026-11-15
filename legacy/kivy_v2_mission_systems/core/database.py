import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "aether.db"

def get_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def init_db():
    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS crew (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crew_id INTEGER,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'synthetic',
            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(crew_id) REFERENCES crew(id)
        );
        CREATE TABLE IF NOT EXISTS module_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
