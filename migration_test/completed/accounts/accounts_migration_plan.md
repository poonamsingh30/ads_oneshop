# Phase 1 — `accounts` Migration: Plan & Change Tracker

> Tracks the Content API v2.1 → Merchant API **v1 (stable)** migration of the **`accounts`**
> resource, end-to-end. Update the Status column as work proceeds.
> Understanding/context: `accounts_migration_understanding.md`.

**Legend:** ⬜ not started · 🟡 in progress · ✅ done · ⛔ blocked

---

## A. Workstream tracker (the strict 7 steps)

| Step | Task | Output / Artifact | Status |
|------|------|-------------------|--------|
| 0 | Set up fresh conda env + install deps (discovery client and/or `google-shopping-merchant-accounts`) | conda env `oneshop_merchant_migration`; deps installed & verified | ✅ |
| 1 | Fetch **old** Content API `accounts` (authinfo + get + list) for a real account; save baseline | `migration_test/old_accounts/*` — `120436857` (MCA, 34 children) | ✅ |
| 2 | Study **new** Merchant API v1 accounts sub-API; finalize old→new field map | `accounts_api_v1_mapping.md` (introspected from client + real data) | ✅ |
| 3 | Build **test fetcher** for v1 accounts, mirroring `resource_downloader`; save output | `fetch_accounts_new.py` + `new_accounts/accounts_rows.jsonlines` (35 rows) | ✅ |
| 4 | **Compare** old vs new for the same account(s) | `compare_accounts.py` + `accounts_diff.md` (35/35 accounts, MEX fields 0 mismatch) | ✅ |
| 5 | Document **gaps** (renamed/relocated/dropped/added) | `accounts_diff.md` §Step 5 (G1–G8, no blockers) | ✅ |
| 6 | **Resolve** gaps; decide final per-account record shape + new BQ schema | ✅ flat native schema at `acit/schemas/acit/accounts.schema` | ✅ |
| 7 | Implement **end-to-end** code changes | ✅ §B done — see `CHANGES_TRACKER.md`; bazel-validated | ✅ |

---

## B. End-to-end code change checklist (Step 7) — ✅ COMPLETE
> All items below implemented and bazel-validated on the Python targets. Per-file log
> in `CHANGES_TRACKER.md`. (Boxes left as-is for historical reference.)

### B1. Ingestion — `acit/acit.py`
- ⬜ Add Merchant API v1 client factory (alongside / replacing `_get_merchant_center_api`).
- ⬜ Replace `accounts.authinfo` topology discovery with `accounts.list` (accessible accounts).
- ⬜ Replace MCA child enumeration `accounts.list` → `accounts.listSubaccounts`.
- ⬜ Replace single `accounts.get` with the v1 **fan-out**: core `Account` + `businessInfo` +
  `homepage` + `users` + `automaticImprovements` + `businessIdentity` (+ relationships/services
  as needed), reassembled into one native-shape record.
- ⬜ Decide & implement output layout: keep `merchant_center/<accountId>/accounts/rows.jsonlines`
  vs split sub-resource files. Update `downloaderMetadata` stamping (`accountId`, parent/relationship).
- ⬜ Confirm OAuth scope / creds work for Merchant API (no scope change expected, verify).
- ⬜ Keep all non-accounts resources on the existing Content API path (no Phase-1 change).

### B2. Generic fetch engine — `acit/resource_downloader.py`
- ⬜ Extend (or add a v1 variant) to support Merchant API resource-name paths (`accounts/{id}/…`)
  and `listSubaccounts`-style methods + pagination, if staying on the discovery client.
- ⬜ Unit tests updated/added.

### B3. Beam processing — `acit/create_base_tables.py`
- ⬜ Accounts isn't joined into `WideProduct` today, but **liasettings/account-derived** logic and
  any account reads must still parse. Verify no accounts-shape assumptions break; update if Beam
  reads the accounts files. (Confirm during Step 4–5.)

### B4. BQ load + schema — `acit/bq.sh`, `acit/schemas/acit/accounts.schema`
- ⬜ Author **new** `accounts` BQ schema reflecting native Merchant API v1 fields (replace the old
  monolithic schema — no legacy field names).
- ⬜ Update `upload_to_bq` source paths/table(s) for the new accounts output (single table vs
  per-sub-resource tables).

### B5. Views / final tables
- ⬜ `acit/views/main_view.sql` / `disapprovals_view.sql` — verify (no direct accounts dependency
  expected; confirm).
- ⬜ **MEX4P SQL — update to new shape** (these read `settings.automaticImprovements.*` & `children[]`):
  - ⬜ `extensions/merchant_excellence/ml_data.sql`
  - ⬜ `extensions/merchant_excellence/account_list.sql`
  - ⬜ `extensions/merchant_excellence/all_metrics.sql`
  - ⬜ `extensions/merchant_excellence/offer_list.sql`
  - ⬜ `extensions/merchant_excellence/offer_funnel.sql`

### B6. Schema codegen / protos (if applicable)
- ⬜ Check `generate_schemas.sh` / `acit/api/v0/storage/schema.proto` — if accounts schema is
  generated, regenerate; otherwise hand-edit `accounts.schema`.

### B7. Tests & validation
- ⬜ Update `acit/tests/` touching accounts.
- ⬜ End-to-end dry run (direct runner) on a test account; confirm BQ table + MEX tables build.
- ⬜ Row-count / spot-check parity vs the old pipeline.

---

## C. Old → New field map — ✅ CONFIRMED in Step 2
Full, authoritative table now lives in **`accounts_api_v1_mapping.md`** (introspected from the
installed `google.shopping.merchant_accounts_v1` client + verified against real MCA `120436857`).
Headlines: `id→account_id`, `name→account_name`, `websiteUrl→homepage.uri`,
`businessInformation→businessInfo` (address fields renamed), `automaticImprovements.*` same shape
in snake_case, `users` remodeled onto `access_rights[]`, **`adsLinks` → `account_services` with
`provider=providers/GOOGLE_ADS`** (confirmed on real data), `kind` dropped.

## D. Gap log (Step 5 — ✅ FINALIZED in `accounts_diff.md`)
**No blocking gaps.** Coverage 35/35 exact; MEX-critical `automatic_improvements` fields 0/35 mismatch.
Remaining items (none consumed downstream): G1 `shipping_improvements` absent→treat as false;
G2 `promotions_consent` enum repr; G3 unset address `""` vs null; G4 `kind` dropped;
G5 `accountManagement` derive from `account_services` oneof; **G6 `conversionSettings` — true drop (no v1 home)**;
G7 `googleMyBusinessLink` — separate `GbpAccountsService`, null in test data, skip Phase 1;
G8 `users` booleans→`access_rights[]` enum. Schema actions: coalesce G1→false, store G2 as enum.

## E. Key decisions
- **Client:** ✅ **DECIDED** — `google-shopping-merchant-accounts` (`google.shopping.merchant_accounts_v1`, stable v1, gRPC). Google-recommended; installed & verified. (See `CHANGES_TRACKER.md` D1.)
- **Record shape:** ✅ **DECIDED** — flat per-account table (one row per account) with explicit relationship fields; drop legacy `{settings, children[]}` rollup. (D2.)
- **Dropped fields & MEX impact:** _TBD after Step 4 comparison._

---

## F. Guardrails / scope
- Phase 1 = **accounts only**. Do not migrate products, productstatuses, liasettings,
  shippingsettings, or Ads in this phase.
- **No legacy-schema transform** — native Merchant API v1 shape end-to-end.
- v1 **stable** only (no v1beta). Test in a **fresh conda env**. Keep scratch artifacts in
  `migration_test/`.

## G. Changelog
- **2026-06-01** — Step 0 done: conda env `oneshop_merchant_migration` (py3.11) + deps (old discovery client + new `google.shopping.merchant_accounts_v1`) installed/verified. Decisions D1 (client) & D2 (flat shape) locked.
- **2026-06-01** — Step 1 done: `fetch_accounts_old.py` pulled old Content API `accounts` for `120436857` → aggregator/MCA with **34 sub-accounts**. Baseline saved to `migration_test/old_accounts/`. Parent settings top-level keys: `accountManagement, adsLinks, adultContent, automaticImprovements, businessIdentity, businessInformation, id, kind, name, users, websiteUrl`.
- **2026-06-01** — Step 2 done: introspected `google.shopping.merchant_accounts_v1` (22 service clients) → full old→new map in `accounts_api_v1_mapping.md`. Confirmed monolith→sub-resource split; `adsLinks`→`account_services(provider=GOOGLE_ADS)`.
- **2026-06-01** — Step 3 done: `fetch_accounts_new.py` (v1 gRPC client, **full fidelity** per user) pulled all 35 accounts → flat native rows in `new_accounts/accounts_rows.jsonlines`. Added retry/backoff for the API's transient 500s + threaded fan-out. **Request optimization:** dropped redundant per-child `get_account` (children core comes free from `list_sub_accounts`), ~247 reqs vs ~281. User chose full fidelity (all 7 sub-resources/account) over lean (~36 reqs).
- **2026-06-01** — Steps 4–5 done: `compare_accounts.py` → `accounts_diff.md`. Coverage **35/35 exact**; **MEX-critical `automatic_improvements` fields 0/35 mismatch**; `#users` and `adsLinks→account_services[GOOGLE_ADS]` counts exact. Gaps G1–G8 are all in non-consumed fields (representation/normalization + 2 true drops `conversionSettings`/`googleMyBusinessLink`). No blockers → cleared to design the new schema (Step 6).
- **2026-06-01** — Steps 6–7 done (end-to-end main code): new flat `accounts.schema`; `acit/merchant_accounts.py` ingestion; `acit.py` rewired (authinfo/get/list → Merchant API, topology reused); `bq.sh` unchanged (per-account file layout preserved); 5 MEX SQL files rewritten to flat self-join; `requirements.in`/lock + `acit/BUILD.bazel` updated (new dep). Validated: `bazel build //acit:acit` ✅, `bazel test //acit:merchant_accounts_test` ✅, real ingestion → 35 rows conform to schema ✅. Cloud Run image build is **Linux-only** (pre-existing protoc/`os=linux` constraint) → builds in Cloud Build, not on macOS.
