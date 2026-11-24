import unittest
from io import BytesIO
from unittest.mock import patch

from docx import Document
from fastapi import HTTPException
from starlette.requests import Request

from app import main
from app.shapefile import Occurrence
from app.wordio import dumps


class WordExportTests(unittest.TestCase):
    def setUp(self):
        self.record = Occurrence(
            id=0,
            name="Примерное месторождение",
            attributes={"NAME": "Примерное месторождение", "MINERAL": "Железная руда"},
            canonical={"MINERAL": "Железная руда"},
            geometry=None,
            center={"lat": 57.63, "lon": 39.72},
        )

    @staticmethod
    def request():
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/export/word",
                "query_string": b"",
                "headers": [],
                "session": {},
            }
        )

    def test_export_route_returns_a_downloadable_word_document(self):
        dataset = type("Dataset", (), {"records": [self.record]})()
        with patch.object(main, "_require_dataset", return_value=dataset):
            response = main.export_word(self.request(), 0)

        self.assertEqual(
            response.media_type,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertIn('filename="deposit-1.docx"', response.headers["content-disposition"])
        self.assertIn(
            "КАРТОЧКА МЕСТОРОЖДЕНИЯ",
            Document(BytesIO(response.body)).paragraphs[0].text,
        )

    def test_export_route_rejects_unknown_record(self):
        dataset = type("Dataset", (), {"records": [self.record]})()
        with patch.object(main, "_require_dataset", return_value=dataset):
            with self.assertRaises(HTTPException) as error:
                main.export_word(self.request(), 1)

        self.assertEqual(error.exception.status_code, 404)

    def test_creates_a_russian_passport_card_with_selected_record_data(self):
        record = Occurrence(
            id=3,
            name="Примерное месторождение",
            attributes={"NAME": "Примерное месторождение", "MINERAL": "Железная руда"},
            canonical={"MINERAL": "Железная руда", "DISTRICT": "Северный"},
            geometry=None,
            center={"lat": 57.63, "lon": 39.72},
        )

        document = Document(BytesIO(dumps(record)))

        self.assertIn("КАРТОЧКА МЕСТОРОЖДЕНИЯ", document.paragraphs[0].text)
        self.assertIn("Примерное месторождение", document.paragraphs[1].text)
        rows = [[cell.text for cell in row.cells] for row in document.tables[0].rows]
        self.assertIn(["Минерал", "Железная руда"], rows)
        self.assertIn(["Район", "Северный"], rows)
        self.assertIn(["Координаты (WGS 84)", "57.630000, 39.720000"], rows)
        self.assertIn(["Номер в каталоге", "4"], rows)

    def test_falls_back_to_source_fields_when_passport_is_empty(self):
        record = Occurrence(
            id=0,
            name="Участок",
            attributes={"FIELD_X": "Исходное значение"},
            canonical={},
            geometry=None,
            center=None,
        )

        document = Document(BytesIO(dumps(record)))

        self.assertEqual(document.tables[0].rows[1].cells[0].text, "Номер в каталоге")
        self.assertEqual(document.tables[0].rows[2].cells[0].text, "FIELD_X")
        self.assertEqual(document.tables[0].rows[2].cells[1].text, "Исходное значение")


if __name__ == "__main__":
    unittest.main()
