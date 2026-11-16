from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_PASSWORD_ROUNDS = 310_000


class AccountStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    source_filename TEXT NOT NULL,
                    record_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS datasets_owner_idx ON datasets(owner_id);
                """
            )
        os.chmod(self.path, 0o600)

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PASSWORD_ROUNDS)
        return "$".join(
            (
                "pbkdf2_sha256",
                str(_PASSWORD_ROUNDS),
                base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
                base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
            )
        )

    @staticmethod
    def _verify_password(password: str, encoded: str) -> bool:
        try:
            algorithm, rounds, salt_text, expected_text = encoded.split("$")
            if algorithm != "pbkdf2_sha256":
                return False
            salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
            expected = base64.urlsafe_b64decode(expected_text + "=" * (-len(expected_text) % 4))
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(actual, expected)

    def create_user(self, username: str, password: str) -> dict[str, str] | None:
        user_id = uuid.uuid4().hex
        password_hash = self._hash_password(password)
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                    (user_id, username, password_hash),
                )
        except sqlite3.IntegrityError:
            return None
        return {"id": user_id, "username": username}

    def authenticate(self, username: str, password: str) -> dict[str, str] | None:
        with self._connect() as connection:
            user = connection.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if user is None or not self._verify_password(password, user["password_hash"]):
            return None
        return {"id": user["id"], "username": user["username"]}

    def get_user(self, user_id: str) -> dict[str, str] | None:
        with self._connect() as connection:
            user = connection.execute(
                "SELECT id, username FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return dict(user) if user else None

    def list_datasets(self, owner_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, owner_id, name, source_filename, record_count, created_at
                FROM datasets WHERE owner_id = ? ORDER BY created_at, id
                """,
                (owner_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_dataset(self, dataset_id: str, owner_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, owner_id, name, source_filename, record_count, created_at
                FROM datasets WHERE id = ? AND owner_id = ?
                """,
                (dataset_id, owner_id),
            ).fetchone()
        return dict(row) if row else None

    def create_dataset(
        self,
        dataset_id: str,
        owner_id: str,
        name: str,
        source_filename: str,
        record_count: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO datasets (id, owner_id, name, source_filename, record_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                (dataset_id, owner_id, name, source_filename, record_count),
            )

    def rename_dataset(self, dataset_id: str, owner_id: str, name: str) -> bool:
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE datasets SET name = ? WHERE id = ? AND owner_id = ?",
                (name, dataset_id, owner_id),
            )
        return result.rowcount == 1

    def delete_dataset(self, dataset_id: str, owner_id: str) -> bool:
        with self._connect() as connection:
            result = connection.execute(
                "DELETE FROM datasets WHERE id = ? AND owner_id = ?",
                (dataset_id, owner_id),
            )
        return result.rowcount == 1
