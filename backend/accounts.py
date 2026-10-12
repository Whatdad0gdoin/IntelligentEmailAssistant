"""Accounts made on the sign-up page, and each user's Gmail connection.

Two tables in one SQLite file (ACCOUNTS_DB, in the gitignored secrets folder):

    users              email, password_hash, created_at
    gmail_connections  email, address, token, connected_at

Accounts in AUTH_USERS (backend/.env) keep working; this adds to them rather
than replacing them. Neither table holds email content (NFR-03): a password
hash and an OAuth token are credentials, not mail.

The Gmail token is encrypted before it is written. It is a live credential for
someone's mailbox, so a copy of the database file on its own must not be
enough to read that mailbox. The key is derived from JWT_SECRET, which stays in
backend/.env. Changing JWT_SECRET makes stored tokens unreadable; the app
treats that as "not connected" and the user connects again.

Reads never create the file. A deployment that never signs anyone up has no
database at all, and the test suite's fixture logins never touch one.
"""

import base64
import datetime as _dt
import functools
import os
import sqlite3
import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    email         TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gmail_connections (
    email        TEXT PRIMARY KEY,
    address      TEXT NOT NULL,
    token        BLOB NOT NULL,
    connected_at TEXT NOT NULL
);
"""


class AccountExists(Exception):
    """Sign-up for an email that already has an account."""


def _now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class AccountStore:
    """One SQLite file. A connection per operation, one writer at a time.

    sqlite3 connections cannot be shared between the threaded dev server's
    request threads, and these operations are rare and tiny, so opening one
    per call costs nothing that matters.
    """

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()

    def _open(self, create):
        if not create and not os.path.exists(self.path):
            return None
        new = not os.path.exists(self.path)
        if new:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5)
        conn.executescript(_SCHEMA)
        if new:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        return conn

    def _read(self, sql, args):
        with self._lock:
            conn = self._open(create=False)
            if conn is None:
                return None
            try:
                return conn.execute(sql, args).fetchone()
            finally:
                conn.close()

    def _write(self, sql, args):
        with self._lock:
            conn = self._open(create=True)
            try:
                with conn:
                    return conn.execute(sql, args).rowcount
            finally:
                conn.close()

    # --- users ---------------------------------------------------------------

    def password_hash(self, email):
        row = self._read("SELECT password_hash FROM users WHERE email = ?", (email,))
        return row[0] if row else None

    def create_user(self, email, password_hash):
        try:
            self._write(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (email, password_hash, _now()),
            )
        except sqlite3.IntegrityError as exc:
            raise AccountExists(email) from exc

    # --- Gmail connections -----------------------------------------------------

    def gmail_connection(self, email):
        row = self._read(
            "SELECT address, token, connected_at FROM gmail_connections WHERE email = ?",
            (email,),
        )
        if not row:
            return None
        return {"address": row[0], "token": bytes(row[1]), "connected_at": row[2]}

    def save_gmail(self, email, address, token):
        """A new connection, replacing any earlier one for this user."""
        self._write(
            "INSERT OR REPLACE INTO gmail_connections (email, address, token, connected_at) "
            "VALUES (?, ?, ?, ?)",
            (email, address, token, _now()),
        )

    def update_gmail_token(self, email, token):
        """A refreshed token for an existing connection. No row, no write:
        a refresh racing a disconnect must not bring the connection back."""
        self._write("UPDATE gmail_connections SET token = ? WHERE email = ?", (token, email))

    def delete_gmail(self, email):
        return bool(self._write("DELETE FROM gmail_connections WHERE email = ?", (email,)))


_stores = {}
_stores_lock = threading.Lock()


def get_store(config):
    """The store for this config's database file. One instance per path."""
    path = os.path.abspath(config.accounts_db)
    with _stores_lock:
        if path not in _stores:
            _stores[path] = AccountStore(path)
        return _stores[path]


# --- token encryption -----------------------------------------------------------


@functools.lru_cache(maxsize=4)
def _fernet(secret):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    # HKDF with its own label, so this key is not the JWT signing key itself
    # and cannot be confused with any other key derived from the same secret.
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"mailkit gmail token v1"
    ).derive(secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_token(config, text):
    return _fernet(config.jwt_secret).encrypt(text.encode("utf-8"))


def decrypt_token(config, blob):
    """The token's JSON, or None when it cannot be decrypted with today's key."""
    from cryptography.fernet import InvalidToken

    try:
        return _fernet(config.jwt_secret).decrypt(blob).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        return None


def connected_gmail(config, email):
    """{address, connected_at} when this user's Gmail is connected and usable.

    A token that no longer decrypts (JWT_SECRET changed) counts as not
    connected, so the user is offered Connect again instead of an error.
    """
    if not email or not getattr(config, "accounts_db", None):
        return None
    row = get_store(config).gmail_connection(email)
    if not row or decrypt_token(config, row["token"]) is None:
        return None
    return {"address": row["address"], "connected_at": row["connected_at"]}


class UserTokenStore:
    """Where GmailApiSource loads and saves one user's token: encrypted, in the
    accounts database, instead of the single token file the gmail_auth script
    writes."""

    def __init__(self, config, email):
        self._config = config
        self._email = email

    def load(self):
        row = get_store(self._config).gmail_connection(self._email)
        if not row:
            return None
        return decrypt_token(self._config, row["token"])

    def save(self, text):
        get_store(self._config).update_gmail_token(
            self._email, encrypt_token(self._config, text)
        )
