import unittest
from io import BytesIO
from unittest.mock import patch

from openpyxl import load_workbook
from starlette.requests import Request

from app import main
from app.shapefile import Occurrence
from app.xlsxio import dumps


def occurrence(record_id, name, attributes, canonical, center=None):
    return Occurrence(
        id=record_id,
        name=name,
        attributes=attributes,
        canonical=canonical,
        geometry=None,
        center=center,
    )


class XlsxExportTests(unittest.TestCase):
    @staticmethod
    def request():
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/export/xlsx",
                "query_string": b"",
                "headers": [],
                "session": {},
            }
        )

    def test_export_route_returns_card_or_full_catalog(self):
        record = occurrence(0, "Участок А", {"NAME": "Участок А"}, {})
        dataset = type("Dataset", (), {"records": [record]})()
        with patch.object(main, "_require_dataset", return_value=dataset):
            full = main.export_xlsx(self.request())
            single = main.export_xlsx(self.request(), 0)

        self.assertIn('filename="deposits.xlsx"', full.headers["content-disposition"])
        self.assertIn('filename="deposit-1.xlsx"', single.headers["content-disposition"])
        self.assertEqual(load_workbook(BytesIO(full.body)).sheetnames, ["Каталог"])
        self.assertEqual(load_workbook(BytesIO(single.body)).sheetnames, ["Карточка"])

    def test_catalog_export_has_russian_headers_filters_and_all_records(self):
        records = [
            occurrence(
                0,
                "Участок А",
                {"NAME": "Участок А", "MINERAL": "Железо", "CODE_X": "A-1"},
                {"MINERAL": "Железо", "AREA": 12.5},
                {"lat": 57.63, "lon": 39.72},
            ),
            occurrence(
                1,
                "Участок Б",
                {"NAME": "Участок Б", "MINERAL": "Золото", "CODE_X": "B-2"},
                {"MINERAL": "Золото"},
            ),
        ]

        workbook = load_workbook(BytesIO(dumps(records)), data_only=False)
        sheet = workbook["Каталог"]
        rows = list(sheet.iter_rows(min_row=4, values_only=True))

        self.assertEqual(rows[0], ("Название", "Минерал", "Площадь, км²", "Широта", "Долгота", "CODE_X"))
        self.assertEqual(rows[1][0:3], ("Участок А", "Железо", 12.5))
        self.assertEqual(rows[1][3:5], (57.63, 39.72))
        self.assertEqual(rows[2][0:2], ("Участок Б", "Золото"))
        self.assertEqual(sheet.freeze_panes, "A5")
        self.assertEqual(len(sheet.tables), 1)
        self.assertEqual(sheet.tables["Deposits"].ref, "A4:F6")
        workbook.close()

    def test_card_export_is_a_readable_two_column_passport(self):
        record = occurrence(
            3,
            "Примерное месторождение",
            {"NAME": "Примерное месторождение", "MINERAL": "Железная руда"},
            {"MINERAL": "Железная руда", "DISTRICT": "Северный"},
            {"lat": 57.63, "lon": 39.72},
        )

        workbook = load_workbook(BytesIO(dumps([record], card=True)), data_only=False)
        sheet = workbook["Карточка"]
        rows = list(sheet.iter_rows(min_row=4, values_only=True))

        self.assertEqual(rows[0], ("Показатель", "Значение"))
        self.assertIn(("Номер в каталоге", 4), rows)
        self.assertIn(("Минерал", "Железная руда"), rows)
        self.assertIn(("Район", "Северный"), rows)
        self.assertIn(("Широта (WGS 84)", 57.63), rows)
        self.assertIn(("Долгота (WGS 84)", 39.72), rows)
        self.assertEqual(sheet.freeze_panes, "A5")
        workbook.close()

    def test_formula_like_source_text_is_not_written_as_a_formula(self):
        record = occurrence(
            0,
            "=2+2",
            {"NAME": "=2+2", "CUSTOM": "=1+1"},
            {},
        )

        workbook = load_workbook(BytesIO(dumps([record])), data_only=False)
        sheet = workbook["Каталог"]

        self.assertEqual(sheet["A5"].value, "=2+2")
        self.assertEqual(sheet["A5"].data_type, "s")
        self.assertEqual(sheet["B5"].value, "=1+1")
        self.assertEqual(sheet["B5"].data_type, "s")
        workbook.close()


if __name__ == "__main__":
    unittest.main()
