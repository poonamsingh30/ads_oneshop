# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Step 4 of the LIASETTINGS migration: reconcile OLD Content API `liasettings`
vs NEW Merchant API v1 `OmnichannelSettings` on the fields the pipeline consumes.

The downstream pipeline reads the `liasettings` table only to compute FOUR
booleans per (merchant, region) in the MEX SQL. So the comparison that matters is:
for each (accountId, region), do the 4 booleans evaluate identically when derived
from the OLD shape vs the NEW shape?

  lia_has_lia_implemented        old: inventory.status='active' AND
                                      inventory.inventoryVerificationContactStatus='active' AND
                                      about.status='active'
                                 new: in_stock.state='ACTIVE' AND
                                      inventory_verification.contact_state='ACTIVE' AND
                                      about.state='ACTIVE'
  lia_has_mhlsf_implemented      old: hostedLocalStorefrontActive OR
                                      omnichannelExperience.lsfType IN (mhlsfBasic,mhlsfFull)
                                 new: lsf_type IN (GHLSF,MHLSF_BASIC,MHLSF_FULL)
  lia_has_store_pickup_implemented old: storePickupActive OR len(pickupType)>0
                                 new: pickup.state='ACTIVE'
  lia_has_odo_implemented        old: onDisplayToOrder.status='active'
                                 new: odo.state='ACTIVE'

Run inside the conda env. Reads old_liasettings/ + new_liasettings/, prints a
reconciliation table, writes compare_liasettings_result.json.
"""

import json
import pathlib

_HERE = pathlib.Path(__file__).parent
_OLD_DIR = _HERE / "old_liasettings"
_NEW_DIR = _HERE / "new_liasettings"


# ---- OLD shape boolean derivations ---------------------------------------
def _old_bools(cs):
    inv = cs.get("inventory", {})
    odo = cs.get("onDisplayToOrder", {})
    about = cs.get("about", {})
    omni = cs.get("omnichannelExperience", {})
    return {
        "lia": (inv.get("status") == "active"
                and inv.get("inventoryVerificationContactStatus") == "active"
                and about.get("status") == "active"),
        "mhlsf": (bool(cs.get("hostedLocalStorefrontActive"))
                  or omni.get("lsfType") in ("mhlsfBasic", "mhlsfFull")),
        "pickup": (bool(cs.get("storePickupActive"))
                   or len(omni.get("pickupType", []) or []) > 0),
        "odo": odo.get("status") == "active",
    }


# ---- NEW shape boolean derivations ---------------------------------------
def _new_bools(s):
    in_stock = s.get("in_stock", {}) or {}
    iv = s.get("inventory_verification", {}) or {}
    about = s.get("about", {}) or {}
    pickup = s.get("pickup", {}) or {}
    odo = s.get("odo", {}) or {}
    return {
        "lia": (in_stock.get("state") == "ACTIVE"
                and iv.get("contact_state") == "ACTIVE"
                and about.get("state") == "ACTIVE"),
        "mhlsf": s.get("lsf_type") in ("GHLSF", "MHLSF_BASIC", "MHLSF_FULL"),
        "pickup": pickup.get("state") == "ACTIVE",
        "odo": odo.get("state") == "ACTIVE",
    }


def _load_old():
    """(accountId, region) -> old countrySettings dict, flattening settings ∪ children."""
    out = {}
    for f in sorted(_OLD_DIR.glob("*_liasettings.json")):
        env = json.loads(f.read_text())
        records = []
        if env.get("settings"):
            records.append(env["settings"])
        records.extend(env.get("children", []))
        for rec in records:
            acc = str(rec.get("accountId") or "")
            for cs in rec.get("countrySettings", []) or []:
                out[(acc, cs.get("country"))] = cs
    return out


def _load_new():
    """(accountId, region) -> new OmnichannelSetting dict."""
    out = {}
    for f in sorted(_NEW_DIR.glob("*_omnichannel_rows.jsonlines")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            s = json.loads(line)
            acc = str(s.get("downloaderMetadata", {}).get("accountId") or "")
            out[(acc, s.get("region_code"))] = s
    return out


def main():
    old = _load_old()
    new = _load_new()
    keys = sorted(set(old) | set(new))

    cols = ["lia", "mhlsf", "pickup", "odo"]
    tally = {c: {"match": 0, "mismatch": 0} for c in cols}
    rows = []
    only_old = sorted(set(old) - set(new))
    only_new = sorted(set(new) - set(old))

    for k in sorted(set(old) & set(new)):
        ob, nb = _old_bools(old[k]), _new_bools(new[k])
        rec = {"account": k[0], "region": k[1]}
        for c in cols:
            same = ob[c] == nb[c]
            tally[c]["match" if same else "mismatch"] += 1
            rec[c] = f"{ob[c]}|{nb[c]}" + ("" if same else "  ❌")
        rows.append(rec)

    print(f"keys: old={len(old)} new={len(new)} "
          f"both={len(set(old)&set(new))} only_old={len(only_old)} only_new={len(only_new)}")
    if only_old:
        print("  only in OLD:", only_old)
    if only_new:
        print("  only in NEW:", only_new)
    print()
    hdr = f"{'account':>12} {'region':>6} | " + " | ".join(f"{c:>14}" for c in cols)
    print(hdr); print("-" * len(hdr))
    for r in rows:
        print(f"{r['account']:>12} {r['region']:>6} | "
              + " | ".join(f"{r[c]:>14}" for c in cols))
    print()
    total_mm = sum(tally[c]["mismatch"] for c in cols)
    for c in cols:
        print(f"  {c:>8}: {tally[c]['match']} match, {tally[c]['mismatch']} mismatch")
    print(f"\nTOTAL boolean mismatches: {total_mm}")

    result = {
        "keys": {"old": len(old), "new": len(new),
                 "both": len(set(old) & set(new)),
                 "only_old": only_old, "only_new": only_new},
        "tally": tally, "total_boolean_mismatches": total_mm, "rows": rows,
    }
    (_HERE / "compare_liasettings_result.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
