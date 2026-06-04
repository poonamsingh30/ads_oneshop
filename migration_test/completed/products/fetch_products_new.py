# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Step 3 of the PRODUCTS migration: fetch `products` from the NEW Merchant API
stable v1 (`google.shopping.merchant_products_v1`).

Mirrors what `acit.py` does per leaf today (`_pull_leaf_collection`), but against
the v1 `Product` resource, which carries BOTH the offer attributes
(`productAttributes`) AND the status (`productStatus`) — so the old
`productstatuses.list` call is gone.

  ProductsServiceClient.list_products(parent="accounts/{leaf}")  -> Product*
  each Product -> dict (enum names as strings) + downloaderMetadata{accountId}

Run inside the `oneshop_products_migration` conda env after sourcing
`migration_test/env.local.sh`. Output goes to `migration_test/new_products/`.

By default it fetches the SAME leaves that the old baseline found (so the diff is
apples-to-apples). Override with LEAF_IDS="a,b,c".
"""

import json
import os
import pathlib
import time

import proto
from google.api_core import exceptions as gexc
from google.oauth2 import credentials as oauth_credentials
from google.shopping.merchant_products_v1 import ProductsServiceClient

_METADATA_KEY = "downloaderMetadata"
_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_PAGE_SIZE = 250
_MAX_RETRIES = 5

_OUT_DIR = pathlib.Path(__file__).parent / "new_products"
_OLD_DIR = pathlib.Path(__file__).parent / "old_products"


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


def _to_dict(product):
    """Render a proto-plus Product to a JSON-ish dict with enum NAMES as strings."""
    return type(product).to_dict(product, use_integers_for_enums=False)


def _leaf_ids():
    env = os.environ.get("LEAF_IDS", "").strip()
    if env:
        return [x for x in env.split(",") if x]
    # default: whatever the old baseline saved
    summary = _OLD_DIR / "summary.json"
    if summary.exists():
        return [a["account_id"] for a in json.loads(summary.read_text())["accounts"]]
    raise SystemExit("No LEAF_IDS given and no old_products/summary.json to mirror.")


def main():
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = ProductsServiceClient(credentials=_get_credentials())

    summary = {"accounts": [], "page_size": _PAGE_SIZE, "api": "merchant_products_v1"}
    for leaf in _leaf_ids():
        parent = f"accounts/{leaf}"
        rows = []
        request = {"parent": parent, "page_size": _PAGE_SIZE}
        pager = _retry(lambda: client.list_products(request=request))
        for product in pager:
            d = _to_dict(product)
            d[_METADATA_KEY] = {"accountId": leaf}
            rows.append(d)
        out = _OUT_DIR / f"{leaf}_products_rows.jsonlines"
        with out.open("w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        if rows:
            (_OUT_DIR / f"{leaf}_product_sample.json").write_text(
                json.dumps(rows[0], indent=2)
            )
        print(f"  {leaf}: {len(rows)} products -> {out.name}")
        summary["accounts"].append({"account_id": leaf, "n_products": len(rows)})

    (_OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nDone -> {_OUT_DIR}")


if __name__ == "__main__":
    main()
