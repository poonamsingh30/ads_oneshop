# Phase 4 — `shippingsettings` Migration: Plan & Change Tracker

> Tracks the Content API v2.1 → Merchant API **v1 (stable)** migration of the
> **`shippingsettings`** (account-level shipping services) path, end-to-end.
> Update the Status column as work proceeds.
> Understanding/context: `shippingsettings_migration_understanding.md`. Per-file log: `CHANGES_TRACKER.md`.
> **This is the final Content API resource** — its removal retires the `discovery.build('content','v2.1')` client.

**Legend:** ⬜ not started · 🟡 in progress · ✅ done · ⛔ blocked

---

## A. Workstream tracker (the strict 7 steps)

| Step | Task | Output / Artifact | Status |
|------|------|-------------------|--------|
| 0 | Set up conda env + confirm deps (old discovery client + `google-shopping-merchant-accounts` — already installed; **no new dep**) | reuse `oneshop_products_migration`; verified `ShippingSettingsServiceClient` + `get_shipping_settings` import | ✅ |
| 1 | Fetch **old** Content API `shippingsettings.get` for real accounts; save baseline | `fetch_shippingsettings_old.py` + `old_shippingsettings/*` — MCA `120436857` self=404, **7 children with services** (rich); oracle in `_oracle_bools.json` | ✅ |
| 2 | Study **new** Merchant API v1 `ShippingSettings`; finalize old→new field map | `shippingsettings_api_v1_mapping.md` (introspected + grounded on the 7-child baseline) | ✅ |
| 3 | Build **test fetcher** for v1 `get_shipping_settings`, fan-out per account; save output | `fetch_shippingsettings_new.py` + `new_shippingsettings/*` — MCA=PermissionDenied, **7/7 children parity**; Q1–Q4 resolved live (free `amount_micros:0` present) | ✅ |
| 4 | **Compare** old vs new for the same account(s) | `compare_shippingsettings.py` + `shippingsettings_diff.md` — **7/7 accounts, 28/28 boolean checks matched, 0 mismatch** | ✅ |
| 5 | Document **gaps** (renames, micros, enum values, dropped `eligibility`, no roll-down) | `shippingsettings_diff.md` §Step 5 (S1–S10, no blockers) | ✅ |
| 6 | **Resolve** gaps; decide native record shape (D2) + hand-written schema rewrite (D3) | ✅ flat `{account_id, services[]}`; hand-rewritten `shippingsettings.schema` | ✅ |
| 7 | Implement **end-to-end** code changes | ✅ `merchant_shipping.py` + `acit.py` rewire (Content API retired) + schema + 5 SQL + BUILD + 6 tests; bazel build + 6 tests pass; 7 records validate | ✅ |

---

## B. End-to-end code change checklist (Step 7)

### B1. Ingestion — `acit/acit.py` (+ new module)
- ⬜ Add `acit/merchant_shipping.py` (consistent with `merchant_accounts/products/lia`):
  `ShippingSettingsServiceClient.get_shipping_settings(name="accounts/{id}/shippingSettings")`,
  enum-as-string `to_dict`, retry/backoff, threaded fan-out; writes one flat record per account.
- ⬜ Remove `shippingsettings` from `_ACIT_ACCOUNT_ADMIN_RESOURCES` → the list becomes **empty**; drop
  `_pull_standalone_account_resource` + the `_get_merchant_center_api()` Content-API factory +
  the `discovery`/`http`/`resource_downloader` imports if nothing else uses them.
- ⬜ Keep the output path `merchant_center/<id>/shippingsettings/rows.jsonlines` (so the `run_acit.sh`
  glob + `bq::load` are unchanged), but write the **flat native** record.
- ⬜ Keep `downloaderMetadata={'accountId': id}` stamping (harmless; `bq::load` ignores unknown fields? —
  verify, else stamp `account_id` only).
- ⬜ Admin-gate it exactly as today (`_ADMIN_RIGHTS`).
- ⬜ Handle `NotFound`/empty `services` → write no row (parallels the old 404 swallow).

### B2. Beam processing — **N/A**
- `shippingsettings` bypasses Beam (`create_base_tables.py`) entirely; loaded directly by `run_acit.sh`.
  **No proto, no `convert_*`, no `create_base_tables` change.**

### B3. Schema — `acit/schemas/acit/shippingsettings.schema` (HAND-WRITTEN)
- ⬜ Rewrite the BQ schema by hand to the **flat native v1** shape (no `bq_gen_schemas`):
  `account_id INT64` + `services ARRAY<STRUCT<…>>` (+ optionally `warehouses`, `etag`), with the
  consumed fields: `service_name`, `active`, `delivery_countries`, `currency_code`,
  `delivery_time STRUCT<min_transit_days, max_transit_days, min_handling_days, max_handling_days,
  cutoff_time STRUCT<hour,minute,time_zone>, handling_business_day_config STRUCT<business_days ARRAY<STRING>>>`,
  `rate_groups ARRAY<STRUCT<applicable_shipping_labels, name,
  main_table STRUCT<name, rows ARRAY<STRUCT<cells ARRAY<STRUCT<flat_rate STRUCT<amount_micros INT64, currency_code STRING>>>>>, …>,
  single_value STRUCT<flat_rate STRUCT<amount_micros INT64, currency_code STRING>>>>`,
  `shipment_type STRING`.

### B4. BQ load — `acit/run_acit.sh`
- ⬜ Confirm the `shippingsettings` `bq::load` (raw glob → table, `shippingsettings.schema`) is
  **unchanged** (path preserved). No edit expected unless the metadata-key handling needs it.

### B5. Views / final tables — MEX SQL (read the `shippingsettings` table)
- ⬜ `account_list.sql` — rewrite `AllShippingData` (drop `children` union → flat read) +
  `AccountLevelShipping` 4 booleans against the new field names + `amount_micros`.
- ⬜ `all_metrics.sql` — identical rewrite.
- ⬜ `offer_list.sql` — identical rewrite.
- ⬜ `ml_data.sql` — `has_account_level_shipping` only (`ARRAY_LENGTH(services) > 0` on the flat table).
- ⬜ `admin_tables.sql` — new flat `CREATE TABLE shippingsettings` matching the hand-written schema.

### B6. Tests & validation
- ⬜ `acit/tests/test_merchant_shipping.py` — enum-as-string, snake keys, micros, METADATA_KEY,
  empty-services handling.
- ⬜ Round-trip the real record → derive the 4 booleans → compare to the old values (parity).

### B7. Bazel / packaging
- ⬜ `acit/BUILD.bazel` — new `merchant_shipping_lib` (dep `google_shopping_merchant_accounts`) +
  `merchant_shipping_test`; wire `:merchant_shipping_lib` into the `acit` binary deps. **No new pip dep.**
- ⬜ `bazel build //acit:acit` + `bazel test //acit:...` on macOS. (No schema-gen target for shipping →
  no new Linux-only step; the image build remains Linux/Cloud-Build only as before.)

---

## C. Old → New field map — ⬜ to confirm in Step 2
Preliminary table in `shippingsettings_migration_understanding.md` §2.2/§3. Headlines:
`{settings,children[]}`→flat per-account; snake_case renames; `deliveryCountry`(STRING)→`delivery_countries[]`;
`*TimeInDays`→`*_days`; **`flatRate.value`(FLOAT major)→`flat_rate.amount_micros`(INT64 micros)**;
table `cells[]` become `Value` (`cells[].flat_rate`); `shipmentType`/`businessDays`→enums;
`eligibility` dropped (no v1 equivalent).

## D. Gap log — ⬜ to finalize in `shippingsettings_diff.md` (Step 5)
Preview: **S1** flat per-account; **S2** snake/nested renames; **S3** free-shipping rate → micros +
`Value` cells; **S4** enums as STRING; **S5** `eligibility` dropped; **S6** new v1-only fields not
consumed; **S7** no proto/no Beam (hand-written schema). Watch items: micros zero-check correctness;
which OR branch fires for the free service live; NotFound/empty vs old 404.

## E. Key decisions — proposed (lock during Steps 2–6)
- **D1 — Client library:** ✅ `ShippingSettingsServiceClient` from the already-installed
  `google-shopping-merchant-accounts` (`merchant_accounts_v1`, stable v1, gRPC). **No new dependency**
  (confirmed by the Step-0 import check).
- **D2 — Record shape:** *(proposed)* **flat per-account** native shape — one record
  `{account_id, services:[…], warehouses:[…]?, etag?}` (drop `name`/`{settings,children[]}`) to
  `merchant_center/<id>/shippingsettings/rows.jsonlines`. MEX recovers MCA→child from the migrated
  `accounts` table (same as LIA). Lock after the Step-3 fetcher.
- **D3 — Schema modeling:** *(proposed)* **hand-rewrite** `shippingsettings.schema` (it is NOT
  proto-generated). Enums/micros as above. No `schema.proto`/`create_base_tables` change.

---

## F. Guardrails / scope
- Phase 4 = **shippingsettings only**. Don't touch accounts/products/liasettings.
- **No legacy-schema transform** — native Merchant API v1 shape end-to-end.
- v1 **stable** only (no v1beta). Test in a conda env. Keep scratch artifacts in `migration_test/`.
- Main code reads standard `GOOGLE_ADS_*` env vars; test creds stay in the gitignored `env.local.sh`.
- Keep the Bazel image build working (BUILD wiring; **no new pip dep**). Retiring the Content API client
  is in-scope (this is the last consumer) — remove dead imports carefully.

## G. Changelog
- **2026-06-08** — Steps 6–7 done (end-to-end main code). New ingestion `acit/merchant_shipping.py`
  (`ShippingSettingsServiceClient.get_shipping_settings`, enum-as-string, retry/backoff, threaded; skips
  PermissionDenied aggregators + NotFound; writes flat `{account_id, services[], warehouses[], etag}`).
  `acit.py` **retired the Content API**: removed the `discovery.build('content','v2.1')` factory,
  `_pull_standalone_account_resource`, `_list_mca_resource`, the admin-resource list, both roll-down loops
  and the now-dead imports; added admin-gated `merchant_shipping.download_shipping_settings` after the LIA
  pull. Hand-rewrote `acit/schemas/acit/shippingsettings.schema` to the flat native v1 shape (snake_case,
  `amount_micros INT64`, enums STRING). 4 MEX SQL rewritten (account_list/all_metrics/offer_list `AllShipping
  Data`+`AccountLevelShipping`; ml_data flat read) + `admin_tables.sql` new flat DDL. `BUILD.bazel`
  (`merchant_shipping_lib` + `merchant_shipping_test`, wired into `acit`). `acit/tests/test_merchant_shipping.py`
  (6 unit tests). **No new pip dep.** **Validated:** `bazel build //acit:acit` ✅; `bazel test`
  merchant_shipping_test (6) + lia/products/accounts/create_base_tables/product all ✅; **all 7 real v1
  records type-compatible** with the rewritten schema (shipping bypasses Beam/proto, so JSON→BQ-schema is the
  round-trip; `ignoreUnknownValues` drops v1-only extras). `//acit:acit_test` fails on a pre-existing
  unmocked live-API call (since Phase 1) — NOT a Phase-4 regression. Next: commit + push (on user go-ahead).
- **2026-06-07** — Steps 1–5 done. **Step 1:** `fetch_shippingsettings_old.py` → baseline MCA
  `120436857` self=404, **7 children with services** (rich/varied), oracle in `_oracle_bools.json`.
  **Step 2:** `shippingsettings_api_v1_mapping.md` — authoritative old→new map grounded on the baseline
  (flat per-account; `*TimeInDays`→`*_days`; `flatRate.value` FLOAT→`flat_rate.amount_micros` micros; `Value`
  cells; `eligibility` dropped; enums STRING). **Step 3:** `fetch_shippingsettings_new.py`
  (`get_shipping_settings`) → MCA=PermissionDenied (skip), **7/7 children parity**; resolved Q1 (free
  `amount_micros:0` is **present** → `=0` SQL correct), Q2 (micros×1e6), Q3 (PermissionDenied/NotFound), Q4
  (per-country service merge, boolean-invariant). **Steps 4–5:** `compare_shippingsettings.py` →
  **7/7 accounts, 28/28 boolean checks matched, 0 mismatch, 0 key gaps**; `shippingsettings_diff.md` gap log
  S1–S10, **no blockers**; D2/D3 locked. `speed` + `free` both branches value-verified live; `fast` True
  (A1) and `main_table` (A2) branches spec-only (un-exercised by data). Next: Steps 6–7 (end-to-end code).
- **2026-06-07** — Phase 4 kicked off. Archived Phase-3 (liasettings) docs to
  `completed/liasettings/`. Created `shippingsettings_migration_understanding.md` + this plan + a fresh
  `CHANGES_TRACKER.md`. **Step 0 done:** reused env `oneshop_products_migration`; verified
  `ShippingSettingsServiceClient`/`get_shipping_settings` import from the already-installed
  `google-shopping-merchant-accounts==1.5.0` (**no new pip dep**). Mapped the current path: Content-API
  `shippingsettings.get` roll-down (`acit.py:281`) → `{settings,children[]}` envelope → **direct
  `bq::load`** (NOT Beam) with the **hand-written** `shippingsettings.schema` → `shippingsettings` table
  → 4 `has_account_level_*` MEX booleans (account_list/all_metrics/offer_list; ml_data uses only
  `has_account_level_shipping`) + `admin_tables.sql` DDL. **Key findings:** v1 replaces it with the
  **`ShippingSettings` singleton** (`get_shipping_settings(name="accounts/{id}/shippingSettings")`, no
  roll-down `list`); biggest change is free-shipping rate **`flatRate.value` FLOAT → `flat_rate.amount_micros`
  INT64 (micros)** + table `cells[]` becoming `Value` messages; no proto/Beam touched (hand-written
  schema only). Steps 1–7 pending the user's go-ahead.
