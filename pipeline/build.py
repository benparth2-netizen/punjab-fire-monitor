"""Merge every parsed bulletin in data/bulletins/ into the single file the dashboard reads.

- Season tables (date-wise and district cumulative) come from the latest bulletin,
  which already carries 2020-2026 for the same dates.
- Fire-by-fire records are joined across all bulletins, each tagged with its date.
- Cross-check: each district's cumulative count should rise by exactly the number of
  fires listed for it that day. Mismatches are reported as warnings (CREAMS sometimes
  revises earlier days) but do not stop publishing.
"""
import glob
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from read_bulletin import district_name  # noqa: E402


def build():
    files = sorted(glob.glob(os.path.join(ROOT, "data", "bulletins", "*.json")))
    if not files:
        raise SystemExit("No parsed bulletins in data/bulletins/")
    bulletins = [json.load(open(f)) for f in files]
    latest = bulletins[-1]

    fires, warnings = [], []
    prev = None
    for b in bulletins:
        for f in b["fires"]:
            f["dist"] = district_name(f["dist"])
            fires.append({**f, "d": b["d"]})
        known = {r["n"] for r in b["dist"]}
        for n in sorted({f["dist"] for f in b["fires"]} - known):
            warnings.append(f'{b["d"]}: fire list names district "{n}", which is not in the district table')
        consecutive = prev is not None and (
            datetime.fromisoformat(b["date"]) - datetime.fromisoformat(prev["date"])).days == 1
        if consecutive:
            got = Counter(f["dist"] for f in b["fires"])
            before = {r["n"]: r["v"][6] for r in prev["dist"]}
            for r in b["dist"]:
                if r["n"] == "TOTAL":
                    continue
                rise = r["v"][6] - before.get(r["n"], 0)
                if rise != got.get(r["n"], 0):
                    warnings.append(f'{b["d"]} {r["n"]}: district total rose by {rise}, fire list has {got.get(r["n"], 0)}')
        prev = b

    # Days in the season table that have no bulletin loaded (for the "missing" note on the map)
    have = {b["d"] for b in bulletins}
    missing = [r["d"] for r in latest["daily"] if r["d"] not in have]

    geo = json.load(open(os.path.join(ROOT, "pipeline", "geo.json")))
    out = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "latest": {"no": latest["no"], "date": latest["date"], "d": latest["d"]},
        "daily": latest["daily"],
        "dist": latest["dist"],
        "fires": fires,
        "fireDays": sorted(have, key=lambda d: datetime.strptime(d + "-2026", "%d-%b-%Y")),
        "missing": missing,
        "warnings": warnings,
        **geo,
    }
    os.makedirs(os.path.join(ROOT, "site", "data"), exist_ok=True)
    with open(os.path.join(ROOT, "site", "data", "dashboard.json"), "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"Built dashboard data: {len(bulletins)} bulletins, {len(fires)} fires, latest {latest['date']} (No. {latest['no']})")
    if missing:
        print(f"Days without a bulletin loaded: {', '.join(missing)}")
    for w in warnings:
        print("WARNING:", w)
    return out


if __name__ == "__main__":
    build()
