# Phase 4 · Step 2 — `shippingsettings` → Merchant API v1 `ShippingSettings`: Field Map

> Authoritative old→new field map for the migration, **introspected** from
> `merchant_accounts_v1.ShippingSettings` and **grounded** on the real Step-1 baseline
> (MCA `120436857`, 7 children with services). Live verification of the open items happens in Step 3.

---

## 0. Endpoint / identity change

| | Old (Content API v2.1) | New (Merchant API v1) |
|---|---|---|
| Resource | `shippingsettings` (get / list) | `ShippingSettings` (singleton per account) |
| Client | `discovery.build('content','v2.1').shippingsettings` | `merchant_accounts_v1.ShippingSettingsServiceClient` |
| Read call | `get(merchantId, accountId)` (scalar) + `list(merchantId)` roll-down | `get_shipping_settings(name="accounts/{id}/shippingSettings")` |
| MCA roll-down | `list` returns all children's settings | **none** — fan out per (sub/standalone)account ourselves |
| Identity | `settings.accountId` (INT) | resource `name` = `accounts/{id}/shippingSettings` → derive `account_id` |
| Package | (Content API) | **`google-shopping-merchant-accounts==1.5.0` — already installed, no new dep** |

The old `{settings, children[]}` envelope is **dropped** → flat per-account record
`{account_id, services[], …}`. MEX recovers the MCA→child relation from the migrated `accounts` table
(same decision D2 as LIA).

---

## 1. Step-1 baseline (the comparison oracle)

MCA `120436857` self → **404** (no settings). 7 children, each with services:

| account | services | notable | has | speed | fast | free |
|---|---|---|---|---|---|---|
| 120131628 | 1 (US) | singleValue flat `5` USD; transit 1–5, handling 0–2 | ✅ | ✅ | ❌ | ❌ |
| 122456618 | 2 (BR, US) | flat `5`; transit 1–2, handling 0–2 | ✅ | ✅ | ❌ | ❌ |
| 215174218 | 1 (US) | flat `1`; transit 2–4, handling 0–2 | ✅ | ✅ | ❌ | ❌ |
| 385740737 | 1 (US) | flat `0` (**free**); transit **None**, handling 1–1; `cutoffTime` set | ✅ | ❌ | ❌ | ✅ |
| 502263348 | 2 (US, IL) | flat `0` (**free**); transit 1–3, handling 2–7 | ✅ | ✅ | ❌ | ✅ |
| 606423213 | 1 (NL) | flat `0` (**free**); transit 0–3, handling 0–1 | ✅ | ✅ | ❌ | ✅ |
| 5354028611 | 1 (NL) | flat `0` (**free**); transit/handling all **None** | ✅ | ❌ | ❌ | ✅ |

Coverage: `has` always True; `speed` and `free` each vary True/False (good); **`fast` is False for all 7**
(no service has `maxTransit+maxHandling ≤ 3`) — so the *fast* True-branch is unverifiable on this data
(documented limitation; logic is a straight field-rename so risk is low). All rate groups here use
**`singleValue.flatRate`**; **no account uses `mainTable`** → the table-cell free-shipping branch is also
unverified live (kept for completeness). Oracle saved to `old_shippingsettings/_oracle_bools.json`.

Notable old-side quirk: `flatRate.value` is a **JSON string** (`"5"`, `"0"`) though the BQ schema types it
FLOAT (BQ coerces). In v1 it becomes an **INT64 micros** field.

---

## 2. Field map (old → new), consumer-relevant fields **bold**

### 2.1 Envelope / identity
| Old | New | Notes |
|---|---|---|
| `settings.accountId` (INT) | derive `account_id` from resource `name` | S1: stamp `account_id` on the flat record |
| `{settings, children[]}` | flat per-account `{account_id, services[], …}` | S1: drop envelope; no roll-down in v1 |
| — | `name`, `etag`, `warehouses[]` | new; `name`/`etag` droppable, `warehouses` not consumed |

### 2.2 `services[]` (service-level)
| Old `services[].…` | New `services[].…` | Notes |
|---|---|---|
| `name` | `service_name` | rename |
| **`active`** | **`active`** | unchanged (bool) |
| `deliveryCountry` (STRING) | `delivery_countries[]` (REPEATED STRING) | S2: scalar→array; not consumed |
| `currency` | `currency_code` | rename; not consumed |
| `shipmentType` (`'delivery'`) | `shipment_type` (enum `DELIVERY`/`LOCAL_DELIVERY`/`COLLECTION_POINT`) | S4: string→enum NAME |
| `eligibility` (`'All scenarios'`) | **— none —** | **S5: dropped (no v1 equivalent)**; not consumed |

### 2.3 `services[].deliveryTime` → `services[].delivery_time`  (**drives `speed` + `fast`**)
| Old | New | Notes |
|---|---|---|
| **`minTransitTimeInDays`** | **`min_transit_days`** | rename |
| **`maxTransitTimeInDays`** | **`max_transit_days`** | rename |
| **`minHandlingTimeInDays`** | **`min_handling_days`** | rename |
| **`maxHandlingTimeInDays`** | **`max_handling_days`** | rename |
| `cutoffTime{hour,minute,timezone}` | `cutoff_time{hour,minute,time_zone}` | rename; not consumed |
| `handlingBusinessDayConfig.businessDays[]` (STRING `'monday'`) | `handling_business_day_config.business_days[]` (enum `MONDAY`) | S4: enum NAME; not consumed |
| — | `transit_business_day_config`, `transit_time_table`, `warehouse_based_delivery_times[]` | new; not consumed |

### 2.4 `services[].rateGroups[]` → `services[].rate_groups[]`  (**drives `free`**)
| Old | New | Notes |
|---|---|---|
| `applicableShippingLabels[]` | `applicable_shipping_labels[]` | rename |
| `name` | `name` | unchanged |
| **`singleValue.flatRate{value,currency}`** | **`single_value.flat_rate{amount_micros,currency_code}`** | **S3: `single_value` is a `Value`; `value` FLOAT(major)→`amount_micros` INT64(micros)** |
| **`mainTable.rows[].cells[].flatRate{value,currency}`** | **`main_table.rows[].cells[].flat_rate{amount_micros,currency_code}`** | **S3: each `cell` is now a `Value`; `cell.flat_rate.amount_micros`** |
| `mainTable.{rowHeaders,columnHeaders}.prices[]{value,currency}` | `main_table.{row_headers,column_headers}.prices[]{amount_micros,currency_code}` | not consumed |
| — | `single_value.{no_shipping,price_percentage,carrier_rate,subtable}`, `subtables[]`, `carrier_rates[]` | new alternative rate encodings (see Q1) |

---

## 3. The 4 MEX booleans re-expressed in v1 terms
1. **`has_account_level_shipping`** = `ARRAY_LENGTH(services) > 0` — *(unchanged)*.
2. **`has_account_level_shipping_speed`** = EXISTS service with all of
   `delivery_time.{min_transit_days, max_transit_days, min_handling_days, max_handling_days}` NOT NULL.
3. **`has_account_level_fast_shipping`** = EXISTS service with
   `delivery_time.max_transit_days + delivery_time.max_handling_days <= 3` (both not null).
4. **`has_account_level_free_shipping`** = EXISTS a zero flat rate:
   `rate_groups[].single_value.flat_rate.amount_micros = 0`
   **OR** `rate_groups[].main_table.rows[].cells[].flat_rate.amount_micros = 0`.

---

## 4. Open questions — ✅ RESOLVED LIVE in Step 3 (`new_shippingsettings/`)
- **Q1 — free-shipping representation. ✅ NO PROBLEM.** For all 4 free accounts (385740737, 502263348,
  606423213, 5354028611) the v1 record renders `single_value.flat_rate = {amount_micros: 0, currency_code}`
  — **`amount_micros: 0` is PRESENT**, not omitted (proto-plus `to_dict` emits the zero scalar because the
  `flat_rate` *message* is present). ⇒ the plain SQL `single_value.flat_rate.amount_micros = 0` is correct;
  the feared NULL-drop does **not** occur. (Defensive `IFNULL(...,0)=0` is optional, not required — but I'll
  keep the predicate guarded so a `no_shipping`/absent-`flat_rate` service can't error.)
- **Q2 — units. ✅** `value:"5"`→`amount_micros:5000000`; `"1"`→`1000000`; `"0"`→`0` (micros = value × 1e6).
  The `= 0` free test is exact.
- **Q3 — aggregator + empty. ✅** MCA `120436857` → **`PermissionDenied`** ("can only be accessed by
  subaccounts and standalone accounts"), same as LIA → **skip the aggregator**. (No account in the set
  returned `NotFound`; the fetcher handles it as "no row" regardless, parallel to the old 404 swallow.)
- **Q4 — `delivery_countries`. ✅** The old single `deliveryCountry` becomes a `delivery_countries[]`
  array. **Plus an observed structural merge:** old `502263348` had **2** identical-except-country services
  (US, IL) → v1 returns **1** service with `delivery_countries=['US','IL']`. `122456618`'s two services
  (different names/currencies) stayed separate. **Impact on the 4 booleans: NONE** — all four are
  `EXISTS`-across-services, invariant under per-country service merging. (Not consumed downstream anyway.)

## 5. Assumptions carried to Step 5
- **A1** — `fast` True-branch is correct by field-rename only (no live account exercises `max_transit_days
  + max_handling_days ≤ 3`; all 7 are > 3).
- **A2** — `main_table` free-shipping branch is correct by spec only (all 7 accounts use `single_value`,
  none use `main_table`).
