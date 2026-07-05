import json
from pathlib import Path

APP_DIR = Path.home() / ".crunchyroll_finder"
CONFIG_FILE = APP_DIR / "config.json"
CATALOG_CACHE = APP_DIR / "catalog_cache.json"
WATCHED_CACHE = APP_DIR / "watched_series_ids.json"
WATCHLIST_CACHE = APP_DIR / "watchlist_series_ids.json"
WATCH_HISTORY_CACHE = APP_DIR / "watch_history.json"

# Locale code → display name (matches Crunchyroll UI)
LOCALE_NAMES = {
    "ja-JP": "Japanese",
    "en-US": "English",
    "en-IN": "English (India)",
    "id-ID": "Bahasa Indonesia",
    "ms-MY": "Bahasa Melayu",
    "ca-ES": "Català",
    "de-DE": "Deutsch",
    "es-419": "Español (América Latina)",
    "es-ES": "Español (España)",
    "fr-FR": "Français",
    "it-IT": "Italiano",
    "pl-PL": "Polski",
    "pt-BR": "Português (Brasil)",
    "pt-PT": "Português (Portugal)",
    "vi-VN": "Tiếng Việt",
    "tr-TR": "Türkçe",
    "ru-RU": "Русский",
    "ar-SA": "العربية",
    "hi-IN": "हिंदी",
    "ta-IN": "தமிழ்",
    "te-IN": "తెలుగు",
    "zh-CN": "中文 (普通话)",
    "zh-HK": "中文 (粵語)",
    "zh-TW": "中文 (國語)",
    "ko-KR": "한국어",
    "th-TH": "ไทย",
}


def locale_list(codes: list[str]) -> list[str]:
    return [LOCALE_NAMES.get(c, c) for c in (codes or [])]


def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_dirs()
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def save_config(data: dict) -> None:
    ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data) -> None:
    ensure_dirs()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
