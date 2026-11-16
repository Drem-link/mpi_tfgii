import unittest
from io import BytesIO

from openpyxl import load_workbook

from app.xlsxio import dumps


class XlsxExportTests(unittest.TestCase):
    def test_exports_source_fields_and_keeps_formula_like_values_as_text(self):
        payload = dumps(
            ["NAME", "COUNT", "LAT"],
            [{"NAME": "=1+1", "COUNT": 12, "LAT": 57.63}],
        )

        workbook = load_workbook(BytesIO(payload), read_only=True, data_only=False)
        sheet = workbook["Месторождения"]
        rows = list(sheet.iter_rows())

        self.assertEqual([cell.value for cell in rows[0]], ["NAME", "COUNT", "LAT"])
        self.assertEqual(rows[1][0].value, "=1+1")
        self.assertEqual(rows[1][0].data_type, "s")
        self.assertEqual(rows[1][1].value, 12)
        self.assertEqual(rows[1][2].value, 57.63)
        workbook.close()


if __name__ == "__main__":
    unittest.main()
