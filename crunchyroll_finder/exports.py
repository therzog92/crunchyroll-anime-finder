"""CSV export helpers for catalog, watchlist, and watch history."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

CATALOG_COLUMNS = [
    "id",
    "title",
    "url",
    "watched",
    "on_watchlist",
    "is_new",
    "is_simulcast",
    "has_english_dub",
    "availability_status",
    "description",
    "season_count",
    "episode_count",
    "series_launch_year",
    "last_public",
    "tenant_categories",
    "audio_locales",
    "subtitle_locales",
    "awards",
    "content_descriptors",
    "maturity_rating",
    "availability_notes",
    "poster_url",
]

HISTORY_COLUMNS = [
    "date_played",
    "series_id",
    "series_title",
    "season_number",
    "episode_number",
    "episode_title",
    "episode_id",
    "fully_watched",
    "duration_ms",
    "duration_seconds",
    "estimated_watch_seconds",
]


def _join_list(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        return " | ".join(str(v) for v in value)
    return str(value)


def catalog_row(item: dict[str, Any], watched_ids: set[str], watchlist_ids: set[str]) -> dict[str, Any]:
    row = {col: item.get(col, "") for col in CATALOG_COLUMNS}
    row["watched"] = item.get("id") in watched_ids
    row["on_watchlist"] = item.get("id") in watchlist_ids
    row["tenant_categories"] = _join_list(item.get("tenant_categories"))
    row["audio_locales"] = _join_list(item.get("audio_locales"))
    row["subtitle_locales"] = _join_list(item.get("subtitle_locales"))
    row["awards"] = _join_list(item.get("awards"))
    row["content_descriptors"] = _join_list(item.get("content_descriptors"))
    return row


def history_row(entry: dict[str, Any], estimated_seconds: float) -> dict[str, Any]:
    return {
        "date_played": entry.get("date_played") or "",
        "series_id": entry.get("series_id") or "",
        "series_title": entry.get("series_title") or "",
        "season_number": entry.get("season_number") or "",
        "episode_number": entry.get("episode_number") or "",
        "episode_title": entry.get("episode_title") or "",
        "episode_id": entry.get("episode_id") or "",
        "fully_watched": entry.get("fully_watched", False),
        "duration_ms": entry.get("duration_ms") or "",
        "duration_seconds": entry.get("duration_seconds") or "",
        "estimated_watch_seconds": round(estimated_seconds, 1),
    }


def write_csv(path: Path | str, rows: Iterable[dict[str, Any]], columns: list[str]) -> int:
    path = Path(path)
    data = list(rows)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in data:
            writer.writerow({col: row.get(col, "") for col in columns})
    return len(data)
