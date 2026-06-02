# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Step 1 of the PRODUCTS migration: fetch `products` + `productstatuses` from
the OLD Content API v2.1.

This intentionally mirrors the production logic in `acit/acit.py`:
  - topology via `accounts.authinfo` (aggregators vs standalone),
  - leaf discovery via `accounts.list` on each aggregator,
  - then, per leaf, `_pull_leaf_collection`-style `products.list` and
    `productstatuses.list` with params {'merchantId': <leaf>, 'maxResults': 250},
    paging via the discovery client's `<method>_next` helper, stamping
    downloaderMetadata={'accountId': <leaf>}.

Run inside the `oneshop_products_migration` conda env after sourcing
`migration_test/env.local.sh`. Output goes to `migration_test/old_products/`.

Env knobs (optional):
  MAX_ACCOUNTS_WITH_PRODUCTS  stop after this many leaves that actually have
                              products (default 2; 0 = no cap / all leaves).
  MAX_PRODUCTS_PER_ACCOUNT    cap products saved per leaf (default 200; 0 = all).
"""

import json
import os
import pathlib

from google.oauth2 import credentials as oauth_credentials
from googleapiclient import discovery

_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_METADATA_KEY = "downloaderMetadata"  # matches resource_downloader.METADATA_KEY
_NUM_RETRIES = 3
_PAGE_SIZE = 250  # matches acit.py _pull_leaf_collection maxResults

_OUT_DIR = pathlib.Path(__file__).parent / "old_products"

_MAX_ACCOUNTS_WITH_PRODUCTS = int(os.environ.get("MAX_ACCOUNTS_WITH_PRODUCTS", "2"))
_MAX_PRODUCTS_PER_ACCOUNT = int(os.environ.get("MAX_PRODUCTS_PER_ACCOUNT", "200"))


def _get_credentials():
    """Same OAuth refresh-token flow as acit.acit._get_credentials."""
    return oauth_credentials.Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_ADS_REFRESH_TOKEN"].strip(),
        token_uri=_OAUTH_TOKEN_ENDPOINT,
        client_id=os.environ["GOOGLE_ADS_CLIENT_ID"].strip(),
        client_secret=os.environ["GOOGLE_ADS_CLIENT_SECRET"].strip(),
    )


def _get_merchant_center_api():
    return discovery.build("content", "v2.1", credentials=_get_credentials())


def _get_results(collection, params, method, result_path, metadata, is_scalar=False,
                 limit=0):
    """Faithful copy of resource_downloader.get_results (with an optional cap)."""
    request = getattr(collection(), method)(**params)
    if is_scalar:
        yield request.execute(num_retries=_NUM_RETRIES)
        return
    n = 0
    while request:
        response = request.execute(num_retries=_NUM_RETRIES)
        for result in response.get(result_path, []):
            result[_METADATA_KEY] = metadata or {}
            yield result
            n += 1
            if limit and n >= limit:
                return
        request = getattr(collection(), f"{method}_next")(request, response)


def _discover_leaves(api, input_ids):
    """authinfo -> classify; accounts.list on aggregators -> leaf merchant IDs."""
    aggregator_ids, standalone_ids = set(), set()
    authinfo = next(_get_results(api.accounts, {}, "authinfo", "", {}, is_scalar=True))
    for ident in authinfo.get("accountIdentifiers", []):
        if "merchantId" in ident:
            standalone_ids.add(ident["merchantId"])
        else:
            aggregator_ids.add(ident["aggregatorId"])

    leaf_ids = []
    for agg in sorted(aggregator_ids & input_ids):
        for child in _get_results(
            api.accounts, {"merchantId": agg}, "list", "resources",
            {"parentId": agg},
        ):
            cid = str(child.get("id"))
            if cid and cid != agg:
                leaf_ids.append(cid)
    # standalone accounts explicitly requested also count as leaves
    leaf_ids += sorted(standalone_ids & input_ids)
    print(f"aggregators={sorted(aggregator_ids)} standalone={sorted(standalone_ids)}")
    print(f"discovered {len(leaf_ids)} leaf account(s)")
    return leaf_ids


def _pull_leaf_collection(api, account_id, resource, result_path="resources",
                          limit=0):
    """Mirror acit.py _pull_leaf_collection: <resource>.list for one leaf."""
    rows = list(_get_results(
        getattr(api, resource),
        {"merchantId": account_id, "maxResults": _PAGE_SIZE},
        "list",
        result_path,
        {"accountId": account_id},
        limit=limit,
    ))
    return rows


def _write_jsonlines(path, rows):
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main():
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    api = _get_merchant_center_api()
    input_ids = set(os.environ.get("MERCHANT_IDS", "").split(","))
    input_ids.discard("")

    leaf_ids = _discover_leaves(api, input_ids)

    summary = {"accounts": [], "page_size": _PAGE_SIZE}
    n_with_products = 0
    for account_id in leaf_ids:
        products = _pull_leaf_collection(
            api, account_id, "products", limit=_MAX_PRODUCTS_PER_ACCOUNT
        )
        if not products:
            print(f"  {account_id}: 0 products (skip)")
            continue
        statuses = _pull_leaf_collection(
            api, account_id, "productstatuses", limit=_MAX_PRODUCTS_PER_ACCOUNT
        )
        _write_jsonlines(_OUT_DIR / f"{account_id}_products_rows.jsonlines", products)
        _write_jsonlines(
            _OUT_DIR / f"{account_id}_productstatuses_rows.jsonlines", statuses
        )
        # pretty sample of the first product + status for quick eyeballing
        (_OUT_DIR / f"{account_id}_product_sample.json").write_text(
            json.dumps(products[0], indent=2)
        )
        (_OUT_DIR / f"{account_id}_productstatus_sample.json").write_text(
            json.dumps(statuses[0], indent=2) if statuses else "{}"
        )
        print(f"  {account_id}: {len(products)} products, {len(statuses)} statuses")
        summary["accounts"].append({
            "account_id": account_id,
            "n_products": len(products),
            "n_statuses": len(statuses),
        })
        n_with_products += 1
        if _MAX_ACCOUNTS_WITH_PRODUCTS and n_with_products >= _MAX_ACCOUNTS_WITH_PRODUCTS:
            break

    (_OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nDone. {n_with_products} account(s) with products -> {_OUT_DIR}")
    if not n_with_products:
        print("!! No products found on any leaf. Check MERCHANT_IDS / credential access.")


if __name__ == "__main__":
    main()
