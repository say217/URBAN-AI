import sqlite3
from typing import Optional

from .config import DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                is_verified INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS verification_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL COLLATE NOCASE,
                code_hash TEXT NOT NULL,
                purpose TEXT NOT NULL DEFAULT 'signup',
                expires_at TEXT NOT NULL,
                consumed INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_verification_codes_email
                ON verification_codes(email, purpose);
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    conn = get_connection()
    try:
        cur = conn.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,))
        return cur.fetchone()
    finally:
        conn.close()


def create_or_update_pending_user(email: str, username: str, password_hash: str) -> None:
    """
    Insert a new unverified user, or - if an unverified signup already
    exists for this email - refresh its username/password hash so someone
    who abandoned signup partway through can just try again with the same
    email. Never overwrites an already-verified account.
    """
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO users (email, username, password_hash, is_verified)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(email) DO UPDATE SET
                username = excluded.username,
                password_hash = excluded.password_hash
            WHERE users.is_verified = 0
            """,
            (email, username, password_hash),
        )
        conn.commit()
    finally:
        conn.close()


def mark_user_verified(email: str) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE users SET is_verified = 1 WHERE email = ? COLLATE NOCASE",
            (email,),
        )
        conn.commit()
    finally:
        conn.close()


def store_verification_code(email: str, code_hash: str, expires_at: str, purpose: str = "signup") -> None:
    conn = get_connection()
    try:
        # Invalidate any older, still-pending codes for this email/purpose -
        # only the most recently issued code should ever be valid.
        conn.execute(
            """
            UPDATE verification_codes SET consumed = 1
            WHERE email = ? COLLATE NOCASE AND purpose = ? AND consumed = 0
            """,
            (email, purpose),
        )
        conn.execute(
            """
            INSERT INTO verification_codes (email, code_hash, purpose, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (email, code_hash, purpose, expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def get_active_code(email: str, purpose: str = "signup") -> Optional[sqlite3.Row]:
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT * FROM verification_codes
            WHERE email = ? COLLATE NOCASE AND purpose = ? AND consumed = 0
            ORDER BY id DESC LIMIT 1
            """,
            (email, purpose),
        )
        return cur.fetchone()
    finally:
        conn.close()


def increment_code_attempts(code_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE verification_codes SET attempts = attempts + 1 WHERE id = ?", (code_id,))
        conn.commit()
    finally:
        conn.close()


def consume_code(code_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE verification_codes SET consumed = 1 WHERE id = ?", (code_id,))
        conn.commit()
    finally:
        conn.close()