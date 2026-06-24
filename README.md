# depop-scraper

Resale-arbitrage alert bot for [Depop](https://www.depop.com). It polls Depop's
search API for cheap vintage hats, scores each listing against a hand-built value
rubric, escalates only the ambiguous ones to an LLM, and pushes a phone
notification when something is worth buying to flip — without ever alerting twice.

Pure Python standard library. **Zero dependencies.** No login, no API key required
(the LLM step is optional).

## How it works

```
search API ──▶ rate-limit ──▶ dedup ──▶ normalize ──▶ rule score ──▶ LLM (maybe band) ──▶ notify ──▶ persist
 depop.py       depop.py     store.py    depop.py     scoring.py        llm.py          notify.py   store.py
```

1. **Fetch** — `GET /presentation/api/v1/search/products/` with fresh UUID headers.
   The search row already contains description, brand, condition, and images, so
   there's **one request per page of 24** — no per-listing detail fetch.
2. **Rate-limit** — jittered delay between requests; on `403/429` it aborts the run
   rather than retrying (politeness over completeness).
3. **Dedup** — skips listing ids already in `seen.db` before doing any work.
4. **Score** — `value_rubric.json` assigns points for brand tier, era, defunct teams,
   rarity factors, negatives, and per-brand max-buy price gating → `buy / maybe / skip`.
   ~90%+ of listings are decided here for **$0**.
5. **LLM (optional)** — only the ambiguous `maybe` band is batched to Claude Haiku;
   images attached for the top few only. Skipped entirely if no `ANTHROPIC_API_KEY`.
6. **Notify** — `buy`s above the notify threshold push to your [ntfy](https://ntfy.sh)
   topic with a tap-to-open link.
7. **Persist** — every scored listing is marked seen (idempotency), run stats logged.

See [`OVERVIEW.html`](OVERVIEW.html) for the full architecture walkthrough and the
reasoning behind each design choice.

## Quick start

```bash
git clone https://github.com/SuvanD0/depop-scraper.git
cd depop-scraper

python3 run.py setup          # interactive: ntfy topic, test push, scheduler
```

`setup` generates a private alert channel, writes your `.env`, sends a test
notification to confirm your phone is wired up, and (on macOS) installs the
launchd scheduler with the correct paths. That's the whole onboarding.

Then, any time:

```bash
python3 run.py doctor         # health check before you trust it (see below)
python3 run.py --dry-run      # test run: no notifications, no DB writes
python3 run.py                # one real pass over the configured queries
python3 run.py --loop         # run forever on the configured cadence
python3 run.py --query "vintage starter snapback"   # one-off custom search
```

Requires Python 3.10+. No `pip install` needed. Prefer manual config? Copy
`.env.example` to `.env` and set `NTFY_TOPIC` yourself instead of running setup.

## Health check

```bash
python3 run.py doctor
```

Verifies Python version, env/notification setup, config + active rubric, the
SQLite store, the ntfy server, and — most importantly — that **Depop's API is
reachable and still returns the shape this bot parses**. If Depop changes their
API, `doctor` is how you'll know. Exits non-zero if anything critical is broken.

## Presets — target a different category

The bot ships with ready-made playbooks in [`presets/`](presets/), each bundling
category-specific search queries with a value rubric:

| Preset | What it hunts |
|--------|---------------|
| `hats` (default) | Vintage snapbacks, fitteds, trucker hats |
| `sneakers` | Vintage/resale sneakers (Jordan, NB, Salomon, …) |
| `denim` | Vintage denim & workwear (Levi's Big E, selvedge, Carhartt, …) |
| `tees` | Vintage t-shirts (band, sports, single-stitch) |

Pick one during `setup`, set `"preset"` in `config.json`, or override per run:

```bash
python3 run.py --preset denim
```

The `sneakers`, `denim`, and `tees` rubrics are **starter templates** — the
`max_buy` price thresholds are placeholders. Tune them to your market by editing
the preset file. Want a new category? Copy a preset, swap the queries and brands.

## Configure

Everything tunable lives in two JSON files:

- **`config.json`** — search queries, max price, cadence, pages per query, request
  delay, notify thresholds, and the optional LLM block.
- **`value_rubric.json`** — the scoring playbook: brand tiers and per-brand max-buy
  prices, defunct/premium teams, rarity factors, era signals, and negatives. Edit
  this to retarget the bot at different items without touching any code.

To enable LLM judging of the `maybe` band, add `ANTHROPIC_API_KEY` to your `.env`.

## Run it on a schedule (macOS)

The easiest path is `python3 run.py setup`, which generates and loads a launchd
agent with the correct paths for your machine automatically.

To do it by hand, `com.depop-scraper.plist` is a template — replace the
`/ABSOLUTE/PATH/TO/depop-scraper` placeholders with your clone path, then:

```bash
cp com.depop-scraper.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.depop-scraper.plist
```

On Linux, a cron entry or systemd timer calling `python3 run.py` works the same way.

## Disclaimer

This tool calls Depop's undocumented internal API and may break if Depop changes it.
Automated access may conflict with Depop's Terms of Service — use at your own risk,
keep request rates polite, and don't run it commercially. Provided as-is under MIT.
