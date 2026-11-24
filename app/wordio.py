from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.shapefile import Occurrence

_FIELD_LABELS = (
    ("NAME", "Название"),
    ("SYNONYM", "Синоним"),
    ("MINERAL", "Минерал"),
    ("PI", "Полезное ископаемое"),
    ("RANK", "Стадия освоения"),
    ("DISTRICT", "Район"),
    ("ASSOC", "Организация"),
    ("CADASTRE", "Кадастровый номер"),
    ("AREA", "Площадь, км²"),
    ("LAT", "Широта"),
    ("LON", "Долгота"),
    ("COND", "Состояние"),
    ("FORMATION", "Возраст / формация"),
    ("GENTYPE", "Генетический тип"),
    ("NOTES", "Примечание"),
)


def _set_cell_shading(cell, color: str) -> None:
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), color)
    cell._tc.get_or_add_tcPr().append(shading)


def _rows(record: Occurrence) -> list[tuple[str, Any]]:
    rows = [("Номер в каталоге", record.id + 1)]
    for field, label in _FIELD_LABELS:
        value = record.canonical.get(field)
        if value not in (None, "") and field != "NAME":
            rows.append((label, value))
    if record.center and not (
        record.canonical.get("LAT") not in (None, "")
        and record.canonical.get("LON") not in (None, "")
    ):
        rows.append(
            (
                "Координаты (WGS 84)",
                f'{record.center["lat"]:.6f}, {record.center["lon"]:.6f}',
            )
        )
    if len(rows) == 1:
        rows.extend(
            (field, value)
            for field, value in record.attributes.items()
            if value not in (None, "")
        )
    return rows


def dumps(record: Occurrence) -> bytes:
    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2)
    section.right_margin = Cm(2)

    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title.add_run("КАРТОЧКА МЕСТОРОЖДЕНИЯ")
    title_run.bold = True
    title_run.font.name = "Arial"
    title_run.font.size = Pt(16)
    title_run.font.color.rgb = RGBColor(39, 67, 55)

    name = document.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_run = name.add_run(record.name or "Без названия")
    name_run.bold = True
    name_run.font.name = "Arial"
    name_run.font.size = Pt(13)

    table = document.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = "Table Grid"
    table.autofit = False
    table.columns[0].width = Cm(6)
    table.columns[1].width = Cm(10)
    for cell, label in zip(table.rows[0].cells, ("Показатель", "Значение")):
        cell.text = label
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _set_cell_shading(cell, "E8EEE8")
        for run in cell.paragraphs[0].runs:
            run.bold = True

    for label, value in _rows(record):
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = str(value)
        cells[0].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        cells[1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        for run in cells[0].paragraphs[0].runs:
            run.bold = True

    output = BytesIO()
    document.save(output)
    return output.getvalue()
