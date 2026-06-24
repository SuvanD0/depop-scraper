#!/usr/bin/env python3
"""Depop vintage hat arbitrage pipeline.

Usage:
    python3 run.py                  # one run over config queries
    python3 run.py --query "..."    # one-off custom query
    python3 run.py --loop           # run forever on config cadence
    python3 run.py --dry-run        # no notifications, no db writes
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import depop
import scoring
import store
from llm import judge_maybes
from notify import notify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_env(path: str = ".env") -> None:
    """Minimal .env loader (no dependency). KEY=VALUE per line; # comments ignored.
    Does not override variables already present in the environment."""
    fp = os.path.join(BASE_DIR, path)
    if not os.path.exists(fp):
        return
    with open(fp) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


def load_config(path: str) -> dict:
    with open(os.path.join(BASE_DIR, path)) as f:
        return json.load(f)


def run_once(cfg: dict, queries: list[str], dry_run: bool = False) -> None:
    rubric = scoring.load_rubric(os.path.join(BASE_DIR, cfg["rubric_path"]))
    conn = store.connect(os.path.join(BASE_DIR, cfg["db_path"]))
    delay = cfg["request_delay_seconds"]
    max_price = cfg["max_price_usd"]

    rows: dict[str, dict] = {}
    try:
        for q in queries:
            for row in depop.search(q, max_price, cfg["pages_per_query"], cfg["items_per_page"], delay):
                rows[str(row.get("id", row.get("slug")))] = row
    except depop.RateLimited as e:
        print(f"[run] rate limited, aborting scrape: {e}")

    fresh = [r for rid, r in rows.items() if not store.is_seen(conn, rid)]
    print(f"[run] {len(rows)} listings, {len(fresh)} unseen")

    scored = []
    for row in fresh:
        listing = depop.normalize(row)
        if listing["price"] <= 0 or listing["price"] > max_price:
            continue
        scored.append({"listing": listing, **scoring.score(listing, rubric)})

    maybes = [s for s in scored if s["verdict"] == "maybe"]
    llm_verdicts, tokens = ({}, 0) if dry_run else judge_maybes(maybes, cfg["llm"])
    for s in maybes:
        v = llm_verdicts.get(s["listing"]["id"])
        if v:
            s["verdict"] = v["verdict"]
            s["signals"].append(f"llm:{v.get('reason', '')}")

    scored.sort(key=lambda s: s["score"], reverse=True)
    buys = [s for s in scored if s["verdict"] == "buy"]
    rule_decided = len(scored) - len(maybes)
    pct = 100 * rule_decided / len(scored) if scored else 100
    print(f"[run] scored={len(scored)} rule-decided={pct:.0f}% llm-judged={len(maybes)} tokens={tokens}")

    notify_cfg = cfg.get("notify", {})
    notify_min_score = notify_cfg.get("min_score", 70)
    notify_max_price = notify_cfg.get("max_price_usd", cfg["max_price_usd"])

    notified = 0
    for s in scored:
        l = s["listing"]
        line = f"{s['verdict']:>5} {s['score']:>3} ${l['price']:<6.2f} {l['title'][:50]} {l['url']}"
        print(line)
        if dry_run:
            continue
        do_notify = (
            s["verdict"] == "buy"
            and s["score"] >= notify_min_score
            and l["price"] <= notify_max_price
        )
        if do_notify:
            try:
                notify(
                    f"BUY ${l['price']:.2f} — {l['title'][:60]}",
                    f"score {s['score']} | {', '.join(s['signals'][:4])}",
                    url=l["url"],
                    priority="high",
                )
                notified += 1
            except Exception as e:
                print(f"[run] notify failed: {e}")
                do_notify = False
        store.mark(conn, l, s["score"], s["verdict"], do_notify)
    if not dry_run:
        store.log_run(conn, len(scored), len(buys), notified, tokens)
    print(f"[run] buys={len(buys)} notified={notified}")
    conn.close()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        import setup
        setup.main()
        return

    ap = argparse.ArgumentParser()
    ap.add_argument("--query", help="one-off custom query instead of config queries")
    ap.add_argument("--loop", action="store_true", help="run forever on config cadence")
    ap.add_argument("--dry-run", action="store_true", help="no notifications, no db writes")
    ap.add_argument("--config", default="config.json")
    args = ap.parse_args()

    load_env()
    cfg = load_config(args.config)
    queries = [args.query] if args.query else cfg["queries"]

    if args.loop:
        while True:
            run_once(cfg, queries, dry_run=args.dry_run)
            mins = cfg["cadence_minutes"]
            print(f"[loop] sleeping {mins}m")
            time.sleep(mins * 60)
    else:
        run_once(cfg, queries, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
