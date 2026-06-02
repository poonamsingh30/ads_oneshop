# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Step 4: compare OLD Content API accounts vs NEW Merchant API v1 accounts.

Reads:
  old_accounts/<mca>_accounts_rows.jsonlines  ({settings, children[]} rollup)
  new_accounts/accounts_rows.jsonlines        (flat one-row-per-account)

Emits a field-level reconciliation to stdout: account coverage, then for a sample
parent + child, the value of each migrated field side by side, plus which old
fields have NO populated new equivalent (true gaps).
"""

import glob
import json
import pathlib

_DIR = pathlib.Path(__file__).parent


def _load_old():
    """Return {account_id: old_account_obj} flattening the {settings, children} rollup."""
    out = {}
    for fp in glob.glob(str(_DIR / "old_accounts" / "*_accounts_rows.jsonlines")):
        rec = json.loads(pathlib.Path(fp).read_text().splitlines()[0])
        parent = rec["settings"]
        out[str(parent["id"])] = parent
        for child in rec["children"]:
            out[str(child["id"])] = child
    return out


def _load_new():
    rows = [
        json.loads(l)
        for l in (_DIR / "new_accounts" / "accounts_rows.jsonlines").read_text().splitlines()
    ]
    return {str(r["account_id"]): r for r in rows}


def _g(d, *path, default=None):
    cur = d
    for p in path:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return default
    return cur if cur is not None else default


# (label, old-extractor, new-extractor)
_FIELD_PROBES = [
    ("id", lambda o: o.get("id"), lambda n: n.get("account_id")),
    ("name", lambda o: o.get("name"), lambda n: n.get("account_name")),
    ("adultContent", lambda o: o.get("adultContent"), lambda n: n.get("adult_content")),
    ("kind", lambda o: o.get("kind"), lambda n: "<dropped>"),
    ("websiteUrl", lambda o: o.get("websiteUrl"), lambda n: _g(n, "homepage", "uri")),
    ("addr.street", lambda o: _g(o, "businessInformation", "address", "streetAddress"),
     lambda n: _g(n, "business_info", "address", "street_address")),
    ("addr.locality->city", lambda o: _g(o, "businessInformation", "address", "locality"),
     lambda n: _g(n, "business_info", "address", "city")),
    ("addr.region->adminArea", lambda o: _g(o, "businessInformation", "address", "region"),
     lambda n: _g(n, "business_info", "address", "administrative_area")),
    ("addr.country->regionCode", lambda o: _g(o, "businessInformation", "address", "country"),
     lambda n: _g(n, "business_info", "address", "region_code")),
    ("addr.postalCode", lambda o: _g(o, "businessInformation", "address", "postalCode"),
     lambda n: _g(n, "business_info", "address", "postal_code")),
    ("bizIdentity.promotions",
     lambda o: _g(o, "businessIdentity", "includeForPromotions"),
     lambda n: _g(n, "business_identity", "promotions_consent")),
    ("AI.image.effective",
     lambda o: _g(o, "automaticImprovements", "imageImprovements", "effectiveAllowAutomaticImageImprovements"),
     lambda n: _g(n, "automatic_improvements", "image_improvements", "effective_allow_automatic_image_improvements")),
    ("AI.item.priceUpd",
     lambda o: _g(o, "automaticImprovements", "itemUpdates", "effectiveAllowPriceUpdates"),
     lambda n: _g(n, "automatic_improvements", "item_updates", "effective_allow_price_updates")),
    ("AI.item.availUpd",
     lambda o: _g(o, "automaticImprovements", "itemUpdates", "effectiveAllowAvailabilityUpdates"),
     lambda n: _g(n, "automatic_improvements", "item_updates", "effective_allow_availability_updates")),
    ("AI.item.strictAvail",
     lambda o: _g(o, "automaticImprovements", "itemUpdates", "effectiveAllowStrictAvailabilityUpdates"),
     lambda n: _g(n, "automatic_improvements", "item_updates", "effective_allow_strict_availability_updates")),
    ("AI.item.conditionUpd",
     lambda o: _g(o, "automaticImprovements", "itemUpdates", "effectiveAllowConditionUpdates"),
     lambda n: _g(n, "automatic_improvements", "item_updates", "effective_allow_condition_updates")),
    ("AI.shipping.allow",
     lambda o: _g(o, "automaticImprovements", "shippingImprovements", "allowShippingImprovements"),
     lambda n: _g(n, "automatic_improvements", "shipping_improvements", "allow_shipping_improvements")),
    ("#users", lambda o: len(o.get("users", []) or []), lambda n: len(n.get("users", []) or [])),
    ("#adsLinks->services",
     lambda o: len(o.get("adsLinks", []) or []),
     lambda n: len([s for s in (n.get("account_services") or [])
                    if "GOOGLE_ADS" in str(s.get("provider", ""))])),
    ("accountManagement",
     lambda o: o.get("accountManagement"),
     lambda n: "<via account_services oneof>"),
    ("conversionSettings",
     lambda o: _g(o, "conversionSettings", "freeListingsAutoTaggingEnabled"),
     lambda n: "<NOT in accounts v1>"),
    ("googleMyBusinessLink",
     lambda o: "present" if o.get("googleMyBusinessLink") else None,
     lambda n: "<GbpAccountsService — not pulled>"),
]


def _probe_table(old_obj, new_obj):
    lines = []
    for label, of, nf in _FIELD_PROBES:
        ov = of(old_obj) if old_obj else None
        nv = nf(new_obj) if new_obj else None
        match = "≈" if str(ov) == str(nv) else " "
        lines.append(f"  {match} {label:26s} OLD={str(ov)[:40]:<42s} NEW={str(nv)[:48]}")
    return "\n".join(lines)


def main():
    old, new = _load_old(), _load_new()
    old_ids, new_ids = set(old), set(new)
    print("=== Account coverage ===")
    print(f"  old accounts: {len(old_ids)}   new accounts: {len(new_ids)}")
    print(f"  only in OLD : {sorted(old_ids - new_ids)}")
    print(f"  only in NEW : {sorted(new_ids - old_ids)}")
    print(f"  in both     : {len(old_ids & new_ids)}")

    # pick a parent (advanced) and a child present in both
    parent_id = next((i for i in new if new[i]["is_advanced"] and i in old), None)
    child_id = next((i for i in new if new[i]["parent_account"] and i in old), None)

    for label, aid in [("PARENT/MCA", parent_id), ("CHILD", child_id)]:
        if not aid:
            continue
        print(f"\n=== {label}  account {aid} ===")
        print(_probe_table(old.get(aid), new.get(aid)))

    # aggregate gap check across ALL common accounts for the MEX-critical fields
    print("\n=== Aggregate check across all common accounts (MEX-critical fields) ===")
    crit = [p for p in _FIELD_PROBES if p[0].startswith("AI.")]
    common = sorted(old_ids & new_ids)
    for label, of, nf in crit:
        mism = [a for a in common if str(of(old[a])) != str(nf(new[a]))]
        print(f"  {label:26s} mismatches: {len(mism)}/{len(common)}"
              + (f"  e.g. {mism[:3]}" if mism else ""))


if __name__ == "__main__":
    main()
