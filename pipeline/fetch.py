"""Download any 2026 CREAMS paddy bulletins we do not have yet, read them, and save the
Punjab tables to data/bulletins/<date>.json. Also reads any PDF dropped into inbox/
(the manual fallback), then removes it.

Run: python pipeline/fetch.py            (new bulletins only)
     python pipeline/fetch.py --redo     (re-read every bulletin from scratch)
"""
import glob
import json
import shutil
import ssl
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
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


def _urllib(url, context=None):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60, context=context) as r:
        return r.read()


def _curl(url):
    if not shutil.which("curl"):
        raise RuntimeError("curl not installed")
    out = subprocess.run(["curl", "-sSfL", "--max-time", "90", "-A", UA["User-Agent"], "-w", "\n%{http_code}", url],
                         capture_output=True)
    if out.returncode == 22 and b"404" in out.stderr:
        return None
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode(errors="ignore").strip())
    body, _, code = out.stdout.rpartition(b"\n")
    return body


def get(url, tries=2):
    """Download a URL. Tries normal HTTPS, then curl, then plain HTTP (some government
    sites send an incomplete certificate chain that Python rejects). None means 404."""
    errors = []
    attempts = [("https", lambda: _urllib(url)), ("curl", lambda: _curl(url))]
    if url.startswith("https://"):
        attempts.append(("http", lambda: _urllib("http://" + url[len("https://"):])))
    # Last resort, CREAMS only: if the site's security certificate has expired or is broken, read
    # the public bulletin without checking the certificate. Every bulletin still has to pass the
    # count checks in read_bulletin.py before it is used, and the run logs a warning each time.
    if urllib.parse.urlparse(url).hostname == "creams.iari.res.in":
        def _unverified():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            body = _urllib(url, context=ctx)
            print(f"::warning::CREAMS certificate could not be verified; downloaded without the check: {url.rsplit('/', 1)[-1]}")
            return body
        attempts.append(("unverified", _unverified))
    for k in range(tries):
        for name, fn in attempts:
            try:
                return fn()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                errors.append(f"{name}: HTTP {e.code}")
            except Exception as e:
                errors.append(f"{name}: {type(e).__name__}: {e}")
        time.sleep(5 * (k + 1))
    raise RuntimeError("; ".join(errors[-3:]))


def candidate_urls():
    """Links listed on the CREAMS page, plus the predictable file name for each season day."""
    urls = {}
    try:
        html = get(LISTING).decode("utf-8", "ignore")
        for href in re.findall(r'href="([^"]*Fire_bulletin_2026r/[^"]*Rice[^"]*\.pdf)"', html):
            m = re.search(r"_(\d\d[A-Z][a-z]{2})_2026", href)
            if m:
                urls[m.group(1)] = urllib.parse.urljoin(LISTING, href.strip())
    except Exception as e:
        print(f"::warning::Listing page not reachable ({e}); using file name pattern only")
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

    # 2. CREAMS website (stops early if the site cannot be reached at all)
    network_errors = 0
    def iso_of(key):
        return date(2026, time.strptime(key[2:], "%b").tm_mon, int(key[:2])).isoformat()

    for key, url in sorted(candidate_urls().items(), key=lambda kv: iso_of(kv[0])):
        iso = iso_of(key)
        if iso in have and not redo:
            continue
        try:
            body = get(url)
        except RuntimeError as e:
            network_errors += 1
            failed.append(f"{url.rsplit('/', 1)[-1]}: could not download ({e})")
            if network_errors >= 2:
                failed.append("CREAMS site not reachable from GitHub; stopped trying. Upload PDFs to inbox/ instead.")
                break
            continue
        network_errors = 0
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
            print(f"::error::{f}")
        with open(os.path.join(ROOT, "fetch_failures.txt"), "w") as fh:
            fh.write("\n".join(failed))


if __name__ == "__main__":
    main()
