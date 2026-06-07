# LiaSettings Migration — Master Change Tracker (Phase 3)

> Single source of truth for **every** file added/modified during the Content API →
> Merchant API v1 migration of the **`liasettings`** (Local Inventory Ads / omnichannel) path.
> Append an entry whenever a file changes.
> Plan/checklist: `liasettings_migration_plan.md` · Context: `liasettings_migration_understanding.md`.
> Phase 1 (`accounts`) and Phase 2 (`products`) are complete; their trackers are archived under
> `completed/accounts/CHANGES_TRACKER.md` and `completed/products/CHANGES_TRACKER.md`.

## Proposed design decisions (recommended options — lock during Steps 2–6)

| # | Decision | Proposed choice | Rationale |
|---|----------|-----------------|-----------|
| D1 | New-API client library | **`google-shopping-merchant-accounts`** → `merchant_accounts_v1.OmnichannelSettingsServiceClient` (stable v1, gRPC) | v1 has no `liasettings`; LIA/omnichannel lives in OmnichannelSettings. **Package already a Phase-1 dependency — no new pip dep.** Confirm after the Step-3 test fetcher. |
| D2 | Record / output shape | *(open)* keep `{settings, children[]}` envelope **vs** flat per-account omnichannel rows | Native-v1 preference favours flat per-account (drop the Content-API `children[]` nesting; join MCA→child via the migrated `accounts` table). Decide in Step 6. Keeping the path `merchant_center/<id>/liasettings/rows.jsonlines` means the BQ glob is unchanged. |
| D3 | Proto / schema modeling | **Rewrite the `Lia*` messages → native `OmnichannelSetting`** in `schema.proto`; regenerate `liasettings.schema` via `bq_gen_schemas` | `liasettings.schema` is proto-generated (not hand-edited). Enums as STRING; keep `table_name="liasettings"`. |

## Environment

- Conda env: reuse **`oneshop_products_migration`** (py3.11) — already has
  `google-shopping-merchant-accounts==1.5.0` (provides `OmnichannelSettingsServiceClient`) +
  the old discovery client for the baseline pull. No new package needed. (Clone a Phase-3 env only
  if isolation is wanted.)
- Test creds: `migration_test/env.local.sh` (GITIGNORED, reused). Main code keeps reading standard
  `GOOGLE_ADS_*` env vars.
- Test accounts: an MCA with LIA-enabled sub-accounts (under MCA `120436857`) — pick during Step 1.

## Change log

| Date | File | Type | Step | Notes |
|------|------|------|------|-------|
| 2026-06-05 | `migration_test/liasettings_migration_understanding.md` | add | pre | Phase-3 understanding doc (current LIA path + preliminary v1 OmnichannelSettings map) |
| 2026-06-05 | `migration_test/liasettings_migration_plan.md` | add | pre | Plan + 7-step tracker + e2e checklist |
| 2026-06-05 | `migration_test/CHANGES_TRACKER.md` | add | pre | This tracker (Phase 3) |
| 2026-06-05 | `migration_test/.gitignore` | edit | 0 | Added `old_liasettings/`, `new_liasettings/` scratch ignores |
| 2026-06-05 | `migration_test/fetch_liasettings_old.py` | add | 1 | OLD Content API liasettings fetcher (authinfo → aggregator `get`+`list`, standalone `get`; mirrors `acit.py` roll-down) |
| 2026-06-05 | `migration_test/old_liasettings/*` (gitignored) | data | 1 | Baseline: MCA `120436857`, 34 children, 1 (`5789905876`/`IN`) has countrySettings (all `inactive`) |
| 2026-06-05 | `migration_test/liasettings_api_v1_mapping.md` | add | 2 | v1 OmnichannelSettings study + authoritative old→new field map (grounded on `5789905876`/`IN`); endpoint/identity change; enum crosswalk; 4 MEX booleans in v1 terms |
| 2026-06-05 | `migration_test/fetch_liasettings_new.py` | add | 3 | NEW v1 fetcher (`list_omnichannel_settings`, enum-as-string, retry/backoff, per-subaccount fan-out) |
| 2026-06-05 | `migration_test/new_liasettings/*` (gitignored) | data | 3 | New v1 output: 34 accounts queried, 1 (`5789905876`/`IN`) has a setting (parity). MCA itself = PermissionDenied (subaccounts-only) |
| 2026-06-05 | `migration_test/compare_liasettings.py` | add | 4 | Derives the 4 MEX booleans from both shapes per (account, region); reconciliation |
| 2026-06-05 | `migration_test/liasettings_diff.md` | add | 4-5 | Comparison (1/1 key, 0/4 boolean mismatch) + finalized gap log (L1–L14, no blockers) + D2/D3 direction |
| 2026-06-05 | `migration_test/compare_liasettings_result.json` (gitignored) | data | 4 | Machine-readable reconciliation result |

### Steps 6–7: end-to-end code changes (main code) — ✅ COMPLETE
| Date | File | Type | Notes |
|------|------|------|-------|
| 2026-06-05 | `acit/api/v0/storage/schema.proto` | rewrite | Replaced `CombinedLiaSettings`/`LiaSettings`/`LiaCountrySettings` + 5 `Lia*` sub-messages with native flat `OmnichannelLiaSettings`(table_name="liasettings"){account_id, omnichannel_settings[]} → `OmnichannelSetting`{name, region_code, lsf_type, in_stock, pickup, lfp_link, odo, about, inventory_verification} + `OmnichannelFeatureState`{uri,state} / `LfpLink`{lfp_provider,external_account_id,state} / `InventoryVerification`{state,contact,contact_email,contact_state}. Enums as STRING. `liasettings.schema` is GENERATED → regenerates via `bq_gen_schemas` in Cloud Build. |
| 2026-06-05 | `acit/merchant_lia.py` | add | Merchant API v1 omnichannel ingestion (`OmnichannelSettingsServiceClient.list_omnichannel_settings`, enum-as-string `to_dict`, retry/backoff, threaded). Skips PermissionDenied (aggregators not valid parents). Writes one flat `{account_id, omnichannel_settings:[...]}` record per account. |
| 2026-06-05 | `acit/acit.py` | edit | Dropped `liasettings` from `_ACIT_ACCOUNT_ADMIN_RESOURCES` (now only shippingsettings) + updated comment; added `from acit import merchant_lia`; admin-gated `merchant_lia.download_omnichannel_settings(creds, product_account_ids, mc_path)` after the products download. |
| 2026-06-05 | `acit/create_base_tables.py` | edit | Rewrote `convert_lia_settings` — parses the flat native record into `schema_pb2.OmnichannelLiaSettings` (`ignore_unknown_fields=True`); dropped the `{settings, children[]}` envelope disambiguation. |
| 2026-06-05 | `extensions/merchant_excellence/account_list.sql` | edit | Replaced `AllLiaSettings`+`Lia` CTEs → single flat `Lia` reading `liasettings` directly; 4 booleans on v1 enums (`in_stock/pickup/odo/about.state='ACTIVE'`, `lsf_type IN (GHLSF,MHLSF_BASIC,MHLSF_FULL)`, `inventory_verification.contact_state`). |
| 2026-06-05 | `extensions/merchant_excellence/all_metrics.sql` | edit | Same `Lia` CTE rewrite as account_list. |
| 2026-06-05 | `extensions/merchant_excellence/ml_data.sql` | edit | `Lia` CTE: dropped `L.children` roll-down → flat read of `liasettings`; same v1 enum booleans (children-only semantics preserved by the downstream INNER JOIN to parent). |
| 2026-06-05 | `extensions/merchant_excellence/admin_tables.sql` | edit | New flat `CREATE TABLE liasettings (account_id, omnichannel_settings ARRAY<STRUCT<...>>)` matching the proto. |
| 2026-06-05 | `acit/tests/test_merchant_lia.py` | add | 5 unit tests: enum-as-string, snake keys, unset→`*_UNSPECIFIED`, `lfp_link`, METADATA_KEY. |
| 2026-06-05 | `acit/BUILD.bazel` | edit | New `merchant_lia_lib` (dep `google_shopping_merchant_accounts`) + `merchant_lia_test`; `acit` binary deps += `:merchant_lia_lib`. |

### Build / validation results (Steps 6–7)
- `bazel build //acit:acit` ✅. `bazel test //acit:{merchant_lia_test,merchant_products_test,merchant_accounts_test,create_base_tables_test,product_test}` ✅ (merchant_lia_test 5 cases).
- `schema_py_pb2` compiles from the rewritten proto on macOS (create_base_tables_test imports it). **End-to-end round-trip:** the real `5789905876`/`IN` record → all 4 MEX booleans **False** (matches old); a synthetic all-active record → all 4 **True** — through the compiled `OmnichannelLiaSettings` proto + the new boolean logic. `account_id` int64 preserved.
- **No new pip dependency** — reused `google-shopping-merchant-accounts` (Phase 1).
- **Known Linux-only step (pre-existing):** `//acit/api/v0:bq_gen_schemas` (regenerates `liasettings.schema`) + `//:cloud_run_job` build in Cloud Build, not macOS-ARM. Phase 3 *changes the proto* → verify the regenerated `liasettings.schema` in Cloud Build.
- **Behavioral note (L10/L11):** the MCA itself is no longer queried (PermissionDenied; old aggregator `get` was empty anyway) and the `{settings,children[]}` envelope is gone — the table is now flat per sub-/standalone account.

## Main-code files expected to change in Step 7 (not yet touched)

- `acit/acit.py` — remove `liasettings` from the Content-API `_ACIT_ACCOUNT_ADMIN_RESOURCES` roll-down
  (+ `_pull_standalone_account_resource`); call the new v1 omnichannel fetcher. Leave `shippingsettings`.
- `acit/merchant_lia.py` *(new)* — Merchant API v1 omnichannel fetcher
  (`OmnichannelSettingsServiceClient.list_omnichannel_settings`, enum-as-string, retry/backoff, threaded).
- `acit/create_base_tables.py` — rewrite `convert_lia_settings` for the native per-region shape;
  re-point the proto parse; preserve the account-id / MCA-child derivation.
- `acit/api/v0/storage/schema.proto` — replace `LiaSettings`/`LiaCountrySettings`/`CombinedLiaSettings`
  + `Lia*` sub-messages with native `OmnichannelSetting`; regenerate `liasettings.schema` via `bq_gen_schemas`.
- `acit/run_acit.sh` — `liasettings` table load (path likely unchanged if output layout preserved).
- `extensions/merchant_excellence/{account_list,all_metrics,ml_data}.sql` — rewrite the `AllLiaSettings`
  CTE + the 4 `lia_has_*` booleans against the new shape/enums.
- `extensions/merchant_excellence/admin_tables.sql` — update the `CREATE TABLE liasettings` contract.
- `acit/BUILD.bazel` — new `merchant_lia_lib` + test; wire into `acit` binary deps (reuse the existing
  `google_shopping_merchant_accounts` requirement — **no new pip dep**).
- `acit/tests/` — new/updated fixtures + the 4-boolean derivation tests.

## Notes / known constraints (carried from Phases 1–2)

- **Image build is Linux-only on this repo**: `//acit/api/v0:bq_gen_schemas` runs a `linux_x86_64` protoc
  and `//:cloud_run_job` is `os=linux/amd64`, so the full image build + schema-gen run in Cloud Build,
  not on macOS-ARM. Phase 3 *changes the proto*, so validate the regenerated `liasettings.schema` in
  Cloud Build (or a native linux/amd64 env), not locally.
- **No new pip dependency expected** — `google-shopping-merchant-accounts` (Phase 1) already ships
  `OmnichannelSettingsServiceClient`.
- Merchant API has no bulk variant + transient 500s → reuse the threaded fan-out + retry/backoff pattern.
- Main code must read standard `GOOGLE_ADS_*` env vars; test creds stay in the gitignored `env.local.sh`.
- Native v1 shape end-to-end — no transform back into the legacy `LiaSettings`/`countrySettings` schema.
