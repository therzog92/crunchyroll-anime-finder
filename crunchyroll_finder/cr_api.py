"""Crunchyroll API: anonymous catalog + authenticated watch history."""

from __future__ import annotations

import base64
import uuid
from typing import Any

import requests

CLIENT_ID = "noaihdevm_6iyg0a8l0q"
CR_HOST = "https://www.crunchyroll.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class CRAuthError(Exception):
    pass


class CrunchyrollClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA})
        self.access_token: str | None = None
        self.account_id: str | None = None

    def _basic_auth(self) -> str:
        return "Basic " + base64.b64encode(f"{CLIENT_ID}:".encode()).decode()

    def login_with_etp_rt(self, etp_rt: str) -> None:
        """Exchange browser session cookie for API access token."""
        r = self.session.post(
            f"{CR_HOST}/auth/v1/token",
            headers={"Authorization": self._basic_auth()},
            cookies={"etp_rt": etp_rt.strip()},
            data={
                "grant_type": "etp_rt_cookie",
                "scope": "offline_access",
                "device_id": str(uuid.uuid4()),
                "device_name": "Chrome on Windows",
                "device_type": "com.crunchyroll.desktop.windows",
            },
            timeout=20,
        )
        if r.status_code != 200:
            raise CRAuthError(f"Login failed ({r.status_code}): {r.text[:300]}")
        data = r.json()
        self.access_token = data["access_token"]
        self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})
        self.account_id = self._fetch_account_id()

    def _fetch_account_id(self) -> str:
        if not self.access_token:
            raise CRAuthError("No access token")
        r = self.session.get(
            f"{CR_HOST}/accounts/v1/me",
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=15,
        )
        if r.status_code != 200:
            raise CRAuthError(f"Account lookup failed ({r.status_code}): {r.text[:300]}")
        return r.json()["account_id"]

    def _anon_token(self) -> str:
        r = self.session.post(
            f"{CR_HOST}/auth/v1/token",
            headers={"Authorization": self._basic_auth()},
            data={
                "grant_type": "client_id",
                "scope": "offline_access",
                "device_id": str(uuid.uuid4()),
                "device_type": "com.crunchyroll.static",
            },
            timeout=20,
        )
        r.raise_for_status()
        d = r.json()
        return f"{d.get('token_type', 'Bearer')} {d['access_token']}"

    def fetch_catalog(self) -> list[dict[str, Any]]:
        token = self._anon_token()
        headers = {"Authorization": token, "User-Agent": UA, "Accept": "*/*"}
        seen: set[str] = set()
        items: list[dict[str, Any]] = []

        for content_type in ("series", "movie_listing"):
            start = 0
            n = 100
            while True:
                r = self.session.get(
                    f"{CR_HOST}/content/v2/discover/browse",
                    headers=headers,
                    params={
                        "start": start,
                        "n": n,
                        "sort_by": "alphabetical",
                        "type": content_type,
                    },
                    timeout=30,
                )
                r.raise_for_status()
                batch = r.json().get("data") or []
                if not batch:
                    break
                for raw in batch:
                    cid = raw.get("id")
                    if cid and cid not in seen:
                        seen.add(cid)
                        items.append(flatten_catalog_item(raw))
                if len(batch) < n:
                    break
                start += n
        return items

    def fetch_watched_series_ids(self) -> set[str]:
        if not self.access_token or not self.account_id:
            raise CRAuthError("Not logged in")

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": UA,
            "Accept": "*/*",
        }
        api_base = CR_HOST
        next_url = f"{api_base}/content/v2/{self.account_id}/watch-history?page_size=1000"
        watched: set[str] = set()

        while next_url:
            r = self.session.get(next_url, headers=headers, timeout=30)
            if r.status_code != 200:
                raise CRAuthError(f"History fetch failed ({r.status_code}): {r.text[:300]}")
            body = r.json()
            for item in body.get("data") or []:
                panel = item.get("panel") or {}
                ep_meta = panel.get("episode_metadata") or {}
                series_id = ep_meta.get("series_id") or panel.get("id")
                if series_id:
                    watched.add(series_id)
            raw_next = None
            meta = body.get("meta") or body.get("pagination") or {}
            raw_next = meta.get("next_page") or body.get("next_page")
            if raw_next:
                if raw_next.startswith("/"):
                    next_url = api_base + raw_next
                elif not raw_next.startswith("http"):
                    next_url = api_base + "/" + raw_next
                else:
                    next_url = raw_next
            else:
                next_url = None
        return watched

    def fetch_watch_history(self) -> list[dict[str, Any]]:
        """Full watch history with play dates and duration when available."""
        if not self.access_token or not self.account_id:
            raise CRAuthError("Not logged in")

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": UA,
            "Accept": "*/*",
        }
        api_base = CR_HOST
        next_url = f"{api_base}/content/v2/{self.account_id}/watch-history?page_size=1000"
        entries: list[dict[str, Any]] = []

        while next_url:
            r = self.session.get(next_url, headers=headers, timeout=30)
            if r.status_code != 200:
                raise CRAuthError(f"History fetch failed ({r.status_code}): {r.text[:300]}")
            body = r.json()
            for item in body.get("data") or []:
                parsed = parse_watch_history_item(item)
                if parsed:
                    entries.append(parsed)
            raw_next = None
            meta = body.get("meta") or body.get("pagination") or {}
            raw_next = meta.get("next_page") or body.get("next_page")
            if raw_next:
                if raw_next.startswith("/"):
                    next_url = api_base + raw_next
                elif not raw_next.startswith("http"):
                    next_url = api_base + "/" + raw_next
                else:
                    next_url = raw_next
            else:
                next_url = None
        return entries

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": UA,
            "Accept": "*/*",
        }

    def add_to_watchlist(self, content_id: str) -> None:
        if not self.access_token or not self.account_id:
            raise CRAuthError("Not logged in")
        url = f"{CR_HOST}/content/v2/{self.account_id}/watchlist"
        r = self.session.post(
            url,
            headers={**self._auth_headers(), "Content-Type": "application/json"},
            json={"content_id": content_id},
            timeout=20,
        )
        if r.status_code not in (200, 201, 204):
            raise CRAuthError(f"Watchlist add failed ({r.status_code}): {r.text[:300]}")

    def remove_from_watchlist(self, content_id: str) -> None:
        if not self.access_token or not self.account_id:
            raise CRAuthError("Not logged in")
        url = f"{CR_HOST}/content/v2/{self.account_id}/watchlist/{content_id}"
        r = self.session.delete(
            url,
            headers=self._auth_headers(),
            timeout=20,
        )
        if r.status_code not in (200, 204):
            raise CRAuthError(f"Watchlist remove failed ({r.status_code}): {r.text[:300]}")

    def fetch_watchlist_ids(self) -> set[str]:
        if not self.access_token or not self.account_id:
            raise CRAuthError("Not logged in")
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": UA,
            "Accept": "*/*",
        }
        ids: set[str] = set()
        start = 0
        n = 100
        while True:
            r = self.session.get(
                f"{CR_HOST}/content/v2/discover/{self.account_id}/watchlist",
                headers=headers,
                params={"order": "desc", "n": n, "start": start},
                timeout=30,
            )
            if r.status_code != 200:
                raise CRAuthError(f"Watchlist fetch failed ({r.status_code}): {r.text[:300]}")
            batch = r.json().get("data") or []
            if not batch:
                break
            for item in batch:
                sid = extract_series_id_from_watchlist_item(item)
                if sid:
                    ids.add(sid)
            if len(batch) < n:
                break
            start += n
        return ids


def parse_watch_history_item(item: dict[str, Any]) -> dict[str, Any] | None:
    panel = item.get("panel") or {}
    if not panel:
        return None

    ep_meta = panel.get("episode_metadata") or {}
    movie_meta = panel.get("movie_metadata") or {}
    duration_ms = (
        panel.get("duration_ms")
        or ep_meta.get("duration_ms")
        or movie_meta.get("duration_ms")
        or 0
    )
    series_id = ep_meta.get("series_id") or panel.get("id") or ""
    series_title = ep_meta.get("series_title") or panel.get("title") or ""

    return {
        "series_id": series_id,
        "series_title": series_title,
        "episode_title": panel.get("title") or "",
        "episode_id": panel.get("id") or "",
        "season_number": ep_meta.get("season_number"),
        "episode_number": ep_meta.get("episode_number"),
        "date_played": item.get("date_played"),
        "fully_watched": bool(item.get("fully_watched")),
        "duration_ms": duration_ms,
        "duration_seconds": (duration_ms / 1000) if duration_ms else None,
    }


def compute_fully_watched_ids(catalog: list[dict[str, Any]], history: list[dict[str, Any]]) -> set[str]:
    """Series where unique watched episodes >= catalog episode_count."""
    episodes_by_series: dict[str, set[tuple]] = {}
    for entry in history:
        sid = entry.get("series_id")
        if not sid:
            continue
        if sid not in episodes_by_series:
            episodes_by_series[sid] = set()
        eid = entry.get("episode_id")
        if eid:
            episodes_by_series[sid].add(("id", str(eid)))
        else:
            episodes_by_series[sid].add((
                "ep",
                str(entry.get("season_number") or ""),
                str(entry.get("episode_number") or ""),
            ))

    by_id = {item["id"]: item for item in catalog}
    fully: set[str] = set()
    for sid, watched_eps in episodes_by_series.items():
        item = by_id.get(sid)
        if not item:
            continue
        total = int(item.get("episode_count") or 0)
        if total > 0 and len(watched_eps) >= total:
            fully.add(sid)
    return fully


def watch_seconds(entry: dict[str, Any]) -> float:
    """Estimate watch time for one history row (seconds)."""
    default = 24 * 60
    duration = entry.get("duration_seconds")
    if duration:
        return float(duration) if entry.get("fully_watched") else float(duration) * 0.5
    return float(default if entry.get("fully_watched") else default * 0.5)


def extract_series_id_from_watchlist_item(item: dict[str, Any]) -> str | None:
    """Map a watchlist API item to the same series id used in browse/catalog."""
    panel = item.get("panel") or item
    key = panel.get("linked_resource_key") or item.get("linked_resource_key") or ""
    if "/series/" in key:
        return key.rsplit("/", 1)[-1]

    ep_meta = panel.get("episode_metadata") or {}
    if ep_meta.get("series_id"):
        return ep_meta["series_id"]

    content_type = panel.get("type") or item.get("type")
    panel_id = panel.get("id") or item.get("id")
    if content_type in ("series", "movie_listing") and panel_id:
        return panel_id

    series_meta = panel.get("series_metadata") or {}
    linked = series_meta.get("linked_guid")
    if linked:
        return linked

    return panel_id


def extract_poster_url(raw: dict[str, Any]) -> str:
    images = raw.get("images") or {}
    best_url = ""
    best_w = 0
    for key in ("poster_wide", "poster_tall", "promo_image"):
        for group in images.get(key) or []:
            if not isinstance(group, list):
                continue
            for img in group:
                if not isinstance(img, dict):
                    continue
                w = img.get("width") or 0
                src = img.get("source") or ""
                if src and w >= best_w:
                    best_w = w
                    best_url = src
    return best_url


def flatten_catalog_item(raw: dict[str, Any]) -> dict[str, Any]:
    meta = raw.get("series_metadata") or {}
    audio = meta.get("audio_locales") or []
    subs = meta.get("subtitle_locales") or []
    maturity = meta.get("extended_maturity_rating") or {}
    rating = maturity.get("rating")
    if meta.get("maturity_ratings"):
        rating = meta["maturity_ratings"][0]
    awards_raw = meta.get("awards") or []
    award_texts = [a.get("text", "") for a in awards_raw if isinstance(a, dict) and a.get("text")]
    sid = raw.get("id", "")
    return {
        "id": sid,
        "title": raw.get("title", ""),
        "url": f"https://www.crunchyroll.com/series/{sid}" if sid else "",
        "is_new": bool(raw.get("new")),
        "is_simulcast": bool(meta.get("is_simulcast")),
        "has_english_dub": "en-US" in audio,
        "is_subbed": bool(meta.get("is_subbed")),
        "is_dubbed": bool(meta.get("is_dubbed")),
        "availability_status": meta.get("availability_status", ""),
        "availability_notes": meta.get("availability_notes", ""),
        "description": (raw.get("description") or "").replace("\n", " ").strip(),
        "season_count": meta.get("season_count", 0),
        "episode_count": meta.get("episode_count", 0),
        "series_launch_year": meta.get("series_launch_year", ""),
        "last_public": raw.get("last_public", ""),
        "tenant_categories": meta.get("tenant_categories") or [],
        "content_descriptors": meta.get("content_descriptors") or [],
        "maturity_rating": rating or "",
        "maturity_ratings": meta.get("maturity_ratings") or [],
        "extended_rating": maturity.get("rating", ""),
        "awards": award_texts,
        "audio_locales": audio,
        "subtitle_locales": subs,
        "poster_url": extract_poster_url(raw),
    }
