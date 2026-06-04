# Phase 2 — `products`: Old vs New Comparison + Gap Log (Steps 4–5)

> Step 4 (compare) + Step 5 (gaps), produced by `compare_products.py` over the Step-1/Step-3
> baselines (leaves `120131628`, `215174218`). Companion to `products_api_v1_mapping.md`.

---

## Step 4 — Reconciliation result

**Coverage: 8/8 products matched** (by `(accountId, offer_id)`); 0 only-old, 0 only-new.
The new v1 `Product` is matched against the old `Product` **plus** its old `productStatus`
(now embedded). Every field the downstream pipeline consumes reconciles **exactly**:

| Field (canonical) | match | mismatch | Notes |
|---|---:|---:|---|
| `channel` (derived from `legacy_local`) | 8 | 0 | `legacy_local→'local'`, else `'online'` == old `channel` |
| `content_language` | 8 | 0 | |
| `feed_label` | 8 | 0 | |
| `offer_id` | 8 | 0 | |
| `title` | 8 | 0 | |
| `brand` | 8 | 0 | |
| `condition` (lower) | 8 | 0 | enum `NEW` ↔ `"new"` |
| `google_product_category` | 8 | 0 | identical string |
| `product_types` | 8 | 0 | |
| `gtin` → `gtins` | 8 | 0 | scalar ↔ `[scalar]` |
| `price` (micros) | 8 | 0 | `value*1e6 == amount_micros`, currency identical |
| `inStock` (semantic) | 8 | 0 | `availability=='IN_STOCK'` ↔ `=='in stock'` |
| `approved/pending/disapproved` (SHOPPING) | 8 | 0 | `reporting_context=='SHOPPING_ADS'` ↔ `destination=='Shopping'` |
| `custom_label_0..4` | 8 | 0 | underscore rename |

**Conclusion:** the v1 `Product` fully covers every product/status field the ACIT pipeline
reads. The structural changes (status merge, channel removal, enums, micros, renames) are all
**mechanically resolvable** with the derivations above — none drops information the pipeline uses.

> FK note: we can't diff directly against the Ads `performance` table here (no Ads pull in
> `migration_test/`), but the production FK already joins on the **old** `channel` value, and the
> derived v1 `channel` equals the old `channel` for all 8 products — so the FK behavior is preserved.

---

## Step 5 — Gap log

Legend: **C** = consumed downstream (must handle) · **N** = not consumed (safe) · **R** = representation/rename.

| # | Gap | Kind | Downstream consumer | Resolution (Step 6/7) |
|---|-----|------|---------------------|------------------------|
| G1 | **`channel` removed** from the product | C | `main_view` FK (`LOWER(P.channel)=LOWER(A.productChannel)`), targeting matcher, `main_view.P.channel` | **Derive** in Beam: `channel = 'local' if legacy_local else 'online'`; keep a `channel` field on the new proto. Verified 8/8 == old. |
| G2 | **`productstatuses` collection merged** into `Product.product_status` | C (structural) | Beam `CoGroupByKey` products↔statuses join | **Remove the join**; read `product.product_status` inline. Drop the `productstatuses/` ingestion + output dir. |
| G3 | status `destination` → `reporting_context` enum | C/R | `set_product_approved` (filters `'Shopping'`) | Filter `reporting_context == 'SHOPPING_ADS'`; read `*_countries` (snake). Verified. |
| G4 | `availability`/`condition` (+ age_group, gender, …) now **enums** | C/R | `set_product_in_stock` (`'in stock'`), targeting `condition` | Store enum NAME string; compare `'IN_STOCK'`; lower-case `condition` in matcher. Verified. |
| G5 | `price` `{value,currency}` → `{amount_micros,currency_code}` | R | none does price math; schema shape only | New proto `Price{amount_micros int64, currency_code}`. (Views don't read price today.) |
| G6 | `gtin` (scalar) → `gtins` (repeated) | C/R | `main_view.P.gtin` | New proto `gtins` repeated; `main_view` → `gtins[SAFE_ORDINAL(1)]` (or first). |
| G7 | `custom_label0..4` → `custom_label_0..4` | C/R | `main_view` + MEX `custom_label0..4` | Native rename in proto; update the SQL field names. |
| G8 | item-level issue renames: `servability→severity`, `attributeName→attribute`, `destination→reporting_context` | C/R | `disapprovals_view.sql` | New proto field names; update `disapprovals_view`. |
| G9 | attributes nested under `product_attributes` (98-field msg); top-level identity (`offer_id`/`content_language`/`feed_label`) | C (structural) | Beam parse, proto, `main_view.P.product.*` | New `WideProduct`/`Product` proto mirrors v1 nesting; update Beam parse + view paths. |
| G10 | id format `online:en:US:A6` → name `en~US~A6`; `target_country` removed | R | product identity / output key | Key downstream on `(account_id, offer_id)`; `feed_label` already the country dimension. |
| G11 | `channelExclusivity` removed | N | targeting matcher reads it but defaults `MULTI_CHANNEL` | Drop; matcher already treats absence as multichannel. |
| G12 | status `status` (deprecated), status `title`/`link`/`kind` dropped | N | none (`set_product_approved` uses country arrays) | Drop. |
| G13 | product `kind`, `source`, `target_country` dropped | N | none | Drop (`source` ≈ `data_source` resource, not needed). |
| G14 | **new** fields added: `legacy_local`, `data_source`, `version_number`, `base64_encoded_name`, `automated_discounts`; new attributes (`maximum_retail_price`, `sustainability_incentives`, `loyalty_programs`, `carrier_shipping`, …) | N (added) | none yet | Include `legacy_local` (needed for G1); add others to schema selectively / as desired. |

| G15 | product `source` ('api'/'feed'/'crawl') **removed** (v1 has only `data_source` resource name) | C | MEX `OffersUploadedViaApi` metric (offer_list, all_metrics) + `source` column (ml_data) | **No clean v1 equivalent.** Dropped the "products uploaded via API" metric and the `ml_data.source` column. (Discovered during Step 7 — the original gap log assumed `source` was unconsumed.) |

### Blockers
**None.** All consumed fields have a verified v1 equivalent or derivation (except `source` → G15, a dropped metric with no v1 home). The only genuinely
load-bearing transformation is **G1 (derive `channel` from `legacy_local`)**, which is verified
8/8 against the old data and preserves the Ads FK join.

### Decisions this unlocks (to finalize in Step 6)
- **D2 — output shape:** one v1 `Product` per line at `merchant_center/<id>/products/rows.jsonlines`;
  **stop** writing `productstatuses/`; remove the Beam products↔statuses join. ✔ supported.
- **D3 — proto modeling:** rewrite `Product`/`ProductStatus`/`WideProduct` in `schema.proto` to the
  native v1 nesting (`product_attributes`, `product_status`, `Price` micros, enum-name strings,
  `gtins`, `custom_label_N`), **plus a derived `channel`** on `WideProduct` for the FK. Regenerate
  `Products.schema`.
- Downstream SQL edits required: `main_view.sql` (channel kept-but-derived, `gtins`, `custom_label_N`,
  nested attribute paths), `disapprovals_view.sql` (issue renames), 6 MEX files (label/attr paths).
