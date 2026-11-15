"""Small local SQLite store. Only synthetic demo data ships with AETHER.

Provenance values stored in ``measurements.source``:
  * ``simulated`` – synthetic seed data generated below (never real people)
  * ``manual``    – values typed in by a user through BODY / Mind Pulse
"""
import json
import math
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("AETHER_DB_PATH", Path(__file__).resolve().parents[2] / "aether.sqlite3"))
METRICS = ("heart_rate_bpm", "sleep_hours", "fatigue_1_10", "reaction_ms", "activity_minutes")

CREW_SEED = [
    ("A01", "Alex Vega", "Mission commander"),
    ("A02", "Mira Chen", "Flight engineer"),
    ("A03", "Sam Okafor", "Medical officer"),
    ("A04", "Noor Patel", "Mission specialist"),
]
# (astronaut, phase shift) – shared with the TypeScript demo adapter (seed.ts)
SEED_SHIFTS = (("A01", 0), ("A02", -2), ("A03", 1), ("A04", -1))
SEED_DAYS = 67


def seed_row(person: str, shift: int, day: int) -> tuple:
    """Deterministic synthetic measurement. A01 accumulates strain after day 56."""
    cyclic = math.sin(day * 0.29 + shift) * 1.9
    strain = max(0, day - 56) if person == "A01" else 0
    return (
        person, day,
        round(66 + shift + cyclic + strain * 1.15, 1),
        round(max(3.2, 7.6 + math.sin(day * .21) * .25 - strain * .19), 2),
        round(min(10, max(1, 2.6 + math.sin(day * .33) * .4 + strain * .37)), 1),
        round(242 + shift * 4 + math.sin(day * .25) * 9 + strain * 10, 1),
        round(55 + math.cos(day * .36) * 9 - strain * 1.2, 1),
        "simulated",
    )


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=FULL")
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS astronauts (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS measurements (
          astronaut_id TEXT NOT NULL, day INTEGER NOT NULL,
          heart_rate_bpm REAL, sleep_hours REAL, fatigue_1_10 REAL,
          reaction_ms REAL, activity_minutes REAL,
          source TEXT NOT NULL DEFAULT 'simulated',
          PRIMARY KEY (astronaut_id, day),
          FOREIGN KEY (astronaut_id) REFERENCES astronauts(id)
        );
        CREATE TABLE IF NOT EXISTS recovery_sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          astronaut_id TEXT NOT NULL,
          activity TEXT NOT NULL,
          before_mood INTEGER NOT NULL,
          after_mood INTEGER NOT NULL,
          duration_seconds INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """)
        con.execute('BEGIN IMMEDIATE')
        # v0.2 migration: optional activity metrics (JSON) for RECOVERY sessions.
        cols = {r[1] for r in con.execute("PRAGMA table_info(recovery_sessions)")}
        if "details" not in cols:
            con.execute("ALTER TABLE recovery_sessions ADD COLUMN details TEXT")
        # v0.8 integration: server-side MISSION LAB experiments (previously browser-only localStorage).
        con.execute("""CREATE TABLE IF NOT EXISTS experiments (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)""")
        if not con.execute("SELECT COUNT(*) FROM astronauts").fetchone()[0]:
            con.executemany("INSERT INTO astronauts VALUES (?, ?, ?)", CREW_SEED)
            values = [seed_row(p, s, d) for p, s in SEED_SHIFTS for d in range(1, SEED_DAYS + 1)]
            con.executemany("INSERT INTO measurements(astronaut_id,day,heart_rate_bpm,sleep_hours,fatigue_1_10,reaction_ms,activity_minutes,source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", values)
    from .migrations import migrate
    with connect() as con:
        migrate(con)


def astronauts():
    with connect() as con:
        return [dict(row) for row in con.execute("SELECT * FROM astronauts ORDER BY id")]


def timeline(astronaut_id: str, day: int = 67):
    with connect() as con:
        rows = [dict(row) for row in con.execute(
            "SELECT * FROM measurements WHERE astronaut_id=? AND day<=? ORDER BY day", (astronaut_id, day))]
    for row in rows:
        row['source_by_signal'] = json.loads(row['source_by_signal'])
    return rows


def add_measurement(astronaut_id: str, day: int, values: dict, source: str = "manual"):
    """Legacy demo projection, plus immutable events for every explicitly supplied metric.

    `source` is retained ONLY as the deprecated last-edit label; use
    source_by_signal / raw_measurements for the provenance of each value.
    """
    from .migrations import UNITS
    from .persistence.common import uid, utcnow, dumps, digest
    with connect() as con:
        con.execute('BEGIN IMMEDIATE')
        prior = con.execute('SELECT * FROM measurements WHERE astronaut_id=? AND day=?',(astronaut_id,day)).fetchone()
        origins = json.loads(prior['source_by_signal']) if prior else {}
        merged = {k: prior[k] if prior else None for k in METRICS}
        for k in METRICS:
            if k not in values: continue
            value = values[k]
            event = uid()
            meta = dumps({'legacy_day':day,'utc_unknown':True})
            con.execute("""INSERT INTO raw_measurements(id,astronaut_id,source,signal,value,unit,received_at,
              origin,quality,missing,processing_version,metadata,idempotency_key,payload_hash)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (event,astronaut_id,'legacy-entry',k,value,UNITS[k],utcnow(),source,'unverified',int(value is None),
               'legacy-1.5',meta,event,digest(dumps([value,source,meta]))))
            merged[k] = value
            origins[k] = source
        con.execute("""INSERT INTO measurements
          (astronaut_id,day,heart_rate_bpm,sleep_hours,fatigue_1_10,reaction_ms,activity_minutes,source,source_by_signal)
          VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(astronaut_id,day) DO UPDATE SET
          heart_rate_bpm=excluded.heart_rate_bpm,sleep_hours=excluded.sleep_hours,fatigue_1_10=excluded.fatigue_1_10,
          reaction_ms=excluded.reaction_ms,activity_minutes=excluded.activity_minutes,source=excluded.source,
          source_by_signal=excluded.source_by_signal""",
          (astronaut_id,day,*(merged[k] for k in METRICS),source,dumps(origins)))


def add_recovery(data: dict):
    with connect() as con:
        cur = con.execute("""INSERT INTO recovery_sessions
          (astronaut_id, activity, before_mood, after_mood, duration_seconds, details)
          VALUES (?, ?, ?, ?, ?, ?)""", (data["astronaut_id"], data["activity"],
                                         data["before_mood"], data["after_mood"], data["duration_seconds"],
                                         json.dumps(data.get("details") or {})))
        return cur.lastrowid


def recovery_history(astronaut_id: str):
    with connect() as con:
        rows = [dict(row) for row in con.execute(
            "SELECT * FROM recovery_sessions WHERE astronaut_id=? ORDER BY id DESC LIMIT 100", (astronaut_id,))]
    for row in rows:
        try:
            row["details"] = json.loads(row.get("details") or "{}")
        except ValueError:
            row["details"] = {}
    return rows


def save_experiment(exp: dict):
    with connect() as con:
        con.execute("""INSERT INTO experiments (id, name, created_at, payload) VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, payload=excluded.payload""",
                    (exp["id"], exp["name"], exp["created_at"], json.dumps(exp)))
    return exp["id"]


def list_experiments(limit: int = 100):
    with connect() as con:
        rows = con.execute("SELECT payload FROM experiments ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        try:
            out.append(json.loads(r[0]))
        except ValueError:
            continue
    return out


def delete_experiment(exp_id: str) -> bool:
    with connect() as con:
        return con.execute("DELETE FROM experiments WHERE id=?", (exp_id,)).rowcount > 0
