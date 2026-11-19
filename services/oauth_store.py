"""
OAuth token store for Araaz Delights restaurant chatbot.

Provides a SQLite-backed store for Google OAuth2 tokens, completely separate
from the main PostgreSQL/mock database so it works in all deployment modes.
Tokens are keyed by session_id and the store is thread-safe.
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Resolve the path to the SQLite file: always in the project root, two levels
# up from this file (services/ -> project root).
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = str(_PROJECT_ROOT / "oauth_tokens.db")


class OAuthStore:
    """
    Thread-safe SQLite store for Google OAuth2 tokens.

    Each row represents one authenticated session and holds the access token,
    refresh token, expiry timestamp (ISO-8601), the user's Google email
    address, and audit timestamps.

    The underlying database file is created automatically on first use.
    """

    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS oauth_tokens (
            session_id    TEXT PRIMARY KEY,
            access_token  TEXT,
            refresh_token TEXT,
            token_expiry  TEXT,
            google_email  TEXT,
            created_at    TEXT,
            updated_at    TEXT
        )
    """

    def __init__(self, db_path: str = _DB_PATH) -> None:
        """
        Initialise the store and create the backing table if it does not exist.

        Args:
            db_path: Filesystem path of the SQLite database file.  Defaults to
                     ``oauth_tokens.db`` in the project root directory.
        """
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Return a new SQLite connection with row_factory set to Row."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the oauth_tokens table if it does not already exist."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(self._CREATE_TABLE_SQL)
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _now_iso() -> str:
        """Return the current UTC time as an ISO-8601 string."""
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_tokens(
        self,
        session_id: str,
        access_token: str,
        refresh_token: str,
        token_expiry_iso: str,
        google_email: str,
    ) -> None:
        """
        Persist (or replace) OAuth tokens for the given session.

        If a row for *session_id* already exists it is completely replaced;
        ``created_at`` is preserved only on insert, while ``updated_at`` is
        always refreshed.

        Args:
            session_id:       Unique identifier for the user session.
            access_token:     Google OAuth2 access token.
            refresh_token:    Google OAuth2 refresh token.
            token_expiry_iso: Expiry timestamp as an ISO-8601 string (UTC).
            google_email:     The authenticated user's Google email address.
        """
        now = self._now_iso()
        with self._lock:
            conn = self._connect()
            try:
                # Use INSERT OR REPLACE so we upsert in a single statement.
                # Preserve created_at by reading the existing value first.
                cur = conn.execute(
                    "SELECT created_at FROM oauth_tokens WHERE session_id = ?",
                    (session_id,),
                )
                row = cur.fetchone()
                created_at = row["created_at"] if row else now

                conn.execute(
                    """
                    INSERT OR REPLACE INTO oauth_tokens
                        (session_id, access_token, refresh_token, token_expiry,
                         google_email, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        access_token,
                        refresh_token,
                        token_expiry_iso,
                        google_email,
                        created_at,
                        now,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def get_tokens(self, session_id: str) -> dict | None:
        """
        Retrieve all stored token data for a session.

        Args:
            session_id: Unique identifier for the user session.

        Returns:
            A dictionary with keys ``session_id``, ``access_token``,
            ``refresh_token``, ``token_expiry``, ``google_email``,
            ``created_at``, and ``updated_at``; or ``None`` if the session
            is not found.
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT * FROM oauth_tokens WHERE session_id = ?",
                    (session_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return dict(row)
            finally:
                conn.close()

    def delete_tokens(self, session_id: str) -> None:
        """
        Remove the stored tokens for a session.

        No-op if the session does not exist.

        Args:
            session_id: Unique identifier for the user session.
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM oauth_tokens WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def has_valid_tokens(self, session_id: str) -> bool:
        """
        Check whether valid (non-expired) tokens exist for a session.

        Validity is determined by comparing the stored ``token_expiry`` value
        against the current UTC time.  A missing or unparseable expiry is
        treated as expired.

        Args:
            session_id: Unique identifier for the user session.

        Returns:
            ``True`` if tokens are present and the expiry is in the future;
            ``False`` otherwise.
        """
        tokens = self.get_tokens(session_id)
        if tokens is None:
            return False
        expiry_iso = tokens.get("token_expiry")
        if not expiry_iso:
            return False
        try:
            expiry_dt = datetime.fromisoformat(expiry_iso)
            # Ensure expiry_dt is timezone-aware for comparison.
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            return expiry_dt > datetime.now(timezone.utc)
        except (ValueError, TypeError):
            return False

    def get_google_email(self, session_id: str) -> str | None:
        """
        Return the Google email address stored for a session.

        Args:
            session_id: Unique identifier for the user session.

        Returns:
            The email string, or ``None`` if the session is not found or the
            email was not recorded.
        """
        tokens = self.get_tokens(session_id)
        if tokens is None:
            return None
        return tokens.get("google_email")


# ---------------------------------------------------------------------------
# Global singleton – import this everywhere, do not instantiate a second one.
# ---------------------------------------------------------------------------
oauth_store = OAuthStore()
