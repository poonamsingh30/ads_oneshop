# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Step 1 of the accounts migration: fetch `accounts` from the OLD Content API v2.1.

This intentionally mirrors the production logic in `acit/acit.py` (authinfo to
classify aggregators vs standalone, then `accounts.get` for the parent plus
`accounts.list` for children, assembled into one `{settings, children[]}` object).

Run inside the `oneshop_merchant_migration` conda env after sourcing
`migration_test/env.local.sh`. Output goes to `migration_test/old_accounts/`.
"""

import json
import os
import pathlib

from google.oauth2 import credentials as oauth_credentials
from googleapiclient import discovery

_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_METADATA_KEY = "downloaderMetadata"  # matches resource_downloader.METADATA_KEY
_NUM_RETRIES = 3

_OUT_DIR = pathlib.Path(__file__).parent / "old_accounts"


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


def _get_results(collection, params, method, result_path, metadata, is_scalar=False):
    """Faithful copy of resource_downloader.get_results."""
    request = getattr(collection(), method)(**params)
    if is_scalar:
        yield request.execute(num_retries=_NUM_RETRIES)
        return
    while request:
        response = request.execute(num_retries=_NUM_RETRIES)
        for result in response.get(result_path, []):
            result[_METADATA_KEY] = metadata or {}
            yield result
        request = getattr(collection(), f"{method}_next")(request, response)


def main():
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    api = _get_merchant_center_api()
    input_ids = set(os.environ.get("MERCHANT_IDS", "").split(","))
    input_ids.discard("")

    # --- authinfo: classify accessible accounts (acit.py topology discovery) ---
    aggregator_ids, standalone_ids = set(), set()
    authinfo = next(
        _get_results(api.accounts, {}, "authinfo", "", {}, is_scalar=True)
    )
    (_OUT_DIR / "authinfo.json").write_text(json.dumps(authinfo, indent=2))
    for ident in authinfo.get("accountIdentifiers", []):
        if "merchantId" in ident:
            standalone_ids.add(ident["merchantId"])
        else:
            aggregator_ids.add(ident["aggregatorId"])
    print(f"aggregators={sorted(aggregator_ids)} standalone={sorted(standalone_ids)}")
    print(f"input MERCHANT_IDS={sorted(input_ids)}")

    # --- pull the 'accounts' resource exactly like acit.py ---
    for account_id in sorted(input_ids):
        if account_id in aggregator_ids:
            kind = "aggregator"
            parent = next(
                _get_results(
                    api.accounts,
                    {"merchantId": account_id, "accountId": account_id},
                    "get",
                    "",
                    {"accountId": account_id},
                    is_scalar=True,
                )
            )
            children = list(
                _get_results(
                    api.accounts,
                    {"merchantId": account_id},
                    "list",
                    "resources",
                    {"parentId": account_id},
                )
            )
            record = {"settings": parent, "children": children}
        elif account_id in standalone_ids:
            kind = "standalone"
            settings = next(
                _get_results(
                    api.accounts,
                    {"merchantId": account_id, "accountId": account_id},
                    "get",
                    "",
                    {"accountId": account_id},
                    is_scalar=True,
                )
            )
            record = {"settings": settings, "children": []}
        else:
            print(f"!! {account_id} not accessible via this credential; skipping")
            continue

        rows = _OUT_DIR / f"{account_id}_accounts_rows.jsonlines"
        rows.write_text(json.dumps(record) + "\n")
        (_OUT_DIR / f"{account_id}_accounts_pretty.json").write_text(
            json.dumps(record, indent=2)
        )
        n_children = len(record["children"])
        print(f"[{kind}] {account_id}: wrote rollup ({n_children} children) -> {rows.name}")


if __name__ == "__main__":
    main()
