# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Steps 4-5 of the PRODUCTS migration: reconcile OLD Content API products+statuses
against NEW Merchant API v1 products, for the same leaf accounts.

Emphasis on the fields the downstream pipeline actually consumes:
  - identity / Ads-FK: derived `channel`, content_language, feed_label, offer_id
  - targeting matcher: brand, condition, product_types, google_product_category,
    custom_label_0..4
  - `set_product_in_stock`: availability -> inStock bool
  - `set_product_approved`: Shopping/SHOPPING_ADS approved/pending/disapproved countries
  - representation: price (value/currency -> amount_micros/currency_code), gtin->gtins

Writes a human-readable report to stdout; the curated findings are hand-written
into `products_diff.md`.
"""

import glob
import json
import os
import pathlib

_HERE = pathlib.Path(__file__).parent
_OLD = _HERE / "old_products"
_NEW = _HERE / "new_products"


def _load_jsonl(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _old_index():
    """(accountId, offerId) -> {'product':..., 'status':...} from OLD data."""
    products, statuses = {}, {}
    for fn in glob.glob(str(_OLD / "*_products_rows.jsonlines")):
        for p in _load_jsonl(fn):
            acc = p["downloaderMetadata"]["accountId"]
            products[(acc, p["offerId"])] = p
    for fn in glob.glob(str(_OLD / "*_productstatuses_rows.jsonlines")):
        for s in _load_jsonl(fn):
            acc = s["downloaderMetadata"]["accountId"]
            # old status productId == product id "channel:lang:country:offer";
            # last colon-segment is the offerId
            offer = s["productId"].split(":")[-1]
            statuses[(acc, offer)] = s
    return products, statuses


def _new_index():
    out = {}
    for fn in glob.glob(str(_NEW / "*_products_rows.jsonlines")):
        for p in _load_jsonl(fn):
            acc = p["downloaderMetadata"]["accountId"]
            out[(acc, p["offer_id"])] = p
    return out


# ---- normalizers (old/new -> canonical) ----

def _old_channel(p):
    return (p.get("channel") or "online").lower()


def _new_channel(p):
    return "local" if p.get("legacy_local") else "online"


def _old_price(p):
    pr = p.get("price")
    if not pr:
        return None
    return (str(round(float(pr["value"]) * 1_000_000)), pr["currency"])


def _new_price(p):
    pr = p.get("product_attributes", {}).get("price")
    if not pr:
        return None
    return (str(pr["amount_micros"]), pr["currency_code"])


def _old_instock(p):
    return p.get("availability", "") == "in stock"


def _new_instock(p):
    return p.get("product_attributes", {}).get("availability", "") == "IN_STOCK"


def _old_shopping_countries(status):
    if not status:
        return None
    for d in status.get("destinationStatuses", []):
        if d.get("destination") == "Shopping":
            return {
                "approved": sorted(d.get("approvedCountries", [])),
                "pending": sorted(d.get("pendingCountries", [])),
                "disapproved": sorted(d.get("disapprovedCountries", [])),
            }
    return {"approved": [], "pending": [], "disapproved": []}


def _new_shopping_countries(p):
    for d in p.get("product_status", {}).get("destination_statuses", []):
        if d.get("reporting_context") == "SHOPPING_ADS":
            return {
                "approved": sorted(d.get("approved_countries", [])),
                "pending": sorted(d.get("pending_countries", [])),
                "disapproved": sorted(d.get("disapproved_countries", [])),
            }
    return {"approved": [], "pending": [], "disapproved": []}


def _old_gtin(p):
    g = p.get("gtin")
    return [g] if g else []


def _new_gtin(p):
    return list(p.get("product_attributes", {}).get("gtins", []) or [])


def main():
    old_products, old_statuses = _old_index()
    new_products = _new_index()

    old_keys, new_keys = set(old_products), set(new_products)
    common = old_keys & new_keys
    only_old = old_keys - new_keys
    only_new = new_keys - old_keys

    print(f"OLD products: {len(old_keys)} | NEW products: {len(new_keys)}")
    print(f"matched: {len(common)} | only_old: {len(only_old)} | only_new: {len(only_new)}")
    if only_old:
        print("  ONLY OLD:", sorted(only_old))
    if only_new:
        print("  ONLY NEW:", sorted(only_new))

    # Field-level reconciliation over matched products
    checks = {
        "channel(derived)": lambda o, s, n: (_old_channel(o), _new_channel(n)),
        "content_language": lambda o, s, n: (o.get("contentLanguage"), n.get("content_language")),
        "feed_label": lambda o, s, n: (o.get("feedLabel"), n.get("feed_label")),
        "offer_id": lambda o, s, n: (o.get("offerId"), n.get("offer_id")),
        "title": lambda o, s, n: (o.get("title"), n.get("product_attributes", {}).get("title")),
        "brand": lambda o, s, n: (o.get("brand"), n.get("product_attributes", {}).get("brand")),
        "condition(lower)": lambda o, s, n: (
            (o.get("condition") or "").lower(),
            (n.get("product_attributes", {}).get("condition") or "").lower(),
        ),
        "google_product_category": lambda o, s, n: (
            o.get("googleProductCategory"),
            n.get("product_attributes", {}).get("google_product_category"),
        ),
        "product_types": lambda o, s, n: (
            o.get("productTypes", []) or [],
            n.get("product_attributes", {}).get("product_types", []) or [],
        ),
        "gtin->gtins": lambda o, s, n: (_old_gtin(o), _new_gtin(n)),
        "price(micros)": lambda o, s, n: (_old_price(o), _new_price(n)),
        "inStock(semantic)": lambda o, s, n: (_old_instock(o), _new_instock(n)),
        "approved(SHOPPING)": lambda o, s, n: (
            _old_shopping_countries(s),
            _new_shopping_countries(n),
        ),
    }
    custom = {f"custom_label_{i}": i for i in range(5)}

    tally = {name: {"match": 0, "mismatch": 0, "examples": []} for name in checks}
    tally.update({name: {"match": 0, "mismatch": 0, "examples": []} for name in custom})

    for key in sorted(common):
        o = old_products[key]
        s = old_statuses.get(key)
        n = new_products[key]
        for name, fn in checks.items():
            ov, nv = fn(o, s, n)
            if ov == nv:
                tally[name]["match"] += 1
            else:
                tally[name]["mismatch"] += 1
                if len(tally[name]["examples"]) < 3:
                    tally[name]["examples"].append((key, ov, nv))
        for name, i in custom.items():
            ov = o.get(f"customLabel{i}")
            nv = n.get("product_attributes", {}).get(f"custom_label_{i}")
            if (ov or None) == (nv or None):
                tally[name]["match"] += 1
            else:
                tally[name]["mismatch"] += 1
                if len(tally[name]["examples"]) < 3:
                    tally[name]["examples"].append((key, ov, nv))

    print("\n==== field reconciliation (matched products) ====")
    print(f"{'field':28} {'match':>6} {'mismatch':>9}")
    for name, t in tally.items():
        print(f"{name:28} {t['match']:>6} {t['mismatch']:>9}")
        for ex in t["examples"]:
            print(f"      MISMATCH {ex[0]}: old={ex[1]!r} new={ex[2]!r}")


if __name__ == "__main__":
    main()
