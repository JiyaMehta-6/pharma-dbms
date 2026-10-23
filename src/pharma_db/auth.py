"""Local authentication: PBKDF2 password hashing, roles and the audit log.

Password storage follows the standard salted-PBKDF2 pattern (no external
dependencies): a per-user random salt, 200k SHA-256 iterations, constant-time
comparison on verify. Roles gate destructive actions in the GUI.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass

from .db import Database
from .models import ValidationError

ITERATIONS = 200_000
_ROLES = ("admin", "editor", "viewer")


class AuthError(RuntimeError):
    """Raised when authentication or user management fails."""


@dataclass(slots=True)
class User:
    id: int
    username: str
    role: str

    @property
    def can_edit(self) -> bool:
        return self.role in ("admin", "editor")

    @property
    def can_admin(self) -> bool:
        return self.role == "admin"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return ``(password_hash, salt)`` for ``password``."""
    if not password:
        raise ValidationError("Password cannot be empty.")
    use_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), use_salt.encode("ascii"), ITERATIONS
    )
    return digest.hex(), use_salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


class AuthService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def ensure_schema(self) -> None:
        """Create the users/audit tables on databases predating migration 2."""
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS users ("
            " user_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " username TEXT NOT NULL UNIQUE,"
            " password_hash TEXT NOT NULL,"
            " salt TEXT NOT NULL,"
            " role TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),"
            " created_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ");"
            "CREATE TABLE IF NOT EXISTS audit_log ("
            " audit_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " user_id INTEGER REFERENCES users(user_id),"
            " action TEXT NOT NULL,"
            " entity TEXT NOT NULL,"
            " entity_id INTEGER,"
            " detail TEXT,"
            " created_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ");"
            "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);"
        )

    def user_count(self) -> int:
        self.ensure_schema()
        return int(self.db.scalar("SELECT COUNT(*) FROM users") or 0)

    def create_user(self, username: str, password: str, role: str = "viewer") -> int:
        self.ensure_schema()
        name = username.strip()
        if not name:
            raise ValidationError("Username is required.")
        if role not in _ROLES:
            raise ValidationError(f"Role must be one of {', '.join(_ROLES)}.")
        password_hash, salt = hash_password(password)
        try:
            with self.db.transaction() as con:
                cur = con.execute(
                    "INSERT INTO users (username, password_hash, salt, role) "
                    "VALUES (?, ?, ?, ?)",
                    (name, password_hash, salt, role),
                )
                return int(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise AuthError(f"A user named '{name}' already exists.") from exc

    def authenticate(self, username: str, password: str) -> User:
        self.ensure_schema()
        row = self.db.query_one(
            "SELECT user_id, username, password_hash, salt, role FROM users "
            "WHERE username = ?",
            (username.strip(),),
        )
        if row is None or not verify_password(password, row["password_hash"], row["salt"]):
            raise AuthError("Invalid username or password.")
        return User(id=int(row["user_id"]), username=row["username"], role=row["role"])

    def list_users(self) -> list[tuple[int, str, str]]:
        self.ensure_schema()
        rows = self.db.query(
            "SELECT user_id, username, role FROM users ORDER BY username"
        )
        return [(int(r["user_id"]), r["username"], r["role"]) for r in rows]

    def record_audit(
        self,
        user: User | None,
        action: str,
        entity: str,
        entity_id: int | None = None,
        detail: str = "",
    ) -> None:
        self.ensure_schema()
        self.db.execute(
            "INSERT INTO audit_log (user_id, action, entity, entity_id, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (user.id if user else None, action, entity, entity_id, detail),
        )

    def recent_audit(self, limit: int = 50) -> list[dict[str, object]]:
        self.ensure_schema()
        rows = self.db.query(
            "SELECT a.audit_id, a.action, a.entity, a.entity_id, a.detail,"
            "       a.created_at, COALESCE(u.username, '(system)') AS username "
            "FROM audit_log a LEFT JOIN users u ON u.user_id = a.user_id "
            "ORDER BY a.audit_id DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]
