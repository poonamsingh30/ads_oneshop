# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License").
"""Reusable old-vs-new Parquet comparison harness for post-migration validation.

Loads the BQ Parquet exports under bq_data/bq_parquet_export_{old,new}/ and
compares a table old vs new:
  - full-equality mode (Category A: tables that must be byte-identical), and
  - key-based mode (Category C: schema-identical derived tables) — reports keys
    only-in-old / only-in-new / shared, then a cell-level value diff on the
    shared keys (numerics within tolerance, list/array cells order-insensitive).

BQ exports use the `dbdate` extension type, so we read via
`pyarrow.read_table(...).to_pandas(ignore_metadata=True)` (plain pd.read_parquet
raises "data type 'dbdate' not understood"). Run in the `dataflow2025` conda env.
"""

import math
import pathlib

import numpy as np
import pyarrow.parquet as pq

_HERE = pathlib.Path(__file__).parent
_BASE = _HERE.parent / "bq_data"
OLD = _BASE / "bq_parquet_export_old"
NEW = _BASE / "bq_parquet_export_new"

_TOL = 1e-6


def load(table, which):
    """Loads a table ('foo' or 'foo.parquet') from old|new as a pandas DataFrame."""
    name = table if table.endswith(".parquet") else f"{table}.parquet"
    root = OLD if which == "old" else NEW
    return pq.read_table(root / name).to_pandas(ignore_metadata=True)


def _norm_scalar(v):
    """Normalize a cell for comparison.

    NaN/None unified; lists/arrays -> order-insensitive sorted tuple; dict/struct
    -> sorted (key, value) tuple. Everything is rendered to comparable primitives.
    """
    if isinstance(v, dict):
        return tuple(sorted((str(k), _norm_scalar(val)) for k, val in v.items()))
    if isinstance(v, (list, tuple, np.ndarray)):
        return tuple(sorted((repr(_norm_scalar(x)) for x in v)))
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _equal(a, b):
    a, b = _norm_scalar(a), _norm_scalar(b)
    if a is None and b is None:
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=_TOL, abs_tol=_TOL)
    return a == b


def full_equality(table):
    """Category A: sort both frames by all columns and assert identical."""
    do, dn = load(table, "old"), load(table, "new")
    res = {"table": table, "mode": "full_equality",
           "old_rows": len(do), "new_rows": len(dn),
           "cols_match": list(do.columns) == list(dn.columns)}
    if not res["cols_match"]:
        res["verdict"] = "SCHEMA_DIFF"
        res["old_cols"], res["new_cols"] = list(do.columns), list(dn.columns)
        return res
    cols = list(do.columns)

    def rowmultiset(df):
        rows = [tuple(repr(_norm_scalar(df.iloc[i][c])) for c in cols)
                for i in range(len(df))]
        return sorted(rows)
    ro, rn = rowmultiset(do), rowmultiset(dn)
    res["equal"] = ro == rn
    res["verdict"] = "IDENTICAL" if res["equal"] else "DIFF"
    return res


def key_compare(table, keys, ignore_cols=()):
    """Category C: key-set diff + cell-level value diff on shared keys."""
    do, dn = load(table, "old"), load(table, "new")
    res = {"table": table, "mode": "key_compare", "keys": list(keys),
           "old_rows": len(do), "new_rows": len(dn),
           "cols_match": list(do.columns) == list(dn.columns)}

    def keyset(df):
        return {tuple(str(df.iloc[i][k]) for k in keys): i for i in range(len(df))}
    ko, kn = keyset(do), keyset(dn)
    so, sn = set(ko), set(kn)
    res["only_in_old"] = len(so - sn)
    res["only_in_new"] = len(sn - so)
    res["shared"] = len(so & sn)
    res["dup_keys_old"] = len(do) - len(so)
    res["dup_keys_new"] = len(dn) - len(sn)

    compare_cols = [c for c in do.columns
                    if c not in set(keys) and c not in set(ignore_cols)]
    mism = {}
    sample = []
    for key in (so & sn):
        ro, rn = do.iloc[ko[key]], dn.iloc[kn[key]]
        for c in compare_cols:
            if not _equal(ro[c], rn[c]):
                mism[c] = mism.get(c, 0) + 1
                if len(sample) < 12:
                    sample.append({"key": key, "col": c,
                                   "old": str(ro[c])[:60], "new": str(rn[c])[:60]})
    res["mismatched_cells_by_col"] = dict(sorted(mism.items(), key=lambda x: -x[1]))
    res["mismatch_sample"] = sample
    clean = (res["only_in_old"] == 0 and res["only_in_new"] == 0
             and not mism and res["dup_keys_old"] == 0 and res["dup_keys_new"] == 0)
    res["verdict"] = "IDENTICAL" if clean else "DIFF"
    return res


def print_result(r):
    print(f"\n=== {r['table']}  [{r['mode']}]  ->  {r['verdict']}")
    print(f"    rows old/new: {r['old_rows']}/{r['new_rows']}  cols_match={r.get('cols_match')}")
    if r["mode"] == "key_compare":
        print(f"    keys: only_old={r['only_in_old']} only_new={r['only_in_new']} "
              f"shared={r['shared']} dup_old={r['dup_keys_old']} dup_new={r['dup_keys_new']}")
        if r["mismatched_cells_by_col"]:
            print(f"    mismatched cells by column: {r['mismatched_cells_by_col']}")
            for s in r["mismatch_sample"][:6]:
                print(f"      {s['col']} @ {s['key']}: old={s['old']!r} new={s['new']!r}")
    if r.get("verdict") == "SCHEMA_DIFF":
        print(f"    old_cols={r['old_cols']}\n    new_cols={r['new_cols']}")
