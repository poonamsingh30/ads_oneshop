# Accounts Migration — Master Change Tracker

> Single source of truth for **every** file added/modified during the Content API →
> Merchant API v1 migration (Phase 1 = accounts). Append an entry whenever a file changes.
> Plan/checklist: `accounts_migration_plan.md` · Context: `accounts_migration_understanding.md`.

## Locked design decisions (recommended options)

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | New-API client library | **`google-shopping-merchant-accounts`** (`google.shopping.merchant_accounts_v1`, stable v1, gRPC) | Google's officially recommended path for Merchant API; typed resources; already installed & import-verified. The legacy discovery-client `resource_downloader` stays for not-yet-migrated resources. |
| D2 | BQ record/table shape | **Flat: one row per account** with explicit relationship fields (e.g. `account_id`, `account_name`, `is_advanced`, `parent_account`) | Matches Merchant API's flat `accounts/{id}` resource model + `listSubaccounts`; drops the legacy `{settings, children[]}` rollup. MEX SQL updated to query rows by relationship instead of `UNNEST(children)`. |

## Environment

- Conda env: **`oneshop_merchant_migration`** (python 3.11). Anaconda default repo is network-blocked; env created from defaults that resolved, deps via pip.
- pip deps: `google-api-python-client`, `google-auth`, `google-auth-oauthlib` (old API) + `google-shopping-merchant-accounts` (new API, package `google.shopping.merchant_accounts_v1`).
- Test creds: `migration_test/env.local.sh` (GITIGNORED). Main code keeps reading standard `GOOGLE_ADS_*` env vars — the local file is for testing only.
- Test account: `MERCHANT_IDS=120436857` (an **aggregator/MCA**, 34 sub-accounts), `CUSTOMER_IDS=8056520078`.

## Change log

| Date | File | Type | Step | Notes |
|------|------|------|------|-------|
| 2026-06-01 | `migration_test/content_api_ingestion.md` | add | pre | Ingestion understanding doc |
| 2026-06-01 | `migration_test/accounts_migration_understanding.md` | add | pre | Phase-1 understanding doc |
| 2026-06-01 | `migration_test/accounts_migration_plan.md` | add | pre | Plan + 7-step + e2e checklist |
| 2026-06-01 | `migration_test/.gitignore` | add | 0 | Ignore secrets + scratch data |
| 2026-06-01 | `migration_test/env.local.sh` | add | 0 | Test creds (gitignored) |
| 2026-06-01 | `migration_test/CHANGES_TRACKER.md` | add | 0 | This tracker |
| 2026-06-01 | `migration_test/fetch_accounts_old.py` | add | 1 | OLD Content API accounts fetcher (mirrors acit.py) |
| 2026-06-01 | `migration_test/old_accounts/*` (gitignored) | data | 1 | Baseline: authinfo + 120436857 rollup (34 children) |
| 2026-06-01 | `migration_test/accounts_api_v1_mapping.md` | add | 2 | v1 endpoint study + authoritative old→new field map |
| 2026-06-01 | `migration_test/fetch_accounts_new.py` | add | 3 | NEW Merchant API v1 fetcher (gRPC, full-fidelity, threaded, retries) |
| 2026-06-01 | `migration_test/new_accounts/*` (gitignored) | data | 3 | New v1 output: 35 flat native rows |
| 2026-06-01 | `migration_test/compare_accounts.py` | add | 4 | Field-level old-vs-new reconciliation |
| 2026-06-01 | `migration_test/accounts_diff.md` | add | 4-5 | Comparison results + finalized gap log (G1–G8) |

### Steps 6–7: end-to-end code changes (main code)
| Date | File | Type | Notes |
|------|------|------|-------|
| 2026-06-01 | `acit/schemas/acit/accounts.schema` | rewrite | NEW flat native-v1 BQ schema (account_id/parent_account INTEGER, enums STRING, all sub-resources). Replaces the old `{settings, children[]}` monolith schema. |
| 2026-06-01 | `acit/merchant_accounts.py` | add | Merchant API v1 accounts ingestion (topology via list_sub_accounts, per-account fan-out, enum-as-string `to_dict`, retries, threaded). Writes flat per-account files. |
| 2026-06-01 | `acit/acit.py` | edit | Replaced `accounts.authinfo` + Content-API accounts pull with `merchant_accounts.download_accounts`; topology reused to drive remaining Content-API pulls. Removed dead `accounts`-resource constants/branch. |
| 2026-06-01 | `acit/bq.sh` | unchanged | Per-account file layout preserved → existing glob + new schema path work as-is. |
| 2026-06-01 | `extensions/merchant_excellence/account_list.sql` | edit | AllAccounts CTE → flat table + self-join on parent_account (Variant A w/ AIU). |
| 2026-06-01 | `extensions/merchant_excellence/all_metrics.sql` | edit | Both AllAccounts CTEs (AIU + names-only) → flat. |
| 2026-06-01 | `extensions/merchant_excellence/offer_list.sql` | edit | AllAccounts CTE → flat (names-only). |
| 2026-06-01 | `extensions/merchant_excellence/offer_funnel.sql` | edit | AllAccounts CTE → flat (names-only). |
| 2026-06-01 | `extensions/merchant_excellence/ml_data.sql` | edit | AccountNames + Account CTEs → flat, INNER JOIN to parent (preserves MCA-children-only semantics). |
| 2026-06-01 | `acit/tests/test_merchant_accounts.py` | add | Unit tests for enum-as-string + service_type oneof flattening. |
| 2026-06-01 | `requirements.in` | edit | + `google-shopping-merchant-accounts`. |
| 2026-06-01 | `requirements_lock.txt` | edit | Surgical insert of `google-shopping-merchant-accounts==1.5.0` + `google-shopping-type==1.4.0` (+hashes) ONLY. No churn to existing pins (full PyPI regen rejected — bumped google-ads/protobuf/dozens). |
| 2026-06-01 | `acit/BUILD.bazel` | edit | New `merchant_accounts_lib` + `merchant_accounts_test`; `acit` binary deps += `:merchant_accounts_lib`. Deps `@acit_deps//{google_api_core,google_shopping_merchant_accounts}`. |
| 2026-06-01 | `migration_test/validate_schema.py` | add | Runs real ingestion + validates output vs accounts.schema. |

### Build / validation results
- `bazel build //acit:merchant_accounts_lib` ✅ · `bazel build //acit:acit` ✅ · `bazel test //acit:merchant_accounts_test` ✅ PASSED.
- Real ingestion (`merchant_accounts.download_accounts`) on MCA 120436857 → 35 flat rows, **all conform to accounts.schema** (`validate_schema.py`).
- **Known macOS limitation (pre-existing, NOT from this change):** `//acit:acit_tar` and `//:cloud_run_job` fail on macOS-ARM because `//acit/api/v0:bq_gen_schemas` invokes a `linux_x86_64` protoc (exit 126) and the image is `os=linux/amd64`. These build on Linux/Cloud Build (`build_images.sh`), where the new dep + library are wired in and will be packaged automatically.
- `acit/schemas/acit/accounts.schema` is hand-maintained (not protoc-generated), so no `generate_schemas.sh` change needed.

### Steps 4–5 result
- Coverage **35/35 exact**; MEX-critical `automatic_improvements` fields **0/35 mismatch**; `#users` + Google-Ads link counts exact.
- All gaps are in fields nothing downstream consumes. Only 2 true drops (`conversionSettings`, `googleMyBusinessLink`) — neither has an accounts-v1 home nor a consumer. **No blockers to proceed to Step 6 (schema).**

### Step 3 efficiency note (answer to "are we over-requesting?")
- Content API: ~4 calls for the whole MCA (monolithic list). Merchant API splits the monolith into per-account sub-resource endpoints with **no bulk variant**.
- Removed the redundant per-child `get_account` (core comes free from `list_sub_accounts`): ~281 → ~247 calls; added threaded fan-out + backoff.
- User chose **full fidelity** (~7 calls/acct) over lean consumed-only (~36 calls total / just core+automatic_improvements). Revisit if ingestion runtime is too high at scale.
- Key finding: old `adsLinks` now live in `account_services` (`provider=providers/GOOGLE_ADS`, `external_account_id`, `campaigns_management`).

## Main-code files expected to change in Step 7 (not yet touched)

- `acit/acit.py` — accounts ingestion (authinfo→list, list→listSubaccounts, get→sub-resource fan-out)
- `acit/resource_downloader.py` — (only if discovery path retained for accounts; per D1 a new module is preferred)
- `acit/bq.sh` — accounts load path/table
- `acit/schemas/acit/accounts.schema` — replaced with native v1 schema
- `acit/create_base_tables.py` — verify no accounts-shape assumptions break
- `extensions/merchant_excellence/{ml_data,account_list,all_metrics,offer_list,offer_funnel}.sql` — new shape
- `acit/tests/test_create_base_tables.py` (+ any accounts tests)
