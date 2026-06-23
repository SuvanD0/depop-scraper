#!/usr/bin/env python3
"""Send a push notification via ntfy.sh (JSON publish — safe for non-ASCII titles).

Usage:
    from notify import notify
    notify("Found a hat", "Vintage wool fedora — $14", url="https://depop.com/...")

CLI:
    python notify.py "Title" "Body" [url]
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request


def notify(title: str, body: str, url: str | None = None, priority: str = "default") -> int:
    # Read at call time so a .env loaded after import is still honored.
    topic = os.environ.get("NTFY_TOPIC")
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
    if not topic:
        raise RuntimeError("NTFY_TOPIC not set — copy .env.example to .env and set your own ntfy topic")
    payload: dict = {
        "topic": topic,
        "title": title,
        "message": body,
        "priority": {"default": 3, "high": 4, "max": 5}.get(priority, 3),
    }
    if url:
        payload["click"] = url
        payload["actions"] = [{"action": "view", "label": "Open listing", "url": url, "clear": True}]

    req = urllib.request.Request(
        server,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: notify.py <title> <body> [url]", file=sys.stderr)
        sys.exit(2)
    title, body = sys.argv[1], sys.argv[2]
    url = sys.argv[3] if len(sys.argv) > 3 else None
    status = notify(title, body, url=url)
    print(f"sent (HTTP {status}) to topic")
