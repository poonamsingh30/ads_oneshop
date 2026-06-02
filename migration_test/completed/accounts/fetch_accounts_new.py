# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Step 3 of the accounts migration: fetch `accounts` from the NEW Merchant API v1.

Mirrors the OLD fetcher (`fetch_accounts_old.py`) in spirit, but uses the
Google-recommended stable v1 client `google.shopping.merchant_accounts_v1`
(decision D1) and emits the NATIVE v1 shape as a FLAT one-row-per-account record
(decision D2) — NO legacy `{settings, children[]}` rollup, NO legacy field names.

Topology: `list_sub_accounts(provider=accounts/{id})` replaces Content API
`accounts.list`; an account that returns sub-accounts is an advanced (MCA) account.
Per account we fan out across the v1 sub-resources that used to be one monolithic
`Account` object.

Run in the `oneshop_merchant_migration` conda env after sourcing
`migration_test/env.local.sh`. Output -> `migration_test/new_accounts/`.
"""

import json
import os
import pathlib
import time
from concurrent import futures

from google.api_core import exceptions as gax_exceptions
from google.oauth2 import credentials as oauth_credentials
from google.shopping import merchant_accounts_v1 as ma

_OAUTH_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_OUT_DIR = pathlib.Path(__file__).parent / "new_accounts"

# The Merchant API v1 backend returns sporadic 500 INTERNAL / 503 errors; retry.
_TRANSIENT = (
    gax_exceptions.InternalServerError,
    gax_exceptions.ServiceUnavailable,
    gax_exceptions.DeadlineExceeded,
    gax_exceptions.TooManyRequests,
)


def _retry(fn, *, what, attempts=6):
    """Call `fn` with exponential backoff on transient server errors."""
    delay = 1.0
    for i in range(1, attempts + 1):
        try:
            return fn()
        except _TRANSIENT as e:
            if i == attempts:
                raise
            print(f"    .. transient {type(e).__name__} on {what} "
                  f"(attempt {i}/{attempts}); retrying in {delay:.0f}s")
            time.sleep(delay)
            delay = min(delay * 2, 16.0)


def _credentials():
    return oauth_credentials.Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_ADS_REFRESH_TOKEN"].strip(),
        token_uri=_OAUTH_TOKEN_ENDPOINT,
        client_id=os.environ["GOOGLE_ADS_CLIENT_ID"].strip(),
        client_secret=os.environ["GOOGLE_ADS_CLIENT_SECRET"].strip(),
        scopes=["https://www.googleapis.com/auth/content"],
    )


def _to_dict(msg):
    return type(msg).to_dict(msg) if msg is not None else None


def _get_or_none(fn, *, what, account):
    """Call a single-object getter, tolerating NOT_FOUND/PERMISSION_DENIED."""
    try:
        return _to_dict(_retry(fn, what=f"{what}:{account}"))
    except gax_exceptions.NotFound:
        print(f"    - {what}: NOT_FOUND for {account}")
        return None
    except gax_exceptions.PermissionDenied as e:
        print(f"    - {what}: PERMISSION_DENIED for {account} ({e.message})")
        return None
    except gax_exceptions.FailedPrecondition as e:
        print(f"    - {what}: FAILED_PRECONDITION for {account} ({e.message})")
        return None


def main():
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    creds = _credentials()

    accounts_c = ma.AccountsServiceClient(credentials=creds)
    business_c = ma.BusinessInfoServiceClient(credentials=creds)
    homepage_c = ma.HomepageServiceClient(credentials=creds)
    identity_c = ma.BusinessIdentityServiceClient(credentials=creds)
    autoimp_c = ma.AutomaticImprovementsServiceClient(credentials=creds)
    user_c = ma.UserServiceClient(credentials=creds)
    rel_c = ma.AccountRelationshipsServiceClient(credentials=creds)
    svc_c = ma.AccountServicesServiceClient(credentials=creds)

    input_ids = [x for x in os.environ.get("MERCHANT_IDS", "").split(",") if x]
    max_workers = int(os.environ.get("FETCH_WORKERS", "8"))

    # --- Topology: advanced (MCA) vs standalone, enumerate sub-accounts ---
    # list_sub_accounts replaces Content API accounts.list. Crucially, the list
    # response already carries each sub-account's full core `Account` object, so
    # we do NOT issue a per-child get_account (that was redundant work).
    cores = {}      # account_id -> core Account dict (from list / get)
    parents = {}    # account_id -> parent_id or None
    advanced_ids = set()
    for acc_id in input_ids:
        provider = accounts_c.account_path(acc_id)  # "accounts/{id}"
        subs = _retry(
            lambda: list(accounts_c.list_sub_accounts(
                ma.ListSubAccountsRequest(provider=provider))),
            what=f"list_sub_accounts:{acc_id}",
        )
        if subs:
            print(f"{acc_id}: advanced/MCA with {len(subs)} sub-accounts")
            advanced_ids.add(acc_id)
            # parent core needs one get_account (list only returns children)
            cores[acc_id] = _to_dict(_retry(
                lambda: accounts_c.get_account(name=provider),
                what=f"get_account:{acc_id}"))
            parents[acc_id] = None
            for s in subs:
                sid = str(s.account_id)
                cores[sid] = _to_dict(s)   # core from list — 0 extra calls
                parents[sid] = acc_id
        else:
            print(f"{acc_id}: standalone (no sub-accounts)")
            cores[acc_id] = _to_dict(_retry(
                lambda: accounts_c.get_account(name=provider),
                what=f"get_account:{acc_id}"))
            parents[acc_id] = None

    # --- Per-account sub-resource fan-out (full fidelity), run concurrently ---
    def build_record(acc_id):
        core = cores[acc_id]
        name = accounts_c.account_path(acc_id)
        return {
            # core Account (free — already fetched above)
            "account_id": acc_id,
            "account_name": core.get("account_name"),
            "adult_content": core.get("adult_content"),
            "test_account": core.get("test_account"),
            "time_zone": core.get("time_zone"),
            "language_code": core.get("language_code"),
            # relationship (replaces the legacy {settings, children[]} rollup)
            "is_advanced": acc_id in advanced_ids,
            "parent_account": parents[acc_id],
            # sub-resources — each was a field on the old monolithic Account
            "homepage": _get_or_none(
                lambda: homepage_c.get_homepage(
                    name=homepage_c.homepage_path(acc_id)),
                what="homepage", account=acc_id),
            "business_info": _get_or_none(
                lambda: business_c.get_business_info(
                    name=business_c.business_info_path(acc_id)),
                what="business_info", account=acc_id),
            "business_identity": _get_or_none(
                lambda: identity_c.get_business_identity(
                    name=identity_c.business_identity_path(acc_id)),
                what="business_identity", account=acc_id),
            "automatic_improvements": _get_or_none(
                lambda: autoimp_c.get_automatic_improvements(
                    name=autoimp_c.automatic_improvements_path(acc_id)),
                what="automatic_improvements", account=acc_id),
            "users": [
                _to_dict(u) for u in _retry(
                    lambda: list(user_c.list_users(
                        ma.ListUsersRequest(parent=name))),
                    what=f"list_users:{acc_id}")],
            "account_relationships": [
                _to_dict(r) for r in _retry(
                    lambda: list(rel_c.list_account_relationships(
                        ma.ListAccountRelationshipsRequest(parent=name))),
                    what=f"list_account_relationships:{acc_id}")],
            "account_services": [
                _to_dict(s) for s in _retry(
                    lambda: list(svc_c.list_account_services(
                        ma.ListAccountServicesRequest(parent=name))),
                    what=f"list_account_services:{acc_id}")],
        }

    out_rows = _OUT_DIR / "accounts_rows.jsonlines"
    records = []
    with futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_id = {ex.submit(build_record, aid): aid for aid in cores}
        for done in futures.as_completed(future_to_id):
            aid = future_to_id[done]
            records.append(done.result())
            print(f"  done {aid} ({len(records)}/{len(cores)})")

    # stable order: parent(s) first, then children
    records.sort(key=lambda r: (r["parent_account"] is not None, r["account_id"]))
    with out_rows.open("w") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")
    n = len(records)

    print(f"\nWrote {n} flat account rows -> {out_rows}")
    # also dump a pretty copy of the first (parent) record for diffing
    first = json.loads(out_rows.read_text().splitlines()[0])
    (_OUT_DIR / f"{first['account_id']}_pretty.json").write_text(
        json.dumps(first, indent=2, default=str)
    )


if __name__ == "__main__":
    main()
