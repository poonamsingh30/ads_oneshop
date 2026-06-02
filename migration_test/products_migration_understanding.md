# Phase 2 — `products` Migration: Understanding Doc

> Companion to `content_api_ingestion.md`. This doc confirms my understanding of the
> task before any code changes. The tracking/plan lives in `products_migration_plan.md`.
> Phase 1 (`accounts`) is complete and archived under `completed/accounts/`.

---

## 1. The goal (as I understand it)

Migrate Ads OneShop's **product** data ingestion from the **Content API for Shopping
v2.1** (`shoppingcontent.googleapis.com`, discovery `content`/`v2.1`) to the new
**Merchant API, stable `v1`** (`merchantapi.googleapis.com`) — **phased, one resource
group at a time**. Phase 2 covers the **`products`** path: the Content API
**`products`** and **`productstatuses`** collections and everything they feed.

The migration must be **end-to-end** for the resource in scope:

```
ingestion (acit.py)  ->  Beam processing (create_base_tables.py + product.py)
                     ->  proto schema (schema.proto -> Products.schema)
                     ->  BQ load (bq.sh)  ->  views (main_view / disapprovals) + MEX SQL
```

**Critical constraint (same as Phase 1):** the new Merchant API data must **NOT** be
re-shaped back into the legacy Content API schema. We adopt the **native Merchant API v1
product shape** at every layer — new field names, new nesting, new proto/BQ schema, and
updated downstream SQL. No compatibility shim that pretends the old `Product`/`ProductStatus`
shape still exists.

Other hard constraints (unchanged):
- **Stable `v1` only** — not `v1beta`.
- **Fresh conda env** for any local testing / test scripts.
- Keep test/throwaway artifacts under `migration_test/`.
- The Cloud Run / Dataflow image is built from **Bazel**; all new deps (pip packages,
  `BUILD.bazel` wiring) must be handled so the image build keeps working.

## 2. The strict 7-step method I will follow (per phase)

| # | Step | Phase-2 meaning |
|---|------|-----------------|
| 1 | Fetch from **old** Content API | Pull `products` + `productstatuses` exactly as prod does today (`products.list`, `productstatuses.list` per leaf), save the raw JSONL as the baseline. |
| 2 | Read & understand the **new** Merchant API endpoints/params | Map every old product/status field to its new v1 home (the unified `Product` resource: `productAttributes` + `productStatus`). |
| 3 | Fetch from **new** Merchant API via a test script mirroring the current one | Build a small fetcher for the v1 products sub-API; save output for the same real leaf account(s). |
| 4 | **Compare** old vs new data | Field-by-field diff for the same real products, with special attention to the fields the Beam targeting/approval/in-stock logic and the views/MEX consume. |
| 5 | Understand the **gaps** | Note dropped/renamed/relocated/added fields, structural differences (esp. the products↔statuses merge, price shape, product-name/ID format). |
| 6 | **Resolve** the issues | Decide the final native record shape + new proto messages + regenerated BQ schema; handle missing equivalents. |
| 7 | Change the **main code end-to-end** | ingestion → Beam join/targeting → `schema.proto` + regenerated `Products.schema` → BQ load → `main_view`/`disapprovals_view` + MEX SQL. |

## 3. What "products" is today (the baseline to migrate)

From `content_api_ingestion.md` + code, the current product path is:

### 3a. Ingestion (`acit/acit.py`)
- For **every leaf account** (`leaf_ids ∪ (standalone_ids ∩ input_ids)`), in parallel via a
  `ProcessPoolExecutor`, `_pull_leaf_collection()` calls:
  - `products.list`  (`params={'merchantId': account_id, 'maxResults': 250}`)
  - `productstatuses.list` (same params)
  - via the generic `resource_downloader.download_resources(...)` (discovery client,
    pagination via `list_next`, 3 retries, `result_path='resources'`,
    stamps `downloaderMetadata={'accountId': account_id}`).
- Output: `merchant_center/<accountId>/products/rows.jsonlines` and
  `merchant_center/<accountId>/productstatuses/rows.jsonlines` (one JSON object per line).
- Quirk: the products endpoint uses param name `merchantId` (not `accountId`).

### 3b. Beam processing (`acit/create_base_tables.py` + helpers)
This is the **core denormalization** and is far more involved than accounts:
1. **Read** the two globs `merchant_center/*/products/*.jsonlines` and `.../productstatuses/*.jsonlines`.
2. **Join products ↔ statuses** on the composite key `(accountId, product['id'])` ↔
   `(accountId, status['productId'])` via `CoGroupByKey` → `{accountId, offerId, product, status}`.
   Defensive: rows missing either side are dropped (downloaders can race).
3. **Enrich from the product/status**:
   - `product.set_product_approved` — reads `status.destinationStatuses` (destination `Shopping`)
     → `approved_countries` / `pending_countries` / `disapproved_countries`.
   - `product.set_product_in_stock` — `product.availability == 'in stock'`.
4. **Cross-reference with Google Ads targeting** (`product.py`, `shopping.py`,
   `performance_max.py`): each product is tested against Shopping listing-group trees and
   PMax asset-group listing filters → `hasShoppingTargeting`, `hasPerformanceMaxTargeting`,
   `shoppingCampaignIds`, `performanceMaxCampaignIds`. **The matcher reads product fields by
   name** — these are the migration-critical fields:
   `offerId`, `channel`, `channelExclusivity`, `condition`, `brand`, `customLabel0..4`,
   `productTypes`, `googleProductCategory`, `contentLanguage`, `feedLabel` (+ `availability`
   for in-stock and the `Shopping` destination statuses for approval).
5. **Serialize via protobuf** `schema_pb2.WideProduct` (`json_format.ParseDict`, then
   `MessageToDict`) → `wide_products_table.jsonlines`.

### 3c. Schema — **proto-generated** (the big structural difference vs accounts)
- `acit/api/v0/storage/schema.proto` defines `Product`, `ProductStatus`,
  `ProductStatusDestinationStatus`, `ProductStatusItemLevelIssue`, `WideProduct`
  (the wrapper: `product`, `status`, targeting booleans/IDs, `in_stock`,
  `approved/pending/disapproved_countries`, `offer_id`, `account_id`), plus all the
  value types (`Price{value,currency}`, `ProductShipping`, `CustomAttribute`, etc.).
- The Bazel target `//acit/api/v0:bq_gen_schemas` runs `protoc-gen-bq-schema` to generate
  `storage/Products.schema` (and `storage/liasettings.schema`) **from the proto**.
  > **This is the exact protoc step that fails on macOS-ARM** (linux_x86_64 protoc), so the
  > image build is Linux/Cloud Build only — same constraint we hit in Phase 1.
- So unlike `accounts.schema` (hand-edited), the products BQ schema is changed by **editing
  `schema.proto` and regenerating**.

### 3d. BQ load (`acit/bq.sh`)
- The `Products` table is loaded from the Beam output `wide_products_table.jsonlines`
  using the generated `Products.schema` (`WRITE_TRUNCATE`, `ignoreUnknownValues`, 60-day TTL).

### 3e. Downstream consumers (must change too)
- `acit/views/main_view.sql` — the **`acit`** view Looker Studio reads. Flattens many
  `P.product.*` fields (`channel`, `content_language`, `feed_label`, `offer_id`, `title`,
  `product_types`, `custom_label0..4`, `google_product_category`, `brand`, `gtin`), plus
  `P.in_stock`, `P.approved/pending/disapproved_countries` (→ `is_approved`), and joins to
  Ads `performance` on `channel:content_language:feed_label:offer_id`.
- `acit/views/disapprovals_view.sql` — second Looker Studio view (item-level issues).
- **MEX4P SQL** that read the `Products` table:
  `all_metrics.sql`, `all_metrics_historical.sql`, `ml_data.sql`,
  `offer_funnel.sql`, `offer_funnel_historical.sql`, `offer_list.sql`.

## 4. What the new Merchant API v1 `products` looks like (key finding — confirm in Step 2)

The single biggest structural change: **the Content API's two collections
(`products` + `productstatuses`) collapse into ONE Merchant API resource, `Product`.**

- Client library (expected): **`google-shopping-merchant-products`**
  (`google.shopping.merchant_products_v1`, gRPC, stable v1) — Google's recommended path,
  same family as the Phase-1 accounts client.
- Two resource types in the products sub-API:
  - **`ProductInput`** — the per-feed *input* you upload (`productInputs.insert/list`).
  - **`Product`** — the **processed/computed** product (`accounts.{account}.products.get/list`).
    For ingestion we want **`Product`** (mirrors today's processed `products.list`).
- The processed `Product` is expected to carry **both**:
  - `productAttributes` — the offer attributes (title, description, price, brand, gtin,
    googleProductCategory, productTypes, customLabel0..4, channel, feedLabel, availability,
    …) restructured into a nested `Attributes` message with camelCase/snake field names.
  - `productStatus` — `destinationStatuses` + `itemLevelIssues` (what `productstatuses`
    returned). **So the separate `productstatuses.list` call goes away.**
- Resource-name / ID format changes (confirm exact form in Step 2/3):
  - `accounts/{account}/products/{product}`, where `{product}` is
    `channel~contentLanguage~feedLabel~offerId` (tilde-separated) — **not** the old
    `online:en:US:SKU` colon form. The Merchant FK used by the Ads `performance` join may
    need rederiving.
  - `Price` becomes `{amountMicros (int64 string), currencyCode}` — **not** `{value, currency}`.

### Implication for ingestion
Pulling "a product" in v1 is a **single `Product`** (attributes + status together), so the
Beam **products↔statuses join is removed** and replaced by reading one collection. The output
layout can stay `merchant_center/<accountId>/products/rows.jsonlines` (one `Product` per line)
so the BQ glob is unchanged — to be decided in Step 6. We may stop writing the
`productstatuses/` directory entirely.

### Client library question (to settle in Step 3, same as Phase 1)
1. **Discovery client** (`googleapiclient.discovery.build('merchantapi', 'products_v1', …)`) —
   smallest change vs the existing `resource_downloader` pattern.
2. **Dedicated Merchant API Python client** (`google-shopping-merchant-products`) — Google's
   recommended path, gRPC; consistent with Phase-1's `google-shopping-merchant-accounts`.
   Likely the chosen option for consistency, decided after the Step-3 test script.

## 5. Open questions to resolve during Steps 2–6 (tracked in the plan)

- Exact v1 `Product` shape: the full `productAttributes` field map vs the old flat `Product`
  proto (which of the ~150 proto fields have a v1 home, which are renamed/nested/dropped).
- The migration-critical **targeting fields** (`channel`, `channelExclusivity`, `condition`,
  `brand`, `customLabel0..4`, `productTypes`, `googleProductCategory`, `contentLanguage`,
  `feedLabel`, `offerId`, `availability`) — confirm each exists in v1 and its new path, since
  `product.py` matching depends on them.
- `destinationStatuses` / `itemLevelIssues` shape under `Product.productStatus` vs the old
  `ProductStatus` proto (used by `set_product_approved` and `disapprovals_view`).
- Price/measure value types (`amountMicros` vs `value`) and how that flows into the proto +
  views (no price math today, but the shape changes).
- Whether the products↔statuses Beam join is fully removed or kept as a no-op safety net.
- Product-name/ID format and whether the `channel:language:feed_label:item_id` Merchant FK in
  the Ads `performance` join still derives correctly.
- Whether to keep one wide `Product` proto message or split attributes/status sub-messages.
- Pagination / page-size / quota behavior of `products.list` in v1 (Phase-1 showed the
  Merchant API has no bulk variant + transient 500s → needed retry/backoff + threading).

## 6. Definition of done for Phase 2

- A test script under `migration_test/` fetches v1 `Product` data into JSONL for real leaf
  account(s), runnable in a fresh conda env.
- A documented old↔new field comparison + gap resolution (esp. targeting-critical fields).
- `acit/acit.py` ingests products from Merchant API v1 (native shape); `productstatuses`
  pull removed/folded.
- `acit/create_base_tables.py` + `product.py`/`shopping.py`/`performance_max.py` updated to
  the new field names; join collapsed; approval/in-stock/targeting still produce the same
  semantic outputs.
- `acit/api/v0/storage/schema.proto` updated to native v1 messages; `Products.schema`
  regenerated via `bq_gen_schemas`; `bq.sh` load still works.
- `main_view.sql` + `disapprovals_view.sql` + the 6 MEX SQL files updated to the new shape;
  views still build.
- Bazel image build wiring updated (new pip dep in `requirements.in`/`requirements_lock.txt`,
  `BUILD.bazel` deps) so Cloud Build still produces the image.
- All **other** resources (accounts already migrated; liasettings, shippingsettings, ads)
  remain on their current path — only `products`/`productstatuses` move in Phase 2.
