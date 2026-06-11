"""Persistence: a SQLite log of sightings plus saved frame images.

Each identified species produces one row. The best frame from the event is saved
to the captures/ directory and referenced by every species row from that event.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from config import CAPTURES_DIR, DB_PATH, settings
from identifier import BirdAnalysis

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sightings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    source          TEXT NOT NULL,
    image_path      TEXT,
    common_name     TEXT NOT NULL,
    scientific_name TEXT,
    confidence      REAL NOT NULL,
    count           INTEGER NOT NULL,
    field_marks     TEXT,
    summary         TEXT
);
CREATE INDEX IF NOT EXISTS idx_sightings_time ON sightings(timestamp);
CREATE INDEX IF NOT EXISTS idx_sightings_species ON sightings(common_name);
"""


def _connect() -> sqlite3.Connection:
    settings.ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def save_frame(jpeg_bytes: bytes, event_id: str) -> Path:
    """Write a representative frame to captures/ and return its path."""
    settings.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitize the label into something safe for a filename on any OS.
    label = re.sub(r"[^A-Za-z0-9._-]", "_", event_id)[:24] or "event"
    path = CAPTURES_DIR / f"{stamp}_{label}.jpg"
    path.write_bytes(jpeg_bytes)
    return path


def record_sighting(
    analysis: BirdAnalysis,
    source: str,
    image_path: Path | None,
    min_confidence: float,
) -> list[str]:
    """Persist confident species rows. Returns the species names actually saved."""
    init_db()
    event_id = uuid.uuid4().hex
    now = datetime.now().isoformat(timespec="seconds")
    img = str(image_path) if image_path else None

    saved: list[str] = []
    with _connect() as conn:
        for sp in analysis.species:
            if sp.confidence < min_confidence:
                continue
            conn.execute(
                """INSERT INTO sightings
                   (event_id, timestamp, source, image_path, common_name,
                    scientific_name, confidence, count, field_marks, summary)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id, now, source, img, sp.common_name,
                    sp.scientific_name, sp.confidence, sp.count,
                    sp.field_marks, analysis.summary,
                ),
            )
            saved.append(sp.common_name)
    return saved


def known_species() -> set[str]:
    """All species names seen so far (used for 'new species' notifications)."""
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT DISTINCT common_name FROM sightings").fetchall()
    return {r["common_name"] for r in rows}


def recent_sightings(limit: int = 100) -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sightings ORDER BY timestamp DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def species_tally() -> list[dict]:
    """Species counts, most-seen first."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """SELECT common_name, scientific_name,
                      COUNT(*) AS sightings,
                      MAX(timestamp) AS last_seen,
                      MAX(confidence) AS best_confidence
               FROM sightings
               GROUP BY common_name
               ORDER BY sightings DESC, last_seen DESC"""
        ).fetchall()
    return [dict(r) for r in rows]
