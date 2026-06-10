# Code Changes Overview — Content API → Merchant API v1 Migration (for QA)

> Every production code change on branch `feat/merchant-api-shippingsettings-migration`
> compared to `main` (the old Content API code). 27 files: **8 new**, **19 updated**.
> Verified against `git diff origin/main...HEAD`.
>
> The migration replaces the deprecated **Content API for Shopping v2.1** with the
> **Merchant API stable v1** across 4 resources — **accounts, products, liasettings,
> shippingsettings** — keeping the native v1 data shape end-to-end (no transform back to
> the legacy schema).

---

## How the changes fit together (data flow)

```
  Merchant API v1  ──►  ingestion (merchant_*.py)  ──►  raw JSONL on GCS
        │                                                     │
        │                                  ┌──────────────────┴───────────────┐
        │                                  ▼                                   ▼
        │                       create_base_tables.py (Beam)         bq load (shippingsettings,
        │                       proto schema.proto                    direct, hand-written schema)
        │                                  │
        ▼                                  ▼
  schemas/*.schema  ──►  BigQuery base tables  ──►  acit views  ──►  MEX extension SQL
```

---

## 1. Ingestion — new Merchant API v1 clients (4 new files)
These replace the old generic `resource_downloader` + `googleapiclient.discovery.build('content','v2.1')` calls. Each pulls one resource from Merchant API v1 and writes native-v1 JSONL.

| File | Status | What it does |
|------|:------:|--------------|
| `acit/merchant_accounts.py` | **new** | Pulls accounts via `AccountsServiceClient` / list-sub-accounts. Returns the set of account ids, the set of product accounts, and a parent/aggregator map. Replaces the Content API `accounts` envelope with flat per-account records. |
| `acit/merchant_products.py` | **new** | Pulls products via `ProductsServiceClient.list_products`. Each native v1 `Product` already embeds its status (`product_status`) — no separate `productstatuses` call. |
| `acit/merchant_lia.py` | **new** | Pulls `OmnichannelSettings` per account (v1 has no `liasettings` resource and no MCA roll-down `list`; the aggregator is not a valid parent → PermissionDenied, so we list per sub-account). Writes one flat record per account. |
| `acit/merchant_shipping.py` | **new** | Pulls the `ShippingSettings` singleton per account via `ShippingSettingsServiceClient.get_shipping_settings`. Threaded (8 workers); skips aggregators (PermissionDenied) and accounts with no settings (NotFound). |

## 2. Orchestrator
| File | Status | What changed |
|------|:------:|--------------|
| `acit/acit.py` | updated | Retired all Content API ingestion: removed the `discovery.build('content','v2.1')` factory, `resource_downloader`, the MCA roll-down loop, and the ProcessPool standalone-account loop. Now calls the 4 `merchant_*` modules directly. Shipping is pulled only when admin rights are present. |

## 3. Schema definitions
| File | Status | What changed |
|------|:------:|--------------|
| `acit/api/v0/storage/schema.proto` | updated | Product/LIA messages re-modelled to the **native v1 shape**: snake_case attributes nested under `product_attributes`, `Price` in micros, enums stored as NAME strings, `gtins` repeated, `custom_label_0..4`. `CombinedLiaSettings {settings, children[]}` → flat `OmnichannelLiaSettings {account_id, omnichannel_settings[]}`. Adds a note that `productstatuses` no longer exists (status is inline) and `channel` is a derived dimension. |
| `acit/schemas/acit/accounts.schema` | updated | BigQuery schema for the flat v1 accounts table (one row per account with `parent`/`automatic_improvements` etc.), replacing the old `{settings, children[]}` envelope schema. |
| `acit/schemas/acit/shippingsettings.schema` | updated | Hand-written flat v1 schema: `account_id` + `services[]` (delivery_time in days, `rate_groups` with `flat_rate.amount_micros`, `main_table` cells, etc.). Used directly by `bq load` (shipping bypasses Beam). |

## 4. Beam base-table builder & product transform
| File | Status | What changed |
|------|:------:|--------------|
| `acit/create_base_tables.py` | updated | Dropped the `productstatuses` read and the products↔statuses join. Added `split_v1_product`: splits the inline `product_status` out into `status` and derives `channel` (`legacy_local ? 'local' : 'online'`) for the Ads performance FK. LIA parse simplified to the flat v1 record with `ignore_unknown_fields=True` (drops the stamped metadata). |
| `acit/product.py` | updated | Reads native-v1 fields: `availability` enum `IN_STOCK` (was `'in stock'`); attributes via `product_attributes.*` (`google_product_category`, `brand`, `condition`, `custom_label_N`, `product_types`); status via `destination_statuses[].reporting_context == 'SHOPPING_ADS'` and snake_case `approved/pending/disapproved_countries`. |

## 5. acit views (BigQuery)
| File | Status | What changed |
|------|:------:|--------------|
| `acit/views/main_view.sql` | updated | All product attributes re-pathed to `P.product.product_attributes.*` (title, product_types, custom_label_0..4, google_product_category, brand). `gtin` now reads `gtins[SAFE_ORDINAL(1)]` (v1 made it repeated). |
| `acit/views/disapprovals_view.sql` | updated | Predicate updated to v1 enums: `item_level_issue.severity = 'DISAPPROVED'` and `reporting_context = 'SHOPPING_ADS'` (was `servability = 'disapproved'` / `destination = 'Shopping'`). |

## 6. Merchant Excellence extension SQL
| File | Status | What changed |
|------|:------:|--------------|
| `extensions/merchant_excellence/admin_tables.sql` | updated | Table DDLs reshaped to the flat v1 base tables (accounts, liasettings, and new flat `shippingsettings {account_id, services[]}`). |
| `extensions/merchant_excellence/account_list.sql` | updated | `AllShippingData` reads flat `shippingsettings` (dropped the `children` UNION); shipping booleans derive from v1 `delivery_time.*_days`, `rate_groups`, `main_table`, `single_value`, `flat_rate.amount_micros = 0`. Accounts read flat. |
| `extensions/merchant_excellence/all_metrics.sql` | updated | Same flat-accounts/flat-shipping reads; destination predicates → v1 `reporting_context` enums. **Free-shipping check changed to `IFNULL(price.amount_micros,0)=0`** (see I4 in the data-validation doc). |
| `extensions/merchant_excellence/offer_list.sql` | updated | Same v1 enum + flat reads; same free-shipping `IFNULL(price.amount_micros,0)=0` change (I4). Drops the `products uploaded via API` metric (Content API `Product.source` has no v1 equivalent). |
| `extensions/merchant_excellence/offer_funnel.sql` | updated | Accounts read flat (parent self-join for aggregator name, `WHERE NOT is_advanced`); destination predicates → `FREE_LISTINGS` / `DEMAND_GEN_ADS` / `SHOPPING_ADS`; product attrs via `product_attributes.*`. |
| `extensions/merchant_excellence/ml_data.sql` | updated | Flat accounts/shipping/LIA reads. **Fix:** LIA booleans wrapped in `IFNULL(..., FALSE)` so accounts absent from the flat LIA table stay explicit-False instead of NULL (item I2). |

## 7. Dependencies
| File | Status | What changed |
|------|:------:|--------------|
| `requirements.in` | updated | Added `google-shopping-merchant-accounts`, `google-shopping-merchant-products`. |
| `requirements_lock.txt` | updated | Pinned `google-shopping-merchant-accounts==1.5.0`, `google-shopping-merchant-products==1.6.0`, transitive `google-shopping-type==1.4.0` (with hashes). |
| `acit/BUILD.bazel` | updated | Bazel targets for the 4 new `merchant_*` libs + their tests; wired the new `google_shopping_*` deps into the `acit` binary (the Cloud Run / Dataflow image is Bazel-built). |

## 8. Tests
| File | Status | What changed |
|------|:------:|--------------|
| `acit/tests/test_merchant_accounts.py` | **new** | Unit tests for the v1 accounts client. |
| `acit/tests/test_merchant_products.py` | **new** | Unit tests for the v1 products client. |
| `acit/tests/test_merchant_lia.py` | **new** | Unit tests for the v1 omnichannel-settings client. |
| `acit/tests/test_merchant_shipping.py` | **new** | 6 tests: enum-as-string, snake_case keys, free `amount_micros=0` present, micros scaling, `main_table` cell `flat_rate`, downloader metadata. |
| `acit/tests/test_product.py` | updated | Fixtures moved to the v1 `product_attributes.*` shape (`google_product_category`, `brand`, `condition`, `custom_label_N`, `offer_id`, `product_types`). |
| `acit/test_acit.py` | updated | Removed Content API `resource_downloader` mocks; mocks the 4 `merchant_*.download_*` functions instead so the test runs offline. |

---

## Not pipeline code (QA reference only)
Everything under `migration_test/` is the **validation harness and documentation**, not part of the deployed pipeline:
- Per-resource fetch/compare scripts and mapping/diff/understanding docs (under `migration_test/` and `migration_test/completed/{accounts,products,liasettings}/`).
- `migration_test/content_api_ingestion.md` — how the old Content API ingestion worked.
- `migration_test/data_validation/` — the post-migration old-vs-new BigQuery data comparison (see `data_validation_understanding.md` and `merchant_excellence_validation.md`).

These can be ignored for code review of the runtime behaviour, but are useful evidence for QA that the migrated data matches the old pipeline.

---

## QA test summary
- `bazel build //acit:acit` ✅
- `bazel test //acit:merchant_{accounts,products,lia,shipping}_test //acit:product_test //acit:create_base_tables_test //acit:acit_test` ✅ (all green, no network)
- Data validation: 13/18 BigQuery tables identical old↔new; the rest differ only for documented intentional reasons (see `data_validation/`). No data-loss or incorrect-value regressions.
