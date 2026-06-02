# Phase 2 — `products` Migration: Plan & Change Tracker

> Tracks the Content API v2.1 → Merchant API **v1 (stable)** migration of the
> **`products`** path (Content API `products` + `productstatuses`), end-to-end.
> Update the Status column as work proceeds.
> Understanding/context: `products_migration_understanding.md`. Per-file log: `CHANGES_TRACKER.md`.

**Legend:** ⬜ not started · 🟡 in progress · ✅ done · ⛔ blocked

---

## A. Workstream tracker (the strict 7 steps)

| Step | Task | Output / Artifact | Status |
|------|------|-------------------|--------|
| 0 | Set up fresh conda env + install deps (old discovery client + `google-shopping-merchant-products`) | conda env `oneshop_products_migration`; deps installed & import-verified | ✅ |
| 1 | Fetch **old** Content API `products` + `productstatuses` for a real leaf account; save baseline | `fetch_products_old.py` + `old_products/*` — leaves `120131628` (7) & `215174218` (1) | ✅ |
| 2 | Study **new** Merchant API v1 products sub-API; finalize old→new field map | `products_api_v1_mapping.md` (introspected from client + real data `A6`) | ✅ |
| 3 | Build **test fetcher** for v1 `Product`, mirroring `_pull_leaf_collection`; save output | `fetch_products_new.py` + `new_products/*` (7 + 1, parity) | ✅ |
| 4 | **Compare** old vs new for the same product(s) | `compare_products.py` + `products_diff.md` — **8/8 matched, 0 mismatch** on all consumed fields | ✅ |
| 5 | Document **gaps** (renamed/relocated/dropped/added; price shape; status merge; ID format) | `products_diff.md` §Step 5 (G1–G14, no blockers) | ✅ |
| 6 | **Resolve** gaps; decide final native record shape + new proto messages + regenerated schema | ✅ rewrote `schema.proto` (native v1); `Products.schema` regenerates via `bq_gen_schemas` | ✅ |
| 7 | Implement **end-to-end** code changes | ✅ §B done — see `CHANGES_TRACKER.md`; bazel-validated on Python targets | ✅ |

---

## B. End-to-end code change checklist (Step 7)

### B1. Ingestion — `acit/acit.py`
- ⬜ Add/extend a Merchant API v1 **products** client factory (consistent with Phase-1
  `merchant_accounts`; likely a new `acit/merchant_products.py` module).
- ⬜ Replace `_pull_leaf_collection`'s `products.list` + `productstatuses.list` with the v1
  `accounts.{account}.products.list` (single resource: attributes + status).
- ⬜ Decide & implement output layout: keep `merchant_center/<accountId>/products/rows.jsonlines`
  (one v1 `Product` per line) so the BQ glob is unchanged; stop writing `productstatuses/`.
- ⬜ Keep `downloaderMetadata={'accountId': account_id}` stamping for the Beam keys.
- ⬜ Confirm OAuth scope / creds work for Merchant API products (no scope change expected, verify).
- ⬜ Keep all non-products resources on their existing path (no Phase-2 change).

### B2. Generic fetch engine — `acit/resource_downloader.py` / new module
- ⬜ If staying on the dedicated gRPC client (per D1), add a small products fetcher with
  pagination + retry/backoff + threading (Phase-1 pattern). Discovery path only if D1 says so.
- ⬜ Unit tests added/updated.

### B3. Beam processing — `acit/create_base_tables.py` (+ `product.py`, `shopping.py`, `performance_max.py`)
- ⬜ **Remove the products↔statuses `CoGroupByKey` join** (status now lives inside `Product`);
  read one `products` collection and carry `productStatus` through.
- ⬜ Update `set_product_approved` to read `Product.productStatus.destinationStatuses` (v1 shape).
- ⬜ Update `set_product_in_stock` to read the v1 availability attribute path.
- ⬜ Update the **targeting matcher field reads** in `product.py` (`offerId`, `channel`,
  `channelExclusivity`, `condition`, `brand`, `customLabel0..4`, `productTypes`,
  `googleProductCategory`, `contentLanguage`, `feedLabel`) to the v1 `productAttributes` paths.
- ⬜ Update the composite join/lookup keys + Merchant FK derivation if the product-ID format changed.
- ⬜ Re-point `schema_pb2.WideProduct` parsing to the new proto messages.

### B4. Proto + generated schema — `acit/api/v0/storage/schema.proto`, `bq_gen_schemas`
- ⬜ Rewrite `Product` / `ProductStatus` (and `WideProduct`) messages to the **native v1 shape**
  (`productAttributes` nesting, `Price{amountMicros,currencyCode}`, merged status). No legacy field names.
- ⬜ Regenerate `storage/Products.schema` via `//acit/api/v0:bq_gen_schemas` (Linux/Cloud Build).
- ⬜ Verify `py_proto_library` (`schema_py_pb2`) still compiles and Beam parses against it.

### B5. BQ load — `acit/bq.sh`
- ⬜ Confirm the `Products` table load still points at `wide_products_table.jsonlines` +
  regenerated `Products.schema` (no path change expected if output layout preserved).

### B6. Views / final tables
- ⬜ `acit/views/main_view.sql` — update all `P.product.*` field references to the new proto field
  names; re-derive `is_approved` / `in_stock` / product-type & category splits / custom labels;
  fix the `performance` join FK if the ID format changed.
- ⬜ `acit/views/disapprovals_view.sql` — update item-level-issue field paths.
- ⬜ **MEX4P SQL** (read the `Products` table):
  - ⬜ `extensions/merchant_excellence/all_metrics.sql`
  - ⬜ `extensions/merchant_excellence/all_metrics_historical.sql`
  - ⬜ `extensions/merchant_excellence/ml_data.sql`
  - ⬜ `extensions/merchant_excellence/offer_funnel.sql`
  - ⬜ `extensions/merchant_excellence/offer_funnel_historical.sql`
  - ⬜ `extensions/merchant_excellence/offer_list.sql`

### B7. Tests & validation
- ⬜ Update `acit/tests/` touching products (`test_create_base_tables.py`, `product`/`shopping`/`pmax`).
- ⬜ Add unit tests for the new v1 product parsing + targeting field reads.
- ⬜ End-to-end dry run (direct runner) on a test account; confirm `Products` table + views + MEX build.
- ⬜ Row-count / spot-check parity vs the old pipeline (esp. approval, in-stock, targeting booleans).

### B8. Bazel / packaging (image build must keep working)
- ⬜ `requirements.in` += `google-shopping-merchant-products`; surgical `requirements_lock.txt` insert
  (no churn to existing pins — same approach as Phase 1).
- ⬜ `acit/BUILD.bazel` — new `merchant_products_lib` + test; wire into the `acit` binary deps.
- ⬜ Validate Python targets on macOS (`bazel build //acit:acit`, `bazel test //acit:...`); note the
  image/schema-gen targets are Linux/Cloud Build only (pre-existing protoc constraint).

---

## C. Old → New field map — ✅ CONFIRMED in Step 2
Authoritative table in **`products_api_v1_mapping.md`** (introspected + verified on real product `A6`).
Headlines: `productstatuses` collection **GONE** → folded into `Product.product_status`;
`price{value,currency}` → `{amount_micros(int64 micros),currency_code}`; offer attributes nested under
`product_attributes` (98-field `ProductAttributes`), snake_case; product id `online:en:US:A6` →
name `en~US~A6` = `content_language~feed_label~offer_id` (**channel + target_country removed**;
`legacy_local` bool replaces channel); `gtin`→`gtins` (repeated); `custom_label0..4`→`custom_label_0..4`;
`availability`/`condition` now **enums** (`IN_STOCK`/`NEW`); status `destination='Shopping'`→
`reporting_context='SHOPPING_ADS'`; item-issue `servability→severity`, `attributeName→attribute`,
`destination→reporting_context`.

## D. Gap log — ✅ FINALIZED in `products_diff.md`
**No blockers.** Coverage 8/8 exact; all consumed fields 0/8 mismatch. Gaps G1–G14:
**G1** `channel` removed → **derive** from `legacy_local` (verified 8/8 == old; load-bearing for the Ads FK);
**G2** `productstatuses` merged into `Product.product_status` → remove Beam join;
**G3** status `destination='Shopping'`→`reporting_context='SHOPPING_ADS'`;
**G4** `availability`/`condition` now enums (compare `IN_STOCK`); **G5** price→micros;
**G6** `gtin`→`gtins`; **G7** `custom_label0..4`→`custom_label_0..4`;
**G8** item-issue `servability/attributeName/destination`→`severity/attribute/reporting_context`;
**G9** attrs nested under `product_attributes`; **G10** id `online:en:US:A6`→`en~US~A6` (target_country dropped);
**G11** `channelExclusivity` dropped (matcher defaults multichannel); **G12–G13** drops (status `status/title/link`,
product `kind/source/target_country`) — none consumed; **G14** new fields added (`legacy_local`, `data_source`, …).

## E. Key decisions — ✅ ALL LOCKED
- **D1 — Client library:** ✅ `google-shopping-merchant-products` (`google.shopping.merchant_products_v1`,
  stable v1, gRPC). Validated by the Step-3 test fetcher; consistent with Phase-1 accounts.
- **D2 — Record shape:** ✅ ingestion dumps the **raw native v1 `Product`** (status embedded) per line at
  `merchant_center/<id>/products/rows.jsonlines` (BQ glob unchanged); `productstatuses/` dir + the Beam
  products↔statuses join removed. The **Beam** stage splits `product_status` into the `status` column and
  derives `channel`.
- **D3 — Proto modeling:** ✅ `WideProduct` keeps `product` + `status` columns (minimizes MEX churn);
  `Product` holds native v1 identity + a **derived `channel`** + nested `product_attributes`
  (`ProductAttributes`, curated v1 subset) + `custom_attributes`; `ProductStatus`/`DestinationStatus`
  (`reporting_context`)/`ItemLevelIssue` (`severity`/`attribute`/`reporting_context`); `Price{amount_micros,
  currency_code}`; enums stored as NAME strings. `Products.schema` is **generated** (not checked in) → only
  `schema.proto` edited; regenerates in Cloud Build.

---

## F. Guardrails / scope
- Phase 2 = **products + productstatuses only**. Do not migrate liasettings, shippingsettings, or Ads
  in this phase. (Accounts already migrated in Phase 1.)
- **No legacy-schema transform** — native Merchant API v1 shape end-to-end.
- v1 **stable** only (no v1beta). Test in a **fresh conda env**. Keep scratch artifacts in `migration_test/`.
- The Cloud Run / Dataflow **image build (Bazel)** must keep working — handle the new pip dep + BUILD wiring.

## G. Changelog
- **2026-06-03** — Steps 6–7 done (end-to-end main code). Proto rewritten to native v1
  (`acit/api/v0/storage/schema.proto`); new ingestion `acit/merchant_products.py` (v1 `list_products`,
  enum-as-string, retry/backoff, threaded) + `acit.py` rewired (dropped `products`/`productstatuses`
  Content-API pulls); `create_base_tables.py` join removed → `split_v1_product` (derives channel, splits
  status); `product.py` field reads → v1 (`product_attributes.*`, `IN_STOCK`, `SHOPPING_ADS`, snake
  identity); `main_view.sql` + `disapprovals_view.sql` + 5 MEX files (offer_list/offer_funnel/all_metrics/
  ml_data/account_list) updated (attribute paths → `product_attributes.*`, status `destination`→
  `reporting_context` w/ value remap, `servability`→`severity`, Price `.value`→`.amount_micros`,
  `gtin`→`gtins[1]`, `sizes`→`size`); `requirements.in`/lock + `acit/BUILD.bazel` (new `merchant_products_lib`
  + test, wired into `acit`). **Validated:** `bazel build //acit:acit` ✅; `bazel test` product_test (34)/
  merchant_products_test (5)/create_base_tables_test/merchant_accounts_test all ✅; end-to-end transform of
  8 real v1 products through the **bazel-built `schema_pb2.WideProduct`** ✅. **New gap found:** product
  `source` ('api'/'feed') has no v1 home but MEX consumed it → dropped the "products uploaded via API" metric
  (offer_list/all_metrics). Image/schema-gen (`bq_gen_schemas`, `cloud_run_job`) remains Cloud-Build-only.
- **2026-06-02** — Steps 4–5 done: `compare_products.py` → `products_diff.md`. **Coverage 8/8 exact**; every consumed field (derived channel, content_language, feed_label, offer_id, title, brand, condition, google_product_category, product_types, gtins, price-micros, **inStock semantic**, **SHOPPING approval countries**, custom_label_0..4) **0/8 mismatch**. Confirmed the one load-bearing transform is **G1 derive `channel` from `legacy_local`** (8/8 == old `channel` → Ads FK preserved). Gap log G1–G14, no blockers. Cleared to design the new proto/schema (Step 6).
- **2026-06-02** — Steps 2–3 done. Step 2: introspected `merchant_products_v1` + verified on real product → `products_api_v1_mapping.md`. Confirmed status-merge, `product_attributes` nesting (98 fields), id/FK format change (`channel`+`target_country` removed; derive channel from `legacy_local`), price micros, enum-as-string, `gtin→gtins`, `custom_label_N`, status `reporting_context`/`severity`/`attribute` renames. Step 3: `fetch_products_new.py` (`ProductsServiceClient.list_products(parent="accounts/{leaf}")`, enum-as-string `to_dict`, retry/backoff) → `new_products/`: parity with old (`120131628`=7, `215174218`=1). Next: Steps 4–5 (compare + gaps), focus on the targeting/approval/in-stock fields + the FK derivation.
- **2026-06-02** — Step 0 done: fresh conda env `oneshop_products_migration` (py3.11, cloned from Phase-1 env — anaconda default repo still network-blocked, so clone + pip) + `google-shopping-merchant-products==1.6.0`. **Stable v1 confirmed**: `google.shopping.merchant_products_v1` (clients `ProductsServiceClient`, `ProductInputsServiceClient`; types `Product`, `ProductInput`, `ProductStatus`). v1beta also present but unused.
- **2026-06-02** — Step 1 done: `fetch_products_old.py` mirrors `acit.py` (authinfo → `accounts.list` leaf discovery → per-leaf `products.list` + `productstatuses.list`, `merchantId` param, maxResults=250, paged). Baseline in `old_products/`: MCA `120436857` has 34 leaves; 2 have products — `120131628` (7) & `215174218` (1). **Old shapes captured**: Product id = colon form `online:en:US:A6` (`channel:lang:country:offerId`), `price:{value,currency}`, flat attrs (availability/brand/channel/condition/contentLanguage/feedLabel/googleProductCategory/gtin/identifierExists/imageLink/offerId/productTypes/shipping/source/targetCountry/title/…). ProductStatus join key = `productId` (== product `id`); `destinationStatuses[{destination,channel,status,disapprovedCountries}]` + `itemLevelIssues[{code,servability,resolution,attributeName,destination,description,detail,documentation,applicableCountries}]`. Next: Step 2 (study v1 `Product` + old→new field map).
- **2026-06-02** — Phase 2 kicked off. Created `products_migration_understanding.md` +
  this plan + `CHANGES_TRACKER.md`. Studied current product path: per-leaf `products.list` +
  `productstatuses.list` → Beam join + Ads-targeting cross-ref (`product.py`) → proto-generated
  `Products.schema` (`schema.proto` via `bq_gen_schemas`) → `Products` BQ table → `main_view`/
  `disapprovals_view` + 6 MEX SQL. Key finding: v1 merges `productstatuses` into the `Product`
  resource (`productStatus`) and restructures attributes (`productAttributes`, new `Price`). Steps 0–7 pending.
