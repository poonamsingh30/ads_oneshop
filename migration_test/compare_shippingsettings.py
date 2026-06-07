# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Step 4 of the SHIPPINGSETTINGS migration: reconcile OLD vs NEW.

Derives the 4 account-level MEX shipping booleans from BOTH shapes per account and
compares them. The booleans are the only thing downstream consumes:
  has_account_level_shipping        ARRAY_LENGTH(services) > 0
  has_account_level_shipping_speed  EXISTS service with all 4 transit/handling day fields set
  has_account_level_fast_shipping   EXISTS service with maxTransit + maxHandling <= 3
  has_account_level_free_shipping   EXISTS a zero flat rate (singleValue OR mainTable cell)

OLD shape (Content API): services[].deliveryTime.{min,max}{Transit,Handling}TimeInDays,
  rateGroups[].singleValue.flatRate.value / mainTable.rows[].cells[].flatRate.value (FLOAT/string major).
NEW shape (Merchant API v1): services[].delivery_time.{min,max}_{transit,handling}_days,
  rate_groups[].single_value.flat_rate.amount_micros / main_table.rows[].cells[].flat_rate.amount_micros (INT64 micros).

Reads old_shippingsettings/ and new_shippingsettings/. Writes
compare_shippingsettings_result.json. Exit 0 iff every boolean matches for every account.
"""

import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).parent
_OLD_DIR = _HERE / "old_shippingsettings"
_NEW_DIR = _HERE / "new_shippingsettings"


# ---- OLD (Content API) boolean derivation ---------------------------------
def _old_bools(services):
    has = len(services) > 0
    speed = any(
        all(s.get("deliveryTime", {}).get(k) is not None for k in
            ("minTransitTimeInDays", "maxTransitTimeInDays",
             "minHandlingTimeInDays", "maxHandlingTimeInDays"))
        for s in services)
    fast = any(
        (s.get("deliveryTime", {}).get("maxTransitTimeInDays") is not None and
         s.get("deliveryTime", {}).get("maxHandlingTimeInDays") is not None and
         s["deliveryTime"]["maxTransitTimeInDays"] +
         s["deliveryTime"]["maxHandlingTimeInDays"] <= 3)
        for s in services)

    def free_svc(s):
        for rg in s.get("rateGroups", []) or []:
            sv = rg.get("singleValue", {}).get("flatRate")
            if sv is not None and float(sv.get("value", "nan")) == 0:
                return True
            for row in (rg.get("mainTable", {}) or {}).get("rows", []) or []:
                for cell in row.get("cells", []) or []:
                    fr = cell.get("flatRate")
                    if fr is not None and float(fr.get("value", "nan")) == 0:
                        return True
        return False
    free = any(free_svc(s) for s in services)
    return {"has": has, "speed": speed, "fast": fast, "free": free}


# ---- NEW (Merchant API v1) boolean derivation -----------------------------
def _new_bools(services):
    has = len(services) > 0
    speed = any(
        all(s.get("delivery_time", {}).get(k) is not None for k in
            ("min_transit_days", "max_transit_days",
             "min_handling_days", "max_handling_days"))
        for s in services)
    fast = any(
        (s.get("delivery_time", {}).get("max_transit_days") is not None and
         s.get("delivery_time", {}).get("max_handling_days") is not None and
         s["delivery_time"]["max_transit_days"] +
         s["delivery_time"]["max_handling_days"] <= 3)
        for s in services)

    def free_svc(s):
        for rg in s.get("rate_groups", []) or []:
            sv = rg.get("single_value")
            if sv is not None:
                fr = sv.get("flat_rate")
                # micros: present-as-0 OR (defensive) absent treated as 0 when flat_rate set
                if fr is not None and int(fr.get("amount_micros", 0)) == 0:
                    return True
            for row in (rg.get("main_table", {}) or {}).get("rows", []) or []:
                for cell in row.get("cells", []) or []:
                    fr = cell.get("flat_rate")
                    if fr is not None and int(fr.get("amount_micros", 0)) == 0:
                        return True
        return False
    free = any(free_svc(s) for s in services)
    return {"has": has, "speed": speed, "fast": fast, "free": free}


# ---- loaders --------------------------------------------------------------
def _load_old():
    """account_id -> services[] from the {settings, children[]} envelopes."""
    out = {}
    for f in sorted(_OLD_DIR.glob("*_shippingsettings.json")):
        doc = json.loads(f.read_text())
        s = doc.get("settings") or {}
        if s.get("services"):
            out[str(s.get("accountId") or f.name.split("_")[0])] = s["services"]
        for child in doc.get("children", []):
            aid = child.get("accountId") or child.get("downloaderMetadata", {}).get("accountId")
            if aid and child.get("services"):
                out[str(aid)] = child["services"]
    return out


def _load_new():
    """account_id -> services[] from the flat per-account records."""
    out = {}
    for f in sorted(_NEW_DIR.glob("*_shippingsettings_rows.jsonlines")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            out[str(rec["account_id"])] = rec.get("services", []) or []
    return out


def main():
    old = _load_old()
    new = _load_new()
    all_ids = sorted(set(old) | set(new), key=lambda x: (len(x), x))

    results, n_match, n_mismatch = [], 0, 0
    print(f"{'account':>12} | {'boolean':<8} | old   new   ok")
    for aid in all_ids:
        ob = _old_bools(old.get(aid, []))
        nb = _new_bools(new.get(aid, []))
        row = {"account_id": aid, "old": ob, "new": nb, "mismatches": []}
        for k in ("has", "speed", "fast", "free"):
            ok = ob[k] == nb[k]
            if ok:
                n_match += 1
            else:
                n_mismatch += 1
                row["mismatches"].append(k)
            flag = "" if ok else "  <-- MISMATCH"
            print(f"{aid:>12} | {k:<8} | {str(ob[k]):<5} {str(nb[k]):<5} {ok}{flag}")
        results.append(row)
        print(f"{'':>12} +{'-'*30}")

    summary = {
        "n_accounts": len(all_ids),
        "n_old_only": sorted(set(old) - set(new)),
        "n_new_only": sorted(set(new) - set(old)),
        "boolean_checks_matched": n_match,
        "boolean_checks_mismatched": n_mismatch,
        "results": results,
    }
    (_HERE / "compare_shippingsettings_result.json").write_text(json.dumps(summary, indent=2))
    print(f"\naccounts={len(all_ids)}  boolean-checks matched={n_match}  mismatched={n_mismatch}")
    if summary["n_old_only"] or summary["n_new_only"]:
        print(f"key gaps: old_only={summary['n_old_only']} new_only={summary['n_new_only']}")
    if n_mismatch == 0 and not summary["n_old_only"] and not summary["n_new_only"]:
        print("RESULT: PASS — every boolean matches for every account.")
        return 0
    print("RESULT: FAIL — see mismatches above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
