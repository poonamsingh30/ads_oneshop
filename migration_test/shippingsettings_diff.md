# Phase 4 · Steps 4–5 — `shippingsettings` Old vs New: Diff & Gap Log

> Reconciliation of the Content API v2.1 baseline against the Merchant API v1 `ShippingSettings`
> fetch, plus the finalized gap log. Driver: `compare_shippingsettings.py`
> (→ `compare_shippingsettings_result.json`). Field map: `shippingsettings_api_v1_mapping.md`.

## Step 4 — Comparison result: ✅ PASS

The only thing downstream consumes is the **4 account-level shipping booleans**. Derived from BOTH
shapes per account and compared:

| account | has | speed | fast | free | all match |
|---|---|---|---|---|---|
| 120131628 | T/T | T/T | F/F | F/F | ✅ |
| 122456618 | T/T | T/T | F/F | F/F | ✅ |
| 215174218 | T/T | T/T | F/F | F/F | ✅ |
| 385740737 | T/T | F/F | F/F | T/T | ✅ |
| 502263348 | T/T | T/T | F/F | T/T | ✅ |
| 606423213 | T/T | T/T | F/F | T/T | ✅ |
| 5354028611 | T/T | F/F | F/F | T/T | ✅ |

**7/7 accounts key-matched · 28/28 boolean checks matched · 0 mismatch · 0 old-only/new-only keys.**

**Coverage quality (much stronger than Phase 3 LIA):**
- `has` — True on all 7 (every account has services).
- `speed` — **both branches exercised live** (False on 385740737 & 5354028611 which lack transit days;
  True on the other 5).
- `free` — **both branches exercised live** (True on the 4 zero-rate accounts; False on the 3 paid ones).
  This is the load-bearing micros change (S3) and it is **value-verified**, not just spec'd.
- `fast` — False on all 7 (no service has `maxTransit + maxHandling ≤ 3`). The True-branch is **not**
  exercised by the data (assumption **A1**); it is a pure field-rename (`*TimeInDays`→`*_days`), low risk.

## Step 5 — Gap log (finalized) · **No blockers**

| # | Gap | Resolution | Consumed? | Verified |
|---|-----|-----------|-----------|----------|
| **S1** | `{settings, children[]}` envelope + MCA roll-down `list` | Drop envelope → **flat per-account** `{account_id, services[], …}`; v1 has no roll-down, fan out per (sub/standalone)account; MEX recovers MCA→child from the migrated `accounts` table (D2) | structural | ✅ 7/7 parity |
| **S2** | snake_case + nested renames (`service.name`→`service_name`, `currency`→`currency_code`, `deliveryTime.*TimeInDays`→`delivery_time.*_days`, `cutoffTime.timezone`→`cutoff_time.time_zone`, `rateGroups`→`rate_groups`, `mainTable`→`main_table`, `singleValue`→`single_value`, `applicableShippingLabels`→`applicable_shipping_labels`) | rename in the fetcher output + hand-written schema + SQL | speed/free fields **yes** | ✅ |
| **S3** | **free-shipping rate**: `flatRate.value` FLOAT/string (major units) → `flat_rate.amount_micros` INT64 (**micros**); table `cells[]` become `Value` messages (`cells[].flat_rate`) | SQL: `flat_rate.amount_micros = 0`. **Q1 resolved live:** the `0` is **present** in `to_dict` output, so `= 0` is correct (not NULL) | **yes (free)** | ✅ value-verified on 4 free accts |
| **S4** | enums as STRING: `shipmentType`→`shipment_type` (enum); `businessDays`→`business_days` (enum `Weekday`) | `to_dict(use_integers_for_enums=False)` → enum NAMEs; schema STRING | no | ✅ |
| **S5** | `eligibility` (old service field, e.g. `'All scenarios'`) — **no v1 equivalent** | **dropped** | no | ✅ n/a |
| **S6** | v1-only new fields (`warehouses`, `etag`, `minimum_order_value`, `store_config`, `loyalty_programs`, `subtables`, `carrier_rates`, transit tables, `transit_business_day_config`) | not consumed; keep a minimal subset (`services` + optional `warehouses`/`etag`) in the hand-written schema | no | ✅ |
| **S7** | no proto / no Beam for shipping | schema is **hand-written**; ingestion writes the final shape; `bq::load` glob/path unchanged (no `bq_gen_schemas`, no `create_base_tables`) | — | ✅ |
| **S8** | **per-country service merge**: identical-except-country old services collapse into one v1 service with `delivery_countries[]` (e.g. `502263348` 2→1) | accept native v1 behavior; **boolean-invariant** (all 4 booleans are `EXISTS`-across-services) | no | ✅ no boolean impact |
| **S9** | MCA/aggregator not queryable | `get_shipping_settings` on the MCA → `PermissionDenied` → **skip aggregators**; old MCA self was a 404 anyway (no data lost) | structural | ✅ |
| **S10** | account with no settings | old swallowed **404**; v1 → `NotFound` (or empty `services`) → **write no row** (same outcome; LEFT JOIN downstream defaults the booleans false) | structural | ✅ handled |

## Assumptions (un-verifiable on this test data)
- **A1** — `has_account_level_fast_shipping` True-branch: no live account has `max_transit_days +
  max_handling_days ≤ 3`. Correct by field-rename + arithmetic only.
- **A2** — `main_table` free-shipping branch: all 7 accounts use `single_value`; none use `main_table`.
  Correct by spec only.

## Direction locked for Steps 6–7
- **D2 — Record shape:** flat per-account `{account_id INT64, services[], warehouses[]?, etag?}` to
  `merchant_center/<id>/shippingsettings/rows.jsonlines` (glob unchanged). Drop `{settings,children[]}`.
- **D3 — Schema:** hand-rewrite `acit/schemas/acit/shippingsettings.schema` to the flat native v1 shape
  (snake_case, `amount_micros` INT64, enums STRING). No `schema.proto` / `create_base_tables` change.
- **Free-shipping SQL:** `single_value.flat_rate.amount_micros = 0 OR main_table…cells[].flat_rate.amount_micros = 0`
  (the `= 0` form is verified correct; keep the `flat_rate IS NOT NULL` guard so a `no_shipping`/absent rate
  can't error). **No blockers — proceed to end-to-end main-code changes.**
