"""Google Sheets Facebook targets importer.

Fetches store sheets (e.g. Funbox, 來玩聚), normalizes Facebook URLs,
and updates config.yaml targets list.
"""

import csv
import io
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SHEETS = [
    {
        "name": "Funbox",
        "url": "https://docs.google.com/spreadsheets/d/1FoLE_Y8EgVoeydoh_WXeCm7EIl0q8SqMIR6zK_6CtQU/edit?gid=0#gid=0",
    },
    {
        "name": "來玩聚",
        "url": "https://docs.google.com/spreadsheets/d/1rVDCV9gKTY9EEjgZk_acHwJt8FVr2yuAbnVnIalq-vg/edit?gid=0#gid=0",
    },
]


def sheet_csv_url(url: str) -> str:
    """Convert Google Sheets view/edit URL to CSV export URL."""
    if "/export?" in url:
        return url
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not match:
        raise ValueError(f"無法辨識的 Google 試算表網址：{url}")
    sheet_id = match.group(1)
    gid = "0"
    gid_match = re.search(r"gid=(\d+)", url)
    if gid_match:
        gid = gid_match.group(1)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def normalize_facebook_url(url: str) -> str:
    url = url.strip().split("#")[0]
    if "m.facebook.com" in url:
        url = url.replace("m.facebook.com", "www.facebook.com")

    if not url.endswith("/") and "/share/" in url:
        url += "/"

    # If it's a share redirect link, follow the redirect using curl User-Agent
    if "/share/" in url:
        try:
            resp = requests.get(
                url,
                allow_redirects=True,
                timeout=8,
                headers={"User-Agent": "curl/8.0.0"},
            )
            url = resp.url
        except Exception:
            pass

    u = urlsplit(url)
    q = parse_qs(u.query)
    # Check profile.php?id=...
    if "id" in q and q["id"][0].isdigit():
        return f"https://www.facebook.com/profile.php?id={q['id'][0]}"

    # Check /people/Name/ID
    m = re.search(r"/people/(?:[^/]+/)+(\d+)", u.path)
    if m:
        return f"https://www.facebook.com/profile.php?id={m.group(1)}"

    # Clean vanity path
    path = u.path.strip("/")
    if path:
        return f"https://www.facebook.com/{path}"
    return url


def import_sheets(sheet_urls=None):
    if not sheet_urls:
        sheet_urls = [s["url"] for s in DEFAULT_SHEETS]

    all_targets = []
    seen_urls = set()

    for item in sheet_urls:
        csv_url = sheet_csv_url(item)
        print(f"[*] 正在讀取試算表: {csv_url} ...")
        resp = requests.get(csv_url, timeout=15)
        resp.raise_for_status()

        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)

        sheet_targets = 0
        for row in rows:
            if len(row) < 2:
                continue
            store_name = row[0].strip()
            fb_url = row[1].strip()

            if "facebook.com" not in fb_url:
                continue

            canonical_url = normalize_facebook_url(fb_url)
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)

            # Derive clean page_id
            page_id_match = re.search(r"id=(\d+)", canonical_url)
            if page_id_match:
                page_id = page_id_match.group(1)
            else:
                page_id = canonical_url.split("/")[-1]

            line_id = row[2].strip() if len(row) >= 3 else ""

            target_entry = {
                "name": store_name,
                "page_id": page_id,
                "url": canonical_url,
                "enabled": True,
            }
            if line_id:
                target_entry["line_id"] = line_id

            all_targets.append(target_entry)
            sheet_targets += 1

        print(f"[+] 成功解析 {sheet_targets} 個有效門市粉專！")

    # Update config.yaml
    config_file = ROOT / "config.yaml"
    with open(config_file, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}

    config_data["targets"] = all_targets

    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    print(f"\n🎉 總共成功導入 {len(all_targets)} 個監控目標至 config.yaml！")
    return all_targets


if __name__ == "__main__":
    urls = sys.argv[1:] if len(sys.argv) > 1 else None
    import_sheets(urls)
