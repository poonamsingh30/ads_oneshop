# Phase 3 — `liasettings` Migration: Understanding & Context

> Background for the Content API v2.1 → Merchant API **v1 (stable)** migration of the
> **`liasettings`** (Local Inventory Ads settings) path, end-to-end.
> Plan/checklist: `liasettings_migration_plan.md`. Per-file log: `CHANGES_TRACKER.md`.
> Phase 1 (`accounts`) and Phase 2 (`products`) are complete; their docs are under
> `migration_test/completed/{accounts,products}/`.

---

## 0. Where `liasettings` sits in the pipeline today

```
Content API v2.1  liasettings.get  (per account, scalar)        ┐
                  liasettings.list (MCA → sub-account children) ┘
        │  (acit/acit.py — admin-resource roll-down loop + _pull_standalone_account_resource)
        ▼
  merchant_center/<accountId>/liasettings/rows.jsonlines
        │   envelope: { "settings": <LiaSettings>, "children": [ <LiaSettings>, … ] }
        ▼
  Beam  acit/create_base_tables.py  →  convert_lia_settings()
        │   parses into proto schema_pb2.CombinedLiaSettings, re-emits JSON
        ▼
  liasettings.jsonlines  →  BQ table `liasettings`
        │   schema = acit/api/v0/storage/liasettings.schema  (GENERATED from schema.proto)
        ▼
  MEX SQL consumers (extensions/merchant_excellence/):
     • account_list.sql   (AllLiaSettings CTE → 4 lia_has_* booleans)
     • all_metrics.sql     (AllLiaSettings CTE → 4 lia_has_* booleans)
     • ml_data.sql         (L.children only — MCA sub-accounts → 4 lia_has_* booleans)
     • admin_tables.sql    (CREATE TABLE liasettings — the column contract)
```

### 1.1 Ingestion (Content API, current)
- `acit/acit.py` pulls `liasettings` as one of `_ACIT_ACCOUNT_ADMIN_RESOURCES = ['liasettings', 'shippingsettings']`
  (admin-rights-gated).
- For **MCAs** (aggregators): `liasettings.get` for the aggregator → `settings`, then `liasettings.list`
  for the children → `children[]`. Written as one envelope file per aggregator
  (`acit.py` main loop, ~L494-536).
- For **standalone** leaf accounts: `_pull_standalone_account_resource` does a single `liasettings.get`
  (`is_scalar=True`) and writes `{ "settings": <LiaSettings>, "children": [] }`.
- Output path: `merchant_center/<accountId>/liasettings/rows.jsonlines`.

### 1.2 Beam transform — `convert_lia_settings` (`create_base_tables.py` ~L200-244)
- Reads `merchant_center/*/liasettings/*.jsonlines`.
- If `row['settings']` is absent → treats `row` itself as a bare `LiaSettings`; else parses the
  `{settings, children}` envelope into `schema_pb2.CombinedLiaSettings` (after deleting each child's
  `downloaderMetadata`).
- Emits proto → dict (`preserving_proto_field_name=True`, `always_print_fields_with_no_presence=True`).
- Output: `liasettings.jsonlines` → BQ load (`run_acit.sh` L190-195) with the GENERATED
  `acit/api/v0/storage/liasettings.schema`.

### 1.3 Proto / schema (GENERATED, not checked in)
- `acit/api/v0/storage/schema.proto` defines `CombinedLiaSettings{settings, children[]}`,
  `LiaSettings{account_id, country_settings[], kind}`, `LiaCountrySettings{country, inventory,
  on_display_to_order, hosted_local_storefront_active, store_pickup_active, about, pos_data_provider,
  omnichannel_experience}`, plus `LiaInventorySettings`, `LiaOnDisplayToOrderSettings`,
  `LiaAboutPageSettings`, `LiaPosDataProvider`, `LiaOmnichannelExperience`.
- `liasettings.schema` is **generated** by `//acit/api/v0:bq_gen_schemas` (protoc-gen-bq-schema on
  `schema.proto`, Linux-only) → same mechanism as `Products.schema`. **Editing the proto regenerates the
  schema in Cloud Build** — nothing checked into git.
- (Contrast: `shippingsettings.schema` is hand-written under `acit/schemas/acit/`. Different mechanism;
  relevant to the *next* phase, not this one.)

### 1.4 Downstream consumers — the load-bearing reads
The `liasettings` table feeds **four boolean derivations** per merchant, computed in
`account_list.sql` + `all_metrics.sql` (both via an `AllLiaSettings` CTE that flattens
`settings` ∪ `children[]`), and in `ml_data.sql` (children only). Per `country_settings`:

| Derived MEX boolean | Old fields read |
|---|---|
| `lia_has_lia_implemented` | `inventory.status='active'` **AND** `inventory.inventory_verification_contact_status='active'` **AND** `about.status='active'` |
| `lia_has_mhlsf_implemented` | `hosted_local_storefront_active` **OR** `omnichannel_experience.lsf_type IN ('mhlsfBasic','mhlsfFull')` |
| `lia_has_store_pickup_implemented` | `store_pickup_active` **OR** `ARRAY_LENGTH(omnichannel_experience.pickup_types) > 0` |
| `lia_has_odo_implemented` | `on_display_to_order.status='active'` |

> `benchmark_scores.sql` and `all_metrics.sql:1922` reference a **literal string column** named
> `lia_settings` and a `lia_metric` flag — these are UI toggle hints, **not** reads of the data table.
> Only `account_list.sql`, `all_metrics.sql`, `ml_data.sql`, `admin_tables.sql` touch the actual table.

---

## 2. The new Merchant API v1 surface (preliminary — to confirm in Steps 2–3)

**Key finding:** v1 has no `liasettings` resource. The LIA/local-storefront settings move to
**`OmnichannelSettings`** in **`google-shopping-merchant-accounts`** — *already a dependency from Phase 1*
(`google-shopping-merchant-accounts==1.5.0`). **No new pip package required.**

- Client: `merchant_accounts_v1.OmnichannelSettingsServiceClient`
  - `list_omnichannel_settings(parent="accounts/{account}")` → **list** of `OmnichannelSetting`
    (one per region) — replaces the single `LiaSettings{countrySettings[]}`.
  - `get/create/update` also available.
- POS data provider → **`LfpProvidersServiceClient`** (`find_lfp_providers`, `link_lfp_provider`) +
  the `lfp_link` field on `OmnichannelSetting` (replaces `posDataProvider`).

### `OmnichannelSetting` shape (introspected from the v1 client)
```
OmnichannelSetting:
  name                  # accounts/{account}/omnichannelSettings/{region}
  region_code           # ← old country_settings[].country
  lsf_type  (enum)      # LSF_TYPE_UNSPECIFIED | GHLSF | MHLSF_BASIC | MHLSF_FULL
  in_stock              # InStock{ uri, state }
  pickup                # Pickup{ uri, state }
  lfp_link              # LfpLink{ lfp_provider, external_account_id, state }
  odo                   # OnDisplayToOrder{ uri, state }
  about                 # About{ uri, state }
  inventory_verification# InventoryVerification{ state, contact, contact_email, contact_state }
```
Sub-message state enums: `InStock/Pickup/About/OnDisplayToOrder/LfpLink.state` ∈
`{STATE_UNSPECIFIED, ACTIVE, FAILED, RUNNING, ACTION_REQUIRED}`;
`InventoryVerification.state` ∈ `{STATE_UNSPECIFIED, ACTION_REQUIRED, INACTIVE, RUNNING, SUCCEEDED, SUSPENDED}`,
`InventoryVerification.contact_state` ∈ `{…, ACTIVE, …}`.

### Preliminary old → new field map (to verify on real data in Steps 2–4)

| Old `liasettings.countrySettings[]` | New `OmnichannelSetting` | Kind |
|---|---|---|
| `country` | `region_code` | rename |
| `about.status` (`'active'`) | `about.state` (`ACTIVE`) | rename + **enum** |
| `about.url` | `about.uri` | rename |
| `onDisplayToOrder.status` | `odo.state` (enum) | rename + enum |
| `onDisplayToOrder.shippingCostPolicyUrl` | `odo.uri` | rename |
| `inventory.status` | `in_stock.state` / `inventory_verification.state` (⚠ split — confirm) | enum + **semantic split** |
| `inventory.inventoryVerificationContactName` | `inventory_verification.contact` | rename |
| `inventory.inventoryVerificationContactEmail` | `inventory_verification.contact_email` | rename |
| `inventory.inventoryVerificationContactStatus` (`'active'`) | `inventory_verification.contact_state` (`ACTIVE`) | rename + enum |
| `hostedLocalStorefrontActive` (bool) | derive from `lsf_type == GHLSF` (confirm) | **semantic** |
| `storePickupActive` (bool) | derive from `pickup.state == ACTIVE` | **semantic** |
| `omnichannelExperience.lsfType` (`'mhlsfBasic'/'mhlsfFull'`) | `lsf_type` (`MHLSF_BASIC`/`MHLSF_FULL`) | **enum value change** |
| `omnichannelExperience.pickupType[]` | `pickup` (single message) | restructure |
| `posDataProvider.posDataProviderId` | `lfp_link.lfp_provider` (resource name) | restructure → LfpProvider |
| `posDataProvider.posExternalAccountId` | `lfp_link.external_account_id` | rename |
| `kind` | — | drop |
| `accountId` (top-level `LiaSettings`) | account in resource `name` | identity |

---

## 3. Anticipated structural changes (the headline gaps)

1. **`countrySettings[]` → a LIST of `OmnichannelSetting`** (one resource per region). The single
   `LiaSettings` object with an embedded country array is gone; `list_omnichannel_settings` returns the
   per-region rows directly.
2. **Status strings → enums** (`'active'` → `ACTIVE`/`SUCCEEDED`/…) across about/odo/in_stock/inventory/pickup.
   The four MEX booleans must be re-expressed against the new enum names.
3. **`hostedLocalStorefrontActive` / `storePickupActive` / `omnichannelExperience.lsfType`** collapse into
   `lsf_type` (enum) + `pickup` (message). The mHLSF detection (`mhlsfBasic/mhlsfFull` → `MHLSF_BASIC/MHLSF_FULL`)
   and store-pickup detection change shape.
4. **`posDataProvider` → `lfp_link` + LfpProvider service** (may be out-of-scope for the consumed booleans;
   none of the 4 MEX booleans read POS data — confirm in Step 5).
5. **MCA roll-down envelope** (`{settings, children[]}`): decide whether to keep the envelope or adopt the
   flat per-account shape established in Phase 1 (accounts uses `parent_account`). Native-v1 preference
   says drop the Content-API `children[]` nesting and write per-account omnichannel rows, joining the
   MCA→child relationship via the already-migrated `accounts` table. **Step 6 decision (D2).**

## 4. Constraints carried from Phases 1–2
- Merchant API **stable v1** only (no v1beta).
- **Native v1 shape end-to-end** — do NOT transform back into the legacy `LiaSettings`/`countrySettings` schema.
- Fresh conda env for testing; reuse `oneshop_products_migration` (already has
  `google-shopping-merchant-accounts==1.5.0`) or clone a new one. Test creds in gitignored `env.local.sh`.
- Main code reads standard `GOOGLE_ADS_*` env vars only.
- The Bazel image build must keep working. `liasettings.schema` is **generated** from `schema.proto` →
  proto edits regenerate it in Cloud Build (Linux-only protoc step, as in Phase 2). **No new pip dep
  expected** (the accounts package already provides OmnichannelSettings).
- Keep scratch artifacts in `migration_test/`.

## 5. Open questions to resolve during the steps
- **Q1** Does `inventory.status='active'` map to `in_stock.state` or `inventory_verification.state`?
  (The old `inventory` block conflated local-product-inventory feed status with verification.) — Step 2/4.
- **Q2** Is `hostedLocalStorefrontActive` ⟺ `lsf_type == GHLSF`, or a separate signal? — Step 2/4.
- **Q3** Does `list_omnichannel_settings` require admin/MCA rights the same way, and does it roll down to
  sub-accounts, or must we iterate accounts ourselves (like Phase-1/2 fan-out)? — Step 3.
- **Q4** Do we keep the `{settings, children[]}` envelope (minimal SQL churn) or go flat per-account
  (true native shape)? — Step 6 (D2).
- **Q5** Are POS/`lfp_link` fields consumed anywhere? (Looks no — only the 4 booleans.) — Step 5.
