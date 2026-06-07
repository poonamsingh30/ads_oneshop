# ShippingSettings Migration — Master Change Tracker (Phase 4)

> Single source of truth for **every** file added/modified during the Content API →
> Merchant API v1 migration of the **`shippingsettings`** (account-level shipping services) path.
> Append an entry whenever a file changes.
> Plan/checklist: `shippingsettings_migration_plan.md` · Context: `shippingsettings_migration_understanding.md`.
> Phases 1–3 (`accounts`, `products`, `liasettings`) are complete; their trackers are archived under
> `completed/accounts/`, `completed/products/`, `completed/liasettings/`.
> **This is the final Content API resource** — completing it retires `discovery.build('content','v2.1')`.

## Proposed design decisions (recommended options — lock during Steps 2–6)

| # | Decision | Proposed choice | Rationale |
|---|----------|-----------------|-----------|
| D1 | New-API client library | **`google-shopping-merchant-accounts`** → `merchant_accounts_v1.ShippingSettingsServiceClient` (stable v1, gRPC) | v1 folds shipping into the accounts surface as the `ShippingSettings` singleton. **Package already installed (Phase 1/3) — no new pip dep.** Verified at Step 0. |
| D2 | Record / output shape | flat per-account `{account_id, services[], …}` (drop `{settings, children[]}`) | Native-v1 preference; no MCA roll-down in v1. MEX joins MCA→child via the migrated `accounts` table. Path `merchant_center/<id>/shippingsettings/rows.jsonlines` kept so the `bq::load` glob is unchanged. Lock in Step 6. |
| D3 | Schema modeling | **Hand-rewrite** `acit/schemas/acit/shippingsettings.schema` to native v1 (snake_case, `amount_micros` INT64, enums STRING) | This schema is hand-written (NOT proto-generated, unlike `liasettings`/`Products`). No `schema.proto`/Beam change. |

## Environment

- Conda env: reuse **`oneshop_products_migration`** (py3.11) — already has
  `google-shopping-merchant-accounts==1.5.0` (provides `ShippingSettingsServiceClient`) + the old
  discovery client for the baseline pull. **No new package needed.**
- Test creds: `migration_test/env.local.sh` (GITIGNORED, reused). Main code keeps reading standard
  `GOOGLE_ADS_*` env vars.
- Test account: the sub-account(s) with shipping data under MCA `120436857` (the user confirmed the test
  account has shipping data configured) — pick the exact account in Step 1.

## Change log

| Date | File | Type | Step | Notes |
|------|------|------|------|-------|
| 2026-06-07 | `migration_test/completed/liasettings/*` | move | pre | Archived all Phase-3 (liasettings) docs/scripts/data from `migration_test/` root |
| 2026-06-07 | `migration_test/.gitignore` | edit | pre | Added `old_shippingsettings/`, `new_shippingsettings/`, `compare_shippingsettings_result.json` + `completed/**` scratch ignores |
| 2026-06-07 | `migration_test/shippingsettings_migration_understanding.md` | add | pre | Phase-4 understanding doc (current path + v1 `ShippingSettings` map + 4 booleans) |
| 2026-06-07 | `migration_test/shippingsettings_migration_plan.md` | add | pre | Plan + 7-step tracker + e2e checklist |
| 2026-06-07 | `migration_test/CHANGES_TRACKER.md` | add | pre | This tracker (Phase 4) |
| 2026-06-07 | (Step 0) env verify | check | 0 | `ShippingSettingsServiceClient` + `get_shipping_settings` import OK from `google-shopping-merchant-accounts==1.5.0` — no new dep |
| 2026-06-07 | `migration_test/fetch_shippingsettings_old.py` | add | 1 | OLD Content API fetcher (authinfo → MCA `get`(self)+`list`(children), standalone `get`; 404-swallow; `{settings,children[]}` envelope) |
| 2026-06-07 | `migration_test/old_shippingsettings/*` (gitignored) | data | 1 | Baseline: MCA `120436857` self=404, **7 children all with services** (rich/varied); oracle booleans saved to `_oracle_bools.json` |
| 2026-06-07 | `migration_test/shippingsettings_api_v1_mapping.md` | add | 2 | v1 `ShippingSettings` study + authoritative old→new field map (grounded on the 7-child baseline); endpoint/identity change; 4 booleans in v1 terms; critical Q1 (free-rate micros=0 may render NULL) |
| 2026-06-07 | `migration_test/fetch_shippingsettings_new.py` | add | 3 | NEW v1 fetcher (`get_shipping_settings`, enum-as-string, per-account fan-out, free-rate probe, retry/backoff) |
| 2026-06-07 | `migration_test/new_shippingsettings/*` (gitignored) | data | 3 | v1 output: MCA=PermissionDenied (skip), all **7 children** returned services (parity). **Q1 resolved: free `amount_micros:0` is PRESENT** (SQL `=0` works); Q2 micros×1e6; Q4 per-country service merge (boolean-invariant) |
| 2026-06-07 | `migration_test/shippingsettings_api_v1_mapping.md` | edit | 3 | §4 marked Q1–Q4 **RESOLVED live**; §5 assumptions A1/A2 narrowed (fast + main_table branches un-exercised by data) |
| 2026-06-07 | `migration_test/compare_shippingsettings.py` | add | 4 | Derives the 4 MEX booleans from both shapes per account; reconciliation |
| 2026-06-07 | `migration_test/compare_shippingsettings_result.json` (gitignored) | data | 4 | **7/7 accounts, 28/28 boolean checks matched, 0 mismatch, 0 key gaps** |
| 2026-06-07 | `migration_test/shippingsettings_diff.md` | add | 4-5 | Comparison (PASS) + finalized gap log S1–S10 (no blockers); speed+free both branches value-verified; A1 (fast) / A2 (main_table) spec-only; D2/D3 locked |

### Steps 6–7: end-to-end code changes (main code) — ✅ COMPLETE
| Date | File | Type | Notes |
|------|------|------|-------|
| 2026-06-08 | `acit/merchant_shipping.py` | add | Merchant API v1 shipping ingestion (`ShippingSettingsServiceClient.get_shipping_settings`, enum-as-string `to_dict`, retry/backoff, threaded fan-out). Skips PermissionDenied (aggregators) + NotFound (no settings). Writes one flat `{account_id, services[], warehouses[], etag}` record per account to `merchant_center/<id>/shippingsettings/rows.jsonlines` (glob unchanged). |
| 2026-06-08 | `acit/acit.py` | edit | **Retired the Content API.** Removed `_ACIT_MC_SHIPPINGSETTINGS_RESOURCE`/`_ACIT_ACCOUNT_ADMIN_RESOURCES`, `_get_merchant_center_api()` (the `discovery.build('content','v2.1')` factory), `_pull_standalone_account_resource`, `_list_mca_resource`, the aggregator roll-down loop + the standalone ProcessPoolExecutor loop. Dropped now-dead imports (`json`, `concurrent.futures`, `multiprocessing`, `resource_downloader`, `googleapiclient.discovery`/`http`, `typing.Any`). Added `from acit import merchant_shipping` + admin-gated `merchant_shipping.download_shipping_settings(creds, product_account_ids, mc_path)` after the LIA pull. |
| 2026-06-08 | `acit/schemas/acit/shippingsettings.schema` | rewrite | Hand-rewritten flat native v1 BQ schema: `account_id INT64` + `services[]` (`service_name, active, delivery_countries[], currency_code, shipment_type, delivery_time{min/max_transit_days, min/max_handling_days, cutoff_time{hour,minute,time_zone}, handling_business_day_config{business_days[]}}, rate_groups[]{applicable_shipping_labels[], name, single_value{flat_rate{amount_micros,currency_code}}, main_table{name, rows[].cells[].flat_rate{amount_micros,currency_code}, row_headers, column_headers}}`). Dropped the `{settings, children[]}` envelope. (Hand-written, NOT proto-generated.) |
| 2026-06-08 | `extensions/merchant_excellence/account_list.sql` | edit | `AllShippingData` → flat read of `shippingsettings` (drop `children` UNION); `AccountLevelShipping` 4 booleans on v1 names (`delivery_time.*_days`, `rate_groups`, `main_table`, `single_value`, `flat_rate.amount_micros = 0`). |
| 2026-06-08 | `extensions/merchant_excellence/all_metrics.sql` | edit | Same `AllShippingData`/`AccountLevelShipping` rewrite as account_list. |
| 2026-06-08 | `extensions/merchant_excellence/offer_list.sql` | edit | Same rewrite. |
| 2026-06-08 | `extensions/merchant_excellence/ml_data.sql` | edit | `AccountLevelShipping`: `S.settings.accountId`/`S.settings.services` → flat `S.account_id`/`S.services`. |
| 2026-06-08 | `extensions/merchant_excellence/admin_tables.sql` | edit | New flat `CREATE TABLE shippingsettings (account_id INT64, services ARRAY<STRUCT<...>>)` matching the hand-written schema (snake_case, `amount_micros INT64`). |
| 2026-06-08 | `acit/tests/test_merchant_shipping.py` | add | 6 unit tests: enum-as-string, snake keys, free `amount_micros` present (=0), micros scale, main_table cell flat_rate, METADATA_KEY. |
| 2026-06-08 | `acit/BUILD.bazel` | edit | New `merchant_shipping_lib` (dep `google_shopping_merchant_accounts`) + `merchant_shipping_test`; `acit` binary deps += `:merchant_shipping_lib`. |

### Build / validation results (Steps 6–7)
- `bazel build //acit:acit` ✅. `bazel test //acit:{merchant_shipping_test,merchant_lia_test,merchant_products_test,merchant_accounts_test,create_base_tables_test,product_test}` ✅ (merchant_shipping_test 6 cases).
- **Schema round-trip:** all **7 real v1 records** are type-compatible with the rewritten hand-written `shippingsettings.schema` (BQ `ignoreUnknownValues:true` drops the v1-only extras like `warehouses`/`store_config`; `amount_micros` string coerces to INT64; the free `= 0` check is exact). Shipping bypasses Beam/proto, so there is no proto round-trip.
- **No new pip dependency** — reused `google-shopping-merchant-accounts` (Phase 1/3).
- **Content API fully retired** — `discovery.build('content','v2.1')` and `resource_downloader` are no longer used by `acit.py` (the binary's BUILD dep on `:resource_downloader_lib` is left in place because `test_acit.py`/`create_base_tables.py` still reference that target).
- **Pre-existing test note:** `//acit:acit_test` (`test_credentials`) fails in the sandbox with a live-API `503 invalid_client` — it mocks only the Content-API surfaces (`resource_downloader`, `gaql`) and makes an unmocked real `merchant_accounts.list_sub_accounts` call. Verified failing identically on HEAD (since the Phase-1 accounts migration); **not a Phase-4 regression**.
- **Known Linux-only step (pre-existing):** `//:cloud_run_job` image build runs in Cloud Build. Phase 4 changes **no** proto and adds **no** schema-gen step (the shipping schema is hand-written), so there is nothing new that is Linux-only.

## Main-code files expected to change in Step 7 (not yet touched)

- `acit/acit.py` — remove `shippingsettings` from `_ACIT_ACCOUNT_ADMIN_RESOURCES` (becomes empty);
  drop `_pull_standalone_account_resource` + `_get_merchant_center_api()` (Content-API factory) + the
  now-dead `discovery`/`http`/`resource_downloader` imports; call the new v1 shipping fetcher
  (admin-gated, over the product account set).
- `acit/merchant_shipping.py` *(new)* — Merchant API v1 shipping fetcher
  (`ShippingSettingsServiceClient.get_shipping_settings`, enum-as-string, retry/backoff, threaded).
- `acit/schemas/acit/shippingsettings.schema` — hand-rewrite to the flat native v1 shape.
- `acit/run_acit.sh` — confirm the `shippingsettings` `bq::load` glob/schema unchanged (path preserved).
- `extensions/merchant_excellence/{account_list,all_metrics,offer_list,ml_data}.sql` — rewrite the
  `AllShippingData`/`AccountLevelShipping` CTEs + the 4 `has_account_level_*` booleans against the new
  shape (`delivery_time.*_days`, `flat_rate.amount_micros`).
- `extensions/merchant_excellence/admin_tables.sql` — update the `CREATE TABLE shippingsettings` contract.
- `acit/BUILD.bazel` — new `merchant_shipping_lib` + test; wire into `acit` binary deps (reuse the existing
  `google_shopping_merchant_accounts` requirement — **no new pip dep**).
- `acit/tests/test_merchant_shipping.py` *(new)* — enum/micros/snake-key + the 4-boolean derivation.
- **N/A:** `acit/create_base_tables.py` + `acit/api/v0/storage/schema.proto` — shipping bypasses Beam/proto.

## Notes / known constraints (carried from Phases 1–3)

- **No new pip dependency** — `google-shopping-merchant-accounts` (Phase 1/3) already ships
  `ShippingSettingsServiceClient`.
- **No proto / no Beam for shipping** — it is `bq::load`ed directly with a **hand-written** schema, so
  there is no `bq_gen_schemas` step (unlike `liasettings`/`Products`). One fewer Linux-only step.
- **Image build is Linux-only on this repo** (`//:cloud_run_job` os=linux/amd64) — full image build runs
  in Cloud Build; Python targets (`//acit:acit`, `bazel test //acit:...`) validate on macOS-ARM.
- Merchant API has no bulk variant → reuse the threaded fan-out + retry/backoff pattern.
- Main code must read standard `GOOGLE_ADS_*` env vars; test creds stay in the gitignored `env.local.sh`.
- Native v1 shape end-to-end — no transform back into the legacy `shippingsettings` schema.
- **Retiring the Content API:** shipping is the last consumer of `discovery.build('content','v2.1')`;
  removing it should fully drop the Content API dependency — do the dead-import cleanup carefully in Step 7.
