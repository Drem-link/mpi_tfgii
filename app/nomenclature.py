"""Номенклатура топографических листов северного полушария.

Лист 1:1 000 000 — пояс 4° латинской буквой и колонна 6° номером
(P-56: 60–64° с.ш., 150–156° в.д.). Дальше стандартное деление:
1:500 000 на А Б / В Г, 1:200 000 на XXXVI листов, 1:100 000 на 144,
затем 1:50 000 (А–Г), 1:25 000 (а–г) и 1:10 000 (1–4).
Южная и западная рамки принадлежат листу, северная и восточная — соседним.
"""

from __future__ import annotations

import re

BELTS = "ABCDEFGHIJKLMNOPQRSTUV"
SCALES: tuple[tuple[int, str], ...] = (
    (1_000_000, "1:1 000 000"),
    (500_000, "1:500 000"),
    (200_000, "1:200 000"),
    (100_000, "1:100 000"),
    (50_000, "1:50 000"),
    (25_000, "1:25 000"),
    (10_000, "1:10 000"),
)
SCALE_LABEL = dict(SCALES)
QUADS_UP = "АБВГ"
QUADS_LO = "абвг"
_QUAD = {
    "А": "А", "Б": "Б", "В": "В", "Г": "Г",
    "а": "а", "б": "б", "в": "в", "г": "г",
    "A": "А", "B": "Б", "G": "Г",
    "a": "а", "b": "б", "g": "г",
}
_BELT_FIX = str.maketrans({
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K",
    "М": "M", "О": "O", "Р": "P", "Т": "T", "Х": "X", "У": "Y", "І": "I",
})
_ROMAN_FIX = str.maketrans({"Х": "X", "х": "X", "І": "I", "і": "I"})


def _roman(number: int) -> str:
    parts: list[str] = []
    for value, symbol in ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while number >= value:
            parts.append(symbol)
            number -= value
    return "".join(parts)


ROMAN = [_roman(i) for i in range(1, 37)]
_ROMAN_INDEX = {name: index for index, name in enumerate(ROMAN)}


def _check(latitude: float, longitude: float) -> None:
    if not 0.0 <= latitude < 88.0:
        raise ValueError("Номенклатура считается для широт от 0° до 88° с.ш.")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("Долгота вне диапазона −180…180.")


def _million(latitude: float, longitude: float) -> tuple[str, float, float, float, float]:
    if longitude == 180.0:
        longitude = -180.0
    _check(latitude, longitude)
    belt_index = int(latitude // 4.0)
    column = int((longitude + 180.0) // 6.0) + 1
    south = belt_index * 4.0
    west = -180.0 + (column - 1) * 6.0
    return f"{BELTS[belt_index]}-{column}", south, south + 4.0, west, west + 6.0


def _cell(
    latitude: float,
    longitude: float,
    south: float,
    north: float,
    west: float,
    east: float,
    rows: int,
    cols: int,
) -> tuple[int, float, float, float, float]:
    cell_h = (north - south) / rows
    cell_w = (east - west) / cols
    row_s = int((latitude - south) / cell_h) if cell_h else 0
    col = int((longitude - west) / cell_w) if cell_w else 0
    row_s = min(max(row_s, 0), rows - 1)
    col = min(max(col, 0), cols - 1)
    index = (rows - 1 - row_s) * cols + col
    child_south = south + row_s * cell_h
    child_west = west + col * cell_w
    return index, child_south, child_south + cell_h, child_west, child_west + cell_w


def _from_index(
    index: int,
    south: float,
    north: float,
    west: float,
    east: float,
    rows: int,
    cols: int,
) -> tuple[float, float, float, float]:
    row_n, col = divmod(index, cols)
    row_s = rows - 1 - row_n
    cell_h = (north - south) / rows
    cell_w = (east - west) / cols
    child_south = south + row_s * cell_h
    child_west = west + col * cell_w
    return child_south, child_south + cell_h, child_west, child_west + cell_w


def sheet(latitude: float, longitude: float, scale: int) -> dict:
    if scale not in SCALE_LABEL:
        known = ", ".join(str(item) for item, _ in SCALES)
        raise ValueError(f"Масштаб {scale} не поддерживается. Доступны: {known}.")
    code, south, north, west, east = _million(latitude, longitude)
    if scale == 1_000_000:
        return _pack(code, scale, south, north, west, east)
    if scale == 500_000:
        index, south, north, west, east = _cell(latitude, longitude, south, north, west, east, 2, 2)
        return _pack(f"{code}-{QUADS_UP[index]}", scale, south, north, west, east)
    if scale == 200_000:
        index, south, north, west, east = _cell(latitude, longitude, south, north, west, east, 6, 6)
        return _pack(f"{code}-{ROMAN[index]}", scale, south, north, west, east)
    index, south, north, west, east = _cell(latitude, longitude, south, north, west, east, 12, 12)
    code = f"{code}-{index + 1}"
    if scale == 100_000:
        return _pack(code, scale, south, north, west, east)
    index, south, north, west, east = _cell(latitude, longitude, south, north, west, east, 2, 2)
    code = f"{code}-{QUADS_UP[index]}"
    if scale == 50_000:
        return _pack(code, scale, south, north, west, east)
    index, south, north, west, east = _cell(latitude, longitude, south, north, west, east, 2, 2)
    code = f"{code}-{QUADS_LO[index]}"
    if scale == 25_000:
        return _pack(code, scale, south, north, west, east)
    index, south, north, west, east = _cell(latitude, longitude, south, north, west, east, 2, 2)
    return _pack(f"{code}-{index + 1}", 10_000, south, north, west, east)


def sheets_for(latitude: float, longitude: float) -> list[dict]:
    return [sheet(latitude, longitude, scale) for scale, _ in SCALES]


def _pack(code: str, scale: int, south: float, north: float, west: float, east: float) -> dict:
    return {
        "code": code,
        "scale": scale,
        "scale_label": SCALE_LABEL[scale],
        "south": south,
        "north": north,
        "west": west,
        "east": east,
    }


def _norm_code(code: str) -> list[str]:
    cleaned = code.strip().upper() if False else code.strip()
    cleaned = cleaned.replace("—", "-").replace("–", "-").replace("−", "-")
    cleaned = re.sub(r"\s+", "", cleaned)
    parts = [part for part in cleaned.split("-") if part]
    if len(parts) < 2:
        raise ValueError("Номенклатура задаётся как P-56 или P-56-XXIV.")
    return parts


def parse_sheet(code: str) -> dict:
    parts = _norm_code(code)
    belt = parts[0].translate(_BELT_FIX).upper()
    if len(belt) != 1 or belt not in BELTS:
        raise ValueError("Первая буква номенклатуры — пояс листа 1:1 000 000, от A до V.")
    if not parts[1].isdigit():
        raise ValueError("После пояса должен стоять номер колонны.")
    column = int(parts[1])
    if not 1 <= column <= 60:
        raise ValueError("Номер колонны должен быть от 1 до 60.")
    belt_index = BELTS.index(belt)
    south = belt_index * 4.0
    north = south + 4.0
    west = -180.0 + (column - 1) * 6.0
    east = west + 6.0
    base = f"{belt}-{column}"
    rest = parts[2:]
    if not rest:
        return _pack(base, 1_000_000, south, north, west, east)

    token = rest[0]
    quad = _QUAD.get(token)
    if quad and quad in QUADS_UP and len(rest) == 1:
        index = QUADS_UP.index(quad)
        south, north, west, east = _from_index(index, south, north, west, east, 2, 2)
        return _pack(f"{base}-{quad}", 500_000, south, north, west, east)

    roman = token.translate(_ROMAN_FIX).upper()
    if roman in _ROMAN_INDEX and len(rest) == 1:
        index = _ROMAN_INDEX[roman]
        south, north, west, east = _from_index(index, south, north, west, east, 6, 6)
        return _pack(f"{base}-{ROMAN[index]}", 200_000, south, north, west, east)

    if not token.isdigit() or not 1 <= int(token) <= 144:
        raise ValueError(f"Не понял часть «{token}» в номенклатуре.")
    index = int(token) - 1
    south, north, west, east = _from_index(index, south, north, west, east, 12, 12)
    code_now = f"{base}-{index + 1}"
    extra = rest[1:]
    if not extra:
        return _pack(code_now, 100_000, south, north, west, east)

    quad = _QUAD.get(extra[0])
    if not quad or quad not in QUADS_UP:
        raise ValueError("После листа 1:100 000 ждётся буква А, Б, В или Г.")
    south, north, west, east = _from_index(QUADS_UP.index(quad), south, north, west, east, 2, 2)
    code_now = f"{code_now}-{quad}"
    if len(extra) == 1:
        return _pack(code_now, 50_000, south, north, west, east)

    small = _QUAD.get(extra[1])
    if not small or small not in QUADS_LO:
        raise ValueError("Лист 1:25 000 обозначается строчной а, б, в или г.")
    south, north, west, east = _from_index(QUADS_LO.index(small), south, north, west, east, 2, 2)
    code_now = f"{code_now}-{small}"
    if len(extra) == 2:
        return _pack(code_now, 25_000, south, north, west, east)
    if len(extra) != 3 or not extra[2].isdigit() or not 1 <= int(extra[2]) <= 4:
        raise ValueError("Лист 1:10 000 заканчивается цифрой 1, 2, 3 или 4.")
    piece = int(extra[2]) - 1
    south, north, west, east = _from_index(piece, south, north, west, east, 2, 2)
    return _pack(f"{code_now}-{piece + 1}", 10_000, south, north, west, east)
