# Depop Scrape Research

Regenerated and **live-verified 2026-06-09** via Chrome network inspection (the original
Phase 1 artifact was missing). Old `webapi.depop.com/api/v2|v3` endpoints return
`{"code":9001,"message":"Deprecated endpoint"}` — do not use.

## Approach: unofficial presentation API (no browser)

The Depop web app fetches search results from:

```
GET https://www.depop.com/presentation/api/v1/search/products/
    ?what=vintage+hat
    &limit=24
    &country=us
    &currency=USD
    &price_max=20
    &from=in_country_search
    &include_like_count=true
    &after=<page_info.last from previous page>   # omit for page 1
```

### Required headers (verified)

Without these the API returns 400. **Freshly generated UUIDs are accepted** — no
login/session needed:

```
Accept: application/json
Content-Type: application/json
User-Agent: <real browser UA>
depop-device-id: <uuid4>
depop-session-id: <uuid4>
depop-search-id: <uuid4>      # new per request
x-cached-sizes: true
```

### Response shape (verified)

```
{
  "meta": {"total_count": 285816},
  "page_info": {"has_more": true, "last": "<cursor for `after`>"},
  "objects": [
    {
      "id": 776584724,
      "slug": "<seller>-<title-words>-<hash>",     // listing URL = depop.com/products/<slug>/
      "brand_name": "Other",                       // "Other" = unbranded
      "category_name": "Hats",
      "description": "full listing description...", // full text — no detail fetch needed!
      "attributes": {"condition": "used_excellent", "colour": [...], "product_type": "hat", ...},
      "pictures": [{"formats": {"P0": {"url": "...", "width": 1280, ...}}}],
      "preview": {...same format...},
      "pricing": {
        "currency_name": "USD",
        "final_price_key": "discounted_price" | "original_price",
        "original_price": {"total_price": "10.00", ...},
        "discounted_price": {"total_price": "7.00", ...},
        "discount_percentage": 30,
        "is_reduced": true
      },
      "like_count": ..., "location": "...", "country": "US",
      "is_boosted": false, "shipping_method": {...}
    }
  ]
}
```

Key takeaways:
- Search rows include **full description, brand, condition, images** → no per-listing
  detail requests needed. One request per page of 24.
- Price = `pricing[pricing.final_price_key].total_price` (string).
- Seller username = slug prefix before first `-` (approximation; good enough for display).
- Pagination: pass `page_info.last` as `after`.

## Rate limits

Unknown published limits. Be polite:
- ≥2s jittered delay between requests (`request_delay_seconds` in config).
- ≤2 pages per query per run.
- On 429/403: abort the run (handled as `RateLimited` in depop.py).

## Cost budget

- Rules (value_rubric.json) classify everything first — target 90%+ decided by rules.
- LLM only for the ambiguous "maybe" band, one batched call per run.
- Vision check only top 3 maybes. Tokens logged per run; cap in config.
