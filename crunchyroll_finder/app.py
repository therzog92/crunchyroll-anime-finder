#!/usr/bin/env python3
"""Crunchyroll Anime Finder — dark Crunchyroll-themed UI."""

from __future__ import annotations

import io
import threading
import tkinter as tk
import webbrowser
from collections import Counter, defaultdict
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import requests
from crunchyroll_finder.browser_login import BrowserLoginError, capture_etp_rt
from crunchyroll_finder.config import (
    CATALOG_CACHE,
    WATCHED_CACHE,
    WATCHLIST_CACHE,
    WATCH_HISTORY_CACHE,
    load_config,
    load_json,
    locale_list,
    save_config,
    save_json,
)
from crunchyroll_finder.cr_api import CRAuthError, CrunchyrollClient, compute_fully_watched_ids, watch_seconds
from crunchyroll_finder.exports import CATALOG_COLUMNS, HISTORY_COLUMNS, catalog_row, history_row, write_csv
from crunchyroll_finder.ui_scrollbar import hscrollbar, vscrollbar

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

# Crunchyroll-inspired palette
CR_ORANGE = "#F47521"
CR_BLACK = "#000000"
CR_DARK = "#0D0D0D"
CR_PANEL = "#141414"
CR_SURFACE = "#1F1F1F"
CR_BORDER = "#2E2E2E"
CR_TEXT = "#FFFFFF"
CR_MUTED = "#9B9B9B"
CR_ROW_ALT = "#181818"


COLUMNS = (
    "has_watched",
    "on_watchlist",
    "title",
    "is_new",
    "is_simulcast",
    "has_english_dub",
    "availability_status",
    "season_count",
    "episode_count",
    "series_launch_year",
    "last_public",
    "categories",
)
COL_HEADERS = {
    "has_watched": "✓",
    "on_watchlist": "♥",
    "title": "Title",
    "is_new": "New",
    "is_simulcast": "Simulcast",
    "has_english_dub": "Dub",
    "availability_status": "Status",
    "season_count": "S",
    "episode_count": "E",
    "series_launch_year": "Year",
    "last_public": "Updated",
    "categories": "Categories",
}


def _mark(value: bool) -> str:
    return "✕" if value else ""


class LoginDialog(tk.Toplevel):
    def __init__(self, parent, on_success):
        super().__init__(parent)
        self.on_success = on_success
        self.title("Connect to Crunchyroll")
        self.configure(bg=CR_PANEL)
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)
        self._busy = False

        frm = tk.Frame(self, bg=CR_PANEL, padx=16, pady=16)
        frm.pack(fill=tk.BOTH, expand=True)

        tk.Label(frm, text="Sign in to Crunchyroll", font=("Segoe UI", 14, "bold"),
                 fg=CR_TEXT, bg=CR_PANEL).pack(anchor=tk.W, pady=(0, 8))
        tk.Label(frm, text="A browser window will open. Sign in normally — we'll capture your session automatically.",
                 fg=CR_MUTED, bg=CR_PANEL, wraplength=440, justify=tk.LEFT).pack(anchor=tk.W)

        self.status_var = tk.StringVar(value="")
        tk.Label(frm, textvariable=self.status_var, fg=CR_ORANGE, bg=CR_PANEL).pack(anchor=tk.W, pady=8)

        self.browser_btn = tk.Button(frm, text="Sign in with Browser", command=self._sign_in_browser,
                                     bg=CR_ORANGE, fg=CR_TEXT, activebackground="#d96518",
                                     activeforeground=CR_TEXT, relief=tk.FLAT, padx=14, pady=8, cursor="hand2")
        self.browser_btn.pack(anchor=tk.W, pady=8)

        tk.Button(frm, text="Cancel", command=self.destroy, bg=CR_SURFACE, fg=CR_TEXT,
                  relief=tk.FLAT, padx=12, pady=6, cursor="hand2").pack(anchor=tk.E, pady=(12, 0))
        self.geometry("480x220")
        self.after(150, self._sign_in_browser)

    def _set_busy(self, busy: bool, status: str):
        self._busy = busy
        self.browser_btn.config(state=tk.DISABLED if busy else tk.NORMAL)
        self.status_var.set(status)

    def _sign_in_browser(self):
        if self._busy:
            return
        self._set_busy(True, "Opening browser…")

        def work():
            try:
                cookie = capture_etp_rt()
                self.after(0, lambda: self._set_busy(True, "Syncing watch history…"))
                self._finish_login(cookie)
            except (BrowserLoginError, CRAuthError) as e:
                self.after(0, lambda: self._done_err(str(e)))
            except Exception as e:
                self.after(0, lambda: self._done_err(str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _finish_login(self, cookie: str):
        def work():
            try:
                client = CrunchyrollClient()
                client.login_with_etp_rt(cookie)
                watched = client.fetch_watched_series_ids()
                watchlist = client.fetch_watchlist_ids()
                history = client.fetch_watch_history()
                cfg = load_config()
                cfg["etp_rt"] = cookie
                cfg["account_id"] = client.account_id
                cfg["last_sync"] = datetime.now().isoformat()
                save_config(cfg)
                save_json(WATCHED_CACHE, sorted(watched))
                save_json(WATCHLIST_CACHE, sorted(watchlist))
                save_json(WATCH_HISTORY_CACHE, {"updated": datetime.now().isoformat(), "entries": history})
                self.after(0, lambda: self._done_ok(len(watched), len(watchlist)))
            except (CRAuthError, Exception) as e:
                self.after(0, lambda: self._done_err(str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _done_ok(self, count: int, wl_count: int = 0):
        self._set_busy(False, "")
        msg = f"Synced {count} watched series."
        if wl_count:
            msg += f"\n{wl_count} on your watchlist."
        messagebox.showinfo("Connected", msg, parent=self)
        self.on_success()
        self.destroy()

    def _done_err(self, msg: str):
        self._set_busy(False, "")
        messagebox.showerror("Login failed", msg, parent=self)


class WatchTimeDialog(tk.Toplevel):
    def __init__(self, parent, entries: list[dict]):
        super().__init__(parent)
        self.entries = entries
        self.title("My Watch Time")
        self.configure(bg=CR_PANEL)
        self.geometry("720x540")
        self.minsize(600, 420)
        self.transient(parent)

        self._monthly_data = self._monthly_hours()
        self._bar_regions: list[tuple[str, float, tuple[float, float, float, float]]] = []
        self._hover_month: str | None = None

        frm = tk.Frame(self, bg=CR_PANEL, padx=16, pady=16)
        frm.pack(fill=tk.BOTH, expand=True)

        total_hours = sum(self._monthly_data.values())
        total_eps = len(entries)
        months = sorted(self._monthly_data.keys())
        range_txt = (
            f"{self._format_month(months[0])} – {self._format_month(months[-1])}"
            if months else "No history"
        )

        tk.Label(
            frm, text="Watch time by month", font=("Segoe UI", 14, "bold"),
            fg=CR_TEXT, bg=CR_PANEL,
        ).pack(anchor=tk.W)
        tk.Label(
            frm,
            text=f"{total_hours:.1f} hours  ·  {total_eps:,} plays  ·  {range_txt}",
            fg=CR_MUTED, bg=CR_PANEL, font=("Segoe UI", 10),
        ).pack(anchor=tk.W, pady=(4, 4))
        self.tooltip_var = tk.StringVar(value="Hover a month for hours  ·  click for series breakdown")
        tk.Label(
            frm, textvariable=self.tooltip_var, fg=CR_ORANGE, bg=CR_PANEL, font=("Segoe UI", 9),
        ).pack(anchor=tk.W, pady=(0, 8))

        chart_wrap = tk.Frame(frm, bg=CR_SURFACE)
        chart_wrap.pack(fill=tk.BOTH, expand=True)
        self.chart = tk.Canvas(chart_wrap, bg=CR_SURFACE, highlightthickness=0, height=280)
        self.chart.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.chart.bind("<Configure>", lambda _e: self._draw_chart())
        self.chart.bind("<Motion>", self._on_chart_motion)
        self.chart.bind("<Leave>", self._on_chart_leave)
        self.chart.bind("<Button-1>", self._on_chart_click)

        btn_row = tk.Frame(frm, bg=CR_PANEL)
        btn_row.pack(fill=tk.X, pady=(12, 0))
        tk.Button(
            btn_row, text="Export watch history CSV", command=self._export_csv,
            bg=CR_ORANGE, fg=CR_TEXT, activebackground="#d96518", relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"), padx=12, pady=8, cursor="hand2",
        ).pack(side=tk.LEFT)
        tk.Button(
            btn_row, text="Close", command=self.destroy,
            bg=CR_SURFACE, fg=CR_TEXT, relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
        ).pack(side=tk.RIGHT)

        self.after(100, self._draw_chart)

    @staticmethod
    def _format_month(key: str) -> str:
        """YYYY-MM → MM/YY"""
        if len(key) >= 7 and "-" in key:
            year, month = key.split("-", 1)
            return f"{month}/{year[2:]}"
        return key

    def _monthly_hours(self) -> dict[str, float]:
        monthly: dict[str, float] = defaultdict(float)
        for entry in self.entries:
            key = self._entry_month_key(entry)
            if not key:
                continue
            monthly[key] += watch_seconds(entry) / 3600
        return dict(monthly)

    def _entry_month_key(self, entry: dict) -> str | None:
        played = entry.get("date_played")
        if not played:
            return None
        try:
            dt = datetime.fromisoformat(played.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt.strftime("%Y-%m")

    def _series_for_month(self, month_key: str) -> list[dict]:
        by_series: dict[str, dict] = {}
        for entry in self.entries:
            if self._entry_month_key(entry) != month_key:
                continue
            sid = entry.get("series_id") or entry.get("series_title") or "unknown"
            title = entry.get("series_title") or "Unknown"
            if sid not in by_series:
                by_series[sid] = {"title": title, "hours": 0.0, "episodes": 0}
            by_series[sid]["hours"] += watch_seconds(entry) / 3600
            by_series[sid]["episodes"] += 1
        return sorted(by_series.values(), key=lambda x: (-x["hours"], x["title"].lower()))

    def _hit_test(self, x: float, y: float) -> str | None:
        for month, _hours, (x0, y0, x1, y1) in self._bar_regions:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return month
        return None

    def _on_chart_motion(self, event):
        month = self._hit_test(event.x, event.y)
        if month != self._hover_month:
            self._hover_month = month
            self._draw_chart()
        if month:
            hours = self._monthly_data[month]
            self.tooltip_var.set(f"{self._format_month(month)}: {hours:.1f} hours  (click for breakdown)")
            self.chart.config(cursor="hand2")
        else:
            self.tooltip_var.set("Hover a month for hours  ·  click for series breakdown")
            self.chart.config(cursor="")

    def _on_chart_leave(self, _event):
        self._hover_month = None
        self.tooltip_var.set("Hover a month for hours  ·  click for series breakdown")
        self.chart.config(cursor="")
        self._draw_chart()

    def _on_chart_click(self, event):
        month = self._hit_test(event.x, event.y)
        if month:
            MonthBreakdownDialog(self, month, self._series_for_month(month), self._monthly_data[month])

    def _draw_chart(self):
        c = self.chart
        c.delete("all")
        self._bar_regions.clear()
        monthly = self._monthly_data
        w = max(c.winfo_width(), 400)
        h = max(c.winfo_height(), 200)
        if not monthly:
            c.create_text(w // 2, h // 2, text="No watch history data", fill=CR_MUTED, font=("Segoe UI", 11))
            return

        months = sorted(monthly.keys())
        values = [monthly[m] for m in months]
        max_val = max(values) or 1
        left, right, top, bottom = 48, 16, 16, 72
        chart_w = w - left - right
        chart_h = h - top - bottom
        bar_gap = 4
        bar_w = max(8, (chart_w - bar_gap * (len(months) - 1)) / len(months))
        month_font = ("Segoe UI", 9)
        year_font = ("Segoe UI", 9)

        c.create_line(left, top, left, top + chart_h, fill=CR_BORDER)
        c.create_line(left, top + chart_h, w - right, top + chart_h, fill=CR_BORDER)
        c.create_text(left - 6, top + 4, text=f"{max_val:.0f}h", fill=CR_MUTED, font=("Segoe UI", 8), anchor=tk.E)

        for i, month in enumerate(months):
            val = values[i]
            bar_h = (val / max_val) * chart_h if max_val else 0
            x0 = left + i * (bar_w + bar_gap)
            y0 = top + chart_h - bar_h
            x1 = x0 + bar_w
            y1 = top + chart_h
            fill = "#ff8c42" if month == self._hover_month else CR_ORANGE
            c.create_rectangle(x0, y0, x1, y1, fill=fill, outline="")
            self._bar_regions.append((month, val, (x0, y0, x1, y1)))
            cx = (x0 + x1) / 2
            month_num = self._month_number(month)
            c.create_text(cx, y1 + 16, text=month_num, fill=CR_MUTED, font=month_font, anchor=tk.N)

        self._draw_year_brackets(c, months, bar_w, bar_gap, left, top + chart_h, year_font)

    @staticmethod
    def _month_number(key: str) -> str:
        if len(key) >= 7 and "-" in key:
            return str(int(key.split("-", 1)[1]))
        return key

    def _draw_year_brackets(
        self,
        canvas: tk.Canvas,
        months: list[str],
        bar_w: float,
        bar_gap: float,
        left: float,
        axis_y: float,
        year_font: tuple,
    ) -> None:
        if not months:
            return

        bracket_y = axis_y + 34
        tick_h = 5
        year_y = bracket_y + 12

        groups: list[tuple[str, int, int]] = []
        current_year = months[0].split("-", 1)[0]
        start_idx = 0
        for i, month in enumerate(months):
            year = month.split("-", 1)[0]
            if year != current_year:
                groups.append((current_year, start_idx, i - 1))
                current_year = year
                start_idx = i
        groups.append((current_year, start_idx, len(months) - 1))

        for year, start_idx, end_idx in groups:
            x0 = left + start_idx * (bar_w + bar_gap)
            x1 = left + end_idx * (bar_w + bar_gap) + bar_w
            canvas.create_line(x0, bracket_y, x1, bracket_y, fill=CR_MUTED, width=1)
            canvas.create_line(x0, bracket_y, x0, bracket_y - tick_h, fill=CR_MUTED, width=1)
            canvas.create_line(x1, bracket_y, x1, bracket_y - tick_h, fill=CR_MUTED, width=1)
            canvas.create_text((x0 + x1) / 2, year_y, text=year, fill=CR_MUTED, font=year_font)

    def _export_csv(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="Export watch history",
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile="crunchyroll_watch_history.csv",
        )
        if not path:
            return
        rows = [history_row(e, watch_seconds(e)) for e in self.entries]
        count = write_csv(path, rows, HISTORY_COLUMNS)
        messagebox.showinfo("Exported", f"Saved {count:,} rows to:\n{path}", parent=self)


class MonthBreakdownDialog(tk.Toplevel):
    def __init__(self, parent: WatchTimeDialog, month_key: str, series_rows: list[dict], total_hours: float):
        super().__init__(parent)
        self.title(f"Watch time — {WatchTimeDialog._format_month(month_key)}")
        self.configure(bg=CR_PANEL)
        self.geometry("560x420")
        self.minsize(440, 300)
        self.transient(parent)

        frm = tk.Frame(self, bg=CR_PANEL, padx=16, pady=16)
        frm.pack(fill=tk.BOTH, expand=True)

        total_eps = sum(r["episodes"] for r in series_rows)
        tk.Label(
            frm,
            text=f"{WatchTimeDialog._format_month(month_key)}  ·  {total_hours:.1f} hours  ·  {total_eps} episodes",
            font=("Segoe UI", 12, "bold"), fg=CR_TEXT, bg=CR_PANEL,
        ).pack(anchor=tk.W, pady=(0, 10))

        table_wrap = tk.Frame(frm, bg=CR_SURFACE)
        table_wrap.pack(fill=tk.BOTH, expand=True)
        cols = ("title", "hours", "episodes")
        tree = ttk.Treeview(table_wrap, columns=cols, show="headings", height=12)
        vsb = vscrollbar(table_wrap, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.heading("title", text="Series")
        tree.heading("hours", text="Hours")
        tree.heading("episodes", text="Episodes")
        tree.column("title", width=300, minwidth=160, anchor=tk.W)
        tree.column("hours", width=80, minwidth=60, anchor=tk.CENTER)
        tree.column("episodes", width=80, minwidth=60, anchor=tk.CENTER)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        table_wrap.rowconfigure(0, weight=1)
        table_wrap.columnconfigure(0, weight=1)

        for i, row in enumerate(series_rows):
            tree.insert(
                "", tk.END,
                values=(row["title"], f"{row['hours']:.1f}", row["episodes"]),
                tags=("odd",) if i % 2 else (),
            )
        tree.tag_configure("odd", background=CR_ROW_ALT)

        tk.Button(
            frm, text="Close", command=self.destroy,
            bg=CR_SURFACE, fg=CR_TEXT, relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
        ).pack(anchor=tk.E, pady=(12, 0))


class ExportDialog(tk.Toplevel):
    def __init__(self, parent, app: "AnimeFinderApp"):
        super().__init__(parent)
        self.app = app
        self.title("Export data")
        self.configure(bg=CR_PANEL)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frm = tk.Frame(self, bg=CR_PANEL, padx=16, pady=16)
        frm.pack(fill=tk.BOTH, expand=True)

        tk.Label(frm, text="Export to CSV", font=("Segoe UI", 13, "bold"), fg=CR_TEXT, bg=CR_PANEL).pack(anchor=tk.W)
        tk.Label(
            frm, text="Choose which dataset to export.", fg=CR_MUTED, bg=CR_PANEL,
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, pady=(4, 12))

        self.export_var = tk.StringVar(value="catalog")
        options = [
            ("catalog", "Full catalog (all series)"),
            ("filtered", "Current filtered view"),
            ("watchlist", "Watchlist titles"),
            ("watched", "Watched series IDs"),
            ("history", "Watch history (episodes + time)"),
        ]
        for value, label in options:
            tk.Radiobutton(
                frm, text=label, variable=self.export_var, value=value,
                bg=CR_PANEL, fg=CR_TEXT, selectcolor=CR_SURFACE,
                activebackground=CR_PANEL, activeforeground=CR_ORANGE,
                font=("Segoe UI", 10), anchor=tk.W,
            ).pack(anchor=tk.W, pady=2)

        btn_row = tk.Frame(frm, bg=CR_PANEL)
        btn_row.pack(fill=tk.X, pady=(16, 0))
        tk.Button(
            btn_row, text="Export", command=self._export,
            bg=CR_ORANGE, fg=CR_TEXT, activebackground="#d96518", relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"), padx=12, pady=8, cursor="hand2",
        ).pack(side=tk.LEFT)
        tk.Button(
            btn_row, text="Cancel", command=self.destroy,
            bg=CR_SURFACE, fg=CR_TEXT, relief=tk.FLAT, padx=12, pady=8, cursor="hand2",
        ).pack(side=tk.RIGHT)

    def _export(self):
        kind = self.export_var.get()
        defaults = {
            "catalog": "crunchyroll_catalog.csv",
            "filtered": "crunchyroll_filtered.csv",
            "watchlist": "crunchyroll_watchlist.csv",
            "watched": "crunchyroll_watched.csv",
            "history": "crunchyroll_watch_history.csv",
        }
        path = filedialog.asksaveasfilename(
            parent=self, title="Export CSV",
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile=defaults.get(kind, "export.csv"),
        )
        if not path:
            return

        app = self.app
        try:
            if kind == "catalog":
                rows = [
                    catalog_row(item, app.watched_ids, app.watchlist_ids)
                    for item in app.catalog
                ]
                count = write_csv(path, rows, CATALOG_COLUMNS)
            elif kind == "filtered":
                rows = [catalog_row(item, app.watched_ids, app.watchlist_ids) for item in app.filtered]
                count = write_csv(path, rows, CATALOG_COLUMNS)
            elif kind == "watchlist":
                by_id = {item["id"]: item for item in app.catalog}
                rows = [
                    catalog_row(by_id[sid], app.watched_ids, app.watchlist_ids)
                    for sid in sorted(app.watchlist_ids)
                    if sid in by_id
                ]
                count = write_csv(path, rows, CATALOG_COLUMNS)
            elif kind == "watched":
                by_id = {item["id"]: item for item in app.catalog}
                rows = [
                    catalog_row(by_id[sid], app.watched_ids, app.watchlist_ids)
                    for sid in sorted(app.watched_ids)
                    if sid in by_id
                ]
                count = write_csv(path, rows, CATALOG_COLUMNS)
            else:
                entries = app._get_watch_history_entries(refresh=False)
                rows = [history_row(e, watch_seconds(e)) for e in entries]
                count = write_csv(path, rows, HISTORY_COLUMNS)
        except Exception as e:
            messagebox.showerror("Export failed", str(e), parent=self)
            return

        messagebox.showinfo("Exported", f"Saved {count:,} rows to:\n{path}", parent=self)
        self.destroy()


class AnimeFinderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Crunchyroll Anime Finder")
        self.geometry("1440x820")
        self.minsize(1100, 600)
        self.configure(bg=CR_BLACK)

        self.client = CrunchyrollClient()
        self.catalog: list[dict] = []
        self.watched_ids: set[str] = set()
        self.watchlist_ids: set[str] = set()
        self.filtered: list[dict] = []
        self.category_vars: dict[str, tk.BooleanVar] = {}
        self._sort_column: str | None = None
        self._sort_reverse_current = False
        self._action_status_after_id = None
        self.logged_in = False
        self._poster_photo = None
        self._selected_row: dict | None = None
        self._cat_visible = False
        self._suppress_select = False
        self._watch_history: list[dict] = []
        self.fully_watched_ids: set[str] = set()

        self._setup_theme()
        self.option_add("*TCombobox*Listbox*Background", CR_SURFACE)
        self.option_add("*TCombobox*Listbox*Foreground", CR_TEXT)
        self.option_add("*TCombobox*Listbox*selectBackground", CR_ORANGE)
        self.option_add("*TCombobox*Listbox*selectForeground", CR_TEXT)
        self._build_ui()
        self._load_cached_data()
        self._ensure_client_from_config()
        self.after(200, self._draw_collapsed_tab)
        self.after(200, self._startup_prompt_login)

    def _setup_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=CR_BLACK, foreground=CR_TEXT, fieldbackground=CR_SURFACE, bordercolor=CR_BORDER)
        style.configure("TFrame", background=CR_BLACK)
        style.configure("TPanedwindow", background=CR_BLACK)
        style.configure("TLabelframe", background=CR_PANEL, foreground=CR_MUTED, bordercolor=CR_BORDER)
        style.configure("TLabelframe.Label", background=CR_PANEL, foreground=CR_MUTED, font=("Segoe UI", 9))
        style.configure("TButton", background=CR_SURFACE, foreground=CR_TEXT, padding=(12, 6), borderwidth=0)
        style.map("TButton", background=[("active", CR_BORDER)])
        style.configure("Accent.TButton", background=CR_ORANGE, foreground=CR_TEXT, padding=(14, 7), font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#d96518")])
        style.configure("Chrome.TButton", background=CR_SURFACE, foreground=CR_TEXT, padding=(14, 7), borderwidth=0)
        style.map("Chrome.TButton", background=[("active", CR_BORDER)])
        style.configure("Treeview", background=CR_SURFACE, foreground=CR_TEXT, fieldbackground=CR_SURFACE,
                        rowheight=28, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=CR_PANEL, foreground=CR_MUTED,
                        relief=tk.FLAT, font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", CR_ORANGE)], foreground=[("selected", CR_TEXT)])
        style.configure("TCheckbutton", background=CR_BLACK, foreground=CR_TEXT)
        style.map("TCheckbutton", background=[("active", CR_BLACK)])
        style.configure(
            "CatSort.TCombobox",
            fieldbackground=CR_SURFACE,
            background=CR_SURFACE,
            foreground=CR_ORANGE,
            arrowcolor=CR_ORANGE,
            bordercolor=CR_BORDER,
            lightcolor=CR_BORDER,
            darkcolor=CR_BORDER,
            selectbackground=CR_ORANGE,
            selectforeground=CR_TEXT,
        )
        style.map(
            "CatSort.TCombobox",
            fieldbackground=[("readonly", CR_SURFACE), ("disabled", CR_SURFACE)],
            foreground=[("readonly", CR_ORANGE), ("disabled", CR_MUTED)],
            arrowcolor=[("readonly", CR_ORANGE), ("disabled", CR_MUTED)],
        )

    def _chrome_divider(self, parent) -> tk.Frame:
        return tk.Frame(parent, bg=CR_BORDER, height=1)

    def _pill_button(self, parent, text: str, command, **kwargs) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command,
            bg=CR_SURFACE, fg=CR_TEXT, activebackground=CR_BORDER, activeforeground=CR_TEXT,
            relief=tk.FLAT, font=("Segoe UI", 9), padx=14, pady=7, cursor="hand2",
            bd=0, highlightthickness=0, **kwargs,
        )

    def _build_ui(self):
        # Seamless top chrome (header + options + filters)
        top = tk.Frame(self, bg=CR_BLACK)
        top.pack(fill=tk.X, padx=16, pady=(12, 8))

        header = tk.Frame(top, bg=CR_BLACK)
        header.pack(fill=tk.X)

        brand = tk.Frame(header, bg=CR_BLACK)
        brand.pack(side=tk.LEFT)
        tk.Label(brand, text="crunchyroll", font=("Segoe UI", 18, "bold"), fg=CR_ORANGE, bg=CR_BLACK).pack(side=tk.LEFT)
        tk.Label(brand, text="  anime finder", font=("Segoe UI", 12), fg=CR_MUTED, bg=CR_BLACK).pack(side=tk.LEFT, pady=(4, 0))

        btn_frame = tk.Frame(header, bg=CR_BLACK)
        btn_frame.pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Connect", command=self._show_login, style="Chrome.TButton").pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(btn_frame, text="Refresh Catalog", command=self._refresh_catalog, style="Chrome.TButton").pack(side=tk.LEFT, padx=(6, 0))

        self.status_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self.status_var, fg=CR_MUTED, bg=CR_BLACK, font=("Segoe UI", 9)).pack(
            side=tk.RIGHT, padx=(0, 20)
        )

        self._chrome_divider(top).pack(fill=tk.X, pady=(10, 0))

        options = tk.Frame(top, bg=CR_BLACK)
        options.pack(fill=tk.X, pady=(10, 0))
        self.watch_time_btn = self._pill_button(
            options, text="Show my watch time", command=self._show_watch_time, state=tk.DISABLED,
        )
        self.watch_time_btn.pack(side=tk.LEFT, padx=(0, 8))
        self._pill_button(options, text="Export data…", command=self._show_export_dialog).pack(side=tk.LEFT)
        self.action_status_var = tk.StringVar(value="")
        tk.Label(
            options, textvariable=self.action_status_var, fg=CR_MUTED, bg=CR_BLACK,
            font=("Segoe UI", 9), anchor=tk.E,
        ).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(16, 0))

        self._chrome_divider(top).pack(fill=tk.X, pady=(10, 0))

        filters = tk.Frame(top, bg=CR_BLACK)
        filters.pack(fill=tk.X, pady=(10, 0))

        self.var_unwatched = tk.BooleanVar(value=False)
        self.var_new = tk.BooleanVar(value=False)
        self.var_simulcast = tk.BooleanVar(value=False)
        self.var_en_dub = tk.BooleanVar(value=False)
        self.var_available = tk.BooleanVar(value=True)
        self.var_watchlist_only = tk.BooleanVar(value=False)

        for var, label in [
            (self.var_unwatched, "Unwatched only"),
            (self.var_watchlist_only, "Watchlist only"),
            (self.var_new, "New"),
            (self.var_simulcast, "Simulcast"),
            (self.var_en_dub, "English dub"),
            (self.var_available, "Available"),
        ]:
            ttk.Checkbutton(filters, text=label, variable=var, command=self._apply_filters).pack(side=tk.LEFT, padx=10)

        tk.Label(filters, text="Search:", fg=CR_MUTED, bg=CR_BLACK).pack(side=tk.LEFT, padx=(20, 4))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filters())
        search_entry = tk.Entry(
            filters, textvariable=self.search_var, bg=CR_SURFACE, fg=CR_TEXT,
            insertbackground=CR_TEXT, relief=tk.FLAT, width=22,
            highlightthickness=1, highlightbackground=CR_BORDER, highlightcolor=CR_ORANGE,
        )
        search_entry.pack(side=tk.LEFT, ipady=5)

        # Main body
        self.body_paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        self.body_paned.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

        # Categories sidebar
        self.cat_outer = tk.Frame(self.body_paned, bg=CR_PANEL, width=220)

        cat_header = tk.Frame(self.cat_outer, bg=CR_PANEL)
        cat_header.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(cat_header, text="CATEGORIES", font=("Segoe UI", 9, "bold"),
                 fg=CR_MUTED, bg=CR_PANEL, anchor=tk.W).pack(side=tk.LEFT)
        self.cat_toggle_btn = tk.Button(
            cat_header, text="◀", command=self._toggle_cat_panel,
            bg=CR_SURFACE, fg=CR_MUTED, relief=tk.FLAT, font=("Segoe UI", 8),
            padx=6, pady=0, cursor="hand2",
        )
        self.cat_toggle_btn.pack(side=tk.RIGHT, padx=(4, 0))
        self.cat_sort_var = tk.StringVar(value="By count")
        tk.Label(
            cat_header, text="Sort", fg=CR_ORANGE, bg=CR_PANEL,
            font=("Segoe UI", 8, "bold"),
        ).pack(side=tk.RIGHT, padx=(4, 2))
        cat_sort = ttk.Combobox(
            cat_header, textvariable=self.cat_sort_var, values=["By count", "A-Z"],
            state="readonly", width=8, font=("Segoe UI", 8), style="CatSort.TCombobox",
        )
        cat_sort.pack(side=tk.RIGHT, padx=4)
        cat_sort.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_category_panel())
        tk.Button(cat_header, text="Clear", command=self._clear_categories,
                  bg=CR_SURFACE, fg=CR_MUTED, relief=tk.FLAT, font=("Segoe UI", 8),
                  cursor="hand2").pack(side=tk.RIGHT, padx=4)

        cat_scroll_wrap = tk.Frame(self.cat_outer, bg=CR_PANEL)
        cat_scroll_wrap.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.cat_canvas = tk.Canvas(cat_scroll_wrap, bg=CR_PANEL, highlightthickness=0, width=200)
        cat_vsb = vscrollbar(cat_scroll_wrap, command=self.cat_canvas.yview)
        self.cat_inner = tk.Frame(self.cat_canvas, bg=CR_PANEL)
        self.cat_inner.bind("<Configure>", lambda e: self.cat_canvas.configure(scrollregion=self.cat_canvas.bbox("all")))
        self.cat_canvas.create_window((0, 0), window=self.cat_inner, anchor=tk.NW)
        self.cat_canvas.configure(yscrollcommand=cat_vsb.set)
        self.cat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cat_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._bind_canvas_mousewheel(self.cat_canvas, self.cat_canvas)
        self._bind_canvas_mousewheel(self.cat_canvas, cat_vsb)
        self._bind_canvas_mousewheel(self.cat_canvas, self.cat_inner)

        # Collapsed category tab (default visible)
        self.cat_collapsed_tab = tk.Frame(self.body_paned, bg=CR_PANEL, width=36)
        self.cat_collapsed_canvas = tk.Canvas(
            self.cat_collapsed_tab, bg=CR_PANEL, highlightthickness=0, width=36, cursor="hand2",
        )
        self.cat_collapsed_canvas.pack(fill=tk.BOTH, expand=True)
        self.cat_collapsed_canvas.bind("<Button-1>", lambda _e: self._toggle_cat_panel())
        self.cat_collapsed_canvas.bind("<Configure>", lambda _e: self._draw_collapsed_tab())
        self.body_paned.add(self.cat_collapsed_tab, weight=0)

        # Table
        table_outer = tk.Frame(self.body_paned, bg=CR_PANEL)
        self.body_paned.add(table_outer, weight=3)
        table_inner = tk.Frame(table_outer, bg=CR_SURFACE)
        table_inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.tree = ttk.Treeview(table_inner, columns=COLUMNS, show="headings", selectmode="browse")
        vsb = vscrollbar(table_inner, command=self.tree.yview)
        hsb = hscrollbar(table_inner, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        # Fixed widths + minwidth; stretch=False prevents title column collapsing on resize
        col_widths = {
            "has_watched": (40, 34),
            "on_watchlist": (36, 30),
            "title": (280, 160),
            "is_new": (44, 36),
            "is_simulcast": (72, 60),
            "has_english_dub": (44, 36),
            "availability_status": (80, 64),
            "season_count": (40, 32),
            "episode_count": (40, 32),
            "series_launch_year": (52, 44),
            "last_public": (100, 80),
            "categories": (200, 100),
        }
        for col in COLUMNS:
            self.tree.heading(col, text=COL_HEADERS[col], command=lambda c=col: self._sort_by_column(c))
            w, minw = col_widths.get(col, (80, 50))
            anchor = tk.W if col in ("title", "categories") else tk.CENTER
            self.tree.column(col, width=w, minwidth=minw, anchor=anchor, stretch=False)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_inner.rowconfigure(0, weight=1)
        table_inner.columnconfigure(0, weight=1)
        self.tree.tag_configure("watched", foreground=CR_MUTED)
        self.tree.tag_configure("odd", background=CR_ROW_ALT)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._open_selected_url)

        # Detail / hero panel
        detail_outer = tk.Frame(self.body_paned, bg=CR_PANEL, width=360)
        self.body_paned.add(detail_outer, weight=0)
        detail_card = tk.Frame(detail_outer, bg=CR_DARK)
        detail_card.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Action buttons pinned to bottom — always visible
        action_row = tk.Frame(detail_card, bg=CR_DARK)
        action_row.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=(8, 12))
        tk.Button(action_row, text="▶  OPEN ON CRUNCHYROLL", command=self._open_selected_url,
                  bg=CR_ORANGE, fg=CR_TEXT, activebackground="#d96518", activeforeground=CR_TEXT,
                  relief=tk.FLAT, font=("Segoe UI", 10, "bold"), padx=12, pady=10, cursor="hand2").pack(fill=tk.X)
        self.wl_container = tk.Frame(action_row, bg=CR_DARK)
        self.wl_container.pack(fill=tk.X, pady=(6, 0))
        self.watchlist_btn = tk.Button(
            self.wl_container, text="+ Add to Watchlist", command=self._toggle_watchlist,
            bg=CR_SURFACE, fg=CR_TEXT, activebackground=CR_BORDER, relief=tk.FLAT,
            font=("Segoe UI", 9), padx=12, pady=8, cursor="hand2", state=tk.DISABLED,
        )
        self.watchlist_btn.pack(fill=tk.X)

        self.wl_confirm_frame = tk.Frame(self.wl_container, bg=CR_DARK)
        self.wl_confirm_banner = tk.Label(
            self.wl_confirm_frame, text="Are you sure?", bg=CR_ORANGE, fg=CR_TEXT,
            font=("Segoe UI", 9, "bold"), pady=5,
        )
        self.wl_confirm_banner.pack(fill=tk.X)
        self.wl_confirm_actions = tk.Frame(self.wl_confirm_frame, bg=CR_DARK)
        self.wl_confirm_actions.pack(fill=tk.X, pady=(4, 0))
        self.wl_confirm_actions.columnconfigure(0, weight=1)
        self.wl_confirm_actions.columnconfigure(1, weight=1)
        self.wl_yes_btn = tk.Button(
            self.wl_confirm_actions, text="Yes, remove", command=self._confirm_remove_watchlist,
            bg=CR_ORANGE, fg=CR_TEXT, activebackground="#d96518", relief=tk.FLAT,
            font=("Segoe UI", 9, "bold"), pady=8, cursor="hand2",
        )
        self.wl_yes_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.wl_cancel_btn = tk.Button(
            self.wl_confirm_actions, text="Cancel", command=self._cancel_remove_watchlist,
            bg=CR_SURFACE, fg=CR_TEXT, activebackground=CR_BORDER, relief=tk.FLAT,
            font=("Segoe UI", 9), pady=8, cursor="hand2",
        )
        self.wl_cancel_btn.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        # Single scroll area for poster, title, audio/subs, description, metadata
        detail_scroll_wrap = tk.Frame(detail_card, bg=CR_DARK)
        detail_scroll_wrap.pack(fill=tk.BOTH, expand=True)
        self.detail_canvas = tk.Canvas(detail_scroll_wrap, bg=CR_DARK, highlightthickness=0)
        detail_vsb = vscrollbar(detail_scroll_wrap, command=self.detail_canvas.yview)
        self.detail_inner = tk.Frame(self.detail_canvas, bg=CR_DARK)
        self.detail_inner.bind(
            "<Configure>",
            lambda e: self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox("all")),
        )
        self._detail_window = self.detail_canvas.create_window((0, 0), window=self.detail_inner, anchor=tk.NW, width=320)
        self.detail_canvas.configure(yscrollcommand=detail_vsb.set)
        self.detail_canvas.bind("<Configure>", self._on_detail_canvas_resize)
        self.detail_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(12, 0), pady=(12, 0))
        detail_vsb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12), pady=(12, 0))

        self.poster_frame = tk.Frame(self.detail_inner, bg=CR_SURFACE, height=200)
        self.poster_frame.pack(fill=tk.X, pady=(0, 6))
        self.poster_frame.pack_propagate(False)
        self.poster_label = tk.Label(
            self.poster_frame, bg=CR_SURFACE, fg=CR_MUTED, text="Select a series",
            font=("Segoe UI", 9),
        )
        self.poster_label.pack(expand=True, fill=tk.BOTH)

        self.detail_title = tk.Label(
            self.detail_inner, text="", font=("Segoe UI", 14, "bold"),
            fg=CR_TEXT, bg=CR_DARK, wraplength=310, justify=tk.LEFT,
        )
        self.detail_title.pack(anchor=tk.W, pady=(4, 0))

        self.detail_top_meta = tk.Frame(self.detail_inner, bg=CR_DARK)
        self.detail_top_meta.pack(fill=tk.X, pady=(6, 0))
        self.detail_audio_lbl = tk.Label(
            self.detail_top_meta, text="", font=("Segoe UI", 9), fg=CR_MUTED,
            bg=CR_DARK, wraplength=310, justify=tk.LEFT, anchor=tk.W,
        )
        self.detail_audio_lbl.pack(fill=tk.X)
        self.detail_subs_lbl = tk.Label(
            self.detail_top_meta, text="", font=("Segoe UI", 9), fg=CR_MUTED,
            bg=CR_DARK, wraplength=310, justify=tk.LEFT, anchor=tk.W,
        )
        self.detail_subs_lbl.pack(fill=tk.X, pady=(2, 0))

        self.detail_desc_lbl = tk.Label(
            self.detail_inner, text="", font=("Segoe UI", 10), fg=CR_TEXT, bg=CR_DARK,
            wraplength=310, justify=tk.LEFT, anchor=tk.W,
        )
        self.detail_desc_lbl.pack(fill=tk.X, pady=(8, 0))

        self.detail_meta_frame = tk.Frame(self.detail_inner, bg=CR_DARK)
        self.detail_meta_frame.pack(fill=tk.X, pady=(0, 12))

        self._bind_canvas_mousewheel(self.detail_canvas, self.detail_canvas)
        self._bind_canvas_mousewheel(self.detail_canvas, detail_vsb)
        self._bind_canvas_mousewheel(self.detail_canvas, self.detail_inner)

    def _on_detail_canvas_resize(self, event):
        self.detail_canvas.itemconfig(self._detail_window, width=event.width)

    def _bind_canvas_mousewheel(self, canvas: tk.Canvas, widget: tk.Widget) -> None:
        """Bind mouse wheel to scroll a canvas (including canvas window children)."""

        def on_wheel(event):
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
            elif event.delta:
                canvas.yview_scroll(int(-event.delta / 120), "units")

        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(seq, on_wheel)
        for child in widget.winfo_children():
            self._bind_canvas_mousewheel(canvas, child)

    def _bind_text_mousewheel(self, widget: tk.Text) -> None:
        def on_wheel(event):
            if event.num == 4:
                widget.yview_scroll(-1, "units")
            elif event.num == 5:
                widget.yview_scroll(1, "units")
            elif event.delta:
                widget.yview_scroll(int(-event.delta / 120), "units")
            return "break"

        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(seq, on_wheel)

    def _draw_collapsed_tab(self):
        c = self.cat_collapsed_canvas
        c.delete("all")
        w = max(c.winfo_width(), 36)
        h = max(c.winfo_height(), 200)
        c.create_text(
            w // 2, h // 2, text="▶  CATEGORIES", fill=CR_ORANGE,
            font=("Segoe UI", 9, "bold"), angle=90,
        )

    def _toggle_cat_panel(self):
        if self._cat_visible:
            self.body_paned.forget(self.cat_outer)
            self.body_paned.insert(0, self.cat_collapsed_tab, weight=0)
            self._cat_visible = False
        else:
            self.body_paned.forget(self.cat_collapsed_tab)
            self.body_paned.insert(0, self.cat_outer, weight=0)
            self._cat_visible = True

    def _meta_row(self, parent, label: str, value: str):
        if not value:
            return
        tk.Label(parent, text=label, font=("Segoe UI", 9, "bold"), fg=CR_TEXT,
                 bg=CR_DARK, anchor=tk.W).pack(fill=tk.X, pady=(6, 2))
        tk.Label(parent, text=value, font=("Segoe UI", 9), fg=CR_MUTED,
                 bg=CR_DARK, wraplength=310, justify=tk.LEFT, anchor=tk.W).pack(fill=tk.X)

    def _render_detail_meta(self, row: dict):
        audio = ", ".join(locale_list(row.get("audio_locales") or []))
        subs = ", ".join(locale_list(row.get("subtitle_locales") or []))
        if audio:
            self.detail_audio_lbl.config(text=f"Audio: {audio}")
        else:
            self.detail_audio_lbl.config(text="")
        if subs:
            self.detail_subs_lbl.config(text=f"Subtitles: {subs}")
        else:
            self.detail_subs_lbl.config(text="")

        for child in self.detail_meta_frame.winfo_children():
            child.destroy()
        awards = ", ".join(row.get("awards") or [])
        genres = " · ".join(row.get("tenant_categories") or [])
        advisories = row.get("content_descriptors") or []
        rating = row.get("extended_rating") or row.get("maturity_rating") or ""
        advisory = ""
        if rating or advisories:
            parts = []
            if rating:
                parts.append(f"{rating}+")
            parts.extend(advisories)
            advisory = " · ".join(parts)
        notes = row.get("availability_notes") or ""
        year = row.get("series_launch_year") or ""
        seasons = row.get("season_count") or 0
        eps = row.get("episode_count") or 0

        if awards:
            self._meta_row(self.detail_meta_frame, "Awards", awards)
        if advisory:
            self._meta_row(self.detail_meta_frame, "Content Advisory", advisory)
        if genres:
            self._meta_row(self.detail_meta_frame, "Genres", genres)
        stats = f"{year}  ·  {seasons} season{'s' if seasons != 1 else ''}  ·  {eps} episode{'s' if eps != 1 else ''}"
        self._meta_row(self.detail_meta_frame, "Info", stats)
        if notes:
            self._meta_row(self.detail_meta_frame, "Availability", notes)
        self._bind_canvas_mousewheel(self.detail_canvas, self.detail_inner)

    def _show_wl_normal(self):
        self.wl_confirm_frame.pack_forget()
        self.watchlist_btn.pack(fill=tk.X)

    def _show_wl_confirm(self):
        self.watchlist_btn.pack_forget()
        self.wl_confirm_frame.pack(fill=tk.X)

    def _update_watchlist_button(self, row: dict | None):
        self._show_wl_normal()
        if not row or not self.logged_in:
            self.watchlist_btn.config(state=tk.DISABLED, text="+ Add to Watchlist")
            return
        self.watchlist_btn.config(state=tk.NORMAL)
        if row.get("id") in self.watchlist_ids:
            self.watchlist_btn.config(text="− Remove from Watchlist")
        else:
            self.watchlist_btn.config(text="+ Add to Watchlist")

    def _rebuild_category_panel(self):
        for child in self.cat_inner.winfo_children():
            child.destroy()
        self.category_vars.clear()
        counts: Counter[str] = Counter()
        for item in self.catalog:
            for cat in item.get("tenant_categories") or []:
                counts[cat] += 1
        if self.cat_sort_var.get() == "A-Z":
            ordered = sorted(counts.items(), key=lambda x: x[0].lower())
        else:
            ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))
        for row, (cat, count) in enumerate(ordered):
            var = tk.BooleanVar(value=False)
            self.category_vars[cat] = var
            tk.Checkbutton(
                self.cat_inner, text=f"{cat}  ({count})", variable=var, command=self._apply_filters,
                bg=CR_PANEL, fg=CR_TEXT, selectcolor=CR_SURFACE, activebackground=CR_PANEL,
                activeforeground=CR_ORANGE, font=("Segoe UI", 9), anchor=tk.W, relief=tk.FLAT,
            ).grid(row=row, column=0, sticky=tk.W, pady=2, padx=4)
        self._bind_canvas_mousewheel(self.cat_canvas, self.cat_inner)

    def _clear_categories(self):
        for var in self.category_vars.values():
            var.set(False)
        self._apply_filters()

    def _selected_categories(self) -> set[str]:
        return {cat for cat, var in self.category_vars.items() if var.get()}

    def _ensure_client_from_config(self):
        cfg = load_config()
        if not cfg.get("etp_rt"):
            self._set_logged_in(False)
            return

        def work():
            try:
                self.client.login_with_etp_rt(cfg["etp_rt"])
                self.after(0, lambda: self._set_logged_in(True))
            except CRAuthError:
                self.after(0, lambda: self._set_logged_in(False))

        threading.Thread(target=work, daemon=True).start()

    def _set_logged_in(self, logged_in: bool):
        self.logged_in = logged_in
        self.watchlist_btn.config(state=tk.NORMAL if logged_in else tk.DISABLED)
        self.watch_time_btn.config(state=tk.NORMAL if logged_in else tk.DISABLED)

    def _get_watch_history_entries(self, refresh: bool = False) -> list[dict]:
        if not refresh and self._watch_history:
            return self._watch_history
        cached = load_json(WATCH_HISTORY_CACHE, {})
        if not refresh and cached.get("entries"):
            self._watch_history = cached["entries"]
            return self._watch_history
        if not self.logged_in:
            return self._watch_history
        try:
            entries = self.client.fetch_watch_history()
            self._watch_history = entries
            save_json(WATCH_HISTORY_CACHE, {"updated": datetime.now().isoformat(), "entries": entries})
        except CRAuthError:
            pass
        return self._watch_history

    def _show_watch_time(self):
        if not self.logged_in:
            messagebox.showinfo("Login required", "Connect your Crunchyroll account first.")
            self._show_login()
            return

        self.watch_time_btn.config(state=tk.DISABLED)
        self.status_var.set("Loading watch history…")

        def work():
            try:
                entries = self._get_watch_history_entries(refresh=True)
                self.after(0, lambda: WatchTimeDialog(self, entries))
            except CRAuthError as e:
                self.after(0, lambda: messagebox.showerror("Watch time", str(e)))
            finally:
                self.after(0, lambda: self.watch_time_btn.config(state=tk.NORMAL))
                self.after(0, self._update_status)

        threading.Thread(target=work, daemon=True).start()

    def _show_export_dialog(self):
        ExportDialog(self, self)

    def _startup_prompt_login(self):
        cfg = load_config()
        if cfg.get("etp_rt"):
            self._sync_history_silent(cfg["etp_rt"])
        elif messagebox.askyesno("Connect?", "Connect Crunchyroll to mark watched series and use the watchlist?"):
            self._show_login()
        if not self.catalog:
            self._refresh_catalog()

    def _show_login(self):
        LoginDialog(self, on_success=self._on_login_success)

    def _on_login_success(self):
        self.watched_ids = set(load_json(WATCHED_CACHE, []))
        self.watchlist_ids = set(load_json(WATCHLIST_CACHE, []))
        cached_history = load_json(WATCH_HISTORY_CACHE, {})
        self._watch_history = cached_history.get("entries") or []
        self._rebuild_fully_watched()
        self._ensure_client_from_config()
        self._sync_watchlist_silent()
        self._apply_filters()
        self._update_status()

    def _sync_history_silent(self, etp_rt: str):
        def work():
            try:
                self.client.login_with_etp_rt(etp_rt)
                watched = self.client.fetch_watched_series_ids()
                save_json(WATCHED_CACHE, sorted(watched))
                watchlist = self.client.fetch_watchlist_ids()
                save_json(WATCHLIST_CACHE, sorted(watchlist))
                history = self.client.fetch_watch_history()
                save_json(WATCH_HISTORY_CACHE, {"updated": datetime.now().isoformat(), "entries": history})
                self.after(0, lambda: self._set_watch_history(history))
                self.after(0, lambda: self._set_watched(watched))
                self.after(0, lambda: self._set_watchlist(watchlist))
                self.after(0, lambda: self._set_logged_in(True))
            except CRAuthError:
                self.after(0, lambda: self._set_logged_in(False))

        threading.Thread(target=work, daemon=True).start()

    def _sync_watchlist_silent(self):
        if not self.logged_in:
            return

        def work():
            try:
                wl = self.client.fetch_watchlist_ids()
                save_json(WATCHLIST_CACHE, sorted(wl))
                self.after(0, lambda: self._set_watchlist(wl))
            except CRAuthError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _rebuild_fully_watched(self):
        self.fully_watched_ids = compute_fully_watched_ids(self.catalog, self._watch_history)

    def _set_watch_history(self, entries: list[dict]):
        self._watch_history = entries
        self._rebuild_fully_watched()

    def _set_watchlist(self, ids):
        self.watchlist_ids = set(ids)
        self._apply_filters()
        self._update_watchlist_button(self._selected_row)
        self._update_status()

    def _set_watched(self, watched):
        self.watched_ids = set(watched)
        self._apply_filters()
        self._update_status()

    def _load_cached_data(self):
        cached = load_json(CATALOG_CACHE, {})
        if cached.get("items"):
            self.catalog = cached["items"]
        self.watched_ids = set(load_json(WATCHED_CACHE, []))
        self.watchlist_ids = set(load_json(WATCHLIST_CACHE, []))
        cached_history = load_json(WATCH_HISTORY_CACHE, {})
        self._watch_history = cached_history.get("entries") or []
        self._rebuild_fully_watched()
        self._rebuild_category_panel()
        self._apply_filters()
        self._update_status()

    def _refresh_catalog(self):
        self.status_var.set("Refreshing catalog…")
        self.config(cursor="watch")

        def work():
            try:
                items = CrunchyrollClient().fetch_catalog()
                save_json(CATALOG_CACHE, {"updated": datetime.now().isoformat(), "items": items})
                self.after(0, lambda: self._catalog_ready(items))
            except Exception as e:
                self.after(0, lambda: self._catalog_error(str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _catalog_ready(self, items):
        self.config(cursor="")
        self.catalog = items
        self._rebuild_fully_watched()
        self._rebuild_category_panel()
        self._apply_filters()
        self._update_status()

    def _catalog_error(self, msg):
        self.config(cursor="")
        messagebox.showerror("Catalog error", msg)
        self._update_status()

    def _apply_filters(self):
        rows = []
        q = self.search_var.get().strip().lower()
        selected_cats = self._selected_categories()

        for item in self.catalog:
            watched = item["id"] in self.watched_ids
            on_wl = item["id"] in self.watchlist_ids
            if self.var_unwatched.get() and watched:
                continue
            if self.var_watchlist_only.get() and not on_wl:
                continue
            if self.var_new.get() and not item.get("is_new"):
                continue
            if self.var_simulcast.get() and not item.get("is_simulcast"):
                continue
            if self.var_en_dub.get() and not item.get("has_english_dub"):
                continue
            if self.var_available.get() and item.get("availability_status") != "available":
                continue
            item_cats = set(item.get("tenant_categories") or [])
            if selected_cats and not (item_cats & selected_cats):
                continue
            if q:
                blob = (
                    item.get("title", "")
                    + " "
                    + " ".join(item_cats)
                    + " "
                    + (item.get("description") or "")
                ).lower()
                if q not in blob:
                    continue
            row = dict(item)
            row["has_watched"] = watched
            row["fully_watched"] = item["id"] in self.fully_watched_ids
            row["on_watchlist"] = on_wl
            row["categories"] = " · ".join(item.get("tenant_categories") or [])
            rows.append(row)

        self.filtered = rows
        self._apply_current_sort()
        preserve_id = self._selected_row.get("id") if self._selected_row else None
        self._fill_tree(preserve_id=preserve_id)

    def _sort_key(self, col: str, row: dict):
        if col in ("has_watched", "on_watchlist"):
            return (row.get("fully_watched", False), row.get(col, False))
        if col in ("is_new", "is_simulcast", "has_english_dub"):
            return row.get(col, False)
        if col in ("season_count", "episode_count", "series_launch_year"):
            return row.get(col) or 0
        return str(row.get(col, "")).lower()

    def _apply_current_sort(self) -> None:
        if not self._sort_column:
            return
        self.filtered.sort(
            key=lambda row: self._sort_key(self._sort_column, row),
            reverse=self._sort_reverse_current,
        )

    def _show_action_status(self, message: str, clear_after_ms: int = 8000) -> None:
        self.action_status_var.set(message)
        if self._action_status_after_id:
            self.after_cancel(self._action_status_after_id)
            self._action_status_after_id = None
        if message and clear_after_ms > 0:
            self._action_status_after_id = self.after(clear_after_ms, lambda: self.action_status_var.set(""))

    def _format_cell(self, col: str, row: dict) -> str:
        if col == "has_watched":
            if row.get("fully_watched"):
                return "XX"
            return "✕" if row.get("has_watched") else ""
        if col == "on_watchlist":
            return "♥" if row.get("on_watchlist") else ""
        if col in ("is_new", "is_simulcast", "has_english_dub"):
            return "✕" if row.get(col) else ""
        v = row.get(col, "")
        if col == "last_public" and v:
            return str(v)[:10]
        return str(v) if v not in (None, False) else ""

    def _fill_tree(self, preserve_id: str | None = None):
        self._suppress_select = True
        self.tree.delete(*self.tree.get_children())
        select_iid = None
        for i, row in enumerate(self.filtered):
            vals = [self._format_cell(col, row) for col in COLUMNS]
            tags = []
            if row.get("has_watched"):
                tags.append("watched")
            if i % 2:
                tags.append("odd")
            iid = self.tree.insert("", tk.END, values=vals, tags=tuple(tags))
            if preserve_id and row.get("id") == preserve_id:
                select_iid = iid
        self._suppress_select = False
        if select_iid:
            self.tree.selection_set(select_iid)
            self.tree.focus(select_iid)
            self._on_select()

    def _sort_by_column(self, col):
        if self._sort_column == col:
            self._sort_reverse_current = not self._sort_reverse_current
        else:
            self._sort_column = col
            self._sort_reverse_current = False
        self._apply_current_sort()
        preserve_id = self._selected_row.get("id") if self._selected_row else None
        self._fill_tree(preserve_id=preserve_id)

    def _get_selected_row(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            return None
        idx = self.tree.index(sel[0])
        if 0 <= idx < len(self.filtered):
            return self.filtered[idx]
        return None

    def _on_select(self, _event=None):
        if self._suppress_select:
            return
        row = self._get_selected_row()
        self._selected_row = row
        if not row:
            self.detail_audio_lbl.config(text="")
            self.detail_subs_lbl.config(text="")
            self.detail_desc_lbl.config(text="")
            return
        self.detail_title.config(text=row.get("title", ""))
        self.detail_desc_lbl.config(text=row.get("description") or "No description available.")
        self._render_detail_meta(row)
        self.detail_canvas.yview_moveto(0)
        self._load_poster(row.get("poster_url") or "")
        self._update_watchlist_button(row)

    def _load_poster(self, url: str):
        if not url or not Image:
            self._poster_photo = None
            self.poster_label.config(image="", text="No image — click Refresh Catalog")
            return

        def work():
            try:
                r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                img = Image.open(io.BytesIO(r.content))
                # Fit inside 316×188 hero area (16:9), never squash to a sliver
                target_w, target_h = 316, 188
                img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self.after(0, lambda: self._show_poster(photo))
            except Exception:
                self.after(0, lambda: self.poster_label.config(image="", text="Image unavailable"))

        threading.Thread(target=work, daemon=True).start()

    def _show_poster(self, photo):
        self._poster_photo = photo
        self.poster_label.config(image=photo, text="", compound=tk.CENTER)

    def _open_selected_url(self, _event=None):
        row = self._get_selected_row() or self._selected_row
        if row and row.get("url"):
            webbrowser.open(row["url"])

    def _toggle_watchlist(self):
        if not self.logged_in:
            messagebox.showinfo("Login required", "Connect your Crunchyroll account first.")
            self._show_login()
            return
        row = self._selected_row or self._get_selected_row()
        if not row:
            messagebox.showinfo("No selection", "Select a series first.")
            return
        if row.get("id") in self.watchlist_ids:
            self._show_wl_confirm()
        else:
            self._execute_watchlist_add(row)

    def _confirm_remove_watchlist(self):
        row = self._selected_row or self._get_selected_row()
        if not row:
            self._show_wl_normal()
            return
        self._show_wl_normal()
        self._execute_watchlist_remove(row)

    def _cancel_remove_watchlist(self):
        self._show_wl_normal()
        self._update_watchlist_button(self._selected_row)

    def _execute_watchlist_add(self, row: dict):
        content_id = row.get("id", "")
        title = row.get("title", "")
        self.watchlist_btn.config(state=tk.DISABLED)

        def work():
            try:
                self.client.add_to_watchlist(content_id)
                self.watchlist_ids.add(content_id)
                save_json(WATCHLIST_CACHE, sorted(self.watchlist_ids))
                self.after(0, lambda: self._apply_filters())
                self.after(0, lambda: self._update_watchlist_button(row))
                self.after(0, lambda: self._show_action_status(f'"{title}" was successfully added to watchlist'))
                self.after(0, self._update_status)
            except CRAuthError as e:
                self.after(0, lambda: self._show_action_status(f"Failed to add to watchlist: {e}"))
                self.after(0, lambda: self._update_watchlist_button(row))

        threading.Thread(target=work, daemon=True).start()

    def _execute_watchlist_remove(self, row: dict):
        content_id = row.get("id", "")
        title = row.get("title", "")
        self.watchlist_btn.config(state=tk.DISABLED)

        def work():
            try:
                self.client.remove_from_watchlist(content_id)
                self.watchlist_ids.discard(content_id)
                save_json(WATCHLIST_CACHE, sorted(self.watchlist_ids))
                self.after(0, lambda: self._apply_filters())
                self.after(0, lambda: self._update_watchlist_button(row))
                self.after(0, lambda: self._show_action_status(f'"{title}" was successfully removed from watchlist'))
                self.after(0, self._update_status)
            except CRAuthError as e:
                self.after(0, lambda: self._show_action_status(f"Failed to remove from watchlist: {e}"))
                self.after(0, lambda: self._update_watchlist_button(row))

        threading.Thread(target=work, daemon=True).start()

    def _update_status(self):
        cfg = load_config()
        sync = f"  ·  synced {cfg['last_sync'][:16]}" if cfg.get("last_sync") else ""
        logged = "connected" if self.logged_in else "not connected"
        n_cats = len(self._selected_categories())
        cat_note = f"  ·  {n_cats} categories" if n_cats else ""
        self.status_var.set(
            f"{logged}  ·  {len(self.catalog)} series  ·  {len(self.watched_ids)} watched  ·  "
            f"{len(self.watchlist_ids)} watchlist  ·  {len(self.filtered)} showing{cat_note}{sync}"
        )


def main():
    app = AnimeFinderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
