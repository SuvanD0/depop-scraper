"""LLM fallback for ambiguous 'maybe' listings. One batched call per run.

Uses the Anthropic API directly via urllib (no SDK dependency).
Requires ANTHROPIC_API_KEY in env. Tokens are logged and capped per run.
"""
from __future__ import annotations

import json
import os
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM = (
    "You appraise vintage hats for resale arbitrage. For each listing decide if it is "
    "underpriced and worth buying to resell. Reply ONLY with a JSON array, one object "
    'per listing: {"id": str, "verdict": "buy"|"skip", "reason": str (<=10 words)}.'
)


def _call(payload: dict, api_key: str) -> dict:
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def judge_maybes(maybes: list[dict], cfg: dict) -> tuple[dict[str, dict], int]:
    """Return ({listing_id: {verdict, reason}}, tokens_used). Empty if disabled/no key."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not maybes or not cfg.get("enabled") or not api_key:
        return {}, 0

    vision_n = cfg.get("vision_top_n", 3)
    top = sorted(maybes, key=lambda x: x["score"], reverse=True)
    content: list[dict] = []
    for i, item in enumerate(top):
        l = item["listing"]
        desc = (l.get("description") or "")[:400]
        content.append({
            "type": "text",
            "text": f"id={l['id']} | ${l['price']:.2f} | brand={l.get('brand') or '?'} | "
                    f"title={l['title']} | signals={','.join(item['signals'])} | desc={desc}",
        })
        if i < vision_n and l.get("images"):
            content.append({"type": "image", "source": {"type": "url", "url": l["images"][0]}})

    payload = {
        "model": cfg.get("model", "claude-haiku-4-5-20251001"),
        "max_tokens": min(1500, cfg.get("max_tokens_per_run", 4000)),
        "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": content}],
    }
    try:
        resp = _call(payload, api_key)
    except Exception as e:
        print(f"[llm] call failed: {e}")
        return {}, 0

    usage = resp.get("usage", {})
    tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    text = "".join(b.get("text", "") for b in resp.get("content", []))
    try:
        start, end = text.index("["), text.rindex("]") + 1
        verdicts = json.loads(text[start:end])
        return {str(v["id"]): v for v in verdicts if "id" in v}, tokens
    except (ValueError, json.JSONDecodeError):
        print(f"[llm] unparseable response: {text[:200]}")
        return {}, tokens
