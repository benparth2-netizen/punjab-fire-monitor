# Punjab Farm Fire Monitor

Dashboard of paddy residue fires in Punjab, built from the daily bulletins published by
the CREAMS Lab, ICAR-IARI (https://creams.iari.res.in/?page_id=1123).

## How the data flows

1. **Fetch** (`pipeline/fetch.py`): checks the CREAMS bulletin page for 2026 rice bulletins
   not yet loaded and downloads them. Any PDF placed in `inbox/` is read too.
2. **Read and check** (`pipeline/read_bulletin.py`): pulls three Punjab tables from each PDF
   (season date-wise counts, district cumulative counts, fire-by-fire list). A bulletin is
   accepted only if the fire list, the date-wise table and the highlights agree on the
   day's count, and the district total matches the season sum.
3. **Store**: each accepted bulletin is saved as `data/bulletins/<date>.json`.
4. **Build** (`pipeline/build.py`): merges all bulletins into `site/data/dashboard.json`,
   and warns if a district's daily rise does not match its listed fires.
5. **Publish**: GitHub Pages serves `site/`, so the dashboard updates itself.

## When it runs

- Automatically at 09:00, 14:00 and 21:00 IST every day.
- On demand: **Actions** tab > **Update dashboard** > **Run workflow**.
- On upload: put a bulletin PDF in `inbox/` (Add file > Upload files). This is the
  fallback if the CREAMS site blocks or times out.

If a bulletin fails the checks, the run is marked failed (GitHub emails the account
owner) and the dashboard is published without that day, never with wrong numbers.

## Season change (next year)

Update the year in `pipeline/fetch.py` (`BASE`, `SEASON_START`, `SEASON_END`) and the
year columns in `pipeline/read_bulletin.py` (`YEARS`).
