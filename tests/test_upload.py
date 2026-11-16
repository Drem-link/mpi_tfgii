import asyncio
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app import main


class UploadTests(unittest.TestCase):
    def test_accepts_multipart_zip_larger_than_one_megabyte(self):
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zipped:
            zipped.writestr("payload.bin", b"x" * (1024 * 1024 + 128))

        boundary = b"mpi-upload-test-boundary"
        body = (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="file"; filename="probe.zip"\r\n'
            b"Content-Type: application/zip\r\n\r\n"
            + archive.getvalue()
            + b"\r\n--"
            + boundary
            + b"--\r\n"
        )
        messages = [{"type": "http.request", "body": body, "more_body": False}]

        async def receive():
            return messages.pop(0)

        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/dataset",
                "raw_path": b"/api/dataset",
                "query_string": b"",
                "headers": [
                    (b"content-type", b"multipart/form-data; boundary=mpi-upload-test-boundary"),
                    (b"content-length", str(len(body)).encode()),
                ],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
                "root_path": "",
                "app": main.app,
            },
            receive,
        )

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(main, "DATASET_PATH", Path(directory) / "deposits.zip"):
                with self.assertRaises(HTTPException) as error:
                    asyncio.run(main.upload_dataset(request))

        self.assertEqual(error.exception.status_code, 400)
        self.assertIn(".shp", error.exception.detail)
        self.assertNotEqual(error.exception.detail, "There was an error parsing the body")
