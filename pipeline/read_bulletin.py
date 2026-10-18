"""Read one CREAMS (ICAR-IARI) paddy residue burning bulletin PDF and pull out the Punjab tables.

Usage: python pipeline/read_bulletin.py path/to/bulletin.pdf  -> prints JSON

Tables are found by their headings, not by page number, because the page count changes
every day as the fire list grows.
"""
import json
import re
import subprocess
import sys
from datetime import datetime

YEARS = ["2020", "2021", "2022", "2023", "2024", "2025", "2026"]
DATE_ROW = re.compile(r"^\s*(\d\d-[A-Z][a-z]{2})\s+([\d\s]+)$")
FIRE_ROW = re.compile(
    r"^\s*(\d+)\s+(.+?)\s{2,}(.+?)\s{2,}(\S+)\s+(\d{1,2}\.\d+)\s+(\d{2,3}\.\d+)\s+"
    r"(\d{1,2}:\d\d(?::\d\d)?)\s+([DN])\s+(\d+(?:\.\d+)?)\s*$"
)


# The fire list sometimes spells a district differently from the district table.
DISTRICT_ALIASES = {
    "SAS NAGAR": "SAS NAGAR (MOHALI)", "S.A.S NAGAR": "SAS NAGAR (MOHALI)", "S.A.S. NAGAR": "SAS NAGAR (MOHALI)",
    "MOHALI": "SAS NAGAR (MOHALI)", "SRI MUKTSAR SAHIB": "MUKTSAR", "SHRI MUKTSAR SAHIB": "MUKTSAR",
    "NAWANSHAHR": "SBS NAGAR", "SHAHID BHAGAT SINGH NAGAR": "SBS NAGAR", "FEROZEPUR": "FIROZPUR",
}


def district_name(n):
    n = " ".join(n.upper().split())
    return DISTRICT_ALIASES.get(n, n)


class BulletinError(Exception):
    pass


def pdf_text(path):
    out = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True)
    if out.returncode != 0:
        raise BulletinError(f"pdftotext failed: {out.stderr.strip()}")
    return out.stdout.splitlines()


def find(lines, pattern, start=0):
    rx = re.compile(pattern)
    for i in range(start, len(lines)):
        if rx.search(lines[i]):
            return i
    return -1


def read_header(lines):
    head = "\n".join(lines[:40])
    no = re.search(r"Bulletin No:\s*(\d+)", head)
    dt = re.search(r"Events Date:\s*(\d\d-[A-Za-z]{3}-\d{4})", head)
    if not (no and dt):
        raise BulletinError("Could not find bulletin number and events date on page 1")
    date = datetime.strptime(dt.group(1), "%d-%b-%Y").date()
    return int(no.group(1)), date


def read_highlight(lines, date):
    """Punjab fires on the bulletin date, as stated in the highlights paragraph."""
    text = " ".join(l.strip() for l in lines[:60])
    m = re.search(r"detected on [\d\w-]+ were\s+(\d+)\s+in Punjab", text)
    return int(m.group(1)) if m else None


def read_daily(lines):
    """State date-wise table: first block has Punjab in its first seven numbers (2020..2026)."""
    i = find(lines, r"^\s*Punjab\s+Haryana\s+Uttar Pradesh")
    if i < 0:
        raise BulletinError("Date-wise state table (Punjab/Haryana/UP) not found")
    h = find(lines, r"^\s*Date\s+2020\s+2021", i)
    nxt = find(lines, r"^\s*Date\s+2020\s+2021", h + 1)
    rows = []
    for line in lines[h + 1:(nxt if nxt > 0 else len(lines))]:
        m = DATE_ROW.match(line)
        if m:
            nums = [int(x) for x in m.group(2).split()]
            if len(nums) < 7:
                raise BulletinError(f"Short row in date-wise table: {line.strip()}")
            rows.append({"d": m.group(1), "v": dict(zip(YEARS, nums[:7]))})
    if not rows:
        raise BulletinError("Date-wise state table had no rows")
    return rows


def read_districts(lines):
    i = find(lines, r"District-wise cumulative number of paddy residue burning events")
    if i < 0:
        raise BulletinError("District cumulative table not found")
    p = find(lines, r"^\s*Punjab\s*$", i)
    rows = []
    for line in lines[p + 1:]:
        m = re.match(r"^\s+([A-Z][A-Z .()&-]+?)\s{2,}([\d\s]+)$", line)
        if m and m.group(1).strip() != "DISTRICT":
            nums = [int(x) for x in m.group(2).split()]
            if len(nums) == 7:
                rows.append({"n": m.group(1).strip(), "v": nums})
                if m.group(1).strip() == "TOTAL":
                    break
    if not rows or rows[-1]["n"] != "TOTAL":
        raise BulletinError("District cumulative table: TOTAL row not found")
    return rows


def read_fires(lines):
    i = find(lines, r"Details of paddy residue burning events in Punjab on")
    if i < 0:
        return None  # no Punjab table: normal on a day with zero Punjab fires
    end = find(lines, r"Details of paddy residue burning events in (?!Punjab)", i + 1)
    fires = []
    for line in lines[i + 1:(end if end > 0 else len(lines))]:
        m = FIRE_ROW.match(line)
        if m:
            fires.append({
                "dist": district_name(m.group(2)), "block": m.group(3).strip(), "sat": m.group(4),
                "lat": float(m.group(5)), "lon": float(m.group(6)), "t": m.group(7),
                "dn": m.group(8), "frp": float(m.group(9)),
            })
    return fires


def read_bulletin(path):
    lines = pdf_text(path)
    no, date = read_header(lines)
    daily = read_daily(lines)
    dist = read_districts(lines)
    fires = read_fires(lines)
    stated = read_highlight(lines, date)
    day_key = date.strftime("%d-%b")
    table_today = next((r["v"]["2026"] for r in daily if r["d"] == day_key), None)
    if fires is None:
        if table_today == 0:
            fires = []  # zero-fire day: CREAMS leaves out the Punjab fire list
        else:
            raise BulletinError(f"Bulletin {no} ({date}): Punjab fire-by-fire table not found, "
                                f"but the date-wise table shows {table_today} fires")

    # Checks: every count for the day must agree before the bulletin is accepted.
    problems = []
    if table_today is None:
        problems.append(f"{day_key} missing from the date-wise table")
    elif table_today != len(fires):
        problems.append(f"fire list has {len(fires)} rows but the date-wise table says {table_today}")
    if stated is not None and stated != len(fires):
        problems.append(f"fire list has {len(fires)} rows but the highlights say {stated}")
    total = dist[-1]["v"][6]
    season = sum(r["v"]["2026"] for r in daily)
    if total != season:
        problems.append(f"district TOTAL {total} differs from the date-wise season sum {season}")
    if problems:
        raise BulletinError(f"Bulletin {no} ({date}): " + "; ".join(problems))

    return {"no": no, "date": date.isoformat(), "d": day_key, "daily": daily, "dist": dist, "fires": fires}


if __name__ == "__main__":
    print(json.dumps(read_bulletin(sys.argv[1]), indent=1))
