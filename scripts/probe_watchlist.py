import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crunchyroll_finder.config import load_config
from crunchyroll_finder.cr_api import CrunchyrollClient

cfg = load_config()
c = CrunchyrollClient()
c.login_with_etp_rt(cfg["etp_rt"])

for label, url in [
    ("discover", f"https://www.crunchyroll.com/content/v2/discover/{c.account_id}/watchlist?order=desc&n=2&start=0"),
    ("direct", f"https://www.crunchyroll.com/content/v2/{c.account_id}/watchlist?n=2&start=0"),
]:
    r = c.session.get(
        url,
        headers={"Authorization": f"Bearer {c.access_token}", "User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    print(label, "status", r.status_code)
    if r.status_code == 200:
        data = r.json().get("data") or []
        out = Path(__file__).parent / f"watchlist_sample_{label}.json"
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print("saved", out, "items", len(data))
        if data:
            item = data[0]
            panel = item.get("panel") or item
            print("  top keys", list(item.keys()))
            print("  top id", item.get("id"))
            print("  panel id", panel.get("id"), "type", panel.get("type"))
            em = panel.get("episode_metadata") or {}
            print("  ep series_id", em.get("series_id"))
            print("  linked_resource_key", panel.get("linked_resource_key"))
