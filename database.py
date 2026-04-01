"""SQLite database for incident logging and IP reputation tracking."""

import sqlite3
import datetime
import json
import threading
from pathlib import Path

DB_DIR = Path("output")
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "security.db"

_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """Return a thread-local SQLite connection, creating it if needed."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db() -> None:
    """Create the incidents and ip_reputation tables if they don't exist."""
    conn = _get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS incidents (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id      TEXT    NOT NULL UNIQUE,
            timestamp       TEXT    NOT NULL,
            source_ip       TEXT    NOT NULL,
            method          TEXT,
            url             TEXT,
            headers         TEXT,
            body            TEXT,
            confidence      REAL    NOT NULL,
            decision        TEXT    NOT NULL CHECK(decision IN ('benign', 'attack')),
            decision_source TEXT    NOT NULL CHECK(decision_source IN ('model', 'llm')),
            action_taken    TEXT    NOT NULL DEFAULT 'log_only',
            llm_reasoning   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_incidents_source_ip
            ON incidents(source_ip);

        CREATE INDEX IF NOT EXISTS idx_incidents_timestamp
            ON incidents(timestamp);

        CREATE TABLE IF NOT EXISTS ip_reputation (
            source_ip        TEXT PRIMARY KEY,
            first_seen       TEXT NOT NULL,
            last_seen        TEXT NOT NULL,
            total_requests   INTEGER NOT NULL DEFAULT 0,
            attack_count     INTEGER NOT NULL DEFAULT 0,
            grey_zone_count  INTEGER NOT NULL DEFAULT 0,
            escalation_level TEXT NOT NULL DEFAULT 'none'
                CHECK(escalation_level IN ('none', 'monitored', 'temp_ban', 'perm_ban')),
            ban_until        TEXT
        );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Incident operations
# ---------------------------------------------------------------------------

def log_incident(
    request_id: str,
    source_ip: str,
    confidence: float,
    decision: str,
    decision_source: str,
    action_taken: str = "log_only",
    method: str | None = None,
    url: str | None = None,
    headers: dict | None = None,
    body: str | None = None,
    llm_reasoning: str | None = None,
) -> dict:
    """Insert an incident record and return it as a dict."""
    conn = _get_connection()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    headers_json = json.dumps(headers) if headers else None

    conn.execute(
        """
        INSERT INTO incidents
            (request_id, timestamp, source_ip, method, url, headers, body,
             confidence, decision, decision_source, action_taken, llm_reasoning)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request_id, now, source_ip, method, url, headers_json, body,
            confidence, decision, decision_source, action_taken, llm_reasoning,
        ),
    )
    conn.commit()
    return {
        "request_id": request_id,
        "timestamp": now,
        "source_ip": source_ip,
        "confidence": confidence,
        "decision": decision,
        "action_taken": action_taken,
    }


def get_recent_incidents(source_ip: str, limit: int = 20) -> list[dict]:
    """Fetch the most recent incidents for a given IP."""
    conn = _get_connection()
    rows = conn.execute(
        """
        SELECT request_id, timestamp, confidence, decision, decision_source, action_taken
        FROM incidents
        WHERE source_ip = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (source_ip, limit),
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# IP reputation operations
# ---------------------------------------------------------------------------

def get_ip_reputation(source_ip: str) -> dict | None:
    """Return the reputation record for an IP, or None if unseen."""
    conn = _get_connection()
    row = conn.execute(
        "SELECT * FROM ip_reputation WHERE source_ip = ?",
        (source_ip,),
    ).fetchone()
    return dict(row) if row else None


def update_ip_after_request(
    source_ip: str,
    is_attack: bool,
    is_grey_zone: bool,
) -> dict:
    """Update (or create) the IP reputation record after analyzing a request.

    Returns the updated reputation dict.
    """
    conn = _get_connection()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    existing = get_ip_reputation(source_ip)

    if existing is None:
        conn.execute(
            """
            INSERT INTO ip_reputation
                (source_ip, first_seen, last_seen, total_requests,
                 attack_count, grey_zone_count, escalation_level)
            VALUES (?, ?, ?, 1, ?, ?, 'none')
            """,
            (source_ip, now, now, int(is_attack), int(is_grey_zone)),
        )
    else:
        conn.execute(
            """
            UPDATE ip_reputation
            SET last_seen       = ?,
                total_requests  = total_requests + 1,
                attack_count    = attack_count + ?,
                grey_zone_count = grey_zone_count + ?
            WHERE source_ip = ?
            """,
            (now, int(is_attack), int(is_grey_zone), source_ip),
        )

    conn.commit()
    return get_ip_reputation(source_ip)


def set_ip_ban(source_ip: str, level: str, ban_until: str | None = None) -> dict:
    """Set the escalation level and optional ban expiry for an IP.

    Args:
        source_ip: The IP address to update.
        level: One of 'none', 'monitored', 'temp_ban', 'perm_ban'.
        ban_until: ISO timestamp when a temp ban expires. None for perm or no ban.
    """
    conn = _get_connection()
    conn.execute(
        """
        UPDATE ip_reputation
        SET escalation_level = ?, ban_until = ?
        WHERE source_ip = ?
        """,
        (level, ban_until, source_ip),
    )
    conn.commit()
    return get_ip_reputation(source_ip)


def is_ip_banned(source_ip: str) -> bool:
    """Check if an IP is currently banned (temp or perm)."""
    rep = get_ip_reputation(source_ip)
    if rep is None:
        return False

    if rep["escalation_level"] == "perm_ban":
        return True

    if rep["escalation_level"] == "temp_ban" and rep["ban_until"]:
        now = datetime.datetime.now(datetime.timezone.utc)
        ban_expiry = datetime.datetime.fromisoformat(rep["ban_until"])
        if now < ban_expiry:
            return True
        # Ban expired — clear it
        set_ip_ban(source_ip, "monitored")

    return False


# ---------------------------------------------------------------------------
# Stats / export helpers (useful for research)
# ---------------------------------------------------------------------------

def get_incident_stats() -> dict:
    """Return aggregate counts for the incident table."""
    conn = _get_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(*)                                         AS total,
            SUM(CASE WHEN decision = 'attack' THEN 1 ELSE 0 END) AS attacks,
            SUM(CASE WHEN decision = 'benign' THEN 1 ELSE 0 END) AS benign,
            SUM(CASE WHEN decision_source = 'llm' THEN 1 ELSE 0 END) AS llm_decided
        FROM incidents
        """
    ).fetchone()
    return dict(row)


# Auto-initialize tables on import
init_db()
