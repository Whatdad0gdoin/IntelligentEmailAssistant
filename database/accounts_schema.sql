-- MailKit (FIT3164, Group DS-25): database dump, schema only.
--
-- The app's one database is the SQLite file backend/secrets/accounts.db, created
-- on first use by backend/accounts.py. It holds accounts made on the sign-up page
-- (email and a one-way password hash) and each user's Gmail connection (the
-- address and an encrypted OAuth token). No email content is ever stored (NFR-03).
--
-- This dump has the tables and no rows, deliberately: the rows are credentials.
-- To recreate an empty database:
--     sqlite3 backend/secrets/accounts.db < database/accounts_schema.sql
-- or simply run the app: backend/accounts.py creates the file and tables itself.
--
-- Generated from backend/accounts.py (_SCHEMA) with sqlite3's iterdump().

BEGIN TRANSACTION;
CREATE TABLE gmail_connections (
    email        TEXT PRIMARY KEY,
    address      TEXT NOT NULL,
    token        BLOB NOT NULL,
    connected_at TEXT NOT NULL
);
CREATE TABLE users (
    email         TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
COMMIT;
