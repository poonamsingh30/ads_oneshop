# Phase 2 — `products`: Old (Content API v2.1) → New (Merchant API v1) Field Map

> Step 2 output. Introspected from the installed `google.shopping.merchant_products_v1`
> client **and verified against real data** (leaf `120131628`, product `A6`; leaf `215174218`).
> Authoritative reference for the Step 6 proto/schema rewrite + Step 7 code changes.

---

## 1. Endpoint / client mapping

| Old (Content API v2.1, discovery `content`) | New (Merchant API v1, `google.shopping.merchant_products_v1`) |
|---|---|
| `products.list` (per leaf, `merchantId`, `maxResults=250`, page via `list_next`) | `ProductsServiceClient.list_products(parent="accounts/{leaf}", page_size=…)` (server pager) |
| `products.get` | `ProductsServiceClient.get_product(name="accounts/{leaf}/products/{product}")` |
| **`productstatuses.list`** (separate collection, join in Beam) | **GONE** — status is folded into `Product.product_status` (returned by `list_products`) |
| `productstatuses.get` | GONE — same as above |

Other clients in the package (not used for ingestion): `ProductInputsServiceClient`
(`ProductInput` = the per-feed *input* you upload; we want the **processed** `Product`).

Rendering: proto-plus `Product.to_dict(p, use_integers_for_enums=False)` → **snake_case keys,
enum NAMES as strings** (same pattern as Phase-1 accounts).

## 2. Product identity & the Ads `performance` FK (important)

| | Old Content API | New Merchant API v1 |
|---|---|---|
| Resource id | `id = "online:en:US:A6"` = `channel:content_language:target_country:offer_id` | `name = "accounts/120131628/products/en~US~A6"`; product id = `content_language~feed_label~offer_id` |
| Components | `channel`, `contentLanguage`, `targetCountry`, `offerId` | `content_language`, `feed_label`, `offer_id` (top-level), + `legacy_local` (bool), `data_source` |
| **`channel`** | top-level product field (`online`/`local`) | **REMOVED** — derive: `legacy_local == True → 'local'`, else `'online'` |
| **`target_country`** | top-level product field | **REMOVED** — `feed_label` now occupies the country slot (`US`) |

**Beam join key** today is `(accountId, product['id'])` ↔ `(accountId, status['productId'])`. In v1
there is no separate status, so the join is removed; the per-product key for downstream is
`(accountId, offer_id)` (or the full `name`).

**Merchant FK** for the Ads `performance` join is `channel:content_language:feed_label:item_id`
(+ merchant id). Ads `segments.product_channel` still emits `online`/`local`, so we must
**re-derive `channel` from `legacy_local`** to keep the FK matching. (Confirm `feed_label`
casing/value against Ads `segments.product_feed_label` in Step 4.)

## 3. Product attribute map (old flat `Product` → new `product_attributes`)

All offer attributes now live under **`product_attributes`** (proto `ProductAttributes`, 98
fields). Top-level `Product` carries only identity: `name`, `offer_id`, `content_language`,
`feed_label`, `legacy_local`, `data_source`, `version_number`, `base64_encoded_name`,
`custom_attributes`, `product_attributes`, `product_status`, `automated_discounts`.

| Old `Product` field | New location | Notes |
|---|---|---|
| `id` | `name` / (`offer_id`,`content_language`,`feed_label`) | format change (§2) |
| `offerId` | `offer_id` (top-level) | now top-level, not under attributes |
| `contentLanguage` | `content_language` (top-level) | |
| `targetCountry` | — | dropped; see `feed_label` |
| `feedLabel` | `feed_label` (top-level) | |
| `channel` | — | dropped; derive from `legacy_local` (§2) |
| `title`, `description`, `link`, `imageLink` | `product_attributes.{title,description,link,image_link}` | renamed snake_case |
| `additionalImageLinks` | `product_attributes.additional_image_links` | |
| `brand`, `color`, `material`, `pattern`, `mpn` | `product_attributes.{…}` | same names (snake) |
| `gtin` (string) | `product_attributes.gtins` (**repeated**) | **single → list** |
| `googleProductCategory` | `product_attributes.google_product_category` | same string value |
| `productTypes` (repeated) | `product_attributes.product_types` | same |
| `customLabel0..4` | `product_attributes.custom_label_0..4` | **underscore** before digit |
| `price` `{value,currency}` | `product_attributes.price` `{amount_micros,currency_code}` | **string dollars → int64 micros**; `6.00 USD → "6000000"/"USD"` |
| `salePrice`, `costOfGoodsSold`, etc. | `product_attributes.{sale_price,cost_of_goods_sold,…}` (all `Price` micros) | |
| `availability` (`"in stock"`) | `product_attributes.availability` (**enum** `IN_STOCK`) | enum: `IN_STOCK/OUT_OF_STOCK/PREORDER/LIMITED_AVAILABILITY/BACKORDER` |
| `condition` (`"new"`) | `product_attributes.condition` (**enum** `NEW`) | enum: `NEW/USED/REFURBISHED` |
| `adult` | `product_attributes.adult` | |
| `ageGroup`, `gender`, `sizeSystem` | enums under `product_attributes` | |
| `identifierExists` | `product_attributes.identifier_exists` | |
| `shipping[]` | `product_attributes.shipping[]` (`Shipping`) | `price` now micros; no `service_alternative_list`; adds `handling_cutoff_time(zone)` |
| `productHeight/Length/Width`, `productWeight` | `product_attributes.{product_height,…,product_weight}` | `{value,unit}` |
| `customAttributes[]` | `Product.custom_attributes[]` (**top-level**, not under attributes) | `{name,value}` (+ nested groups) |
| `source` | — | not an attribute in v1 (≈ `data_source` resource on `Product`) |
| `kind` | — | dropped (REST artifact) |

> The migration-critical **targeting fields** all survive (renamed): `offer_id`,
> `content_language`, `feed_label`, `condition`, `brand`, `custom_label_0..4`,
> `product_types`, `google_product_category` — **except `channel` (derive) and
> `channelExclusivity` (dropped)**. `availability` is now the `IN_STOCK` enum.

## 4. Status map (old `ProductStatus` → new `Product.product_status`)

| Old `ProductStatus` | New `product_status` | Notes |
|---|---|---|
| `productId` | (= the product's own identity) | no separate row → no join key needed |
| `destinationStatuses[]` | `destination_statuses[]` | see below |
| `destinationStatuses[].destination` (`"Shopping"`) | `…reporting_context` (**enum** `SHOPPING_ADS`) | **`Shopping` → `SHOPPING_ADS`**; also `FREE_LISTINGS`, `DEMAND_GEN_ADS`, `VIDEO_ADS`, … |
| `…channel`, `…status` | — | dropped (`status` was already deprecated) |
| `…approved/pending/disapprovedCountries` | `…approved_countries/pending_countries/disapproved_countries` | same arrays |
| `itemLevelIssues[]` | `item_level_issues[]` | renames below |
| `…servability` | `…severity` | **rename** (values e.g. `DISAPPROVED`) |
| `…attributeName` | `…attribute` | **rename** |
| `…destination` | `…reporting_context` | **rename → enum** |
| `…code,resolution,description,detail,documentation,applicableCountries` | same (snake_case) | |
| `creationDate/lastUpdateDate/googleExpirationDate` | `creation_date/last_update_date/google_expiration_date` | now RFC3339 `Timestamp` strings |
| `title`, `link`, `kind` (on status) | — | dropped (live on `Product`) |

**Downstream impact:**
- `product.set_product_approved` filters `destination == 'Shopping'` → must become
  `reporting_context == 'SHOPPING_ADS'`, reading `product.product_status.destination_statuses`.
- `disapprovals_view.sql` reads item-level issues → field renames
  (`servability→severity`, `attributeName→attribute`, `destination→reporting_context`).

## 5. Value-representation changes to handle in the proto/schema (Step 6)
- **Price**: `{value:string, currency:string}` → `{amount_micros:int64, currency_code:string}`.
- **Enums**: `availability`, `condition`, `age_group`, `gender`, `size_system`,
  `destination_statuses[].reporting_context`, `item_level_issues[].severity`/`reporting_context`
  are now enums (store the NAME string in BQ, as we did for accounts).
- **`gtin` → `gtins`** (scalar → repeated).
- **`custom_label0..4` → `custom_label_0..4`**.
- **Timestamps**: status dates are `Timestamp` (RFC3339).

## 6. Confirmed counts (parity with old baseline)
- `120131628`: old 7 products / 7 statuses → new **7 products** (status embedded). ✅
- `215174218`: old 1 / 1 → new **1**. ✅

## 7. Open items for Step 4–5 (diff + gaps)
- Confirm `feed_label` value matches Ads `segments.product_feed_label` (FK join) and that the
  derived `channel` (`legacy_local`) matches `segments.product_channel`.
- Enumerate any old product attribute that has **no** v1 home (beyond `channel`,
  `channelExclusivity`, `targetCountry`, `kind`, `source`, status `status/title/link`).
- Decide `gtins` handling for the (single-valued) downstream consumers, if any.
