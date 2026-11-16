"""Чтение и запись dBase III, кодовая страница Windows-1251.

Поле имён — не длиннее 10 латинских символов, текстовое поле — не длиннее
254 байт. Так файл открывается в LibreOffice и Excel. Длинные разделы
паспорта в таблицу не входят: для них есть текстовый отчёт.
"""

from __future__ import annotations

from datetime import datetime

FIELDS: tuple[tuple[str, str, int, int], ...] = (
    ("NAME", "C", 120, 0),
    ("SYNONYM", "C", 160, 0),
    ("MINERAL", "C", 80, 0),
    ("PI", "C", 160, 0),
    ("RANK", "C", 40, 0),
    ("DISTRICT", "C", 80, 0),
    ("ASSOC", "C", 160, 0),
    ("CADASTRE", "C", 60, 0),
    ("AREA", "N", 12, 4),
    ("LAT", "N", 14, 8),
    ("LON", "N", 14, 8),
    ("COND", "C", 40, 0),
    ("FORMATION", "C", 120, 0),
    ("GENTYPE", "C", 80, 0),
    ("NOTES", "C", 240, 0),
)

_CODEPAGE = {0xC9: "cp1251", 0xC8: "cp1251", 0x26: "cp866", 0x65: "cp866"}


def dumps(rows: list[dict]) -> bytes:
    now = datetime.now()
    header_len = 32 + 32 * len(FIELDS) + 1
    record_len = 1 + sum(field[2] for field in FIELDS)
    out = bytearray()
    out += bytes([0x03, max(now.year - 1900, 0) & 0xFF, now.month, now.day])
    out += len(rows).to_bytes(4, "little")
    out += header_len.to_bytes(2, "little")
    out += record_len.to_bytes(2, "little")
    tail = bytearray(20)
    tail[17] = 0xC9  # байт 29 заголовка — языковой драйвер CP1251
    out += tail
    for name, kind, length, decimals in FIELDS:
        desc = bytearray(32)
        raw = name.encode("ascii")[:11]
        desc[: len(raw)] = raw
        desc[11] = ord(kind)
        desc[16] = length
        desc[17] = decimals
        out += desc
    out += b"\x0d"
    for row in rows:
        record = bytearray(b" " * record_len)
        cursor = 1
        for name, kind, length, decimals in FIELDS:
            value = row.get(name)
            if kind == "N":
                if value is None or value == "":
                    chunk = b" " * length
                else:
                    text = f"{float(value):.{decimals}f}" if decimals else str(int(value))
                    if len(text) > length:
                        text = "*" * length
                    chunk = text.encode("ascii").rjust(length)
            else:
                text = "" if value is None else str(value)
                chunk = text.encode("cp1251", errors="replace")[:length].ljust(length)
            record[cursor : cursor + length] = chunk
            cursor += length
        out += record
    out += b"\x1a"
    return bytes(out)


def loads(data: bytes) -> list[dict]:
    if len(data) < 33 or data[0] not in (0x03, 0x83, 0x30, 0xF5):
        raise ValueError("Файл не похож на dBase III.")
    count = int.from_bytes(data[4:8], "little")
    header_len = int.from_bytes(data[8:10], "little")
    record_len = int.from_bytes(data[10:12], "little")
    if header_len < 33 or record_len < 1 or header_len > len(data):
        raise ValueError("Заголовок DBF повреждён.")
    encoding = _CODEPAGE.get(data[29], "cp1251")
    fields: list[tuple[str, str, int, int]] = []
    cursor = 32
    while cursor + 1 < header_len:
        if data[cursor] == 0x0D:
            break
        if cursor + 32 > len(data):
            break
        chunk = data[cursor : cursor + 32]
        name = chunk[:11].split(b"\x00", 1)[0].decode(encoding, errors="replace").strip()
        kind = chr(chunk[11]) if 32 <= chunk[11] < 127 else "?"
        length = chunk[16] or 1
        decimals = chunk[17]
        fields.append((name, kind, length, decimals))
        cursor += 32
    if not fields:
        raise ValueError("В DBF нет полей.")
    rows: list[dict] = []
    for index in range(count):
        start = header_len + index * record_len
        record = data[start : start + record_len]
        if len(record) < record_len:
            break
        if record[0] == 0x2A:
            continue
        row: dict = {}
        pos = 1
        for name, kind, length, decimals in fields:
            cell = record[pos : pos + length]
            pos += length
            if kind == "N":
                text = cell.decode("ascii", errors="replace").strip()
                if not text or set(text) <= {"*"}:
                    row[name] = None
                else:
                    try:
                        row[name] = float(text)
                    except ValueError:
                        row[name] = None
            else:
                row[name] = cell.decode(encoding, errors="replace").rstrip(" \x00")
        rows.append(row)
    return rows
