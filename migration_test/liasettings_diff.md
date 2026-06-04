# Phase 3 — `liasettings`: Old vs New Comparison + Gap Log (Steps 4–5)

> Step 4 (compare) + Step 5 (gaps), produced by `compare_liasettings.py` over the
> Step-1/Step-3 baselines (MCA `120436857`; the one configured account `5789905876`/`IN`).
> Companion to `liasettings_api_v1_mapping.md`.

---

## Step 4 — Reconciliation result

The `liasettings` table is consumed downstream **only** to compute four booleans per
`(merchant, region)` in the MEX SQL. So the comparison derives those four booleans from
**both** shapes and checks they agree.

**Coverage: 1/1 `(accountId, region)` key matched** (`5789905876`/`IN`); 0 only-old, 0 only-new.

| Derived boolean | old\|new | match | mismatch |
|---|---|---:|---:|
| `lia_has_lia_implemented` | `False`\|`False` | 1 | 0 |
| `lia_has_mhlsf_implemented` | `False`\|`False` | 1 | 0 |
| `lia_has_store_pickup_implemented` | `False`\|`False` | 1 | 0 |
| `lia_has_odo_implemented` | `False`\|`False` | 1 | 0 |

**TOTAL boolean mismatches: 0.**

> **Coverage caveat (honest):** the entire test MCA has exactly one account with any LIA
> config, and it is **all-inactive**. So this verifies the *structural* mapping and the
> **false/unset** path of all four booleans (old `inactive`/`false`/absent ⟺ new
> `STATE_UNSPECIFIED`/`LSF_TYPE_UNSPECIFIED`/absent). The **active** path of each boolean is
> mapped by spec (`liasettings_api_v1_mapping.md` §3) but not observed in live data — see
> assumptions A1/A2. This is a data limitation, not a mapping gap; an active LIA account
> would be needed to value-verify the `True` branches.

---

## Step 5 — Gap log

Legend: **C** = consumed downstream (must handle) · **N** = not consumed (safe) ·
**R** = rename · **E** = enum value change · **S** = semantic/structural.

| # | Gap | Kind | Downstream consumer | Resolution (Step 6/7) |
|---|-----|------|---------------------|------------------------|
| L1 | **`liasettings`/`countrySettings[]` → per-region `OmnichannelSetting` list** | C,S | Beam `convert_lia_settings`; MEX `AllLiaSettings` CTE | New proto models a per-account list of `OmnichannelSetting` (one per region). Beam emits one row per (account, region) or an account row carrying the region list. |
| L2 | status strings → **enums** (`'active'`→`ACTIVE`; `'inactive'`/unset→`STATE_UNSPECIFIED`) across about/odo/in_stock/pickup/contact | C,E | the 4 MEX booleans | Store enum NAME string; rewrite the booleans to compare `='ACTIVE'`. Verified (false branch). |
| L3 | `inventory.status` → **`in_stock.state`** (the local-inventory-feed signal, NOT verification) | C,S | `lia_has_lia_implemented` | Read `in_stock.state='ACTIVE'`. **Verified**: old `inactive` ⟺ new `in_stock.state=STATE_UNSPECIFIED`. |
| L4 | `inventory.inventoryVerificationContact{Name,Email,Status}` → `inventory_verification.{contact,contact_email,contact_state}` | C,R | `lia_has_lia_implemented` (uses `contact_state`) | Rename; compare `contact_state='ACTIVE'`. |
| L5 | `hostedLocalStorefrontActive` + `omnichannelExperience.lsfType` → single **`lsf_type`** enum (`GHLSF`/`MHLSF_BASIC`/`MHLSF_FULL`) | C,S,E | `lia_has_mhlsf_implemented` | `lsf_type IN ('GHLSF','MHLSF_BASIC','MHLSF_FULL')` (≡ `!= 'LSF_TYPE_UNSPECIFIED'`). **Assumption A1**: `GHLSF`⟺`hostedLocalStorefrontActive`. |
| L6 | `storePickupActive` + `omnichannelExperience.pickupType[]` → **`pickup`** message (`state`) | C,S | `lia_has_store_pickup_implemented` | `pickup.state='ACTIVE'`. |
| L7 | `onDisplayToOrder.{status,shippingCostPolicyUrl}` → `odo.{state,uri}` | C,R,E | `lia_has_odo_implemented` | `odo.state='ACTIVE'`. |
| L8 | `about.{status,url}` → `about.{state,uri}` | C,R,E | `lia_has_lia_implemented` | `about.state='ACTIVE'`. |
| L9 | `country` → `region_code`; `LiaSettings.accountId` → resource `name` `accounts/{id}/omnichannelSettings/{region}` | C,R,S | MEX join key (`account_id`) + region grouping | Carry `account_id` (from downloaderMetadata) + `region_code` on the proto. |
| **L10** | **MCA itself not queryable** — `list_omnichannel_settings(MCA)` → `PermissionDenied` ("only subaccounts and standalone accounts") | C,S | ingestion loop | **Query subaccounts + standalone only**, never the aggregator. No data lost (old aggregator `get` returned empty `countrySettings`). |
| **L11** | **No MCA roll-down `list`** (old `liasettings.list(merchantId=agg)` is gone) | C,S | ingestion loop; the `{settings,children[]}` envelope | **Fan out per-account** ourselves (Phase-1/2 threaded pattern). **Drop the `{settings,children[]}` envelope** → flat per-account rows; join MCA→child via the migrated `accounts` table. |
| L12 | `posDataProvider.*` → `lfp_link` (+ `LfpProvidersServiceClient`) | N | none (no MEX boolean reads POS) | Out of scope for parity. Model `lfp_link` in the proto only if cheap; no separate LfpProviders pull needed. |
| L13 | `kind` (`content#liaSettings`) dropped | N | none | Drop. |
| L14 | **new** v1 fields: `in_stock.uri`, `pickup.uri`, `about.uri`, `odo.uri`, `inventory_verification.state`, `lfp_link.state` | N (added) | none yet | Include selectively in the proto; none consumed today. |

### Assumptions (un-verifiable on all-inactive test data)
- **A1** `lsf_type == GHLSF` ⟺ old `hostedLocalStorefrontActive == true`. Inferred from the LSF
  taxonomy (Google-Hosted Local Storefront). No active-GHLSF account in the test MCA to confirm.
- **A2** For an active account, old `inventoryVerificationContactStatus='active'` ⟺ new
  `inventory_verification.contact_state='ACTIVE'` (and `in_stock.state='ACTIVE'` for the feed). Only the
  unset case is observed.

### Blockers
**None.** Every consumed field has a verified or spec'd v1 equivalent. The four MEX booleans reconcile
0-mismatch on the available data. The only behavioral changes are **structural ingestion** (L10/L11:
query subaccounts directly, drop the `{settings,children[]}` envelope) — both mechanically clean.

### Decisions this unlocks (to finalize in Step 6)
- **D2 — output/record shape:** adopt the **flat per-account** native shape — write each subaccount's
  per-region `OmnichannelSetting` list to `merchant_center/<id>/liasettings/rows.jsonlines` (BQ glob
  unchanged); **drop the `{settings, children[]}` envelope** and the aggregator pull (L10/L11). MEX
  recovers the MCA→child relationship from the already-migrated `accounts` table (Phase-1 `parent_account`).
- **D3 — proto modeling:** replace `CombinedLiaSettings`/`LiaSettings`/`LiaCountrySettings` + the 5
  `Lia*` sub-messages with native `OmnichannelSetting` messages (`region_code`, `lsf_type`, `in_stock`,
  `pickup`, `lfp_link`, `odo`, `about`, `inventory_verification`), enums as STRING, keep
  `table_name="liasettings"`. Regenerate `liasettings.schema`.
- **SQL edits required:** `account_list.sql`, `all_metrics.sql`, `ml_data.sql` — rewrite the
  `AllLiaSettings` CTE for the flat shape + the 4 booleans against the new enums; `admin_tables.sql` —
  new `CREATE TABLE liasettings` contract.
