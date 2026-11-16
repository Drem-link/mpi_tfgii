"""Гаусс–Крюгер на эллипсоиде Красовского (СК-42).

В русской нотации X — северное направление от экватора, Y — восточное
внутри шестиградусной зоны, без префикса номера зоны. Осевой меридиан
зоны n равен 6n − 3°, ложный восток 500 000 м.

Долгота и широта здесь — геодезические координаты Пулково 1942. Настольная
программа пересчитывала их в проекцию без перехода на WGS 84, и калькулятор
делает то же самое. Для карты точка переводится отдельно.
"""

from __future__ import annotations

import math
from functools import lru_cache

from pyproj import CRS, Transformer

_GEOG = CRS.from_proj4("+proj=longlat +ellps=krass +no_defs")


def zone_from_longitude(longitude: float) -> int:
    zone = int(math.floor(longitude / 6.0)) + 1
    if zone < 1 or zone > 60:
        raise ValueError("Долгота вне шестиградусных зон 1–60. Укажите зону вручную.")
    return zone


def central_meridian(zone: int) -> float:
    if zone < 1 or zone > 60:
        raise ValueError("Зона Гаусса–Крюгера должна быть от 1 до 60.")
    return zone * 6 - 3


def _gk(zone: int) -> CRS:
    return CRS.from_proj4(
        "+proj=tmerc +lat_0=0 +lon_0="
        + str(central_meridian(zone))
        + " +k=1 +x_0=500000 +y_0=0 +ellps=krass +units=m +no_defs"
    )


@lru_cache(maxsize=64)
def _forward(zone: int) -> Transformer:
    return Transformer.from_crs(_GEOG, _gk(zone), always_xy=True)


@lru_cache(maxsize=64)
def _inverse(zone: int) -> Transformer:
    return Transformer.from_crs(_gk(zone), _GEOG, always_xy=True)


@lru_cache(maxsize=1)
def _to_wgs() -> Transformer:
    return Transformer.from_crs("EPSG:4284", "EPSG:4326", always_xy=True)


@lru_cache(maxsize=1)
def _from_wgs() -> Transformer:
    return Transformer.from_crs("EPSG:4326", "EPSG:4284", always_xy=True)


def split_km(meters: float) -> tuple[int, float]:
    """Километры сетки и остаток «по рамке», в метрах внутри километра."""
    km = math.floor(meters / 1000.0)
    return int(km), meters - km * 1000.0


def normalize_y(y: float) -> tuple[int | None, float]:
    """Снимает префикс зоны с ординаты вида 26 640 000."""
    if abs(y) < 1_000_000:
        return None, y
    sign = -1 if y < 0 else 1
    embedded = int(math.floor(abs(y) / 1_000_000))
    rest = abs(y) - embedded * 1_000_000
    if 1 <= embedded <= 60 and rest < 1_000_000:
        return embedded, sign * rest
    return None, y


def dms_to_decimal(degrees: int, minutes: int, seconds: float, *, negative: bool = False) -> float:
    if not 0 <= minutes <= 59:
        raise ValueError("Минуты должны быть от 0 до 59.")
    if not 0 <= seconds < 60:
        raise ValueError("Секунды должны быть от 0 до 60, не включая 60.")
    if abs(degrees) > 180:
        raise ValueError("Градусы вне диапазона.")
    value = abs(int(degrees)) + minutes / 60.0 + seconds / 3600.0
    if negative or int(degrees) < 0:
        value = -value
    return value


def decimal_to_dms(value: float) -> tuple[int, int, float, bool]:
    negative = value < 0
    rest = abs(value)
    degrees = int(math.floor(rest + 1e-12))
    minutes_full = (rest - degrees) * 60.0
    minutes = int(math.floor(minutes_full + 1e-10))
    seconds = round((minutes_full - minutes) * 60.0, 8)
    if seconds >= 59.99999995:
        seconds = 0.0
        minutes += 1
    if minutes >= 60:
        minutes = 0
        degrees += 1
    return degrees, minutes, seconds, negative


def check_geographic(longitude: float, latitude: float) -> None:
    if not -90.0 <= latitude <= 90.0:
        raise ValueError("Широта вне диапазона −90…90.")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("Долгота вне диапазона −180…180.")


def forward(longitude: float, latitude: float, zone: int | None = None) -> tuple[int, float, float]:
    """Возвращает зону, X (северное) и Y (восточное внутри зоны)."""
    check_geographic(longitude, latitude)
    if zone is None:
        zone = zone_from_longitude(longitude)
    else:
        central_meridian(zone)
    easting, northing = _forward(zone).transform(longitude, latitude)
    return zone, northing, easting


def inverse(x: float, y: float, zone: int | None = None) -> tuple[float, float, int]:
    """X, Y → долгота, широта СК-42 и зона, которая пошла в расчёт."""
    embedded, y = normalize_y(y)
    if zone is None:
        zone = embedded
    if zone is None:
        raise ValueError("Укажите зону Гаусса–Крюгера.")
    central_meridian(zone)
    longitude, latitude = _inverse(zone).transform(y, x)
    return longitude, latitude, zone


def to_wgs84(longitude: float, latitude: float) -> tuple[float, float]:
    check_geographic(longitude, latitude)
    return _to_wgs().transform(longitude, latitude)


def from_wgs84(longitude: float, latitude: float) -> tuple[float, float]:
    check_geographic(longitude, latitude)
    return _from_wgs().transform(longitude, latitude)
