# Crunchyroll Anime Finder

A desktop app to browse Crunchyroll’s full anime catalog, filter by category, manage your watchlist, and explore your watch history — with a dark Crunchyroll-inspired UI.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

---

## Screenshots

> Drop your images into [`docs/screenshots/`](docs/screenshots/) and update the paths below.

### Main window

Browse the catalog, filter, and open series details.

<!-- Replace with your screenshot -->
<!-- ![Main window](docs/screenshots/main-window.png) -->
`docs/screenshots/main-window.png`

### Series detail panel

Poster, audio/subtitles, description, and watchlist actions.

<!-- ![Detail panel](docs/screenshots/detail-panel.png) -->
`docs/screenshots/detail-panel.png`

### Watch time chart

Monthly hours with per-series breakdown on click.

<!-- ![Watch time](docs/screenshots/watch-time.png) -->
`docs/screenshots/watch-time.png`

### Category filters

Collapsible category sidebar with sort by count or A–Z.

<!-- ![Categories](docs/screenshots/categories.png) -->
`docs/screenshots/categories.png`

---

## Features

- **Full catalog** — paginated browse (~2,000+ titles), cached locally
- **Connect** — sign in via browser; syncs watched series, watchlist, and history
- **Filters** — unwatched, watchlist only, new, simulcast, dub, available, search (title + description + categories)
- **Categories** — multi-select genre sidebar
- **Watched markers** — `✕` started, `XX` all episodes watched (from history)
- **Watchlist** — add/remove in-app
- **Watch time** — monthly chart + per-series breakdown; export CSV
- **Export** — catalog, filtered view, watchlist, watched, or history to CSV

---

## Quick start (from source)

### Requirements

- Windows 10/11
- Python 3.10+

### Install

```powershell
cd crunchyroll_finder
pip install -r requirements.txt
playwright install chromium
```

### Run

```powershell
python -m crunchyroll_finder
```

Or:

```powershell
python run.py
```

User data and cache are stored in `%USERPROFILE%\.crunchyroll_finder\` (not in this repo).

---

## Windows release (.exe)

Download the latest **`CrunchyrollAnimeFinder-Windows.zip`** from [Releases](https://github.com/therzog92/crunchyroll-anime-finder/releases).

1. Unzip anywhere
2. Run `CrunchyrollAnimeFinder.exe`
3. On first **Connect**, Chromium may be installed automatically for login (requires internet)

### Build the release yourself

```powershell
.\scripts\build_release.ps1
```

Output: `dist\CrunchyrollAnimeFinder\` and `dist\CrunchyrollAnimeFinder-Windows.zip`

---

## Project layout

```
crunchyroll_finder/          # Python package (app, API, UI)
docs/screenshots/            # README images
scripts/                     # build + dev utilities
run.py                       # dev / PyInstaller entry
requirements.txt
requirements-build.txt
```

---

## Connect & privacy

- Login opens Chromium via Playwright; only your session cookie is saved locally
- No data is sent anywhere except Crunchyroll’s official APIs
- Not affiliated with Crunchyroll / Sony

---

## Use

No license file — do whatever you want with the code.
