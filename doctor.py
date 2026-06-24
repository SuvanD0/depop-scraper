#!/usr/bin/env python3
"""Health check — confirms the bot can actually run on this machine.

Run via:  python3 run.py doctor   (or)   python3 doctor.py

Checks Python, env/notifications, config + active rubric, the SQLite store, the
ntfy server, and (the big one) that Depop's API is reachable and still returns the
shape this bot depends on. Exits non-zero if anything is broken.
"""
from __future__ import annotations

import os
import sys
import urllib.request

import depop
import store
import run

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def _mark(status: str) -> str:
    sym = {PASS: "✓", WARN: "!", FAIL: "✗"}[status]
    if not sys.stdout.isatty():
        return f"[{status}] {sym}"
    color = {PASS: "32", WARN: "33", FAIL: "31"}[status]
    return f"\033[{color}m{sym} {status}\033[0m"


class Report:
    def __init__(self) -> None:
        self.fails = 0
        self.warns = 0

    def add(self, status: str, name: str, detail: str = "") -> None:
        if status == FAIL:
            self.fails += 1
        elif status == WARN:
            self.warns += 1
        tail = f" — {detail}" if detail else ""
        print(f"  {_mark(status):<14} {name}{tail}")


def check_python(r: Report) -> None:
    v = sys.version_info
    ok = v >= (3, 10)
    r.add(PASS if ok else FAIL, "Python >= 3.10", f"found {v.major}.{v.minor}.{v.micro}")


def check_env(r: Report) -> None:
    run.load_env()
    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        r.add(PASS, "NTFY_TOPIC set", topic)
    else:
        r.add(WARN, "NTFY_TOPIC not set", "no phone alerts — run setup or set it in .env")
    if os.environ.get("ANTHROPIC_API_KEY"):
        r.add(PASS, "ANTHROPIC_API_KEY set", "LLM maybe-judging enabled")
    else:
        r.add(WARN, "ANTHROPIC_API_KEY not set", "running on rules only (fine, $0)")


def check_config(r: Report) -> dict | None:
    try:
        cfg = run.load_config("config.json")
    except Exception as e:
        r.add(FAIL, "config.json", f"could not load: {e}")
        return None
    missing = [k for k in ("queries", "max_price_usd", "request_delay_seconds",
                           "pages_per_query", "items_per_page") if k not in cfg]
    if missing:
        r.add(FAIL, "config.json keys", f"missing: {', '.join(missing)}")
    else:
        r.add(PASS, "config.json", f"{len(cfg.get('queries', []))} queries, max ${cfg['max_price_usd']}")
    try:
        cfg = run.apply_preset(cfg)
        if cfg.get("preset"):
            r.add(PASS, f"preset '{cfg['preset']}'", f"{len(cfg['queries'])} queries loaded")
    except Exception as e:
        r.add(FAIL, "preset", f"could not load: {e}")
        return None
    return cfg


def check_rubric(r: Report, cfg: dict | None) -> None:
    if not cfg:
        return
    try:
        rubric = cfg.get("_rubric") or run.scoring.load_rubric(
            os.path.join(run.BASE_DIR, cfg["rubric_path"]))
    except Exception as e:
        r.add(FAIL, "rubric", f"could not load: {e}")
        return
    brands = len(rubric.get("brands", {}))
    th = rubric.get("thresholds", {})
    if brands and "buy" in th:
        r.add(PASS, "rubric", f"{brands} brands, buy>={th['buy']} maybe>={th.get('maybe', '?')}")
    else:
        r.add(WARN, "rubric", "no brands or thresholds — everything will score low")


def check_store(r: Report) -> None:
    try:
        path = os.path.join(run.BASE_DIR, "seen.db")
        conn = store.connect(path)
        n = conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
        conn.close()
        r.add(PASS, "seen.db", f"writable, {n} listings tracked")
    except Exception as e:
        r.add(FAIL, "seen.db", f"not writable: {e}")


def check_ntfy(r: Report) -> None:
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
    try:
        req = urllib.request.Request(server, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            r.add(PASS, "ntfy reachable", f"{server} (HTTP {resp.status})")
    except Exception as e:
        r.add(WARN, "ntfy reachable", f"{server}: {e}")


def check_depop(r: Report) -> None:
    try:
        rows = depop.search("vintage", 75, 1, 4, 0.5)
    except depop.RateLimited as e:
        r.add(WARN, "Depop API", f"reachable but rate-limited: {e}")
        return
    except Exception as e:
        r.add(FAIL, "Depop API", f"request failed: {e}")
        return
    if not rows:
        r.add(WARN, "Depop API", "reachable but returned 0 rows")
        return
    sample = depop.normalize(rows[0])
    ok = bool(sample.get("slug")) and sample.get("price") is not None
    if ok:
        r.add(PASS, "Depop API + shape", f"{len(rows)} rows, parsed e.g. ${sample['price']:.2f} {sample['title'][:30]}")
    else:
        r.add(FAIL, "Depop API shape", "rows returned but normalize() got no slug/price — API may have changed")


def main() -> int:
    print("\n  depop-scraper doctor\n  " + "─" * 22)
    r = Report()
    check_python(r)
    check_env(r)
    cfg = check_config(r)
    check_rubric(r, cfg)
    check_store(r)
    check_ntfy(r)
    check_depop(r)

    print("  " + "─" * 22)
    if r.fails:
        print(f"  {r.fails} failed, {r.warns} warning(s). Fix the ✗ items above.\n")
        return 1
    if r.warns:
        print(f"  All critical checks passed ({r.warns} warning(s)).\n")
        return 0
    print("  All checks passed. You're good to go.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
