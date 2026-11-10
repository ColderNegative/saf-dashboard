# SAF vs Jet A-1 Dashboard

Standalone website for the BEng project *Techno-Economic and Climate Assessment of Alternative Aviation Fuels* (C. Smallbone, Loughborough University). Static HTML, no server, no build step.

## Files
- `index.html` – the dashboard (model, charts and UI in one file)
- `vendor/chart.umd.js` – Chart.js 4.4.1, bundled so the site works without a CDN
- `data/feed.json` – latest prices; the page loads this on open
- `data/manual.json` – prices you set by hand (SAF, and EU ETS if the automatic quote fails)
- `scripts/update_feed.py` – refreshes `feed.json` from IATA, EIA/FRED, ECB and an EU ETS quote
- `.github/workflows/update-prices.yml` – runs the script every weekday morning and commits the result

## Put it online (GitHub Pages, free)
1. Create a new public repository on github.com, e.g. `saf-dashboard`.
2. Upload everything in this folder (keep the folder structure, including `.github`). On the web: **Add file → Upload files**, drag the folder contents in, commit.
3. **Settings → Pages**: Source = *Deploy from a branch*, Branch = `main`, folder `/ (root)`. Save. After a minute the site is at `https://<your-username>.github.io/saf-dashboard/`.
4. **Settings → Actions → General → Workflow permissions**: choose *Read and write permissions* so the price bot can commit.
5. **Actions → Update prices → Run workflow** to test it once. Each commit to `data/feed.json` republishes the site automatically.

## Keeping prices honest
The script never invents a value: if a source fails it keeps the previous one and logs a warning in the Action run. The IATA page gives no week date, so new weekly points are dated one week after the last one and marked ≈. The EU ETS source often blocks automated requests; if the Action log shows an EUA warning, put the latest settlement in `data/manual.json`.

## Preview locally
`python -m http.server` in this folder, then open http://localhost:8000 (opening `index.html` directly also works, but then it shows the built-in snapshot instead of `feed.json`).
