"""Authentication, password hashing, roles and permission enforcement.

Passwords use PBKDF2-HMAC-SHA256 with a per-user random salt (stdlib only, no
external crypto dependency). Format stored in users.password_hash:

    pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

An empty password_hash means "no password set" — the account can sign in without
a password until one is assigned (keeps first-run simple).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Iterable

from .database import Database

ITERATIONS = 200_000

# ---------------------------------------------------------------- permissions
PERMISSIONS = {
    "items_view": "View item master",
    "items_edit": "Create / edit items",
    "items_delete": "Delete / deactivate items",
    "stock_in": "Receive stock (GRN)",
    "stock_out": "Issue stock / delivery notes",
    "returns": "Process returns",
    "transfers": "Transfer stock",
    "adjustments": "Post stock adjustments",
    "counts": "Physical stock counts",
    "documents": "Browse documents",
    "doc_reverse": "Reverse / correct finalized documents",
    "reports": "Report center",
    "settings": "Change settings",
    "users": "Manage users",
    "backup": "Backup / restore database",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "Administrator": set(PERMISSIONS),
    "Storekeeper": {"items_view", "items_edit", "stock_in", "stock_out", "returns",
                    "transfers", "adjustments", "counts", "documents", "reports"},
    "Logistics": {"items_view", "stock_out", "returns", "transfers", "documents", "reports"},
    "Viewer": {"items_view", "documents", "reports"},
}

ROLES = list(ROLE_PERMISSIONS)


# ------------------------------------------------------------------ hashing
def hash_password(password: str) -> str:
    if not password:
        return ""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Blank stored hash = no password required."""
    if not stored:
        return True
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def has_password(db: Database, username: str) -> bool:
    r = db.one("SELECT password_hash FROM users WHERE username=?", (username,))
    return bool(r and r["password_hash"])


def any_password_set(db: Database) -> bool:
    """True when at least one active account has a password -> show login screen."""
    return bool(db.scalar(
        "SELECT COUNT(*) FROM users WHERE active=1 AND password_hash<>''"))


def set_password(db: Database, username: str, password: str) -> None:
    db.execute("UPDATE users SET password_hash=? WHERE username=?",
               (hash_password(password), username))
    db.commit()
    db.audit("EDITED", "user", username, "password changed")


# --------------------------------------------------------------------- auth
class Session:
    """Currently signed-in user + permission checks."""

    def __init__(self, db: Database):
        self.db = db
        self.username = "admin"
        self.full_name = "Administrator"
        self.role = "Administrator"
        self._perms: set[str] = set(PERMISSIONS)
        self.authenticated = False

    def login(self, username: str, password: str) -> tuple[bool, str]:
        r = self.db.one("SELECT * FROM users WHERE username=? AND active=1", (username,))
        if r is None:
            return False, "Unknown user name, or the account is inactive."
        if not verify_password(password, r["password_hash"] or ""):
            self.db.audit("LOGIN_FAILED", "user", username)
            return False, "Incorrect password."
        self.username = r["username"]
        self.full_name = r["full_name"] or r["username"]
        self.role = r["role"] or "Viewer"
        self._perms = permissions_for(r)
        self.authenticated = True
        self.db.current_user = self.username
        self.db.audit("LOGIN", "user", self.username, self.role)
        return True, "ok"

    def can(self, perm: str) -> bool:
        return perm in self._perms

    def require(self, perm: str) -> None:
        if not self.can(perm):
            raise PermissionError(
                f"Your role ({self.role}) is not allowed to perform this action.\n\n"
                f"Required permission: {PERMISSIONS.get(perm, perm)}\n"
                f"Ask an administrator to grant it in Settings → Users & Permissions.")

    def refresh(self) -> None:
        r = self.db.one("SELECT * FROM users WHERE username=?", (self.username,))
        if r:
            self.role = r["role"]
            self._perms = permissions_for(r)


def permissions_for(row) -> set[str]:
    """Explicit per-user permission list wins; otherwise the role defaults."""
    custom = (row["permissions"] or "").strip()
    if custom:
        return {p.strip() for p in custom.replace(";", ",").split(",") if p.strip()}
    return set(ROLE_PERMISSIONS.get(row["role"], ROLE_PERMISSIONS["Viewer"]))


def verify_admin(db: Database, password: str, username: str = "") -> tuple[bool, str]:
    """Confirm an administrator password — used to authorise deletions."""
    if username:
        rows = db.query("SELECT * FROM users WHERE username=? AND active=1", (username,))
    else:
        rows = db.query("SELECT * FROM users WHERE role='Administrator' AND active=1")
    if not rows:
        return False, "No active administrator account exists."
    for r in rows:
        if r["role"] != "Administrator":
            continue
        if verify_password(password, r["password_hash"] or ""):
            return True, r["username"]
    return False, "The administrator password is not correct."


def admin_password_required(db: Database) -> bool:
    """Only enforce the prompt when an admin actually has a password configured."""
    if not db.get_bool("require_admin_password_delete", True):
        return False
    return bool(db.scalar("SELECT COUNT(*) FROM users WHERE role='Administrator'"
                          " AND active=1 AND password_hash<>''"))
