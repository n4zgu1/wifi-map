from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid

EARTH_RADIUS = 6378137


def default_db() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "wifi-map/survey.sqlite3"


def coarse_position(lat: float, lon: float, grid: float = 100) -> tuple[float, float]:
    """Snap to a metre grid in Web Mercator (not an anonymity guarantee)."""
    lat = max(-85, min(85, lat))
    x = EARTH_RADIUS * math.radians(lon)
    y = EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    x, y = round(x / grid) * grid, round(y / grid) * grid
    return math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2), math.degrees(x / EARTH_RADIUS)


class Store:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Set permissions before opening; never briefly create a world-readable DB.
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, started REAL NOT NULL, ended REAL, mode TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                ap_id TEXT NOT NULL, second INTEGER NOT NULL,
                lat REAL NOT NULL, lon REAL NOT NULL, accuracy REAL,
                rssi INTEGER NOT NULL, frequency INTEGER, security TEXT NOT NULL,
                PRIMARY KEY(session_id, ap_id, second)
            );
            CREATE INDEX IF NOT EXISTS observations_session ON observations(session_id);
        """)

    def start(self, mode: str) -> str:
        sid = uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO sessions VALUES (?, ?, NULL, ?)", (sid, time.time(), mode))
        return sid

    def finish(self, sid: str):
        with self.db:
            self.db.execute("UPDATE sessions SET ended=? WHERE id=?", (time.time(), sid))

    def prune(self, days: int):
        with self.db:
            self.db.execute("DELETE FROM sessions WHERE started < ?", (time.time() - days * 86400,))

    def add(self, sid: str, ap: str, when: float, fix: dict, rssi: int, frequency: int | None, security: str):
        with self.db:
            self.db.execute("""INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (sid, ap, int(when), fix["lat"], fix["lon"], fix.get("accuracy"), rssi, frequency, security))

    def sessions(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("""
            SELECT s.*, COUNT(o.ap_id) AS observations, COUNT(DISTINCT o.ap_id) AS access_points
            FROM sessions s LEFT JOIN observations o ON s.id=o.session_id
            GROUP BY s.id ORDER BY s.started DESC
        """)]

    def points(self, sid: str, limit: int = 50000) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM observations WHERE session_id=? ORDER BY second LIMIT ?", (sid, limit))]

    def close(self):
        self.db.close()


class Anonymizer:
    def __init__(self):
        self.key = secrets.token_bytes(32)

    def identify(self, bssid: str) -> str:
        if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", bssid):
            raise ValueError("Invalid BSSID")
        return hmac.new(self.key, bssid.lower().encode(), hashlib.sha256).hexdigest()[:24]


def parse_beacon(line: str) -> tuple[str, int, int | None, str] | None:
    # Only explicitly selected fields arrive from tshark. No SSID or client data.
    fields = line.rstrip("\r\n").split("\t")
    if len(fields) != 5:
        return None
    bssid, signal, frequency, rsn, privacy = fields
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", bssid):
        return None
    try:
        rssi = int(signal)
        freq = int(frequency) if frequency else None
    except ValueError:
        return None
    if not -127 <= rssi <= 0:
        return None
    security = "RSN" if rsn else ("protected-unknown" if privacy in ("1", "True") else
                                  "open" if privacy in ("0", "False") else "unknown")
    return bssid, rssi, freq, security


def geojson(points: list[dict], exact: bool = False) -> dict:
    features = []
    for p in points:
        lat, lon = (p["lat"], p["lon"]) if exact else coarse_position(p["lat"], p["lon"])
        # No timestamps, route, session identifiers or accuracy in public exports.
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                         "properties": {k: p[k] for k in ("ap_id", "rssi", "frequency", "security")}})
    return {"type": "FeatureCollection", "features": features}


def write_export(path: Path, document: dict):
    # Refuse overwriting an existing file, including a symlink.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False)
