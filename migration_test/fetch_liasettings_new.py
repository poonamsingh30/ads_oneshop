# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Step 3 of the LIASETTINGS migration: fetch the LIA/omnichannel config from the
NEW Merchant API stable v1 (`google.shopping.merchant_accounts_v1`).

v1 has NO `liasettings` resource. The Local Inventory Ads / local-storefront
config lives in **OmnichannelSettings**:

  OmnichannelSettingsServiceClient.list_omnichannel_settings(
      parent="accounts/{id}")  ->  OmnichannelSetting*   (one per region)

Unlike the old Content API, there is NO MCA roll-down `list` that returns the
children's settings — `list_omnichannel_settings` is per-account. So we fan out
over the SAME accounts the old baseline saw (aggregator + its children), reading
the account IDs from `old_liasettings/`. Each OmnichannelSetting -> dict (enum
names as strings) + downloaderMetadata{accountId}, written one per line.

Run inside the `oneshop_products_migration` conda env after sourcing
`migration_test/env.local.sh`. Output goes to `migration_test/new_liasettings/`.

Override the account set with ACCOUNT_IDS="a,b,c".
"""

import json
import os
import pathlib
import time

from google.api_core import exceptions as gexc
from google.oauth2 import credentials as oauth_credentials
from google.shopping.merchant_accounts_v1 import (
    OmnichannelSettingsServiceClient,
    ListOmnichannelSettingsRequest,
    OmnichannelSetting,
)

_METADATA_KEY = "downloaderMetadata"
_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_PAGE_SIZE = 250
_MAX_RETRIES = 5

_OUT_DIR = pathlib.Path(__file__).parent / "new_liasettings"
_OLD_DIR = pathlib.Path(__file__).parent / "old_liasettings"


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


def _to_dict(setting):
    """Render a proto-plus OmnichannelSetting to a dict with enum NAMES as strings."""
    return type(setting).to_dict(setting, use_integers_for_enums=False)


def _account_ids():
    """Same accounts the old baseline saw: aggregator(s) + their children."""
    env = os.environ.get("ACCOUNT_IDS", "").strip()
    if env:
        return [x for x in env.split(",") if x]
    ids = []
    for f in sorted(_OLD_DIR.glob("*_liasettings.json")):
        env_doc = json.loads(f.read_text())
        agg = str(env_doc["settings"].get("accountId") or f.name.split("_")[0])
        ids.append(agg)
        for child in env_doc.get("children", []):
            cid = child.get("accountId") or child.get("downloaderMetadata", {}).get("accountId")
            if cid:
                ids.append(str(cid))
    # de-dup, preserve order
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i); out.append(i)
    if not out:
        raise SystemExit("No ACCOUNT_IDS given and no old_liasettings/* to mirror.")
    return out


def main():
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = OmnichannelSettingsServiceClient(credentials=_get_credentials())

    summary = {"accounts": [], "api": "merchant_accounts_v1.OmnichannelSettings"}
    n_with_settings = 0
    for account_id in _account_ids():
        parent = f"accounts/{account_id}"
        request = ListOmnichannelSettingsRequest(parent=parent, page_size=_PAGE_SIZE)
        try:
            pager = _retry(lambda: client.list_omnichannel_settings(request=request))
            rows = []
            for setting in pager:
                d = _to_dict(setting)
                d[_METADATA_KEY] = {"accountId": account_id}
                rows.append(d)
        except gexc.PermissionDenied as e:
            print(f"  {account_id}: permission denied ({e.message[:60]}…); skip")
            continue
        except gexc.NotFound:
            rows = []
        out = _OUT_DIR / f"{account_id}_omnichannel_rows.jsonlines"
        with out.open("w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        if rows:
            (_OUT_DIR / f"{account_id}_omnichannel_sample.json").write_text(
                json.dumps(rows[0], indent=2)
            )
            n_with_settings += 1
        regions = [r.get("region_code") for r in rows]
        print(f"  {account_id}: {len(rows)} omnichannel setting(s) regions={regions}")
        summary["accounts"].append({
            "account_id": account_id, "n_settings": len(rows), "regions": regions,
        })

    (_OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nDone. {n_with_settings} account(s) with omnichannel settings -> {_OUT_DIR}")


if __name__ == "__main__":
    main()
