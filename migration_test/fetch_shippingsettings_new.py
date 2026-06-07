# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Step 3 of the SHIPPINGSETTINGS migration: fetch shipping config from the NEW
Merchant API stable v1 (`google.shopping.merchant_accounts_v1`).

v1 has NO Content-API `shippingsettings` resource. Account-level shipping config
lives in **ShippingSettings**, a singleton per account:

  ShippingSettingsServiceClient.get_shipping_settings(
      name="accounts/{id}/shippingSettings")  ->  ShippingSettings

There is NO MCA roll-down `list`. So we fan out over the SAME accounts the old
baseline saw (the MCA's children), reading account IDs from `old_shippingsettings/`.
Each ShippingSettings -> a flat dict `{account_id, services[], warehouses[], etag}`
(enum names as strings, snake_case) + downloaderMetadata{accountId}, one per line.

Also answers the Step-2 open questions live:
  Q1  how is a FREE rate (old flatRate.value=0) rendered? Is `amount_micros`
      present-as-0 or omitted? (drives the free-shipping SQL).
  Q3  does an account with no settings raise NotFound, or return empty services?

Run inside the `oneshop_products_migration` conda env after sourcing
`migration_test/env.local.sh`. Output -> `migration_test/new_shippingsettings/`.

Override the account set with ACCOUNT_IDS="a,b,c".
"""

import json
import os
import pathlib
import time

from google.api_core import exceptions as gexc
from google.oauth2 import credentials as oauth_credentials
from google.shopping.merchant_accounts_v1 import (
    ShippingSettingsServiceClient,
    GetShippingSettingsRequest,
    ShippingSettings,
)

_METADATA_KEY = "downloaderMetadata"
_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_MAX_RETRIES = 5

_OUT_DIR = pathlib.Path(__file__).parent / "new_shippingsettings"
_OLD_DIR = pathlib.Path(__file__).parent / "old_shippingsettings"


def _get_credentials():
    return oauth_credentials.Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_ADS_REFRESH_TOKEN"].strip(),
        token_uri=_OAUTH_TOKEN_ENDPOINT,
        client_id=os.environ["GOOGLE_ADS_CLIENT_ID"].strip(),
        client_secret=os.environ["GOOGLE_ADS_CLIENT_SECRET"].strip(),
    )


def _retry(fn):
    """Exponential backoff for the Merchant API's transient 500s (Phase-1 pattern)."""
    delay = 1.0
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except (gexc.InternalServerError, gexc.ServiceUnavailable,
                gexc.DeadlineExceeded) as e:
            if attempt == _MAX_RETRIES - 1:
                raise
            print(f"    transient {type(e).__name__}; retry in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 16.0)


def _to_dict(settings):
    """Render a proto-plus ShippingSettings to a dict with enum NAMES as strings."""
    return type(settings).to_dict(settings, use_integers_for_enums=False)


def _account_ids():
    """Same accounts the old baseline saw: MCA + its children."""
    env = os.environ.get("ACCOUNT_IDS", "").strip()
    if env:
        return [x for x in env.split(",") if x]
    ids = []
    for f in sorted(_OLD_DIR.glob("*_shippingsettings.json")):
        doc = json.loads(f.read_text())
        agg = str((doc.get("settings") or {}).get("accountId") or f.name.split("_")[0])
        ids.append(agg)
        for child in doc.get("children", []):
            cid = child.get("accountId") or child.get("downloaderMetadata", {}).get("accountId")
            if cid:
                ids.append(str(cid))
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i); out.append(i)
    if not out:
        raise SystemExit("No ACCOUNT_IDS given and no old_shippingsettings/* to mirror.")
    return out


def _free_probe(services):
    """Q1: report how a 0 flat rate renders (amount_micros present-as-0, omitted, or no_shipping)."""
    notes = []
    for s in services:
        for rg in s.get("rate_groups", []) or []:
            sv = rg.get("single_value")
            if sv is not None:
                fr = sv.get("flat_rate")
                if fr is not None:
                    notes.append(f"single_value.flat_rate keys={sorted(fr.keys())} "
                                 f"amount_micros={fr.get('amount_micros', '<<ABSENT>>')}")
                elif sv.get("no_shipping"):
                    notes.append("single_value.no_shipping=true")
    return notes


def main():
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = ShippingSettingsServiceClient(credentials=_get_credentials())

    summary = {"accounts": [], "api": "merchant_accounts_v1.ShippingSettings", "free_probe": {}}
    n_with = 0
    for account_id in _account_ids():
        name = f"accounts/{account_id}/shippingSettings"
        request = GetShippingSettingsRequest(name=name)
        try:
            settings = _retry(lambda: client.get_shipping_settings(request=request))
        except gexc.PermissionDenied as e:
            print(f"  {account_id}: permission denied ({e.message[:60]}…); skip")
            continue
        except gexc.NotFound:
            print(f"  {account_id}: NotFound (no shipping settings)")
            summary["accounts"].append({"account_id": account_id, "found": False, "n_services": 0})
            continue

        d = _to_dict(settings)
        services = d.get("services", []) or []
        record = {
            "account_id": int(account_id),
            "services": services,
            "warehouses": d.get("warehouses", []) or [],
            "etag": d.get("etag"),
            _METADATA_KEY: {"accountId": account_id},
        }
        out = _OUT_DIR / f"{account_id}_shippingsettings_rows.jsonlines"
        out.write_text(json.dumps(record) + "\n")
        (_OUT_DIR / f"{account_id}_shippingsettings_sample.json").write_text(
            json.dumps(record, indent=2))

        probe = _free_probe(services)
        if probe:
            summary["free_probe"][account_id] = probe
        n_with += 1 if services else 0
        countries = [s.get("delivery_countries") for s in services]
        print(f"  {account_id}: {len(services)} service(s) countries={countries}")
        for p in probe:
            print(f"      [free-probe] {p}")
        summary["accounts"].append({
            "account_id": account_id, "found": True, "n_services": len(services),
        })

    (_OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nDone. {n_with} account(s) with services -> {_OUT_DIR}")


if __name__ == "__main__":
    main()
