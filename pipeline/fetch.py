"""Download any 2026 CREAMS paddy bulletins we do not have yet, read them, and save the
Punjab tables to data/bulletins/<date>.json. Also reads any PDF dropped into inbox/
(the manual fallback), then removes it.

Run: python pipeline/fetch.py            (new bulletins only)
     python pipeline/fetch.py --redo     (re-read every bulletin from scratch)
"""
import glob
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from read_bulletin import BulletinError, read_bulletin  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "bulletins")
LISTING = "https://creams.iari.res.in/?page_id=1123"
BASE = "https://creams.iari.res.in/Creams_website_bulletin/Fire_bulletin_2026/Fire_bulletin_2026r/"
SEASON_START, SEASON_END = date(2026, 9, 15), date(2026, 11, 30)
UA = {"User-Agent": "Mozilla/5.0 (Punjab Farm Fire Monitor; data refresh)"}


def get(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:  # network hiccup: wait and retry
            err = e
        time.sleep(5 * (k + 1))
    raise RuntimeError(f"Could not download {url}: {err}")


def candidate_urls():
    """Links listed on the CREAMS page, plus the predictable file name for each season day."""
    urls = {}
    try:
        html = get(LISTING).decode("utf-8", "ignore")
        for href in re.findall(r'href="([^"]*Fire_bulletin_2026r/[^"]*Rice[^"]*\.pdf)"', html):
            m = re.search(r"_(\d\d[A-Z][a-z]{2})_2026", href)
            if m:
                urls[m.group(1)] = href
    except Exception as e:
        print(f"Listing page not reachable ({e}); using file name pattern only")
    d, n = SEASON_START, 1
    while d <= min(SEASON_END, date.today()):
        key = d.strftime("%d%b")
        urls.setdefault(key, f"{BASE}{n:02d}.RiceResidueFireBulletin_{key}_2026_ICAR.pdf")
        d += timedelta(days=1)
        n += 1
    return urls


def save(parsed):
    path = os.path.join(OUT, parsed["date"] + ".json")
    with open(path, "w") as fh:
        json.dump(parsed, fh, separators=(",", ":"))
    print(f"Saved bulletin No. {parsed['no']} for {parsed['date']}: {len(parsed['fires'])} Punjab fires")


def main():
    redo = "--redo" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    have = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(OUT, "*.json"))}
    failed = []

    # 1. Manual fallback: PDFs uploaded to inbox/
    for pdf in sorted(glob.glob(os.path.join(ROOT, "inbox", "*.pdf"))):
        try:
            save(read_bulletin(pdf))
            os.remove(pdf)
        except BulletinError as e:
            failed.append(f"{os.path.basename(pdf)}: {e}")

    # 2. CREAMS website
    def iso_of(key):
        return date(2026, time.strptime(key[2:], "%b").tm_mon, int(key[:2])).isoformat()

    for key, url in sorted(candidate_urls().items(), key=lambda kv: iso_of(kv[0])):
        iso = iso_of(key)
        if iso in have and not redo:
            continue
        body = get(url)
        if body is None:
            continue  # not published yet
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(body)
        try:
            save(read_bulletin(tmp.name))
        except BulletinError as e:
            failed.append(f"{url.rsplit('/', 1)[-1]}: {e}")
        finally:
            os.remove(tmp.name)

    if failed:
        print("\nBulletins NOT loaded (check needed):")
        for f in failed:
            print(" -", f)
        with open(os.path.join(ROOT, "fetch_failures.txt"), "w") as fh:
            fh.write("\n".join(failed))


if __name__ == "__main__":
    main()
