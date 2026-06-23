"""Rule-based scoring against value_rubric.json v2.

Implements the playbook's per-brand max-buy rule and the 3+ rarity-factor rule.
No tokens spent here.
"""
from __future__ import annotations

import json
import re


def load_rubric(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _text(listing: dict) -> str:
    return " ".join([
        listing.get("title", ""),
        listing.get("brand", ""),
        listing.get("description", ""),
    ]).lower()


def _match(text: str, keyword: str) -> bool:
    return re.search(r"\b" + re.escape(keyword) + r"\b", text) is not None


def _first_match(text: str, keywords: list[str]) -> str | None:
    for k in keywords:
        if _match(text, k):
            return k
    return None


def _any_match(text: str, keywords: list[str]) -> bool:
    return _first_match(text, keywords) is not None


def score(listing: dict, rubric: dict) -> dict:
    text = _text(listing)
    pts = 0
    hits: list[str] = []
    price = listing.get("price", 999.0)

    # Brand match
    matched_brand: str | None = None
    matched_spec: dict | None = None
    for brand, spec in rubric["brands"].items():
        if not _match(text, brand):
            continue
        requires = spec.get("requires_kw")
        if requires and not _any_match(text, requires):
            continue
        matched_brand = brand
        matched_spec = spec
        pts += spec["weight"]
        hits.append(f"brand:{brand}({spec['tier']})")
        break

    # Era
    era = rubric["era_signals"]
    if _any_match(text, era["strong"]):
        pts += era["strong_weight"]
        hits.append("era:strong")
    elif _any_match(text, era["weak"]):
        pts += era["weak_weight"]
        hits.append("era:weak")

    # Defunct teams (rare = big bonus)
    defunct = rubric["defunct_teams"]
    df_match = _first_match(text, defunct["tier1"])
    if df_match:
        pts += defunct["weight"]
        hits.append(f"defunct:{df_match}")

    # Premium (non-defunct) teams
    premium = rubric["premium_teams"]
    pt_match = _first_match(text, premium["names"])
    if pt_match and not df_match:
        pts += premium["weight"]
        hits.append(f"team:{pt_match}")

    # 3+ rarity factor rule
    factors = rubric["rarity_factors"]
    factor_hits = [k for k in factors["keywords"] if _match(text, k)]
    if factor_hits:
        pts += min(len(factor_hits), 3) * factors["weight_per_factor"]
        hits.append(f"factors:{len(factor_hits)}({','.join(factor_hits[:3])})")
    if len(factor_hits) >= 3:
        pts += factors["three_plus_bonus"]
        hits.append("3+factor_rule")

    # Premium-keyword brand bonus (script Sports Specialties, Big Logo Game, etc.)
    if matched_spec and matched_spec.get("premium_kw"):
        pk = _first_match(text, matched_spec["premium_kw"])
        if pk:
            pts += 12
            hits.append(f"premium_kw:{pk}")

    # Negatives
    neg = rubric["negative_signals"]
    n = _first_match(text, neg["keywords"])
    if n:
        pts += neg["weight"]
        hits.append(f"neg:{n}")

    # Per-brand price gating (playbook's "Guaranteed Buy" thresholds)
    bonuses = rubric["price_bonuses"]
    if matched_spec:
        max_buy = matched_spec.get("max_buy", 0)
        max_buy_premium = matched_spec.get("max_buy_premium", max_buy)
        if max_buy and price <= max_buy:
            pts += bonuses["at_or_under_max_buy"]
            hits.append(f"price<=brand_max(${max_buy})")
            if price <= max_buy * bonuses["well_under_max_buy_pct"]:
                pts += bonuses["well_under_max_buy_bonus"]
                hits.append("price<<brand_max")
        elif max_buy_premium and price <= max_buy_premium and matched_spec.get("premium_kw") and _any_match(text, matched_spec["premium_kw"]):
            pts += bonuses["under_premium_max_buy"]
            hits.append(f"price<=premium_max(${max_buy_premium})")
        elif max_buy and price > max_buy:
            # Above brand's max-buy threshold — playbook says skip; drag score down
            pts -= 15
            hits.append(f"price>brand_max(${max_buy})")

    pts = max(0, min(100, pts))
    th = rubric["thresholds"]
    if pts >= th["buy"]:
        verdict = "buy"
    elif pts >= th["maybe"]:
        verdict = "maybe"
    else:
        verdict = "skip"
    return {"score": pts, "verdict": verdict, "signals": hits}
