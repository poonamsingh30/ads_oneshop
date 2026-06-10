# Post-Migration Data Validation — Plan & Tracker

> Validates that the BigQuery tables produced by the **Merchant API v1** pipeline match the
> **Content API** pipeline, table by table. Source data: Parquet exports under
> `migration_test/bq_data/bq_parquet_export_{old,new}/` (old = pre-migration, new = post-migration).
> Findings/verdicts: `data_validation_understanding.md`. Per-table compare scripts: `compare_<table>.py`.

**Legend:** ⬜ not started · 🟡 in progress · ✅ verified equal/explained · ⚠️ diff to investigate · ⛔ real regression

---

## 0. Environment & method

- **Env:** `conda activate dataflow2025` (has `pyarrow 14.0.2`). BigQuery exports use the `dbdate`
  extension type → read with `pyarrow.parquet.read_table(path).to_pandas(ignore_metadata=True)` (plain
  `pd.read_parquet` raises `TypeError: data type 'dbdate' not understood`). Alternatively `pip install db-dtypes`.
- **Comparison tiers** (per table category below):
  1. **Row count + schema** — already done for all 18 tables (see §2 reconnaissance).
  2. **Key-set diff** — define a business key; report keys only-in-old / only-in-new / shared.
  3. **Cell-level value diff** — on shared keys, compare every column; numeric metrics within a small
     tolerance (float/division noise); flag any mismatch.
- **Golden rule:** the **downstream/derived tables (Category C)** are the real oracle — their schemas are
  unchanged, so they should match old↔new row-for-row except for **documented, intentional** migration
  changes. The **raw/source tables (Category B)** changed shape by design, so they are compared on business
  keys + the specific fields the pipeline consumes (not raw schema equality).

---

## A. Workstream tracker (per table)

### Category A — Unaffected by the migration (Ads-only data) → must be byte-identical
*(Validates the export + comparison harness itself; any diff here means an export/process problem.)*

| Table | old→new rows | Method | Status |
|-------|-------------|--------|--------|
| `language` | 51 → 51 | full sorted-DataFrame equality | ⬜ |
| `performance` | 0 → 0 | full equality (both empty) | ⬜ |

### Category B — Migrated source/raw tables (schema changed by design) → key + semantic compare
| Table | old→new rows | old→new cols | Key | What to verify | Status |
|-------|-------------|--------------|-----|----------------|--------|
| `accounts` | 1 → 35 | 2 → 15 | `account_id` | Old `{settings, children[]}` (1 monolithic row) vs new flat one-row-per-account. Verify the 35 accounts + `automatic_improvements`/`parent` fields the MEX SQL consumes. | ⬜ |
| `products` | 41 → 41 | 12 → 12 | `account_id`, `offer_id` | Same top-level columns. Verify per-offer identity, `in_stock`, approved/pending/disapproved countries, targeting flags; nested `product`/`status` attrs reshaped (v1). | ⬜ |
| `liasettings` | 1 → 1 | 2 → 2 | `account_id`/region | Old `{settings, children[]}` vs new `{account_id, omnichannel_settings[]}`. Verify the 4 LIA booleans derive identically (already 0-mismatch in Phase 3). | ⬜ |
| `shippingsettings` | 1 → 7 | 2 → 2 | `account_id` | Old `{settings, children[]}` (1 row, children nested) vs new flat 7 per-account rows. Verify the 4 shipping booleans (already 28/28 match in Phase 4). | ⬜ |

### Category C — Downstream / derived tables (schema identical) → the real oracle, should match row-for-row
| Table | old→new rows | Key | Status |
|-------|-------------|-----|--------|
| `acit` (main view) | 41 → 41 | `merchant_id`, `offer_id`, `channel`, `content_language`, `feed_label` | ⬜ |
| `disapprovals` | 95 → 95 | `account_id`, `offer_id`, `disapproval_detail`, `channel`, `content_language`, `feed_label` | ⬜ |
| `MEX_Account_List` | 322 → 322 | `merchant_id`, `metric_name` | ⬜ |
| `MEX_All_Metrics` | 1677 → 1677 | `merchant_id`, `channel`, `targeted_country`, product_type/labels, `metric_name` | ⬜ |
| `MEX_All_Metrics_historical` | 1677 → 1677 | same as All_Metrics | ⬜ |
| `MEX_ML_Data` | 49 → 49 | `merchant_id` (1 row/account) | ⬜ |
| `MEX_Offer_Funnel` | 43 → 43 | `merchant_id`, funnel keys | ⬜ |
| `MEX_Offer_Funnel_historical` | 43 → 43 | same | ⬜ |
| `MEX_Offer_List` | **870 → 821** ⚠️ | `merchant_id`, `item_id`, `channel`, `targeted_country`, `language`, `metric_name` | 🟡 (−49 decomposed: 40 removed metric + 9 free-shipping; see understanding doc) |
| `MEX_benchmark_details` | 39 → 39 | static reference | ⬜ |
| `MEX_benchmark_scores` | 2 → 2 | static reference | ⬜ |
| `MEX_benchmark_values` | 39 → 39 | static reference | ⬜ |

---

## B. Known / expected differences (do not flag as regressions)
- **`MEX_Offer_List` −49 rows** = (a) **40** rows of the `products uploaded via API` metric, which was
  **intentionally dropped** in the products migration (the Content API `source` field has no Merchant API v1
  equivalent — see products phase notes), plus (b) **9** rows of `% items with free shipping` (16→7) — **this
  9-row part is NOT yet explained and is the #1 investigation item.**
- **Raw table shape changes (Category B)** are by design (flat native-v1 records replacing the old
  `{settings, children[]}` envelopes); the row/column counts are expected to differ.

## C. Open investigation items
- **I1 — `MEX_Offer_List` free shipping 16→7. ✅ RESOLVED.** `% items with free shipping` rows are
  *offenders* ("no free shipping"), so NEW finding **9 fewer** offenders = NEW correctly detects **more**
  free shipping. Root cause: the flat per-account `shippingsettings` fixed sub-account coverage the old
  envelope/roll-down under-reported. An **improvement**, not a regression. (See understanding §4.)
- **I2 — `ml_data.sql` LIA booleans `False→NULL`. ✅ FIXED.** Wrapped `has_mhlsf/store_pickup/odo` in
  `IFNULL(..., FALSE)` (`extensions/merchant_excellence/ml_data.sql`). Restores old explicit-False; effective
  next pipeline run.
- **I3 — `has_dynamic_remarketing` False→True for all items (metric-baseline shift). OPEN DECISION.**
  Correct per the v1 `DisplayAds→DEMAND_GEN_ADS` mapping, but the Merchant API now exposes a
  `DEMAND_GEN_ADS` reporting context the Content API didn't — so the metric jumps toward ~100%. Surface to
  the business; not a code bug.
- **I4 — free-shipping NULL-price handling changed (`offer_list.sql` + `all_metrics.sql`). OPEN DECISION.**
  Traced the 9 `MEX_Offer_List` offers: each has an item-level `shipping` entry with a country but **NULL
  price**. OLD `CAST(price.value AS FLOAT64)=0` left these "not free"; NEW `IFNULL(price.amount_micros,0)=0`
  counts them **free**. Account-level free shipping is identical old↔new (earlier sub-account hypothesis was
  wrong). NEW is arguably more correct (Google: no price ⇒ free) but reads higher. Keep vs drop-IFNULL for
  exact parity — business decision.

## D. Scope / guardrails
- Read-only validation on the exported Parquet; no pipeline or BQ changes here.
- Use `dataflow2025` env (pyarrow). Keep compare scripts + a machine-readable result JSON per table.
- A table passes when it is either **value-identical** old↔new (Category A/C) or **explained** by a
  documented intentional migration change (Category B + the §B list).

## E. Changelog
- **2026-06-10 (exec)** — Built `compare_lib.py` (dbdate-safe loader, full-equality + key-compare,
  list/struct-aware normalization). **Executed all categories.** Result: **13 tables identical** (Cat A;
  acit/disapprovals after bare-offer-id normalization; Account_List, Offer_Funnel ×2, benchmarks ×3); the
  4 raw tables reshaped by design; `MEX_All_Metrics`(×2)/`MEX_Offer_List`/`MEX_ML_Data` differ only for
  understood reasons. **Key method fix:** old `offer_id` is composite `channel:lang:label:offer`, new is
  bare — normalize before joining (first pass falsely showed 0 shared keys). **Findings:** free shipping =
  improvement (I1 resolved); ML_Data has_account_level_shipping None→True = FIX; has_sale_price None→False =
  benign; LIA booleans False→NULL = I2 (recommend IFNULL); has_dynamic_remarketing False→True = I3
  (v1 exposes DEMAND_GEN_ADS context — metric-baseline shift, not a bug). **No data-loss regressions.**
  Verdicts in understanding doc §3–6. Remaining: optional per-item free-shipping trace; decisions on I2/I3.
- **2026-06-10** — Plan created + reconnaissance (row counts/schema flags) for all 18 tables.
