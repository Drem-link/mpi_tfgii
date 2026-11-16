"""Свёртка строк для поиска. Одинаково работает в SQLite и PostgreSQL."""

from __future__ import annotations


def fold(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.casefold().replace("ё", "е").split())


def like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
