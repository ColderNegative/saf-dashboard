"""Refresh data/feed.json for the SAF vs Jet A-1 dashboard.

Runs in GitHub Actions on weekday mornings (see .github/workflows/update-prices.yml),
or locally:  python scripts/update_feed.py

Every source is optional: if one can't be fetched or parsed, its old value is kept
and a warning is printed. Values in data/manual.json override the automatic ones
(use it for the SAF price, and for the carbon price if the automatic quote fails).
Standard library only.
"""
import csv, io, json, re, sys, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "feed.json"
MANUAL = ROOT / "data" / "manual.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; saf-dashboard-price-updater)"}
warnings = []


def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fred(series):
    """[(date, value)] from FRED's public CSV download (no API key needed)."""
    text = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}")
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or not re.match(r"\d{4}-\d{2}-\d{2}", row[0]):
            continue
        try:
            rows.append((row[0], float(row[1])))
        except ValueError:
            pass  # '.' marks a missing day
    return rows


def ecb(currency):
    url = (f"https://data-api.ecb.europa.eu/service/data/EXR/D.{currency}.EUR.SP00.A"
           "?format=csvdata&lastNObservations=1")
    rows = list(csv.DictReader(io.StringIO(get(url))))
    return rows[-1]["TIME_PERIOD"], float(rows[-1]["OBS_VALUE"])


def merge_series(old, new, key_len=None, keep=250):
    d = {p[0]: list(p) for p in old}
    for p in new:
        d[p[0]] = list(p)
    out = [d[k] for k in sorted(d)]
    return out[-keep:]


def main():
    feed = json.loads(FEED.read_text(encoding="utf-8"))
    h = feed.setdefault("history", {})
    today = date.today().isoformat()

    # 1. IATA global average (weekly; the page shows no week date)
    try:
        page = re.sub(r"<[^>]+>", " ", get("https://www.iata.org/en/publications/economics/fuel-monitor/"))
        page = re.sub(r"\s+", " ", page)
        m = re.search(r"global average jet fuel price last week (rose|fell|increased|decreased|was unchanged)"
                      r"\s*(?:by\s*)?([\d.]+)?\s*%?.*?\$\s?([\d,]+\.?\d*)\s*/\s*bbl", page, re.I)
        if not m:
            raise ValueError("price sentence not found")
        val = float(m.group(3).replace(",", ""))
        pct = float(m.group(2) or 0) * (-1 if m.group(1).lower() in ("fell", "decreased") else 1)
        if not 20 <= val <= 600:
            raise ValueError(f"implausible {val}")
        iata = feed["jet"]["iata"]
        if abs(val - iata.get("usd_bbl", 0)) > 1e-6:
            weeks = h.get("iata_weekly", [])
            last = date.fromisoformat(weeks[-1][0]) if weeks else date.today() - timedelta(days=9)
            wk = last + timedelta(days=7)
            h["iata_weekly"] = merge_series(weeks, [[wk.isoformat(), val, 1]], keep=200)
            iata["period"] = f"latest week (≈ w/e {wk.day} {wk.strftime('%b %Y')})"
        iata.update(usd_bbl=val, wow_pct=pct, retrieved=today)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"IATA: {e}")

    # 2. EIA US Gulf Coast jet fuel spot, daily and monthly (via FRED)
    try:
        daily = [r for r in fred("DJFUELUSGULF") if 0.3 <= r[1] <= 15]
        if daily:
            feed["jet"]["usgc"].update(date=daily[-1][0], usd_gal=daily[-1][1])
            h["usgc_daily"] = merge_series(h.get("usgc_daily", []), [list(r) for r in daily[-120:]], keep=120)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"FRED daily: {e}")
    try:
        monthly = [[r[0][:7], r[1]] for r in fred("MJFUELUSGULF") if r[0] >= "2024-01-01"]
        if monthly:
            h["usgc_monthly"] = merge_series(h.get("usgc_monthly", []), monthly, keep=240)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"FRED monthly: {e}")

    # 3. ECB reference rates
    try:
        d1, usd = ecb("USD")
        d2, gbp = ecb("GBP")
        feed["fx"].update(usd_per_eur=usd, gbp_per_eur=gbp, date=max(d1, d2))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"ECB: {e}")

    # 4. EU ETS allowance (best effort; this site often blocks automated requests)
    try:
        page = get("https://www.investing.com/commodities/european-union-allowance-eua-year-futures")
        m = re.search(r'data-test="instrument-price-last"[^>]*>\s*([\d.,]+)', page)
        if not m:
            raise ValueError("price not found")
        val = float(m.group(1).replace(",", ""))
        if not 20 <= val <= 300:
            raise ValueError(f"implausible {val}")
        feed["carbon"].update(eua_eur_t=val, date=today, source="Investing.com (EEX contract)")
        h["eua_daily"] = merge_series(h.get("eua_daily", []), [[today, val]], keep=250)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"EUA (set it in data/manual.json if this keeps failing): {e}")

    # 5. Manual overrides
    if MANUAL.exists():
        man = json.loads(MANUAL.read_text(encoding="utf-8"))
        saf = man.get("saf") or {}
        if isinstance(saf.get("hefa_usd_t"), (int, float)):
            feed["saf"].update({k: v for k, v in saf.items() if k in ("hefa_usd_t", "period", "source", "url")})
        car = man.get("carbon") or {}
        if isinstance(car.get("eua_eur_t"), (int, float)) and car.get("date", "") >= feed["carbon"].get("date", ""):
            feed["carbon"].update({k: v for k, v in car.items() if k in ("eua_eur_t", "date", "label", "source", "url")})
            h["eua_daily"] = merge_series(h.get("eua_daily", []), [[car["date"], car["eua_eur_t"]]], keep=250)

    feed["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    feed["updated_by"] = "GitHub Action"
    FEED.write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8")
    print("feed updated", feed["updated_at"])
    for w in warnings:
        print("WARNING", w, file=sys.stderr)


if __name__ == "__main__":
    main()
