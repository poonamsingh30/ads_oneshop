# Phase 3 — `liasettings` → `OmnichannelSettings`: v1 API study + old→new field map (Step 2)

> Authoritative mapping from Content API v2.1 `liasettings` to Merchant API v1
> `OmnichannelSettings`. Introspected from the v1 client **and grounded on real
> data** for account `5789905876`, region `IN` (the one account in the test MCA
> `120436857` that has LIA config). Companion: `liasettings_diff.md` (Steps 4–5).

---

## 1. Endpoint / resource change

| | Old — Content API v2.1 | New — Merchant API v1 (stable) |
|---|---|---|
| Package | `googleapiclient` discovery (`content`,`v2.1`) | `google-shopping-merchant-accounts==1.5.0` *(already a Phase-1 dep)* |
| Service | `liasettings` | `merchant_accounts_v1.OmnichannelSettingsServiceClient` |
| Per-account read | `liasettings.get(merchantId, accountId)` → ONE `LiaSettings{countrySettings[]}` | `list_omnichannel_settings(parent="accounts/{id}")` → **list** of `OmnichannelSetting` (one per region) |
| MCA roll-down | `liasettings.list(merchantId=agg)` → children's `LiaSettings` | **none** — no roll-down list; fan out per subaccount yourself |
| POS providers | `liasettings.listposdataproviders` + `countrySettings[].posDataProvider` | `LfpProvidersServiceClient` + `OmnichannelSetting.lfp_link` |
| Identity | `LiaSettings.accountId` + `countrySettings[].country` | resource `name` = `accounts/{id}/omnichannelSettings/{region}`; `region_code` |

**Structural headline:** the single `LiaSettings` object with an embedded
`countrySettings[]` array is gone. v1 returns **one `OmnichannelSetting` resource per
region**, listed directly under the account. The old `countrySettings[]` array ⟺ the
v1 per-region list.

**⚠ Aggregator (MCA) not queryable:** `list_omnichannel_settings` on the MCA itself
returns `PermissionDenied` — *"This method can only be accessed by subaccounts and
standalone accounts."* (Verified on `120436857`.) The old `liasettings.get` on the
aggregator returned an empty `countrySettings`, so no data is lost — but the ingestion
must **only query subaccounts/standalone accounts**, never the aggregator.

---

## 2. Field map — `countrySettings[]` (old) → `OmnichannelSetting` (new)

Legend: **R** rename · **E** enum (string value change) · **S** semantic/structural · **D** dropped · **N** new

| Old `countrySettings[].*` | New `OmnichannelSetting.*` | Kind | Notes |
|---|---|---|---|
| `country` | `region_code` | R | `"IN"` ↔ `"IN"` (verified) |
| `inventory.status` (`active`/`inactive`) | `in_stock.state` (enum) | E,S | **Local-inventory feed** status. Verified: old `inactive` ↔ new `in_stock.state=STATE_UNSPECIFIED`. (NOT `inventory_verification` — that's the contact block below.) |
| `inventory.inventoryVerificationContactName` | `inventory_verification.contact` | R | |
| `inventory.inventoryVerificationContactEmail` | `inventory_verification.contact_email` | R | |
| `inventory.inventoryVerificationContactStatus` (`active`) | `inventory_verification.contact_state` (enum `ACTIVE`) | R,E | |
| *(implicit verification status)* | `inventory_verification.state` (enum) | N | v1 splits verification *workflow* state out (`ACTION_REQUIRED/INACTIVE/RUNNING/SUCCEEDED/SUSPENDED`). |
| `onDisplayToOrder.status` | `odo.state` (enum) | R,E | |
| `onDisplayToOrder.shippingCostPolicyUrl` | `odo.uri` | R | |
| `about.status` | `about.state` (enum) | R,E | |
| `about.url` | `about.uri` | R | |
| `hostedLocalStorefrontActive` (bool) | `lsf_type == GHLSF` | S,E | Google-hosted LSF folds into the single `lsf_type` enum. Verified: old `false` ↔ new `lsf_type=LSF_TYPE_UNSPECIFIED`. |
| `omnichannelExperience.lsfType` (`mhlsfBasic`/`mhlsfFull`) | `lsf_type` (`MHLSF_BASIC`/`MHLSF_FULL`) | S,E | Merchant-hosted tiers fold into the SAME `lsf_type` enum. |
| `omnichannelExperience.country` | *(= `region_code`)* | D | redundant; the setting is already per-region |
| `storePickupActive` (bool) | `pickup.state == ACTIVE` | S,E | |
| `omnichannelExperience.pickupType[]` | `pickup` (single message) | S | pickup collapses to one sub-message + `uri`/`state` |
| `posDataProvider.posDataProviderId` | `lfp_link.lfp_provider` (resource name) | S | via `LfpProvidersServiceClient` |
| `posDataProvider.posExternalAccountId` | `lfp_link.external_account_id` | R | |
| *(n/a)* | `lfp_link.state` (enum) | N | |
| *(n/a)* | `in_stock.uri`, `pickup.uri`, `about.uri`, `odo.uri` | N | feed/landing URIs per sub-feature |
| `kind` (`content#liaSettings`) | — | D | discovery-only artifact |
| `LiaSettings.accountId` | account in resource `name` | S | top-level identity moves into `name` |

### Enum value crosswalk (the load-bearing part for MEX)
| Old string | New enum (NAME string) |
|---|---|
| `"active"` | `ACTIVE` (about/odo/in_stock/pickup/lfp_link, `contact_state`) — or `SUCCEEDED` for `inventory_verification.state` |
| `"inactive"` / unset | `STATE_UNSPECIFIED` (sub-feature) / `INACTIVE` (`inventory_verification.state`) / absent message |
| `hostedLocalStorefrontActive=true` | `lsf_type = GHLSF` |
| `"mhlsfBasic"` | `lsf_type = MHLSF_BASIC` |
| `"mhlsfFull"` | `lsf_type = MHLSF_FULL` |

---

## 3. The 4 MEX booleans re-expressed in v1 terms (provisional — finalize in Steps 4–5)

| MEX boolean | Old condition | New (v1) condition |
|---|---|---|
| `lia_has_lia_implemented` | `inventory.status='active'` AND `inventory.inventory_verification_contact_status='active'` AND `about.status='active'` | `in_stock.state='ACTIVE'` AND `inventory_verification.contact_state='ACTIVE'` AND `about.state='ACTIVE'` |
| `lia_has_mhlsf_implemented` | `hostedLocalStorefrontActive` OR `lsf_type IN ('mhlsfBasic','mhlsfFull')` | `lsf_type IN ('GHLSF','MHLSF_BASIC','MHLSF_FULL')` (≡ `lsf_type != 'LSF_TYPE_UNSPECIFIED'`) |
| `lia_has_store_pickup_implemented` | `storePickupActive` OR `ARRAY_LENGTH(pickup_types)>0` | `pickup.state='ACTIVE'` |
| `lia_has_odo_implemented` | `on_display_to_order.status='active'` | `odo.state='ACTIVE'` |

For the all-inactive test record (`5789905876`/`IN`) **all four = false on both sides** (verified
structurally: old `inactive`/`false`; new `STATE_UNSPECIFIED`/`LSF_TYPE_UNSPECIFIED`/absent).

---

## 4. Real records (verified)

**OLD** `countrySettings[0]` (`5789905876`/`IN`):
```json
{ "country": "IN",
  "inventory": {"status": "inactive"},
  "onDisplayToOrder": {"status": "inactive"},
  "about": {"status": "inactive"},
  "hostedLocalStorefrontActive": false,
  "storePickupActive": false }
```
**NEW** `OmnichannelSetting` (`5789905876`/`IN`):
```json
{ "name": "accounts/5789905876/omnichannelSettings/IN",
  "region_code": "IN",
  "in_stock": {"uri": "", "state": "STATE_UNSPECIFIED"},
  "lsf_type": "LSF_TYPE_UNSPECIFIED" }
```
(absent in the new record because unset: `pickup`, `odo`, `about`, `lfp_link`, `inventory_verification`.)

## 5. Open items carried to Steps 4–5
- Confirm `GHLSF` ⟺ `hostedLocalStorefrontActive` (no active-GHLSF account in the test data to verify
  directly — mapping inferred from the LSF taxonomy; flag as **assumption A1**).
- Confirm `inventory_verification.state` vs `contact_state` semantics for an active account (test data
  is all-inactive, so only the unset case is verified — **assumption A2**).
- POS/`lfp_link`: **not consumed** by any of the 4 MEX booleans → out of scope for parity, model in the
  proto only if cheap. Confirm in Step 5.
