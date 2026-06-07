# Phase 3 — `liasettings` Migration: Plan & Change Tracker

> Tracks the Content API v2.1 → Merchant API **v1 (stable)** migration of the
> **`liasettings`** (Local Inventory Ads / omnichannel) path, end-to-end.
> Update the Status column as work proceeds.
> Understanding/context: `liasettings_migration_understanding.md`. Per-file log: `CHANGES_TRACKER.md`.

**Legend:** ⬜ not started · 🟡 in progress · ✅ done · ⛔ blocked

---

## A. Workstream tracker (the strict 7 steps)

| Step | Task | Output / Artifact | Status |
|------|------|-------------------|--------|
| 0 | Set up conda env + confirm deps (old discovery client + `google-shopping-merchant-accounts` — already installed) | env import-verified (`OmnichannelSettingsServiceClient`, `list_omnichannel_settings`) — reused `oneshop_products_migration` | ✅ |
| 1 | Fetch **old** Content API `liasettings.get` + `liasettings.list` for real accounts; save baseline | `fetch_liasettings_old.py` + `old_liasettings/*` — MCA `120436857`: 34 children, **1** (`5789905876`, `IN`) has countrySettings (all `inactive`) | ✅ |
| 2 | Study **new** Merchant API v1 `OmnichannelSettings`; finalize old→new field map | `liasettings_api_v1_mapping.md` (introspected + grounded on real `5789905876`/`IN`) | ✅ |
| 3 | Build **test fetcher** for v1 `list_omnichannel_settings`, fan-out per subaccount; save output | `fetch_liasettings_new.py` + `new_liasettings/*` — 34 accounts queried, **1** (`5789905876`/`IN`) has a setting (parity with old) | ✅ |
| 4 | **Compare** old vs new for the same account(s)/region(s) | `compare_liasettings.py` + `liasettings_diff.md` — **1/1 key matched; 0/4 boolean mismatch** | ✅ |
| 5 | Document **gaps** (renames, enum values, semantic splits, MCA roll-down, POS/lfp) | `liasettings_diff.md` §Step 5 (L1–L14, no blockers) | ✅ |
| 6 | **Resolve** gaps; decide native record shape + new proto messages + regenerated schema | ✅ flat `OmnichannelLiaSettings` in `schema.proto`; `liasettings.schema` regenerates via `bq_gen_schemas` | ✅ |
| 7 | Implement **end-to-end** code changes | ✅ §B done — see `CHANGES_TRACKER.md`; bazel build + 5 tests + real-record round-trip | ✅ |

---

## B. End-to-end code change checklist (Step 7)

### B1. Ingestion — `acit/acit.py` (+ new module)
- ⬜ Add a Merchant API v1 **omnichannel** fetcher (likely `acit/merchant_lia.py`, consistent with
  `merchant_accounts.py` / `merchant_products.py`): `OmnichannelSettingsServiceClient.list_omnichannel_settings(parent="accounts/{id}")`.
- ⬜ Remove `liasettings` from the Content-API `_ACIT_ACCOUNT_ADMIN_RESOURCES` roll-down loop +
  `_pull_standalone_account_resource` (leave `shippingsettings` untouched — that's Phase 4).
- ⬜ Decide & implement output layout (D2): keep `merchant_center/<id>/liasettings/rows.jsonlines`
  (BQ glob unchanged) but with native v1 records.
- ⬜ Keep `downloaderMetadata={'accountId': id}` stamping for Beam keys / account derivation.
- ⬜ Confirm OAuth scope / creds (same `content`/merchant scope; no change expected — verify).
- ⬜ Reuse the threaded fan-out + retry/backoff pattern (no bulk variant; transient 500s).

### B2. Beam processing — `acit/create_base_tables.py`
- ⬜ Rewrite `convert_lia_settings` for the native v1 shape (per-region `OmnichannelSetting` list);
  drop the `CombinedLiaSettings`/`{settings,children}` envelope handling if D2 goes flat.
- ⬜ Re-point the proto parse to the new message(s); strip `downloaderMetadata` as needed.
- ⬜ Preserve the account-id / MCA-child derivation the 4 MEX booleans depend on.

### B3. Proto + generated schema — `acit/api/v0/storage/schema.proto`, `bq_gen_schemas`
- ⬜ Replace `LiaSettings`/`LiaCountrySettings`/`CombinedLiaSettings` + the 5 `Lia*` sub-messages with
  native v1 `OmnichannelSetting` messages (`region_code`, `lsf_type`, `in_stock`, `pickup`, `lfp_link`,
  `odo`, `about`, `inventory_verification`); enums as STRING. Keep `table_name = "liasettings"`.
- ⬜ Regenerate `storage/liasettings.schema` via `//acit/api/v0:bq_gen_schemas` (Linux/Cloud Build).
- ⬜ Verify `schema_py_pb2` still compiles and Beam parses against it.

### B4. BQ load — `acit/run_acit.sh`
- ⬜ Confirm the `liasettings` table load still points at `liasettings.jsonlines` + regenerated
  `liasettings.schema` (no path change expected if output layout preserved).

### B5. Views / final tables — MEX SQL (read the `liasettings` table)
- ⬜ `extensions/merchant_excellence/account_list.sql` — rewrite the `AllLiaSettings` CTE + the 4
  `lia_has_*` booleans against the new shape/enums.
- ⬜ `extensions/merchant_excellence/all_metrics.sql` — same 4 booleans.
- ⬜ `extensions/merchant_excellence/ml_data.sql` — children-only variant of the 4 booleans.
- ⬜ `extensions/merchant_excellence/admin_tables.sql` — update the `CREATE TABLE liasettings` contract.

### B6. Tests & validation
- ⬜ Update/add `acit/tests/` for the new omnichannel parsing + the 4-boolean derivations.
- ⬜ Add unit tests for `merchant_lia.py` (enum-as-string, snake keys, per-region list, account stamping).
- ⬜ Round-trip real v1 omnichannel records through the bazel-built proto (as done for products).

### B7. Bazel / packaging
- ⬜ `acit/BUILD.bazel` — new `merchant_lia_lib` + test; wire into the `acit` binary deps.
  (Likely depends on the existing `google_shopping_merchant_accounts` requirement — **no new pip dep**.)
- ⬜ Validate Python targets on macOS (`bazel build //acit:acit`, `bazel test //acit:...`); image/schema-gen
  targets remain Linux/Cloud Build only (pre-existing protoc constraint).

---

## C. Old → New field map — ⬜ to confirm in Step 2
Preliminary table in `liasettings_migration_understanding.md` §2 (introspected from the v1 client).
Headlines: `liasettings`/`countrySettings[]` → **`OmnichannelSettings` list** (one per region);
status strings → **enums** (`'active'`→`ACTIVE`/`SUCCEEDED`); `country`→`region_code`; `*.url`→`*.uri`;
`hostedLocalStorefrontActive`/`storePickupActive`/`omnichannelExperience.lsfType` collapse into
`lsf_type` (enum) + `pickup` (message); `posDataProvider`→`lfp_link` (+ LfpProvider service);
`mhlsfBasic/mhlsfFull`→`MHLSF_BASIC/MHLSF_FULL`.

## D. Gap log — ✅ FINALIZED in `liasettings_diff.md`
**No blockers.** Coverage 1/1 key matched; 0/4 boolean mismatch (false branch verified; active branch
spec'd, see A1/A2). Gaps L1–L14: **L1** `countrySettings[]`→per-region `OmnichannelSetting` list;
**L2** statuses→enums (`'active'`→`ACTIVE`); **L3** `inventory.status`→`in_stock.state` (verified);
**L4** verification-contact→`inventory_verification.*`; **L5** `hostedLocalStorefrontActive`+`lsfType`→single
`lsf_type` enum; **L6** `storePickupActive`+`pickupType[]`→`pickup` msg; **L7** `onDisplayToOrder`→`odo`;
**L8** `about.url/status`→`about.uri/state`; **L9** `country`→`region_code` + accountId→resource name;
**L10** MCA not queryable (PermissionDenied → subaccounts only); **L11** no roll-down list → fan out +
drop `{settings,children[]}` envelope; **L12** `posDataProvider`→`lfp_link` (not consumed); **L13** `kind`
dropped; **L14** new uri/state fields (not consumed). Assumptions **A1** (GHLSF⟺hostedLocalStorefront),
**A2** (active verification state) — un-verifiable on all-inactive test data.

## E. Key decisions — ✅ ALL LOCKED
- **D1 — Client library:** ✅ `OmnichannelSettingsServiceClient` from the already-installed
  `google-shopping-merchant-accounts` (`merchant_accounts_v1`, stable v1, gRPC). **No new dependency** —
  confirmed by the Step-3 fetcher and the `merchant_lia` ingestion.
- **D2 — Record shape:** ✅ **flat per-account** native shape — `merchant_lia` writes one record
  `{account_id, omnichannel_settings:[<per-region>...]}` to `merchant_center/<id>/liasettings/rows.jsonlines`
  (BQ glob unchanged). The `{settings, children[]}` envelope + the aggregator pull are gone; MEX recovers
  the MCA→child relationship from the migrated `accounts` table. Only sub-/standalone accounts are queried
  (the MCA is not a valid parent — L10).
- **D3 — Proto modeling:** ✅ replaced `CombinedLiaSettings`/`LiaSettings`/`LiaCountrySettings` + 5 `Lia*`
  sub-messages with native `OmnichannelLiaSettings`(table) → `OmnichannelSetting` + `OmnichannelFeatureState`
  /`LfpLink`/`InventoryVerification`; enums as STRING; kept `table_name="liasettings"`. `liasettings.schema`
  is **generated** → only `schema.proto` edited; regenerates in Cloud Build.

---

## F. Guardrails / scope
- Phase 3 = **liasettings only**. Do NOT migrate `shippingsettings` (Phase 4) or touch accounts/products.
- **No legacy-schema transform** — native Merchant API v1 shape end-to-end.
- v1 **stable** only (no v1beta). Test in a conda env. Keep scratch artifacts in `migration_test/`.
- The Cloud Run / Dataflow **image build (Bazel)** must keep working — handle proto/BUILD wiring
  (no new pip dep expected).

## G. Changelog
- **2026-06-05** — Steps 6–7 done (end-to-end main code). Proto rewritten to native v1 flat shape
  (`OmnichannelLiaSettings` + `OmnichannelSetting`/`OmnichannelFeatureState`/`LfpLink`/`InventoryVerification`,
  `acit/api/v0/storage/schema.proto`); new ingestion `acit/merchant_lia.py`
  (`OmnichannelSettingsServiceClient.list_omnichannel_settings`, enum-as-string, retry/backoff, threaded,
  skips PermissionDenied aggregators) + `acit.py` rewired (dropped `liasettings` from the Content-API admin
  list; admin-gated `merchant_lia.download_omnichannel_settings` over the product account set);
  `create_base_tables.py` `convert_lia_settings` → flat-record parse; 3 MEX SQL (account_list/all_metrics/
  ml_data) rewrote the `Lia` CTE against the flat shape + enum booleans (`in_stock`/`pickup`/`odo`/`about`.
  `state='ACTIVE'`, `lsf_type IN (GHLSF,MHLSF_BASIC,MHLSF_FULL)`, `inventory_verification.contact_state`);
  `admin_tables.sql` new flat `CREATE TABLE liasettings`; `acit/BUILD.bazel` (new `merchant_lia_lib` +
  `merchant_lia_test`, wired into `acit`); `acit/tests/test_merchant_lia.py` (5 unit tests).
  **No new pip dep** (reused `google-shopping-merchant-accounts`). **Validated:** `bazel build //acit:acit` ✅;
  `bazel test` merchant_lia_test/merchant_products_test/merchant_accounts_test/create_base_tables_test/
  product_test all ✅; **end-to-end round-trip** of the real `5789905876`/`IN` record (→ all 4 booleans
  False, matching old) + a synthetic all-active record (→ all True) through the compiled
  `OmnichannelLiaSettings` proto + the new boolean logic. Image/schema-gen (`bq_gen_schemas` →
  `liasettings.schema`, `cloud_run_job`) remains Cloud-Build-only (proto changed → verify regenerated schema
  in Cloud Build).
- **2026-06-05** — Steps 4–5 done. **Step 4:** `compare_liasettings.py` derives the 4 MEX booleans from
  both shapes per `(account, region)`. **1/1 key matched** (`5789905876`/`IN`), **0/4 boolean mismatch**
  (all `False|False`). Honest caveat: only the **false/unset** branch is value-verified (test MCA has one
  all-inactive LIA account); active branches are spec'd (A1/A2). **Step 5:** `liasettings_diff.md` gap log
  L1–L14, **no blockers**. Load-bearing items are structural ingestion (**L10** MCA not queryable →
  subaccounts only; **L11** no roll-down → fan out + drop the `{settings,children[]}` envelope). Locked the
  Step-6 direction: **D2** flat per-account native shape (MEX recovers MCA→child from the migrated accounts
  table); **D3** proto rewrite to `OmnichannelSetting`. Next: Steps 6–7.
- **2026-06-05** — Steps 2–3 done. **Step 2:** `liasettings_api_v1_mapping.md` — authoritative
  old→new map, grounded on real `5789905876`/`IN`. Resolved **Q1** (`inventory.status`→`in_stock.state`,
  NOT `inventory_verification`) and **Q2** (`hostedLocalStorefrontActive`+`omnichannelExperience.lsfType`
  collapse into the single `lsf_type` enum: GHLSF / MHLSF_BASIC / MHLSF_FULL). Old `inactive`/unset ⟺ new
  `STATE_UNSPECIFIED`/`LSF_TYPE_UNSPECIFIED`/absent. The 4 MEX booleans re-expressed in v1 terms (see
  mapping §3). **Step 3:** `fetch_liasettings_new.py` — `OmnichannelSettingsServiceClient.list_omnichannel_settings(parent="accounts/{id}")`,
  enum-as-string `to_dict`, retry/backoff, fans out per subaccount (read from the old baseline). Output in
  `new_liasettings/`: 34 accounts queried, **1** (`5789905876`/`IN`) returns a setting — **parity** with old.
  **New gap (G-agg):** the MCA itself returns `PermissionDenied` ("only subaccounts and standalone
  accounts") → ingestion must query subaccounts only, never the aggregator (old aggregator `get` returned
  empty anyway, so no data lost). Open assumptions **A1** (GHLSF⟺hostedLocalStorefrontActive) / **A2**
  (verification state) un-verifiable on all-inactive test data — carried to Step 5. Next: Steps 4–5.
- **2026-06-05** — Steps 0–1 done. **Step 0:** reused env `oneshop_products_migration` (py3.11);
  verified both the old Content API discovery client and the new `OmnichannelSettingsServiceClient`
  (`google-shopping-merchant-accounts==1.5.0`, `list_omnichannel_settings` present) import. **Step 1:**
  `fetch_liasettings_old.py` mirrors the `acit.py` roll-down (authinfo → aggregator `get`+`list`,
  standalone `get`). Baseline in `old_liasettings/`: only MCA `120436857` (no standalone), 34 children,
  **1 child** (`5789905876`, country `IN`) has `countrySettings` — all `inactive`
  (`inventory/onDisplayToOrder/about.status='inactive'`, `hostedLocalStorefrontActive=false`,
  `storePickupActive=false`; no `omnichannelExperience`/`posDataProvider`/verification-contact fields
  present). Sparse but real → Step 4 will be mostly **structural/shape** parity, not rich value parity.
  (Token had expired → user refreshed before the run.) Next: Steps 2–3.
- **2026-06-05** — Phase 3 kicked off. Created `liasettings_migration_understanding.md` + this plan +
  appended Phase-3 section to `CHANGES_TRACKER.md`. Studied the current LIA path: Content-API
  `liasettings.get`/`.list` roll-down (`acit.py`) → `{settings,children[]}` envelope → Beam
  `convert_lia_settings` → proto `CombinedLiaSettings` (GENERATED `liasettings.schema`) → `liasettings`
  BQ table → 4 `lia_has_*` MEX booleans (account_list/all_metrics/ml_data) + admin_tables contract.
  **Key finding:** v1 replaces `liasettings` with **`OmnichannelSettings`** in the *already-installed*
  `google-shopping-merchant-accounts` (no new dep) — `OmnichannelSettingsServiceClient.list_omnichannel_settings`
  returns a per-region `OmnichannelSetting` list (status strings → enums; `country`→`region_code`;
  `posDataProvider`→`lfp_link`). Steps 0–7 pending the user's go-ahead.
