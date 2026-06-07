# Phase 4 — `shippingsettings` Migration: Understanding & Context

> Grounding doc for the Content API v2.1 → Merchant API **v1 (stable)** migration of the
> **`shippingsettings`** (account-level shipping services) path, end-to-end.
> Tracker: `shippingsettings_migration_plan.md` · Per-file log: `CHANGES_TRACKER.md`.
> This is the **last** resource still on the Content API — once it migrates, the
> `discovery.build('content','v2.1')` client and the whole Content API dependency can be removed.

---

## 1. Current Content API path (what exists today)

### 1.1 Ingestion — `acit/acit.py`
- `shippingsettings` is the **only** remaining member of `_ACIT_ACCOUNT_ADMIN_RESOURCES`
  (`acit.py:243`). It is **admin-gated** (`_ADMIN_RIGHTS` / `ADMIN=true`).
- Pulled by `_pull_standalone_account_resource(acit_mc_output_dir, parent_id, account_id, resource)`
  (`acit.py:281`):
  - builds the **Content API** client `discovery.build('content', 'v2.1', …)` (`acit.py:277`) — the
    **sole** remaining use of the Content API in the repo;
  - calls `shippingsettings.get` per account (`resource_method='get'`, `is_scalar=True`,
    params `{merchantId: parent_id, accountId: account_id}`);
  - wraps each result in the **`{settings, children[]}` envelope** and writes one line to
    `merchant_center/<account_id>/shippingsettings/rows.jsonlines`;
  - **404 is swallowed** ("possible no such setting exists") — accounts without shipping settings
    simply produce no row.
- The MCA roll-down is the same pattern as the old LIA path: an MCA's children each get their own
  per-account file (each file has exactly one entry; `children` is populated when pulled from an MCA).

### 1.2 BQ load — `acit/run_acit.sh` (NO Beam!)
- **Key difference from every prior phase:** `shippingsettings` does **NOT** go through
  Dataflow/Beam (`create_base_tables.py`). It is loaded **directly** to BigQuery:
  - `run_acit.sh:148/159` globs `merchant_center/*/shippingsettings/rows.jsonlines` (raw ingestion
    output, `SOURCES_DIR`) — *not* a Beam sink (`SINKS_DIR`);
  - `run_acit.sh:183` `bq::load`s it into the `shippingsettings` table using the **hand-written**
    schema `acit/schemas/acit/shippingsettings.schema`.
- ⇒ There is **no `convert_shipping_settings` Beam transform** and **no proto message** for shipping.
  `create_base_tables.py` only mentions it in a docstring. So Phase 4 touches **no proto / no Beam**.

### 1.3 Schema — `acit/schemas/acit/shippingsettings.schema` (HAND-WRITTEN)
- Unlike `liasettings.schema`/`Products.schema` (proto-**generated**), this BQ schema is **hand-edited
  JSON**. It must be **hand-rewritten** to match the new native v1 shape — there is no `bq_gen_schemas`
  step for it.
- Current shape: top-level `{children[] , settings}` envelope. `settings` (and each `children[].settings`)
  = `{accountId INT, services[]}`. Each `service` =
  `{deliveryTime{handlingBusinessDayConfig.businessDays[], max/minTransitTimeInDays,
  max/minHandlingTimeInDays, cutoffTime{timezone,minute,hour}}, rateGroups[]{applicableShippingLabels[],
  name, mainTable{name, rows[].cells[].flatRate{currency,value FLOAT}, rowHeaders.prices[], columnHeaders.prices[]},
  singleValue.flatRate{currency,value FLOAT}}, eligibility, shipmentType, currency, deliveryCountry, active, name}`.

### 1.4 Consumers — MEX SQL (read the `shippingsettings` table)
| File | Uses |
|------|------|
| `extensions/merchant_excellence/account_list.sql` (L56–108) | `AllShippingData` (unions standalone `settings` + `children[].settings`) → `AccountLevelShipping` → 4 booleans |
| `extensions/merchant_excellence/all_metrics.sql` (L89–139) | identical `AllShippingData`/`AccountLevelShipping` block |
| `extensions/merchant_excellence/offer_list.sql` (L140–190) | identical block |
| `extensions/merchant_excellence/ml_data.sql` (L72–74) | only `ARRAY_LENGTH(S.settings.services) > 0 AS has_account_level_shipping` |
| `extensions/merchant_excellence/admin_tables.sql` (L47–…) | `CREATE TABLE shippingsettings (...)` DDL contract (mirrors the hand-written schema) |

### 1.5 The 4 account-level shipping booleans (the load-bearing output)
Derived per `merchant_id` (= `settings.accountId`) in `AccountLevelShipping`:
1. **`has_account_level_shipping`** — `ARRAY_LENGTH(services) > 0`.
2. **`has_account_level_shipping_speed`** — EXISTS a service whose `deliveryTime` has **all four**
   `min/maxTransitTimeInDays` + `min/maxHandlingTimeInDays` NOT NULL.
3. **`has_account_level_fast_shipping`** — EXISTS a service with
   `maxTransitTimeInDays + maxHandlingTimeInDays <= 3` (both not null).
4. **`has_account_level_free_shipping`** — EXISTS a `rateGroups[].mainTable.rows[].cells[].flatRate.value = 0`
   **OR** a `rateGroups[].singleValue.flatRate.value = 0`.

These 4 booleans are the **only** thing downstream actually consumes — the migration must keep them
correct. (Everything else in the schema is carried for completeness.)

---

## 2. New Merchant API v1 path (target)

### 2.1 Endpoint / client
- v1 has **no `shippingsettings` REST resource with a roll-down `list`**. Shipping config is the
  **`ShippingSettings`** resource — a **singleton per account**:
  `ShippingSettingsServiceClient.get_shipping_settings(name="accounts/{account_id}/shippingSettings")`.
- Client lives in **`google-shopping-merchant-accounts`** (`merchant_accounts_v1`) — **already
  installed** (v1.5.0, the Phase-1/Phase-3 dependency). **NO new pip dependency.**
- No MCA aggregation: like LIA, we **fan out per (sub/standalone)account** ourselves and drop the
  `{settings, children[]}` envelope; MEX recovers MCA→child from the migrated `accounts` table.

### 2.2 Native v1 `ShippingSettings` shape (introspected)
```
ShippingSettings {
  name                                  # accounts/{id}/shippingSettings (drop / derive account_id)
  services[] {
    service_name                        # was service.name
    active
    delivery_countries[]                # was service.deliveryCountry (STRING → REPEATED)
    currency_code                       # was service.currency
    delivery_time {
      min_transit_days                  # was minTransitTimeInDays
      max_transit_days                  # was maxTransitTimeInDays
      min_handling_days                 # was minHandlingTimeInDays
      max_handling_days                 # was maxHandlingTimeInDays
      cutoff_time { hour, minute, time_zone }       # was cutoffTime{…, timezone}
      handling_business_day_config.business_days[]  # enum Weekday (was STRING days)
      transit_business_day_config.business_days[]   # NEW
      transit_time_table / warehouse_based_delivery_times[]  # NEW (not consumed)
    }
    rate_groups[] {
      applicable_shipping_labels[]
      name
      single_value  { flat_rate { amount_micros INT64, currency_code }, no_shipping, … }  # a Value
      main_table {
        name
        rows[].cells[]  # each cell is a Value → cell.flat_rate.amount_micros / currency_code
        row_headers / column_headers { prices[]{amount_micros,currency_code}, weights[], … }
      }
      subtables[] / carrier_rates[]     # NEW (not consumed)
    }
    shipment_type                       # enum ShipmentType (was STRING)
    minimum_order_value / minimum_order_value_table / store_config / loyalty_programs[]  # NEW
  }
  warehouses[] { … }                    # NEW (not consumed)
  etag                                  # NEW
}
```

### 2.3 The 4 booleans re-expressed in v1 terms
1. `has_account_level_shipping` — `ARRAY_LENGTH(services) > 0` *(unchanged)*.
2. `has_account_level_shipping_speed` — all of `delivery_time.min_transit_days`,
   `max_transit_days`, `min_handling_days`, `max_handling_days` NOT NULL.
3. `has_account_level_fast_shipping` — `delivery_time.max_transit_days + delivery_time.max_handling_days <= 3`.
4. `has_account_level_free_shipping` — `rate_groups[].main_table.rows[].cells[].flat_rate.amount_micros = 0`
   **OR** `rate_groups[].single_value.flat_rate.amount_micros = 0`.
   ⚠ **Units change:** old `flatRate.value` was a **FLOAT in major units**; new `flat_rate.amount_micros`
   is **INT64 micros**. The `= 0` test is still correct for the *free* case, but the field path + type change.

---

## 3. Key changes vs old (preview of the gap log)
- **S1** `{settings, children[]}` envelope → **flat per-account** `{account_id, …native ShippingSettings…}`
  (drop `children`; MEX recovers MCA→child from `accounts`). *(mirrors LIA D2)*
- **S2** snake_case + nested renames: `service.name`→`service_name`, `currency`→`currency_code`,
  `deliveryCountry`(STRING)→`delivery_countries[]`(ARRAY), `deliveryTime.*TimeInDays`→`delivery_time.*_days`,
  `cutoffTime.timezone`→`cutoff_time.time_zone`, `rateGroups`→`rate_groups`, `mainTable`→`main_table`,
  `singleValue`→`single_value`, `applicableShippingLabels`→`applicable_shipping_labels`.
- **S3** **free-shipping rate**: `flatRate.{currency,value FLOAT}` → `flat_rate.{currency_code, amount_micros INT64}`;
  table **cells are now `Value` messages** (`cells[].flat_rate`), not a bare `flatRate`.
- **S4** enums as STRING: `shipmentType`→`shipment_type` (enum), `businessDays`→`business_days` (enum Weekday).
- **S5** `eligibility` (old service field) — **no v1 equivalent** → dropped (not consumed by MEX).
- **S6** new v1-only fields (`warehouses`, `etag`, `minimum_order_value`, `store_config`,
  `loyalty_programs`, `subtables`, `carrier_rates`, transit tables) — not consumed; keep a minimal subset
  in the hand-written schema.
- **S7** no proto / no Beam: schema is **hand-written**; ingestion writes the final shape directly;
  `bq::load` path/glob unchanged.

## 4. Open questions to resolve in Steps 2–5 (against real test data)
- **Q1** Does the test account's free service render as `single_value.flat_rate` or via
  `main_table…cells[].flat_rate`? (Verify which branch of the OR fires live.)
- **Q2** Confirm `delivery_countries[]` (plural) — does the old single `deliveryCountry` map 1:1 to a
  one-element array? (Not consumed, but document.)
- **Q3** Confirm `get_shipping_settings` returns an **empty `services[]`** (not `NotFound`) for an
  account with no shipping configured, so the "no row" behavior parallels the old 404 swallow.
