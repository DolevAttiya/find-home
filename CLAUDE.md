# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal Streamlit app for apartment hunting in Israel. It scrapes Facebook groups, Madlan, and Yad2 for listings, stores everything in SQLite with price-change history, and presents a Hebrew (RTL) UI with a table, map, and per-listing tracking (seen/inactive/notes).

The UI, config, and all in-app strings are in Hebrew. Keep new UI text, config keys, and comments consistent with the existing Hebrew conventions unless told otherwise.

## Commands

```bash
# install
pip install -r requirements.txt
playwright install chromium

# run the app
streamlit run app.py

# one-time Facebook login (writes fb_session.json)
python setup/save_session.py

# Madlan session (used as fallback when CDP isn't available)
python setup/save_madlan_session.py

# optional: launch a real Chrome for Madlan scraping via CDP (preferred path)
python setup/start_madlan_browser.py

# run a scan manually (same entry point the "סרוק עכשיו" button uses)
python scrapers/scraper.py

# run the background scheduler (auto-scan every N hours from config.yaml)
python workers/scheduler.py

# run a single worker directly (what scraper.py fans out to)
python workers/worker.py facebook '<group_json>'
python workers/worker.py madlan
python workers/worker.py yad2
```

There is no test suite, linter, or CI config in this repo.

## Architecture

**Package layout** (post-reorg, see `git log` — README.md's file list is stale and still describes the pre-reorg flat layout):
- `core/` — `database.py` (all SQLite access), `geocoder.py` (address → lat/lon), `image_utils.py` (downloading listing images)
- `scrapers/` — `scraper.py` (Facebook groups + scan orchestration), `madlan_scraper.py`, `yad2_scraper.py`, `madlan_captcha_solver.py` (PerimeterX bypass for Madlan)
- `workers/` — `worker.py` (subprocess entry point for a single scrape task), `scheduler.py` (periodic auto-scan loop)
- `setup/` — one-time/manual session bootstrapping scripts (`save_session.py`, `save_madlan_session.py`, `start_madlan_browser.py`) plus the saved `fb_session.json`
- `app.py` — the Streamlit UI (single file), imports only from `core.database`

**Process model**: scraping always runs in separate `python` subprocesses, not in-process, because Playwright browsers can't run inside the Streamlit process/thread cleanly and each source needs its own browser context.
- The "סרוק עכשיו" (scan now) button in `app.py` shells out to `scrapers/scraper.py` and streams its stdout back into the UI, watching for a final `__RESULT__:<json>` line.
- `scrapers/scraper.py::run_scrape()` is the orchestrator: it fans out to `workers/worker.py` via `ThreadPoolExecutor`, launching one subprocess per Facebook group plus one for Madlan and one for Yad2. Madlan and Yad2 are submitted to the pool *before* the Facebook groups so they grab a worker slot immediately instead of waiting behind 60+ FB group tasks (see commit `15f2116`).
- `workers/worker.py` is invoked with `cwd` set to the project root (not `scrapers/`) and inserts the project root onto `sys.path` itself, so it can be run standalone or as a subprocess from anywhere (see commits `a0e6be2`, `b73557f`).
- Each worker prints progress lines to stdout and a final `__RESULT__:<n>` (or `__RESULT__:0` on error) that the parent process parses.

**Madlan scraping is the fragile part**: Madlan sits behind PerimeterX bot protection. `workers/worker.py::run_madlan()` tries, in order:
1. Connect over CDP to an already-running real Chrome (`start_madlan_browser.py` launches this ahead of time) on port 9222 — preferred because it looks like a real browser session.
2. If CDP isn't up, try to auto-launch Chrome via `scrapers/madlan_captcha_solver.py::PerimeterXSolver`, then retry CDP.
3. Fall back to a persistent Playwright profile directory (`madlan_profile/`, created by `setup/save_madlan_session.py`).
4. Last resort: a plain fresh browser context (least likely to pass PerimeterX).

Only the CDP page is closed after scraping (`page.close()`), not the browser itself, since that Chrome instance is meant to be reused across scans.

**Database** (`core/database.py`): single SQLite file (`apartments.db`, gitignored). Schema evolves via an additive `_migrate()` that `ALTER TABLE`s in missing columns on every `init_db()` call — there are no separate migration files. Three tables: `apartments`, `groups`, `price_history`. `save_apartment()` does upsert-by-`post_id`: on conflict it diffs the price, appends to `price_history`, and preserves the first-ever price as `original_price` for showing price drops. Rows are never hard-deleted; removed/irrelevant listings are soft-deleted via `is_active`.

**Config** (`config.yaml`, tracked in git — not a secret, contains search location, price/room/size ranges, required/blocked keywords, Madlan search URL, and scan interval). All keys are Hebrew. `app.py`'s settings page reads and rewrites this file directly (`load_config`/`save_config`), so config edits from the UI must preserve the exact Hebrew key structure the scrapers expect (`core/database.py` and scrapers read the same `config.yaml` via their own `load_config()` duplicated in each module).

**Secrets/local state excluded from git**: `apartments.db`, `fb_session.json`, `madlan_profile/`, `apartment_images/`, `.env` (holds `FB_EMAIL`/`FB_PASSWORD` used only by `setup/save_session.py`).
