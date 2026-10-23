"""Authentication: PBKDF2 hashing, user management, roles, audit log."""
from __future__ import annotations

import unittest

from tests.support import FixtureCsvTestCase

from pharma_db.auth import (
    AuthError,
    AuthService,
    hash_password,
    verify_password,
)
from pharma_db.models import ValidationError


class PasswordHashTest(unittest.TestCase):
    def test_hash_is_salted_and_deterministic(self) -> None:
        first_hash, first_salt = hash_password("hunter2")
        second_hash, second_salt = hash_password("hunter2", salt=first_salt)
        self.assertNotEqual(first_salt, second_hash)
        self.assertEqual(first_hash, second_hash)

    def test_different_passwords_different_hashes(self) -> None:
        hash_a, salt_a = hash_password("password1")
        hash_b, salt_b = hash_password("password2")
        self.assertNotEqual(hash_a, hash_b)
        self.assertNotEqual(salt_a, salt_b)

    def test_verify_accepts_correct_rejects_wrong(self) -> None:
        password_hash, salt = hash_password("s3cret")
        self.assertTrue(verify_password("s3cret", password_hash, salt))
        self.assertFalse(verify_password("wrong", password_hash, salt))

    def test_empty_password_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            hash_password("")


class AuthServiceTest(FixtureCsvTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.auth = AuthService(self.db)

    def test_create_and_authenticate(self) -> None:
        user_id = self.auth.create_user("alice", "pw123456", role="admin")
        self.assertGreater(user_id, 0)
        user = self.auth.authenticate("alice", "pw123456")
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.role, "admin")
        self.assertTrue(user.can_admin)
        self.assertTrue(user.can_edit)

    def test_duplicate_username_rejected(self) -> None:
        self.auth.create_user("bob", "pw123456", role="viewer")
        with self.assertRaises(AuthError):
            self.auth.create_user("bob", "other1234", role="editor")

    def test_bad_credentials_rejected(self) -> None:
        self.auth.create_user("carol", "pw123456", role="viewer")
        with self.assertRaises(AuthError):
            self.auth.authenticate("carol", "wrong-pass")
        with self.assertRaises(AuthError):
            self.auth.authenticate("nobody", "pw123456")

    def test_roles_gate_permissions(self) -> None:
        self.auth.create_user("viewer1", "pw123456", role="viewer")
        self.auth.create_user("editor1", "pw123456", role="editor")
        viewer = self.auth.authenticate("viewer1", "pw123456")
        editor = self.auth.authenticate("editor1", "pw123456")
        self.assertFalse(viewer.can_edit)
        self.assertFalse(viewer.can_admin)
        self.assertTrue(editor.can_edit)
        self.assertFalse(editor.can_admin)

    def test_invalid_role_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.auth.create_user("dave", "pw123456", role="superuser")

    def test_blank_username_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self.auth.create_user("   ", "pw123456")

    def test_list_users(self) -> None:
        self.auth.create_user("eve", "pw123456", role="viewer")
        self.auth.create_user("frank", "pw123456", role="admin")
        names = [username for _, username, _ in self.auth.list_users()]
        self.assertEqual(names, ["eve", "frank"])

    def test_audit_log_records_actions(self) -> None:
        self.auth.create_user("alice", "pw123456", role="admin")
        user = self.auth.authenticate("alice", "pw123456")
        self.auth.record_audit(user, "create", "medicine", 42, "Alpha Tab")
        entries = self.auth.recent_audit()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["username"], "alice")
        self.assertEqual(entry["action"], "create")
        self.assertEqual(entry["entity"], "medicine")
        self.assertEqual(entry["entity_id"], 42)
        self.assertEqual(entry["detail"], "Alpha Tab")

    def test_audit_log_allows_anonymous(self) -> None:
        self.auth.record_audit(None, "rebuild", "database")
        entries = self.auth.recent_audit()
        self.assertEqual(entries[0]["username"], "(system)")


if __name__ == "__main__":
    unittest.main()
