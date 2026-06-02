# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Validates that the REAL ingestion module output conforms to accounts.schema.

Runs the production `acit.merchant_accounts.download_accounts` against the live
test account, then checks every produced JSON record against the BigQuery schema
at acit/schemas/acit/accounts.schema (the exact file `bq.sh` loads with).

Run in the conda env after sourcing migration_test/env.local.sh.
"""

import json
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from acit import merchant_accounts  # noqa: E402
from google.oauth2 import credentials as oauth_credentials  # noqa: E402

_SCHEMA = pathlib.Path(__file__).resolve().parents[1] / "acit/schemas/acit/accounts.schema"

_PY_TYPE = {
    "STRING": str,
    "INTEGER": int,
    "BOOLEAN": bool,
    "FLOAT": float,
    "RECORD": dict,
}


def _creds():
    return oauth_credentials.Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_ADS_REFRESH_TOKEN"].strip(),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_ADS_CLIENT_ID"].strip(),
        client_secret=os.environ["GOOGLE_ADS_CLIENT_SECRET"].strip(),
        scopes=["https://www.googleapis.com/auth/content"],
    )


def _check(value, field, path, errors):
    name, typ, mode = field["name"], field["type"], field.get("mode", "NULLABLE")
    if value is None:
        return
    if mode == "REPEATED":
        if not isinstance(value, list):
            errors.append(f"{path}: expected REPEATED list, got {type(value).__name__}")
            return
        for i, item in enumerate(value):
            _check_scalar_or_record(item, field, f"{path}[{i}]", errors)
        return
    _check_scalar_or_record(value, field, path, errors)


def _check_scalar_or_record(value, field, path, errors):
    typ = field["type"]
    if typ == "RECORD":
        if not isinstance(value, dict):
            errors.append(f"{path}: expected RECORD dict, got {type(value).__name__}")
            return
        subfields = {f["name"]: f for f in field["fields"]}
        for k, v in value.items():
            if k in subfields:
                _check(v, subfields[k], f"{path}.{k}", errors)
            # unknown keys are tolerated (bq load uses ignoreUnknownValues=true)
        return
    expected = _PY_TYPE[typ]
    if typ == "INTEGER":
        # BQ accepts quoted integers for INTEGER columns
        ok = isinstance(value, int) and not isinstance(value, bool)
        ok = ok or (isinstance(value, str) and value.lstrip("-").isdigit())
        if not ok:
            errors.append(f"{path}: expected INTEGER, got {value!r}")
    elif typ == "BOOLEAN":
        if not isinstance(value, bool):
            errors.append(f"{path}: expected BOOLEAN, got {value!r}")
    elif typ == "STRING":
        if not isinstance(value, str):
            errors.append(f"{path}: expected STRING, got {value!r}")
    elif typ == "FLOAT":
        if not isinstance(value, (int, float)):
            errors.append(f"{path}: expected FLOAT, got {value!r}")


def main():
    schema = json.loads(_SCHEMA.read_text())
    top = {f["name"]: f for f in schema}
    input_ids = [x for x in os.environ.get("MERCHANT_IDS", "").split(",") if x]

    with tempfile.TemporaryDirectory() as tmp:
        mc_path = pathlib.Path(tmp) / "merchant_center"
        mc_path.mkdir(parents=True)
        agg, standalone, leaf_to_parent = merchant_accounts.download_accounts(
            _creds(), input_ids, mc_path)
        print(f"topology: {len(agg)} advanced, {len(standalone)} standalone, "
              f"{len(leaf_to_parent)} sub-accounts")

        rows = []
        for fp in mc_path.glob("*/accounts/rows.jsonlines"):
            rows.extend(json.loads(l) for l in fp.read_text().splitlines())
        print(f"validated rows: {len(rows)}")

        errors = []
        unknown_top = set()
        for r in rows:
            for k, v in r.items():
                if k in top:
                    _check(v, top[k], k, errors)
                else:
                    unknown_top.add(k)

    if unknown_top:
        print(f"WARNING unknown top-level keys (ignored by bq load): {unknown_top}")
    if errors:
        print(f"\n!! {len(errors)} SCHEMA VIOLATIONS:")
        for e in errors[:40]:
            print("  ", e)
        sys.exit(1)
    print("\nSCHEMA OK: all records conform to accounts.schema")


if __name__ == "__main__":
    main()
