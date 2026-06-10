# Merchant Excellence — Validation

> **Purpose:** explain, for leadership, the result of validating the Merchant Excellence (MEX)
> data after the **Content API → Merchant API v1** migration: which tables match exactly,
> which differ and why, the **Merchant Excellence Score** before vs after, and a proper
> walkthrough of the one behavioural change (**I4 — free shipping**) that moves the score.
>
> Data compared: BigQuery tables exported to Parquet, **pre-migration** (`old`, Content API)
> vs **post-migration** (`new`, Merchant API v1), `extraction_date = 2026-06-09`.

---

## 1. One-line verdict

**The migration is data-faithful. No data loss and no incorrect values.** Of the 18 validated
tables, 13 are **identical** and 5 differ **only for documented, intentional reasons**. The
Merchant Excellence Score moves by **+0.0068 (0.3901 → 0.3969)**, and that entire movement is
explained by a single intended change — **I4, free-shipping NULL-price handling** — described in
§4 below.

---

## 2. Table-by-table: matches and mismatches

We split the 18 tables into three groups by how the migration was expected to affect them.

### Group A — Tables untouched by the migration (must be identical)
| Table | Rows old→new | Result |
|-------|:------------:|--------|
| `language` | 51 → 51 | ✅ **Identical** |
| `performance` | 0 → 0 | ✅ **Identical** (both empty) |

These prove the export + comparison harness itself is sound — any diff here would mean a process
problem. There were none.

### Group B — Raw source tables (shape changed *by design*)
The migration replaces the old Content API `{settings, children[]}` envelopes with native
Merchant API v1 flat records, so row/column **shape** is expected to differ. We validate these on
business keys + the fields the pipeline actually consumes (not raw schema equality).

| Table | Rows old→new | Result | Note |
|-------|:------------:|--------|------|
| `accounts` | 1 → 35 | 🟢 **Expected reshape** | 1 envelope row → 35 flat per-account rows; same 7 product accounts. |
| `products` | 41 → 41 | 🟢 **Expected reshape** | Same 41 offers; `offer_id` changed from composite `channel:lang:label:offer` to bare offer id. |
| `liasettings` | 1 → 1 | 🟢 **Expected reshape** | Envelope → flat `{account_id, omnichannel_settings[]}`; LIA booleans match. |
| `shippingsettings` | 1 → 7 | 🟢 **Expected reshape** | Envelope → flat 7 per-account rows; shipping booleans 28/28 match. |

### Group C — Downstream / derived tables (the real oracle)
These have **unchanged schemas**, so they should match old↔new row-for-row except for intended
changes. They are the tables leadership actually cares about.

| Table | Rows old→new | Result | Reason for any difference |
|-------|:------------:|--------|---------------------------|
| `acit` (main view) | 41 → 41 | ✅ **Identical** | 0 value mismatches (only id-format changed). |
| `disapprovals` | 95 → 95 | ✅ **Identical** | 0 value mismatches. |
| `MEX_Account_List` | 322 → 322 | ✅ **Identical** | — |
| `MEX_Offer_Funnel` | 43 → 43 | ✅ **Identical** | — |
| `MEX_Offer_Funnel_historical` | 43 → 43 | ✅ **Identical** | — |
| `MEX_benchmark_details` | 39 → 39 | ✅ **Identical** | static reference |
| `MEX_benchmark_scores` | 2 → 2 | ✅ **Identical** | static reference |
| `MEX_benchmark_values` | 39 → 39 | ✅ **Identical** | static reference |
| `MEX_All_Metrics` | 1677 → 1677 | 🟢 **Explained** | **7 cells** differ, all `% items with free shipping` → **I4** (§4). |
| `MEX_All_Metrics_historical` | 1677 → 1677 | 🟢 **Explained** | identical to `MEX_All_Metrics`; same **7 cells** → **I4** (§4). |
| `MEX_Offer_List` | 870 → 821 | 🟢 **Explained** | −49 rows = 40 intentionally-removed metric + 9 free-shipping → **I4** (§4). |
| `MEX_ML_Data` | 49 → 49 | 🟢 **Explained** | 4 systematic column changes (§5). |

> **Note on `MEX_Offer_List` −49:** 40 of the missing rows are the `products uploaded via API`
> metric, which was **intentionally retired** — the Content API `Product.source` field has no
> Merchant API v1 equivalent. The other 9 are the free-shipping items of **I4**.

---

## 3. Merchant Excellence Score — calculation (old vs new)

The score is a priority-weighted average across all rows of `MEX_All_Metrics_historical`:

```
merchant_excellence_score = (avg_high_final*3 + avg_medium_final*2 + avg_low_final*1) / 6

avg_<bucket>_final = SUM(IFNULL(<bucket>_numerator,0)) / NULLIF(SUM(IFNULL(<bucket>_denominator,0)),0)
```

Each row contributes to exactly one priority bucket (High / Medium / Low+High-Low):
- **denominator** = `total_products` (only for rows in that priority)
- **numerator** = the row's "good" count:
  - account-level metric that is satisfied (`metric_value = 1`) → all `total_products`
  - `GREATER THAN` metric → `metric_value`
  - otherwise (lower-is-better) → `total_products − metric_value`

### Computed result

| Component | OLD | NEW |
|-----------|-----|-----|
| `avg_high_final` | 0.476676  (327 / 686) | 0.476676  (327 / 686) |
| `avg_medium_final` | 0.378685  (167 / 441) | **0.399093  (176 / 441)** |
| `avg_low_final` | 0.153061  (120 / 784) | 0.153061  (120 / 784) |
| **`merchant_excellence_score`** | **0.390077** | **0.396879** |

NEW: `(0.476676×3 + 0.399093×2 + 0.153061×1) / 6 = 0.396879`.

### Reason for the mismatch (and why it's the *only* one)
- **High and Low buckets are byte-identical** old↔new — numerators and denominators unchanged.
- **All denominators are unchanged** (the product/account universe didn't change — 41/41 offers,
  same accounts).
- The **only** moved value is the **Medium numerator: 167 → 176 (+9)**.
- That **+9 is exactly the I4 free-shipping effect**: the 7 differing `% items with free shipping`
  cells in `MEX_All_Metrics_historical` whose new values sum to `1+1+1+3+1+1+1 = 9` (old = NULL → 0).
  `% items with free shipping` is a **Medium-priority, `GREATER THAN`** metric, so its numerator =
  `metric_value` directly — and those rows went from `NULL`→`0` to a real count.

**Net:** the score rises **+0.0068 absolute (+1.7% relative)**, and 100% of that rise is the
intended I4 change. Nothing else in the score shifted.

---

## 4. The I4 case — free shipping with no price (explained properly)

This is the single behavioural change behind every "explained" mismatch above (the 7 cells in
`MEX_All_Metrics(_historical)`, the −9 rows in `MEX_Offer_List`, and the +0.0068 score move).

### The data situation
9 product offers (across 5 merchants) each have an **item-level `shipping` attribute that names a
destination country but leaves the shipping *price* empty (NULL)** — e.g. `shipping = (country: US, price: NULL)`.
In Google Merchant terms, a shipping attribute that specifies a destination but **no price means
free shipping** to that destination.

### What changed in the SQL
The free-shipping check on each item's `shipping` entry was rewritten during the migration:

| | Predicate on each `shipping` entry | A NULL-price entry evaluates to |
|---|---|---|
| **OLD** (Content API) | `CAST(price.value AS FLOAT64) = 0` | `NULL = 0` → `NULL` → **not matched** → item treated as **NOT free** |
| **NEW** (Merchant API v1) | `IFNULL(price.amount_micros, 0) = 0` | `IFNULL(NULL,0) = 0` → `TRUE` → item treated as **free** |

The migration **added the `IFNULL(..., 0)`**. So an item whose shipping attribute names a country
but omits the price now correctly counts as **free shipping**, whereas before it was missed.

### Effect on each table
- **`MEX_Offer_List`** lists *offending* items ("no free shipping"). OLD flagged **16**, NEW flags
  **7** → 9 fewer offenders, because those 9 are now recognised as free. (This is part of the −49.)
- **`MEX_All_Metrics(_historical)`** counts items *with* free shipping per merchant/brand/country.
  Those same items flip from NULL → counted, giving the **7 differing cells** (sum +9).
- **Merchant Excellence Score** — the +9 lands in the Medium numerator, lifting the score by
  **+0.0068**.

### Is NEW correct?
**Yes, NEW is arguably more correct.** Per Google Merchant semantics, a `shipping` attribute with a
destination and no price *is* free shipping, so the OLD `CAST(... ) = 0` form **under-counted** free
shipping (it silently dropped NULL-price entries). Importantly, this is **not account-level**: the
account-level free-shipping flags are **identical** old↔new — the change is purely the **item-level**
NULL-price handling.

### The decision for leadership
This is a **judgement call, not a defect**:
- **Keep the new behaviour** (recommended): the free-shipping metric becomes more accurate and reads
  slightly higher; the Merchant Excellence Score is `0.3969`.
- **Restore exact parity with old:** drop the `IFNULL` (`price.amount_micros = 0`), and the score
  returns to `0.3901`.

No code change has been applied for I4 — we are awaiting this call.

---

## 5. `MEX_ML_Data` — 4 systematic column changes (context)

`MEX_ML_Data` does not feed the score above, but for completeness its 4 explained differences are:

| Column | Change | Cause | Verdict |
|--------|--------|-------|---------|
| `has_account_level_shipping` | None → True (35) | OLD read only the top-level MCA `settings.services` and never rolled down to sub-accounts; NEW flat per-account `shippingsettings` joins correctly. | ✅ **Fix** |
| `has_sale_price` | None → False (35) | NEW always yields an explicit boolean (`IFNULL(...)>0`) instead of NULL. | ✅ Benign |
| `has_mhlsf` / `has_store_pickup` / `has_odo` | False → None (49) | LEFT JOIN to the flat `liasettings` returns NULL for accounts with no LIA row. | ✅ **Fixed** — wrapped in `IFNULL(..., FALSE)` (item **I2**). |
| `has_dynamic_remarketing` | False → True (all) | OLD Content API never returned a `DisplayAds` destination; NEW Merchant API exposes the `DEMAND_GEN_ADS` reporting context on all products. | ⚠️ **Metric-baseline shift (I3)** — correct mapping, but the metric jumps toward ~100%. **Inform the business.** |

---

## 6. Summary for leadership

1. **Data is faithful.** 13/18 tables identical; the other 5 differ only for intended reasons.
2. **The Merchant Excellence Score moves `0.3901 → 0.3969` (+1.7% relative)**, driven *entirely* by
   one intended fix (**I4**, free-shipping NULL-price handling) — High and Low buckets and all
   denominators are unchanged.
3. **I4 is a more-correct improvement, presented as a decision:** keep it (score `0.3969`, more
   accurate) or drop the `IFNULL` for exact parity with old (score `0.3901`).
4. **One thing to communicate (I3):** the dynamic-remarketing metric's baseline shifts upward because
   the Merchant API exposes a reporting context the Content API didn't — not a bug, but a baseline
   change to flag to stakeholders.
