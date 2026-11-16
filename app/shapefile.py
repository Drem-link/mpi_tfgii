"""Read zipped ESRI Shapefiles and expose their records for the local web UI."""

from __future__ import annotations

import math
import posixpath
import struct
import zipfile
import zlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any, BinaryIO

from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError, ProjError

from app import dbfio
from app.textutil import fold

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_UNPACKED_BYTES = 2 * 1024 * 1024 * 1024
MAX_DBF_BYTES = 256 * 1024 * 1024
MAX_RECORDS = 250_000
MAX_POINTS_PER_SHAPE = 100_000
MAX_TOTAL_POINTS = 500_000
MAX_PART_POINTS = 1_000

_FIELD_ALIASES = {
    "NAME": ("name", "naim", "naimenovanie", "nazvanie", "mest_name", "ob_name", "месторождение", "наименование", "название"),
    "SYNONYM": ("synonym", "syn", "alias", "иноеназвание", "синоним"),
    "MINERAL": ("mineral", "miner", "element", "useful", "iskop", "полезноеископаемое", "полезное", "минерал", "элемент"),
    "PI": ("pi", "p_i", "полезноеископаемое"),
    "RANK": ("rank", "stage", "typ", "стадия", "тип"),
    "DISTRICT": ("district", "region", "район", "регион"),
    "ASSOC": ("assoc", "association", "организация", "предприятие"),
    "CADASTRE": ("cadastre", "cadnum", "кадастр", "номер"),
    "AREA": ("area", "square", "площадь"),
    "LAT": ("lat", "latitude", "b", "широта"),
    "LON": ("lon", "long", "longitude", "l", "долгота"),
    "COND": ("cond", "condition", "состояние"),
    "FORMATION": ("formation", "age", "возраст", "формация"),
    "GENTYPE": ("gentype", "genesis", "тип", "генетическийтип"),
    "NOTES": ("notes", "note", "comment", "примечание", "описание"),
}
_FIELD_KEYS = {
    field: {fold(field), *(fold(alias) for alias in aliases)}
    for field, aliases in _FIELD_ALIASES.items()
}
_SUPPORTED_SHAPES = {0, 1, 3, 5, 8, 11, 13, 15, 18, 21, 23, 25, 28}


@dataclass
class Occurrence:
    id: int
    name: str
    attributes: dict[str, Any]
    canonical: dict[str, Any]
    geometry: dict[str, Any] | None
    center: dict[str, float] | None

    def as_dict(self, *, include_geometry: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "name": self.name,
            "attributes": self.attributes,
            "canonical": self.canonical,
            "center": self.center,
        }
        if include_geometry:
            result["geometry"] = self.geometry
        return result


@dataclass
class ShapefileDataset:
    filename: str
    fields: list[str]
    records: list[Occurrence]
    warnings: list[str]

    def summary(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "count": len(self.records),
            "fields": self.fields,
            "warnings": self.warnings,
        }


def _normalize_field(value: str) -> str:
    return "".join(char for char in fold(value) if char.isalnum())


def _canonical_values(attributes: dict[str, Any]) -> dict[str, Any]:
    normalized = {_normalize_field(name): value for name, value in attributes.items()}
    result: dict[str, Any] = {}
    for field, aliases in _FIELD_KEYS.items():
        for alias in aliases:
            key = _normalize_field(alias)
            if key in normalized and normalized[key] not in (None, ""):
                result[field] = normalized[key]
                break
    return result


def _shape_geometry(content: bytes) -> dict[str, Any] | None:
    if len(content) < 4:
        raise ValueError("Повреждена запись SHP: нет типа геометрии.")
    shape_type = struct.unpack_from("<i", content)[0]
    if shape_type == 0:
        return None
    if shape_type not in _SUPPORTED_SHAPES:
        raise ValueError(f"Тип геометрии SHP {shape_type} не поддерживается.")

    base_type = shape_type - (20 if shape_type >= 21 else 10 if shape_type >= 11 else 0)
    if base_type == 1:
        if len(content) < 20:
            raise ValueError("Повреждена точечная запись SHP.")
        x, y = struct.unpack_from("<2d", content, 4)
        return {"type": "Point", "coordinates": [x, y]}

    if base_type == 8:
        if len(content) < 40:
            raise ValueError("Повреждена запись MultiPoint SHP.")
        count = struct.unpack_from("<i", content, 36)[0]
        start = 40
        if count < 0 or count > MAX_POINTS_PER_SHAPE or start + count * 16 > len(content):
            raise ValueError("Неверное число точек в записи SHP.")
        points = [list(struct.unpack_from("<2d", content, start + i * 16)) for i in range(count)]
        return {"type": "MultiPoint", "coordinates": points}

    if base_type not in (3, 5) or len(content) < 44:
        raise ValueError("Повреждена линейная или полигональная запись SHP.")
    part_count, point_count = struct.unpack_from("<2i", content, 36)
    if (
        part_count < 0
        or point_count < 0
        or point_count > MAX_POINTS_PER_SHAPE
        or point_count > MAX_UNPACKED_BYTES // 16
    ):
        raise ValueError("Неверное число частей или точек в записи SHP.")
    parts_start = 44
    points_start = parts_start + part_count * 4
    if points_start + point_count * 16 > len(content):
        raise ValueError("Запись SHP короче указанного числа точек.")
    starts = list(struct.unpack_from(f"<{part_count}i", content, parts_start)) if part_count else []
    if point_count and (not starts or starts[0] != 0 or any(a >= b for a, b in zip(starts, starts[1:]))):
        raise ValueError("Неверные границы частей в записи SHP.")
    if any(start < 0 or start >= point_count for start in starts):
        raise ValueError("Граница части выходит за пределы точек SHP.")
    points = [
        list(struct.unpack_from("<2d", content, points_start + i * 16))
        for i in range(point_count)
    ]
    starts.append(point_count)
    parts = [points[starts[i] : starts[i + 1]] for i in range(len(starts) - 1)]
    if base_type == 3:
        if len(parts) == 1:
            return {"type": "LineString", "coordinates": parts[0]}
        return {"type": "MultiLineString", "coordinates": parts}
    return {"type": "Polygon", "coordinates": parts}


def _iter_points(geometry: dict[str, Any]):
    coordinates = geometry["coordinates"]
    if geometry["type"] == "Point":
        yield coordinates
    else:
        stack = list(coordinates)
        while stack:
            item = stack.pop()
            if item and isinstance(item[0], (float, int)):
                yield item
            else:
                stack.extend(item)


def _thin_line(points: list[list[float]]) -> list[list[float]]:
    if len(points) <= MAX_PART_POINTS:
        return points
    stride = math.ceil((len(points) - 1) / (MAX_PART_POINTS - 1))
    result = points[::stride]
    if result[-1] != points[-1]:
        result.append(points[-1])
    return result


def _convert_geometry(
    geometry: dict[str, Any],
    transformer: Transformer | None,
    assume_geographic: bool,
) -> tuple[dict[str, Any] | None, dict[str, float] | None]:
    converted: list[list[float]] = []

    def convert_point(point: list[float]) -> list[float]:
        x, y = point[:2]
        if transformer:
            x, y = transformer.transform(x, y, errcheck=True)
        elif not assume_geographic:
            raise ValueError("Для координат не задана система координат.")
        if not (math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90):
            raise ValueError("Преобразованные координаты вне диапазона WGS 84.")
        result = [float(x), float(y)]
        converted.append(result)
        return result

    def convert_line(line: list[list[float]]) -> list[list[float]]:
        return _thin_line([convert_point(point) for point in line])

    kind = geometry["type"]
    if kind == "Point":
        coordinates = convert_point(geometry["coordinates"])
    elif kind == "LineString":
        coordinates = convert_line(geometry["coordinates"])
    elif kind == "MultiPoint":
        coordinates = [convert_point(point) for point in geometry["coordinates"]]
    elif kind == "Polygon":
        coordinates = [convert_line(ring) for ring in geometry["coordinates"]]
    elif kind == "MultiLineString":
        coordinates = [convert_line(line) for line in geometry["coordinates"]]
    else:
        raise ValueError(f"Геометрия {kind} не поддерживается.")
    if not converted:
        return None, None
    result = {"type": kind, "coordinates": coordinates}
    center = {
        "lon": sum(point[0] for point in converted) / len(converted),
        "lat": sum(point[1] for point in converted) / len(converted),
    }
    return result, center


def _read_shape_header(stream: BinaryIO, file_size: int) -> tuple[int, int, tuple[float, float, float, float]]:
    header = stream.read(100)
    if len(header) < 100:
        raise ValueError("Файл SHP короче заголовка.")
    file_code = struct.unpack_from(">i", header)[0]
    declared_length = struct.unpack_from(">i", header, 24)[0] * 2
    version, shape_type = struct.unpack_from("<2i", header, 28)
    if file_code != 9994 or version != 1000:
        raise ValueError("Файл не является корректным ESRI Shapefile.")
    if declared_length < 100 or declared_length != file_size:
        raise ValueError("Заголовок SHP указывает неверную длину файла.")
    if shape_type not in _SUPPORTED_SHAPES:
        raise ValueError(f"Тип геометрии SHP {shape_type} не поддерживается.")
    xmin, ymin, xmax, ymax = struct.unpack_from("<4d", header, 36)
    return declared_length, shape_type, (xmin, ymin, xmax, ymax)


def _iter_shapes(stream: BinaryIO, declared_length: int):
    total_points = 0
    record_count = 0
    offset = 100
    while offset < declared_length:
        record_header = stream.read(8)
        if len(record_header) != 8:
            raise ValueError("Оборван заголовок записи SHP.")
        content_length = struct.unpack_from(">i", record_header, 4)[0] * 2
        if content_length < 4 or offset + 8 + content_length > declared_length:
            raise ValueError("Неверная длина записи SHP.")
        content = stream.read(content_length)
        if len(content) != content_length:
            raise ValueError("Оборвана запись SHP.")
        shape = _shape_geometry(content)
        if shape is not None:
            total_points += sum(1 for _ in _iter_points(shape))
            if total_points > MAX_TOTAL_POINTS:
                raise ValueError(f"В шейпе больше {MAX_TOTAL_POINTS:,} вершин.")
        record_count += 1
        if record_count > MAX_RECORDS:
            raise ValueError(f"В шейпе больше {MAX_RECORDS:,} записей.")
        yield shape
        offset += 8 + content_length
        if offset > declared_length:
            raise ValueError("Записи SHP выходят за пределы файла.")


def load_shapefile_zip(filename: str, data: bytes | BinaryIO) -> ShapefileDataset:
    if isinstance(data, bytes):
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError("ZIP-архив больше 512 МБ.")
        archive_source = BytesIO(data)
        archive_size = len(data)
    else:
        archive_source = data
        current_position = archive_source.tell()
        archive_source.seek(0, 2)
        archive_size = archive_source.tell()
        archive_source.seek(current_position)
    if archive_size > MAX_ARCHIVE_BYTES:
        raise ValueError("ZIP-архив больше 512 МБ.")
    try:
        archive = zipfile.ZipFile(archive_source)
    except zipfile.BadZipFile as error:
        raise ValueError("Файл не является корректным ZIP-архивом.") from error

    with archive:
        infos = archive.infolist()
        if len(infos) > 500:
            raise ValueError("В архиве слишком много файлов.")
        total_size = sum(info.file_size for info in infos)
        if total_size > MAX_UNPACKED_BYTES:
            raise ValueError("Распакованный размер архива превышает 2 ГБ.")
        shapes_in_zip = [
            info for info in infos
            if PurePosixPath(info.filename).suffix.casefold() == ".shp"
        ]
        if len(shapes_in_zip) != 1:
            raise ValueError("В ZIP должен быть ровно один файл .shp.")
        shp_info = shapes_in_zip[0]
        base = posixpath.splitext(shp_info.filename)[0].casefold()
        matching = {}
        for info in infos:
            if posixpath.splitext(info.filename)[0].casefold() != base:
                continue
            extension = PurePosixPath(info.filename).suffix.casefold()
            if extension in matching:
                raise ValueError(f"В архиве несколько файлов {extension}.")
            matching[extension] = info
        if ".dbf" not in matching:
            raise ValueError("Рядом с .shp в архиве должен быть одноимённый файл .dbf.")
        if matching[".dbf"].file_size > MAX_DBF_BYTES:
            raise ValueError("DBF больше 256 МБ.")
        if any(info.flag_bits & 1 for info in matching.values()):
            raise ValueError("Зашифрованные ZIP-архивы не поддерживаются.")

        try:
            dbf_data = archive.read(matching[".dbf"])
            prj_data = archive.read(matching[".prj"]) if ".prj" in matching else None
            rows = dbfio.loads(dbf_data)
        except (
            KeyError,
            RuntimeError,
            zipfile.BadZipFile,
            ValueError,
            IndexError,
            NotImplementedError,
            UnicodeError,
            zlib.error,
        ) as error:
            raise ValueError(f"Не удалось прочитать SHP/DBF: {error}") from error

        try:
            with archive.open(shp_info) as shp_stream:
                declared_length, _shape_type, bounds = _read_shape_header(shp_stream, shp_info.file_size)

                transformer = None
                assume_geographic = False
                warnings: list[str] = []
                if prj_data:
                    try:
                        source_crs = CRS.from_wkt(prj_data.decode("utf-8-sig"))
                        transformer = Transformer.from_crs(source_crs, CRS.from_epsg(4326), always_xy=True)
                    except (CRSError, UnicodeError, ProjError, ValueError) as error:
                        raise ValueError(f"Не удалось разобрать файл .prj: {error}") from error
                else:
                    xmin, ymin, xmax, ymax = bounds
                    assume_geographic = (
                        -180 <= xmin <= 180 and -180 <= xmax <= 180
                        and -90 <= ymin <= 90 and -90 <= ymax <= 90
                    )
                    if assume_geographic:
                        warnings.append(
                            "Файл .prj отсутствует; координаты в допустимом диапазоне приняты за WGS 84."
                        )
                    else:
                        warnings.append("Файл .prj отсутствует; геометрия не показана на карте.")

                fields = list(rows[0].keys()) if rows else []
                records: list[Occurrence] = []
                skipped_geometry = 0
                for index, shape in enumerate(_iter_shapes(shp_stream, declared_length), start=1):
                    if index > len(rows):
                        raise ValueError(
                            f"Число записей не совпадает: SHP — больше {len(rows)}, DBF — {len(rows)}."
                        )
                    row = rows[index - 1]
                    attributes = {
                        key: None if isinstance(value, float) and not math.isfinite(value) else value
                        for key, value in row.items()
                    }
                    canonical = _canonical_values(attributes)
                    geometry = None
                    center = None
                    if shape:
                        try:
                            geometry, center = _convert_geometry(shape, transformer, assume_geographic)
                        except (ProjError, ValueError, OverflowError):
                            geometry = None
                    if geometry is None:
                        skipped_geometry += 1
                        latitude = canonical.get("LAT")
                        longitude = canonical.get("LON")
                        try:
                            lat, lon = float(latitude), float(longitude)
                            if (
                                math.isfinite(lat) and math.isfinite(lon)
                                and -90 <= lat <= 90 and -180 <= lon <= 180
                            ):
                                geometry = {"type": "Point", "coordinates": [lon, lat]}
                                center = {"lon": lon, "lat": lat}
                        except (TypeError, ValueError):
                            pass
                    name = canonical.get("NAME")
                    if not name:
                        name = next(
                            (
                                str(value)
                                for value in attributes.values()
                                if isinstance(value, str) and value.strip()
                            ),
                            f"Участок {index:03d}",
                        )
                    canonical.setdefault("NAME", name)
                    if center:
                        canonical.setdefault("LAT", center["lat"])
                        canonical.setdefault("LON", center["lon"])
                    records.append(Occurrence(index - 1, str(name), attributes, canonical, geometry, center))
                if len(records) != len(rows):
                    raise ValueError(
                        f"Число записей не совпадает: SHP — {len(records)}, DBF — {len(rows)}."
                    )
        except (
            struct.error,
            OverflowError,
            zipfile.BadZipFile,
            RuntimeError,
            NotImplementedError,
            zlib.error,
        ) as error:
            raise ValueError(f"Повреждён файл SHP: {error}") from error

    if skipped_geometry:
        warnings.append(f"Без геометрии на карте: {skipped_geometry} из {len(records)} записей.")
    return ShapefileDataset(filename, fields, records, warnings)
