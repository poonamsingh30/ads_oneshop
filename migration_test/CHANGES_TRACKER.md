# Products Migration — Master Change Tracker (Phase 2)

> Single source of truth for **every** file added/modified during the Content API →
> Merchant API v1 migration of the **`products`** path (Phase 2 = products + productstatuses).
> Append an entry whenever a file changes.
> Plan/checklist: `products_migration_plan.md` · Context: `products_migration_understanding.md`.
> Phase 1 (`accounts`) is complete; its tracker is archived at `completed/accounts/CHANGES_TRACKER.md`.

## Proposed design decisions (recommended options — lock during Steps 2–6)

| # | Decision | Proposed choice | Rationale |
|---|----------|-----------------|-----------|
| D1 | New-API client library | **`google-shopping-merchant-products`** (`google.shopping.merchant_products_v1`, stable v1, gRPC) | Google's recommended path; consistent with Phase-1 `google-shopping-merchant-accounts`. Confirm after the Step-3 test script. |
| D2 | Record / output shape | **One native v1 `Product` per line** (attributes + status together) at `merchant_center/<id>/products/rows.jsonlines`; drop the separate `productstatuses/` dir + the Beam products↔statuses join | v1 merges status into the `Product` resource, so the two-collection join collapses. Keeping the path means the BQ glob is unchanged. Confirm in Step 6. |
| D3 | Proto / schema modeling | **Rewrite `Product`/`ProductStatus`/`WideProduct` in `schema.proto`** to native v1 fields; regenerate `Products.schema` via `bq_gen_schemas` | Products BQ schema is proto-generated (not hand-edited). No legacy field names. Single-wide vs split sub-messages decided in Step 6. |

## Environment

- Conda env: **`oneshop_products_migration`** (python 3.11). Anaconda default repo still network-blocked → created by **cloning** the Phase-1 env `oneshop_merchant_migration` (local, no network), then `pip install google-shopping-merchant-products==1.6.0`. Stable v1 import-verified (`google.shopping.merchant_products_v1`).
- pip deps: old discovery client (`google-api-python-client`, `google-auth*`) for the baseline pull +
  `google-shopping-merchant-products` (new API).
- Test creds: `migration_test/env.local.sh` (GITIGNORED, reused from Phase 1). Main code keeps reading
  standard `GOOGLE_ADS_*` env vars — the local file is for testing only.
- Test account: a **leaf** merchant account with products (under MCA `120436857`); pick during Step 1.

## Change log

| Date | File | Type | Step | Notes |
|------|------|------|------|-------|
| 2026-06-02 | `migration_test/products_migration_understanding.md` | add | pre | Phase-2 understanding doc |
| 2026-06-02 | `migration_test/products_migration_plan.md` | add | pre | Plan + 7-step + e2e checklist |
| 2026-06-02 | `migration_test/CHANGES_TRACKER.md` | add | pre | This tracker (Phase 2) |
| 2026-06-02 | `migration_test/.gitignore` | edit | 0 | Added `old_products/`, `new_products/` scratch ignores |
| 2026-06-02 | `migration_test/fetch_products_old.py` | add | 1 | OLD Content API products+productstatuses fetcher (mirrors `_pull_leaf_collection`) |
| 2026-06-02 | `migration_test/old_products/*` (gitignored) | data | 1 | Baseline: leaves `120131628` (7 products) & `215174218` (1) under MCA `120436857` |
| 2026-06-02 | `migration_test/products_api_v1_mapping.md` | add | 2 | v1 endpoint study + authoritative old→new field map (grounded on real product `A6`) |
| 2026-06-02 | `migration_test/fetch_products_new.py` | add | 3 | NEW Merchant API v1 products fetcher (`list_products`, enum-as-string, retry/backoff) |
| 2026-06-02 | `migration_test/new_products/*` (gitignored) | data | 3 | New v1 output: `120131628`=7, `215174218`=1 (parity; status embedded) |
| 2026-06-02 | `migration_test/compare_products.py` | add | 4 | Field-level old-vs-new reconciliation (consumed/critical fields) |
| 2026-06-02 | `migration_test/products_diff.md` | add | 4-5 | Comparison (8/8, 0 mismatch) + finalized gap log (G1–G14) |

### Steps 6–7: end-to-end code changes (main code) — ✅ COMPLETE
| Date | File | Type | Notes |
|------|------|------|-------|
| 2026-06-03 | `acit/api/v0/storage/schema.proto` | rewrite | Native v1 `Product` (identity + derived `channel` + nested `ProductAttributes` + `custom_attributes`), `ProductStatus`/`DestinationStatus`(`reporting_context`)/`ItemLevelIssue`(`severity`/`attribute`/`reporting_context`), `Price{amount_micros,currency_code}`, enums as STRING, `gtins` repeated, `custom_label_0..4`. `WideProduct` keeps `product`+`status` columns. LiaSettings block preserved. `Products.schema` is GENERATED → regenerates via `bq_gen_schemas` in Cloud Build. |
| 2026-06-03 | `acit/merchant_products.py` | add | Merchant API v1 products ingestion (`ProductsServiceClient.list_products`, enum-as-string `to_dict`, retry/backoff, threaded). Dumps raw native v1 `Product` per line. |
| 2026-06-03 | `acit/acit.py` | edit | Dropped `products`/`productstatuses` from the Content-API leaf loop (removed `_ACIT_MC_RESOURCES` + `_pull_leaf_collection`); added `merchant_products.download_products(...)`. ProcessPoolExecutor now only does standalone admin resources. |
| 2026-06-03 | `acit/create_base_tables.py` | edit | Removed the products↔statuses `CoGroupByKey` join + the `productstatuses` read; added `split_v1_product` (derives `channel` from `legacy_local`, splits `product_status`→`status`); `products_table_row` no longer dels status metadata. |
| 2026-06-03 | `acit/product.py` | edit | `_attrs()` helper; `set_product_in_stock` (`IN_STOCK`), `set_product_approved` (`reporting_context=='SHOPPING_ADS'`, snake countries), matcher reads → `product_attributes.*` + `offer_id`/`feed_label`/`content_language` + derived `channel`. |
| 2026-06-03 | `acit/views/main_view.sql` | edit | Product attribute paths → `P.product.product_attributes.*`; `gtin`→`gtins[1]`; identity + derived `channel` stay on `P.product`. |
| 2026-06-03 | `acit/views/disapprovals_view.sql` | edit | `servability='disapproved'`→`severity='DISAPPROVED'`; `destination='Shopping'`→`reporting_context='SHOPPING_ADS'`. |
| 2026-06-03 | `extensions/merchant_excellence/offer_list.sql` | edit | Attribute paths, status value remap, `sizes`→`size`, Price `.value`→`.amount_micros`, dropped `OffersUploadedViaApi` (no v1 `source`). |
| 2026-06-03 | `extensions/merchant_excellence/offer_funnel.sql` | edit | Status value remap (`FREE_LISTINGS`/`DEMAND_GEN_ADS`/`SHOPPING_ADS`); attribute paths; `availability != 'OUT_OF_STOCK'`. |
| 2026-06-03 | `extensions/merchant_excellence/all_metrics.sql` | edit | Status value remap; attribute paths; `sizes`→`size`; Price `.value`→`.amount_micros` (sale_price/shipping/cogs); dropped `OffersUploadedViaApi`. |
| 2026-06-03 | `extensions/merchant_excellence/ml_data.sql` | edit | Status value remap; attribute paths; `sizes`→`size`; `sale_price.value`→`.amount_micros`; dropped `source` column. |
| 2026-06-03 | `extensions/merchant_excellence/account_list.sql` | edit | Product-status `destination='SurfacesAcrossGoogle'`→`reporting_context='FREE_LISTINGS'`. |
| 2026-06-03 | `acit/tests/test_product.py` | edit | Fixtures → v1 shape (`product_attributes` nesting, `offer_id`, `custom_label_N`; `channel` stays top-level). |
| 2026-06-03 | `acit/tests/test_merchant_products.py` | add | Unit tests: enum-as-string, snake keys, price micros, status `reporting_context`. |
| 2026-06-03 | `requirements.in` / `requirements_lock.txt` | edit | + `google-shopping-merchant-products==1.6.0` (surgical, both hashes; `google-shopping-type` already 1.4.0). No churn. |
| 2026-06-03 | `acit/BUILD.bazel` | edit | New `merchant_products_lib` + `merchant_products_test`; `acit` binary deps += `:merchant_products_lib`. |

### Build / validation results (Steps 6–7)
- `bazel build //acit:acit` ✅. `bazel test //acit:{merchant_products_test,product_test,create_base_tables_test,merchant_accounts_test}` ✅ (product_test 34 cases, merchant_products_test 5).
- `schema_pb2` compiles from the new proto on macOS (proven by `create_base_tables_test` importing it); 8 real v1 products round-trip end-to-end through the **bazel-built `schema_pb2.WideProduct`** (derived channel, price micros, `SHOPPING_ADS` status, in_stock, disapproved countries all correct).
- **Known Linux-only step (pre-existing):** `//acit/api/v0:bq_gen_schemas` (regenerates `Products.schema`) + `//:cloud_run_job` build in Cloud Build, not macOS-ARM. Since Phase 2 *changes the proto*, the regenerated schema must be verified in Cloud Build.
- **New gap (G15):** product `source` has no Merchant API v1 equivalent but the MEX `OffersUploadedViaApi` metric consumed it → metric dropped (offer_list/all_metrics); `source` column dropped from ml_data.

## Main-code files expected to change in Step 7 (not yet touched)

- `acit/acit.py` — products ingestion (`products.list` + `productstatuses.list` → v1 `products.list`);
  remove the `productstatuses` pull.
- `acit/merchant_products.py` *(new)* — Merchant API v1 products fetcher (pagination, retry/backoff, threading).
- `acit/create_base_tables.py` — remove the products↔statuses join; carry `productStatus`; re-point proto parse.
- `acit/product.py` (+ `shopping.py`, `performance_max.py`) — update targeting/approval/in-stock field reads
  to v1 `productAttributes` / `productStatus` paths.
- `acit/api/v0/storage/schema.proto` — rewrite `Product`/`ProductStatus`/`WideProduct` to native v1; regenerate
  `Products.schema` via `//acit/api/v0:bq_gen_schemas`.
- `acit/bq.sh` — `Products` table load (path likely unchanged if output layout preserved).
- `acit/views/main_view.sql`, `acit/views/disapprovals_view.sql` — new product field names + FK derivation.
- `extensions/merchant_excellence/{all_metrics,all_metrics_historical,ml_data,offer_funnel,offer_funnel_historical,offer_list}.sql` — new shape.
- `acit/tests/test_create_base_tables.py` (+ product/shopping/pmax tests) — update fixtures to v1 shape.
- `requirements.in` / `requirements_lock.txt` — add `google-shopping-merchant-products` (surgical, no churn).
- `acit/BUILD.bazel` — new `merchant_products_lib` + test; wire into `acit` binary deps.

## Notes / known constraints (carried from Phase 1)

- **Image build is Linux-only on this repo**: `//acit/api/v0:bq_gen_schemas` runs a `linux_x86_64` protoc and
  `//:cloud_run_job` is `os=linux/amd64`, so the full image build runs in Cloud Build, not on macOS-ARM.
  Phase 2 *changes the proto*, so the schema-gen step is now in-scope — validate the regenerated schema in
  Cloud Build (or a native linux/amd64 env), not locally.
- Merchant API has no bulk variant + transient 500s → reuse the Phase-1 retry/backoff + threaded fan-out pattern.
- Main code must read standard `GOOGLE_ADS_*` env vars; test creds stay in the gitignored `env.local.sh`.
