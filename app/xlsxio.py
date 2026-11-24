from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.shapefile import Occurrence
from app.textutil import fold

_FIELDS = (
    ("NAME", "Название", ("name", "naim", "naimenovanie", "nazvanie", "месторождение", "наименование", "название")),
    ("SYNONYM", "Синоним", ("synonym", "syn", "alias", "синоним")),
    ("MINERAL", "Минерал", ("mineral", "miner", "element", "полезноеископаемое", "полезное", "минерал", "элемент")),
    ("PI", "Полезное ископаемое", ("pi", "p_i")),
    ("RANK", "Стадия освоения", ("rank", "stage", "стадия")),
    ("DISTRICT", "Район", ("district", "region", "район", "регион")),
    ("ASSOC", "Организация", ("assoc", "association", "организация", "предприятие")),
    ("CADASTRE", "Кадастровый номер", ("cadastre", "cadnum", "кадастр", "номер")),
    ("AREA", "Площадь, км²", ("area", "square", "площадь")),
    ("LAT", "Широта", ("lat", "latitude", "широта")),
    ("LON", "Долгота", ("lon", "long", "longitude", "долгота")),
    ("COND", "Состояние", ("cond", "condition", "состояние")),
    ("FORMATION", "Возраст / формация", ("formation", "age", "возраст", "формация")),
    ("GENTYPE", "Генетический тип", ("gentype", "genesis", "генетическийтип")),
    ("NOTES", "Примечание", ("notes", "note", "comment", "примечание", "описание")),
)
_CANONICAL = {field: label for field, label, _ in _FIELDS}
_ALIASES = {
    "".join(char for char in fold(alias) if char.isalnum()): field
    for field, _, aliases in _FIELDS
    for alias in (field, *aliases)
}
_GREEN = "355D3D"
_PALE_GREEN = "EAF0E8"
_THIN_GREEN = Side(style="thin", color="D8E2D6")


def _source_field(field: str) -> str | None:
    normalized = "".join(char for char in fold(field) if char.isalnum())
    return _ALIASES.get(normalized)


def _write_value(cell, value: Any) -> None:
    cell.value = value
    if isinstance(value, str):
        cell.data_type = "s"


def _catalog_columns(records: Sequence[Occurrence]) -> list[tuple[str, str]]:
    canonical_fields = {
        field for record in records for field, value in record.canonical.items()
        if value not in (None, "")
    }
    canonical_fields.add("NAME")
    if any(record.center for record in records):
        canonical_fields.update(("LAT", "LON"))
    columns = [(field, _CANONICAL[field]) for field, _, _ in _FIELDS if field in canonical_fields]
    source_fields = dict.fromkeys(
        field for record in records for field in record.attributes if _source_field(field) is None
    )
    columns.extend((field, field) for field in source_fields)
    return columns


def _catalog_value(record: Occurrence, field: str) -> Any:
    if field in _CANONICAL:
        if field in record.canonical:
            value = record.canonical[field]
            if value not in (None, ""):
                return value
        if field == "NAME":
            return record.name
        if field == "LAT" and record.center:
            return record.center["lat"]
        if field == "LON" and record.center:
            return record.center["lon"]
        return None
    return record.attributes.get(field)


def _card_rows(record: Occurrence) -> list[tuple[str, Any]]:
    rows = [("Номер в каталоге", record.id + 1), ("Название", record.name)]
    present_canonical = set()
    for field, label, _ in _FIELDS:
        value = record.canonical.get(field)
        if value not in (None, "") and field != "NAME":
            rows.append((label, value))
            present_canonical.add(field)
    if record.center:
        if "LAT" not in present_canonical:
            rows.append(("Широта (WGS 84)", record.center["lat"]))
        if "LON" not in present_canonical:
            rows.append(("Долгота (WGS 84)", record.center["lon"]))
    source_fields = [
        (field, value)
        for field, value in record.attributes.items()
        if value not in (None, "") and _source_field(field) is None
    ]
    rows.extend(source_fields)
    if len(rows) == 2:
        rows.extend(
            (field, value)
            for field, value in record.attributes.items()
            if value not in (None, "") and field.upper() != "NAME"
        )
    return rows


def _add_title(sheet, title: str, subtitle: str, last_column: int) -> None:
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_column)
    cell = sheet.cell(1, 1, title)
    cell.fill = PatternFill("solid", fgColor=_GREEN)
    cell.font = Font(name="Arial", size=16, bold=True, color="FFFFFF")
    cell.alignment = Alignment(vertical="center")
    sheet.row_dimensions[1].height = 30
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_column)
    subheading = sheet.cell(2, 1, subtitle)
    subheading.font = Font(name="Arial", size=10, italic=True, color="526458")
    subheading.alignment = Alignment(vertical="center")
    sheet.row_dimensions[2].height = 22
    sheet.sheet_view.showGridLines = False


def _style_header(sheet, row: int, columns: int) -> None:
    for column in range(1, columns + 1):
        cell = sheet.cell(row, column)
        cell.fill = PatternFill("solid", fgColor=_GREEN)
        cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.row_dimensions[row].height = 30


def _set_column_widths(sheet, headers: list[str], rows: Sequence[Sequence[Any]], start_row: int) -> None:
    for column, header in enumerate(headers, 1):
        width = max(len(header), *(len(str(row[column - 1])) for row in rows[:200] if row[column - 1] is not None))
        sheet.column_dimensions[sheet.cell(start_row, column).column_letter].width = min(max(width + 3, 14), 42)


def _add_catalog_sheet(workbook: Workbook, records: Sequence[Occurrence]) -> None:
    sheet = workbook.active
    sheet.title = "Каталог"
    columns = _catalog_columns(records)
    headers = [label for _, label in columns]
    header_row = 4
    _add_title(sheet, "Каталог месторождений", f"Записей: {len(records)}", len(headers))
    for column, header in enumerate(headers, 1):
        sheet.cell(header_row, column, header)
    _style_header(sheet, header_row, len(headers))
    data_rows = [
        [_catalog_value(record, field) for field, _ in columns]
        for record in records
    ]
    for row_index, values in enumerate(data_rows, header_row + 1):
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row_index, column)
            _write_value(cell, value)
            cell.font = Font(name="Arial", size=10, color="26352B")
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if column == 1 and row_index % 2:
                cell.fill = PatternFill("solid", fgColor=_PALE_GREEN)
            if headers[column - 1] in ("Площадь, км²", "Широта", "Долгота"):
                cell.number_format = "#,##0.######"
    end_row = header_row + len(data_rows)
    table = Table(displayName="Deposits", ref=f"A{header_row}:{sheet.cell(end_row, len(headers)).coordinate}")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium4",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    sheet.add_table(table)
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.print_title_rows = f"{header_row}:{header_row}"
    _set_column_widths(sheet, headers, data_rows, header_row)


def _add_card_sheet(workbook: Workbook, record: Occurrence) -> None:
    sheet = workbook.active
    sheet.title = "Карточка"
    rows = _card_rows(record)
    _add_title(sheet, "КАРТОЧКА МЕСТОРОЖДЕНИЯ", record.name or "Без названия", 2)
    for column, header in enumerate(("Показатель", "Значение"), 1):
        sheet.cell(4, column, header)
    _style_header(sheet, 4, 2)
    for row_index, (label, value) in enumerate(rows, 5):
        label_cell = sheet.cell(row_index, 1, label)
        value_cell = sheet.cell(row_index, 2)
        _write_value(value_cell, value)
        label_cell.font = Font(name="Arial", size=10, bold=True, color=_GREEN)
        value_cell.font = Font(name="Arial", size=10, color="26352B")
        for cell in (label_cell, value_cell):
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(bottom=_THIN_GREEN)
        if row_index % 2:
            label_cell.fill = PatternFill("solid", fgColor=_PALE_GREEN)
            value_cell.fill = PatternFill("solid", fgColor=_PALE_GREEN)
    sheet.column_dimensions["A"].width = 28
    sheet.column_dimensions["B"].width = 60
    sheet.freeze_panes = "A5"
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = "portrait"
    sheet.page_setup.fitToWidth = 1


def dumps(records: Sequence[Occurrence], *, card: bool = False) -> bytes:
    workbook = Workbook()
    workbook.properties.title = "Карточка месторождения" if card else "Каталог месторождений"
    workbook.properties.subject = "Паспортные данные месторождений"
    if card:
        _add_card_sheet(workbook, records[0])
    else:
        _add_catalog_sheet(workbook, records)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
