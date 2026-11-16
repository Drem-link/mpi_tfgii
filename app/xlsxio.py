from __future__ import annotations

from collections.abc import Iterable, Mapping
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell


def dumps(fields: list[str], rows: Iterable[Mapping[str, Any]]) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Месторождения")

    def text_safe_row(values):
        cells = []
        for value in values:
            cell = WriteOnlyCell(sheet, value=value)
            if isinstance(value, str):
                cell.data_type = "s"
            cells.append(cell)
        return cells

    sheet.append(text_safe_row(fields))
    for row in rows:
        sheet.append(text_safe_row(row.get(field) for field in fields))

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
