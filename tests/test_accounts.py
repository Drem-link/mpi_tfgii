import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app import main
from app.accounts import AccountStore


def json_request(path: str, payload: dict, user_id: str | None = None) -> Request:
    body = json.dumps(payload).encode()
    messages = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        return messages.pop(0)

    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"host", b"testserver"),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
            "app": main.app,
            "session": {"user_id": user_id} if user_id else {},
        },
        receive,
    )


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = AccountStore(Path(self.temporary.name) / "accounts.sqlite3")
        self.store.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def test_passwords_are_hashed_and_username_is_case_insensitive(self):
        user = self.store.create_user("geologist", "a-very-long-password")

        self.assertIsNotNone(user)
        self.assertIsNotNone(self.store.authenticate("GEOLOGIST", "a-very-long-password"))
        self.assertIsNone(self.store.authenticate("geologist", "wrong-password"))
        self.assertIsNone(self.store.create_user("GEOLOGIST", "another-long-password"))

    def test_registration_creates_a_persistent_session(self):
        request = json_request(
            "/api/auth/register",
            {"username": "geologist", "password": "a-very-long-password"},
        )

        with patch.object(main, "_store", self.store):
            result = asyncio.run(main.register(request))

        self.assertEqual(result["user"]["username"], "geologist")
        self.assertEqual(request.session["user_id"], result["user"]["id"])
        self.assertEqual(request.session["active_dataset_id"], "shared")

    def test_users_cannot_select_or_list_another_users_dataset(self):
        first = self.store.create_user("geologist1", "a-very-long-password")
        second = self.store.create_user("geologist2", "a-very-long-password")
        dataset_id = "a" * 32
        self.store.create_dataset(dataset_id, first["id"], "Private", "private.zip", 1)
        request = json_request(
            f"/api/datasets/{dataset_id}/select",
            {},
            user_id=second["id"],
        )

        with patch.object(main, "_store", self.store):
            with self.assertRaises(HTTPException) as error:
                main.select_dataset(dataset_id, request)
            self.assertEqual(error.exception.status_code, 404)
            self.assertEqual(self.store.list_datasets(second["id"]), [])
            with self.assertRaises(HTTPException) as error:
                asyncio.run(
                    main.rename_dataset(
                        dataset_id,
                        json_request(
                            f"/api/datasets/{dataset_id}",
                            {"name": "Stolen"},
                            user_id=second["id"],
                        ),
                    )
                )
            self.assertEqual(error.exception.status_code, 404)
            self.assertEqual(self.store.list_datasets(first["id"])[0]["name"], "Private")

    def test_mutations_reject_a_cross_origin_request(self):
        request = json_request("/api/auth/logout", {})
        request.scope["headers"].append((b"origin", b"https://attacker.example"))

        with self.assertRaises(HTTPException) as error:
            main._check_origin(request)

        self.assertEqual(error.exception.status_code, 403)

    def test_user_can_rename_and_delete_only_their_dataset(self):
        owner = self.store.create_user("geologist", "a-very-long-password")
        dataset_id = "b" * 32
        self.store.create_dataset(dataset_id, owner["id"], "Old", "source.zip", 2)
        data_root = Path(self.temporary.name) / "users"
        user_dir = data_root / owner["id"]
        user_dir.mkdir(parents=True)
        archive = user_dir / f"{dataset_id}.zip"
        archive.write_bytes(b"test archive")

        with (
            patch.object(main, "_store", self.store),
            patch.object(main, "USER_DATASETS_DIR", data_root),
        ):
            request = json_request(
                f"/api/datasets/{dataset_id}",
                {"name": "New name"},
                user_id=owner["id"],
            )
            result = asyncio.run(main.rename_dataset(dataset_id, request))
            self.assertEqual(result["datasets"]["items"][0]["name"], "New name")

            request = json_request(
                f"/api/datasets/{dataset_id}",
                {},
                user_id=owner["id"],
            )
            main.delete_dataset(dataset_id, request)

        self.assertFalse(archive.exists())
        self.assertEqual(self.store.list_datasets(owner["id"]), [])


if __name__ == "__main__":
    unittest.main()
