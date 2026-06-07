# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Step 1 of the SHIPPINGSETTINGS migration: fetch `shippingsettings` from the
OLD Content API v2.1.

This mirrors the production roll-down logic in `acit/acit.py`
(`_pull_standalone_account_resource`, which calls `shippingsettings.get` per
account and wraps it in a `{settings, children[]}` envelope):
  - topology via `accounts.authinfo` (aggregators vs standalone),
  - for each AGGREGATOR (MCA): `shippingsettings.get(merchantId=agg, accountId=agg)`
    -> `settings`, then `shippingsettings.list(merchantId=agg)` -> `children[]`
    (result_path='resources'), written as one `{settings, children[]}` envelope.
  - for each STANDALONE leaf: `shippingsettings.get(merchantId=parent, accountId=leaf)`
    (is_scalar) -> `{settings, children: []}`.
Each row stamps downloaderMetadata={'accountId': <id>} like resource_downloader.
404 (no shipping settings for the account) is swallowed, mirroring acit.py.

Run inside the `oneshop_products_migration` conda env after sourcing
`migration_test/env.local.sh`. Output goes to `migration_test/old_shippingsettings/`.

Env knobs (optional):
  MERCHANT_IDS                comma-separated input account IDs (from env.local.sh).
  MAX_CHILDREN_PER_MCA        cap children saved per aggregator (default 0 = all).
"""

import json
import os
import pathlib

from google.oauth2 import credentials as oauth_credentials
from googleapiclient import discovery
from googleapiclient import errors as gapi_errors

_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_METADATA_KEY = "downloaderMetadata"  # matches resource_downloader.METADATA_KEY
_NUM_RETRIES = 3
_PAGE_SIZE = 250

_OUT_DIR = pathlib.Path(__file__).parent / "old_shippingsettings"
_MAX_CHILDREN_PER_MCA = int(os.environ.get("MAX_CHILDREN_PER_MCA", "0"))


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


def _get_results(collection, params, method, result_path, metadata,
                 is_scalar=False, limit=0):
    """Faithful copy of resource_downloader.get_results (with an optional cap)."""
    request = getattr(collection(), method)(**params)
    if is_scalar:
        result = request.execute(num_retries=_NUM_RETRIES)
        if metadata:
            result[_METADATA_KEY] = metadata
        yield result
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


def _classify(api, input_ids):
    """authinfo -> (aggregator_ids, standalone_ids) intersected with input_ids."""
    aggregator_ids, standalone_ids = set(), set()
    authinfo = next(_get_results(api.accounts, {}, "authinfo", "", {}, is_scalar=True))
    for ident in authinfo.get("accountIdentifiers", []):
        if "merchantId" in ident:
            standalone_ids.add(ident["merchantId"])
        else:
            aggregator_ids.add(ident["aggregatorId"])
    print(f"aggregators={sorted(aggregator_ids)} standalone={sorted(standalone_ids)}")
    if input_ids:
        aggregator_ids &= input_ids
        standalone_ids &= input_ids
    return aggregator_ids, standalone_ids


def _get_one(api, merchant_id, account_id):
    """shippingsettings.get for a single account; None on 404 (no settings)."""
    try:
        return next(_get_results(
            api.shippingsettings,
            {"merchantId": merchant_id, "accountId": account_id},
            "get", "", {"accountId": account_id}, is_scalar=True,
        ))
    except gapi_errors.HttpError as e:
        if str(e.status_code) == "404":
            print(f"  {account_id}: 404 (no shipping settings); skipping")
            return None
        raise


def _n_services(settings):
    return len((settings or {}).get("services", []) or [])


def _write_envelope(account_id, envelope):
    path = _OUT_DIR / f"{account_id}_shippingsettings.json"
    path.write_text(json.dumps(envelope, indent=2))
    return path


def main():
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    api = _get_merchant_center_api()
    input_ids = set(os.environ.get("MERCHANT_IDS", "").split(","))
    input_ids.discard("")

    aggregator_ids, standalone_ids = _classify(api, input_ids)
    summary = {"aggregators": [], "standalone": []}

    # --- Aggregators (MCA): get(self) + list(children) ----------------------
    for agg in sorted(aggregator_ids):
        settings = _get_one(api, agg, agg)
        children = list(_get_results(
            api.shippingsettings,
            {"merchantId": agg, "maxResults": _PAGE_SIZE},
            "list", "resources", {"parentId": agg},
            limit=_MAX_CHILDREN_PER_MCA,
        ))
        envelope = {"settings": settings or {}, "children": children}
        _write_envelope(agg, envelope)
        n_self = _n_services(settings)
        n_kids_with = sum(1 for c in children if c.get("services"))
        print(f"  MCA {agg}: self services={n_self}, {len(children)} children "
              f"({n_kids_with} with services)")
        summary["aggregators"].append({
            "account_id": agg,
            "self_services": n_self,
            "n_children": len(children),
            "children_with_services": n_kids_with,
        })

    # --- Standalone leaves: scalar get only ---------------------------------
    for leaf in sorted(standalone_ids):
        settings = _get_one(api, leaf, leaf)
        if settings is None:
            continue
        envelope = {"settings": settings, "children": []}
        _write_envelope(leaf, envelope)
        n = _n_services(settings)
        print(f"  standalone {leaf}: services={n}")
        summary["standalone"].append({"account_id": leaf, "n_services": n})

    (_OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    total = len(summary["aggregators"]) + len(summary["standalone"])
    print(f"\nDone. {total} account(s) with shippingsettings -> {_OUT_DIR}")
    if not total:
        print("!! No shippingsettings found. Check MERCHANT_IDS / ADMIN rights / credential access.")


if __name__ == "__main__":
    main()
